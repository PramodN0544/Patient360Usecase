import ast
import aiohttp
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import EncounterHistory
from typing import List
from datetime import date, datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,KeepTogether
from reportlab.lib import colors
from io import BytesIO
import os
import json
import re
import httpx
from app.database import get_db
from app.models import Encounter, Doctor, Patient, Vitals, Medication, Assignment, LabOrder
from app.schemas import EncounterCreate, EncounterOut, EncounterUpdate, LabTestDetail, CarePlanGenerationInput, PatientProfile, CurrentEncounter, CurrentVitals, MedicationInfo, LabInfo, MedicalHistory, ConditionInfo, MedicationHistoryInfo, AllergyInfo, GuidelineRulesInfo
from app.auth import get_current_user
from app.S3connection import generate_presigned_url, upload_encounter_document_to_s3

router = APIRouter(prefix="/encounters", tags=["Encounters"])

def calculate_status(enc):
    """
    Calculate encounter status based on completion criteria
    Rules:
    1. If diagnosis, notes, and vitals are complete → Completed
    2. If lab tests required or follow-up date set → In Progress
    3. Otherwise → Pending
    """
    # Check if essential fields are filled
    has_essential_data = (
        enc.diagnosis and 
        enc.notes and 
        enc.vitals and
        enc.vitals.height and
        enc.vitals.weight
    )
    
    if not has_essential_data:
        return "Pending"

    if enc.follow_up_date or enc.is_lab_test_required:
        return "In Progress"
    
    return "Completed"


def safe_parse(data: str):
    try:
        return json.loads(data)
    except:
        try:
            return ast.literal_eval(data)
        except:
            raise HTTPException(422, "Invalid encounter_in format")

# CREATE ENCOUNTER
@router.post("/", response_model=EncounterOut)
async def create_encounter(
    encounter_in: str = Form(...), 
    files: List[UploadFile] | None = File(None), 
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    parsed_data = json.loads(encounter_in) 
    encounter_in = EncounterCreate(**parsed_data)

    # ---------- DOCTOR / HOSPITAL VALIDATION ----------
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.unique().scalar_one_or_none()

    if current_user.role == "hospital":
        doctor_result = await db.execute(
            select(Doctor).where(
                Doctor.id == encounter_in.doctor_id,
                Doctor.hospital_id == current_user.hospital_id
            )
        )
        doctor = doctor_result.unique().scalar_one_or_none()

        if not doctor:
            raise HTTPException(404, "Doctor not found in hospital")

    elif not doctor:
        raise HTTPException(403, "Only doctors or hospitals can create encounters")

    # ---------- PATIENT VALIDATION ----------
    if not encounter_in.patient_public_id:
        raise HTTPException(400, "patient_public_id is required")

    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == encounter_in.patient_public_id)
    )
    patient = patient_result.unique().scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    # ---------- ASSIGNMENT CHECK ----------
    assign = await db.execute(
        select(Assignment).where(
            Assignment.patient_id == patient.id,
            Assignment.doctor_id == doctor.id
        )
    )
    assignment_record = assign.scalars().first() 
    if not assignment_record:
        raise HTTPException(403, "Doctor is not assigned to this patient")

    # ---------- CREATE ENCOUNTER ----------
    new_encounter = Encounter(
        patient_id=patient.id,
        patient_public_id=patient.public_id,
        doctor_id=doctor.id,
        hospital_id=doctor.hospital_id,
        encounter_date=encounter_in.encounter_date or date.today(),
        encounter_type=encounter_in.encounter_type,
        reason_for_visit=encounter_in.reason_for_visit,
        diagnosis=encounter_in.diagnosis,
        notes=encounter_in.notes,
        follow_up_date=encounter_in.follow_up_date,
        is_lab_test_required=encounter_in.is_lab_test_required,
        status=calculate_status(encounter_in),
        documents=[]
    )

    db.add(new_encounter)
    await db.flush()

    # ---------- SAVE VITALS ----------
    if encounter_in.vitals:
        v = encounter_in.vitals
        bmi = None
        if v.height and v.weight:
            bmi = round(v.weight / ((v.height / 100) ** 2), 2)

        db.add(Vitals(
            patient_id=patient.id,
            encounter_id=new_encounter.id,
            height=v.height,
            weight=v.weight,
            bmi=bmi,
            blood_pressure=v.blood_pressure,
            heart_rate=v.heart_rate,
            temperature=v.temperature,
            respiration_rate=v.respiration_rate,
            oxygen_saturation=v.oxygen_saturation,
        ))

    # ---------- SAVE MEDICATIONS ----------
    if encounter_in.medications:
        for m in encounter_in.medications:
            db.add(Medication(
                patient_id=patient.id,
                doctor_id=doctor.id,
                encounter_id=new_encounter.id,
                medication_name=m.medication_name,
                dosage=m.dosage,
                frequency=m.frequency,
                route=m.route,
                start_date=m.start_date,
                end_date=m.end_date,
                status=m.status,
                notes=m.notes,
                icd_code=m.icd_code,
                ndc_code=m.ndc_code,
            ))

    # ---------- FILE UPLOAD TO S3 ----------
    if files:
        current_docs = new_encounter.documents or []
        for file in files:
            file_path = await upload_encounter_document_to_s3(
                hospital_id=doctor.hospital_id,
                patient_id=patient.id,
                encounter_id=new_encounter.id,
                file=file
            )
            current_docs.append(file_path)
            new_encounter.documents = current_docs
    
    if encounter_in.follow_up_date:
        db.add(
            EncounterHistory(
                encounter_id=new_encounter.id,
                status="FOLLOW_UP_SCHEDULED",
                updated_by=current_user.id,
                notes="Follow-up created during encounter"
            )
        )
    # --- CONTINUATION LOGIC ---
    if encounter_in.follow_up_date:
        new_encounter.is_continuation = True
        new_encounter.previous_encounter_id = (
        encounter_in.previous_encounter_id if hasattr(encounter_in, "previous_encounter_id") else None
    )

    await db.commit()
    await db.refresh(new_encounter)

    # ---------- FETCH COMPLETE OBJECT ----------
    final = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.patient)
        )
        .where(Encounter.id == new_encounter.id)
    )
    e = final.unique().scalar_one()

    out = EncounterOut.from_orm(e)
    out.doctor_name = f"{doctor.first_name} {doctor.last_name}"
    out.hospital_name = e.hospital.name
    out.patient_public_id = e.patient.public_id

    return out

@router.put("/{encounter_id}", response_model=EncounterOut)
async def update_encounter(
    background_tasks: BackgroundTasks,
    encounter_id: int,
    encounter_in: str = Form(...),
    files: List[UploadFile] | None = File(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    parsed_data = json.loads(encounter_in)
    print(f"📥 Incoming update payload: {parsed_data}")

    encounter_update = EncounterUpdate(**parsed_data)

    # ---- Fetch Encounter ----
    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.patient)
        )
        .where(Encounter.id == encounter_id)
    )
    encounter = result.unique().scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "❌ No encounter found. Please start encounter first.")

    # ---- Permission Check ----
    doctor_result = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
    doctor = doctor_result.unique().scalar_one_or_none()

    if not doctor and current_user.role != "hospital":
        raise HTTPException(403, "Not allowed")

    # ---- Update Main Fields ----
    for field, value in encounter_update.dict(exclude_unset=True).items():
        if field not in ["vitals", "medications", "lab_orders", "previous_encounter_id", "is_continuation"]:
            if value is not None:
                setattr(encounter, field, value)

    # ---- Follow-up Logic ----
    if encounter_update.follow_up_date:
        encounter.is_continuation = True
        encounter.status = "in_progress"

        if not encounter_update.previous_encounter_id:
            prev_result = await db.execute(
                select(Encounter)
                .where(Encounter.patient_id == encounter.patient_id)
                .where(Encounter.id != encounter.id)
                .order_by(Encounter.encounter_date.desc())
            )
            previous_encounter = prev_result.scalars().first()
            encounter.previous_encounter_id = previous_encounter.id if previous_encounter else None
    else:
        encounter.is_continuation = False
        encounter.previous_encounter_id = None
        encounter.status = "completed"
        
        # If encounter is completed, trigger care plan generation
        if encounter.status == "completed":
            # This will be handled after the encounter update is committed
            background_tasks = BackgroundTasks()
            background_tasks.add_task(
                generate_care_plan_for_encounter,
                encounter_id=encounter.id,
                user_id=current_user.id,
                db=db
            )

    # ---- Update Vitals ----
    if encounter_update.vitals is not None:
        vitals_result = await db.execute(select(Vitals).where(Vitals.encounter_id == encounter.id))
        vitals = vitals_result.unique().scalar_one_or_none()

        if vitals:
            for key, val in encounter_update.vitals.dict(exclude_unset=True).items():
                setattr(vitals, key, val)
        else:
            db.add(Vitals(encounter_id=encounter.id, **encounter_update.vitals.dict()))

    # ---- Update Medications ----
    if encounter_update.medications is not None:
        await db.execute(Medication.__table__.delete().where(Medication.encounter_id == encounter.id))
        for med in encounter_update.medications:
            db.add(Medication(
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                **med.dict(exclude_unset=True)
            ))

    # ---- Update LAB ORDERS ----
    if encounter_update.lab_orders is not None and encounter_update.is_lab_test_required:

        # Remove old lab orders
        await db.execute(LabOrder.__table__.delete().where(LabOrder.encounter_id == encounter.id))

        for lab in encounter_update.lab_orders:
            db.add(LabOrder(
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                test_code=lab.test_code,
                test_name=getattr(lab, "test_name", None),
                sample_type= None,
                status="Ordered"
            ))

    # ---- File Upload ----
    if files:
        docs = encounter.documents or []
        for file in files:
            url = await upload_encounter_document_to_s3(
                hospital_id=encounter.hospital_id,
                patient_id=encounter.patient_id,
                encounter_id=encounter.id,
                file=file
            )
            docs.append(url)
        encounter.documents = docs

    # ---- Save History ----
    db.add(EncounterHistory(
        encounter_id=encounter.id,
        status=encounter.status,
        updated_by=current_user.id,
        notes="Encounter updated"
    ))

    await db.commit()
    await db.refresh(encounter)

    # ---- Build Response ----
    response = EncounterOut.from_orm(encounter)
    response.doctor_name = f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
    response.hospital_name = encounter.hospital.name
    response.patient_public_id = encounter.patient.public_id

    return response

# GET ALL ENCOUNTERS FOR A PATIENT (BY PUBLIC ID) - For Patient Dashboard
@router.get("/patient/{public_id}")
async def get_patient_encounters(
    public_id: str, 
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all encounters for a patient by their public_id.
    Used in patient dashboard to show all their encounters.
    """
    # First, get the patient
    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == public_id)
    )
    patient = patient_result.unique().scalar_one_or_none()
    
    if not patient:
        raise HTTPException(404, "Patient not found")
    
    # Check permissions
    if current_user.role == "doctor":
        # Doctor can only see encounters for patients assigned to them
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.unique().scalar_one_or_none()
        
        if doctor:
            assign = await db.execute(
                select(Assignment).where(
                    Assignment.patient_id == patient.id,
                    Assignment.doctor_id == doctor.id
                )
            )
            if not assign.scalars().first():
                raise HTTPException(403, "Not authorized to view this patient's encounters")
    elif current_user.role == "patient":
        # Patient can only see their own encounters
        if patient.user_id != current_user.id:
            raise HTTPException(403, "You can only view your own encounters")
    
    # Fetch encounters with all relationships
    stmt = (
        select(Encounter)
        .where(Encounter.patient_id == patient.id)
        .order_by(Encounter.encounter_date.desc(), Encounter.created_at.desc())
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
        )
    )

    result = await db.execute(stmt)
    encounters = result.scalars().unique().all()
    
    # Build response
    response = []
    for e in encounters:
        encounter_data = {
            "id": e.id,
            "patient_id": e.patient_id,
            "patient_public_id": patient.public_id,
            "doctor_id": e.doctor_id,
            "hospital_id": e.hospital_id,
            "encounter_date": e.encounter_date,
            "encounter_type": e.encounter_type,
            "reason_for_visit": e.reason_for_visit,
            "diagnosis": e.diagnosis,
            "notes": e.notes,
            "follow_up_date": e.follow_up_date,
            "is_lab_test_required": e.is_lab_test_required,
            "status": e.status,
            "created_at": e.created_at,
            "updated_at": e.updated_at,
            "doctor": {
                "id": e.doctor.id,
                "first_name": e.doctor.first_name,
                "last_name": e.doctor.last_name,
                "specialty": e.doctor.specialty,
            } if e.doctor else None,
            "doctor_name": f"{e.doctor.first_name} {e.doctor.last_name}" if e.doctor else None,
            "hospital": {
                "id": e.hospital.id,
                "name": e.hospital.name,
            } if e.hospital else None,
            "hospital_name": e.hospital.name if e.hospital else None,
            "vitals": e.vitals[0] if e.vitals else None,
            "medications": [
                {
                    "id": m.id,
                    "medication_name": m.medication_name,
                    "dosage": m.dosage,
                    "frequency": m.frequency,
                    "route": m.route,
                    "start_date": m.start_date,
                    "end_date": m.end_date,
                    "status": m.status,
                    "notes": m.notes,
                    "icd_code": m.icd_code,
                    "ndc_code": m.ndc_code,
                }
                for m in e.medications
            ] if e.medications else [],
        }
        response.append(encounter_data)
    
    return response

# GET PATIENT ENCOUNTERS FOR DOCTOR - Doctor's view of their patient's encounters
@router.get("/doctor/patient/{public_id}")
async def get_doctor_patient_encounters(
    public_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get encounters for a specific patient that belong to the current doctor.
    This is for doctors to see encounters they've created for a particular patient.
    """
    if current_user.role != "doctor":
        raise HTTPException(403, "Only doctors can access this endpoint")
    
    # Get current doctor
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.unique().scalar_one_or_none()
    
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    
    # Get patient by public_id
    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == public_id)
    )
    patient = patient_result.unique().scalar_one_or_none()
    
    if not patient:
        raise HTTPException(404, "Patient not found")
    
    # Check if doctor is assigned to this patient
    assign = await db.execute(
        select(Assignment).where(
            Assignment.patient_id == patient.id,
            Assignment.doctor_id == doctor.id
        )
    )
    if not assign.scalars().first():
        raise HTTPException(403, "Doctor is not assigned to this patient")
    
    # Fetch encounters created by this doctor for this patient
    stmt = (
        select(Encounter)
        .where(
            Encounter.patient_id == patient.id,
            Encounter.doctor_id == doctor.id
        )
        .order_by(Encounter.encounter_date.desc(), Encounter.created_at.desc())
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
        )
    )

    result = await db.execute(stmt)
    encounters = result.scalars().unique().all()
    
    # Build response
    response = []
    for e in encounters:
        encounter_data = {
            "id": e.id,
            "patient_id": e.patient_id,
            "patient_public_id": patient.public_id,
            "doctor_id": e.doctor_id,
            "hospital_id": e.hospital_id,
            "encounter_date": e.encounter_date,
            "encounter_type": e.encounter_type,
            "reason_for_visit": e.reason_for_visit,
            "diagnosis": e.diagnosis,
            "notes": e.notes,
            "follow_up_date": e.follow_up_date,
            "is_lab_test_required": e.is_lab_test_required,
            "status": e.status,
            "created_at": e.created_at,
            "updated_at": e.updated_at,
            "doctor": {
                "id": e.doctor.id,
                "first_name": e.doctor.first_name,
                "last_name": e.doctor.last_name,
                "specialty": e.doctor.specialty,
            } if e.doctor else None,
            "doctor_name": f"{e.doctor.first_name} {e.doctor.last_name}" if e.doctor else None,
            "hospital": {
                "id": e.hospital.id,
                "name": e.hospital.name,
            } if e.hospital else None,
            "hospital_name": e.hospital.name if e.hospital else None,
            "vitals": e.vitals[0] if e.vitals else None,
            "medications": [
                {
                    "id": m.id,
                    "medication_name": m.medication_name,
                    "dosage": m.dosage,
                    "frequency": m.frequency,
                    "route": m.route,
                    "start_date": m.start_date,
                    "end_date": m.end_date,
                    "status": m.status,
                    "notes": m.notes,
                    "icd_code": m.icd_code,
                    "ndc_code": m.ndc_code,
                }
                for m in e.medications
            ] if e.medications else [],
        }
        
        has_followup = e.follow_up_date and e.follow_up_date > datetime.now().date()

        encounter_data["is_continuation_pending"] = bool(has_followup)
        encounter_data["continue_from_encounter_id"] = e.previous_encounter_id if has_followup else None
        encounter_data["label"] = "Continue previous encounter" if has_followup else None

        response.append(encounter_data)
    
    return response

# GET MY OWN ENCOUNTERS (PATIENT) - Patient view of all their encounters
@router.get("/my-encounters", response_model=List[EncounterOut])
async def get_my_encounters(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can view their own encounters")

    patient_result = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = patient_result.unique().scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital)
        )
        .where(Encounter.patient_id == patient.id)
        .order_by(Encounter.encounter_date.desc())
    )

    encounters = result.unique().scalars().all()

    response = []
    for e in encounters:
        data = EncounterOut.from_orm(e)
        data.doctor_name = f"{e.doctor.first_name} {e.doctor.last_name}"
        data.hospital_name = e.hospital.name
        response.append(data)

    return response

# GET DOCTOR'S ENCOUNTERS - All encounters created by the current doctor
@router.get("/doctor/all", response_model=List[EncounterOut])
async def get_doctor_all_encounters(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all encounters created by the current doctor"""
    if current_user.role != "doctor":
        raise HTTPException(403, "Only doctors can access this endpoint")

    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.unique().scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor not found")

    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.patient)
        )
        .where(Encounter.doctor_id == doctor.id)
        .order_by(Encounter.encounter_date.desc())
    )

    encounters = result.unique().scalars().all()

    response = []
    for e in encounters:
        data = EncounterOut.from_orm(e)
        data.doctor_name = f"{e.doctor.first_name} {e.doctor.last_name}"
        data.hospital_name = e.hospital.name
        data.patient_name = f"{e.patient.first_name} {e.patient.last_name}"
        data.patient_public_id = e.patient.public_id
        response.append(data)

    return response

@router.get("/{encounter_id}", response_model=EncounterOut)
async def get_encounter(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.patient),
            selectinload(Encounter.hospital),
            selectinload(Encounter.doctor),
            selectinload(Encounter.lab_orders)   # 👈 Added lab orders
        )
        .where(Encounter.id == encounter_id)
    )

    encounter = result.unique().scalar_one_or_none()
    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # Role security rules:
    if current_user.role == "patient" and encounter.patient.user_id != current_user.id:
        raise HTTPException(403, "You can only view your own encounters")

    if current_user.role == "doctor" and encounter.doctor.user_id != current_user.id:
        raise HTTPException(403, "You can only view encounters you created")

    # ----- Build Response -----
    out = EncounterOut.from_orm(encounter)

    # Assign UI-friendly values
    out.doctor_name = f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
    out.hospital_name = encounter.hospital.name
    out.patient_public_id = encounter.patient.public_id

    # Attach lab orders to response (if any)
    out.lab_orders = [
        {
            "id": lab.id,
            "test_code": lab.test_code,
            "test_name": lab.test_name,
            "status": lab.status,
            "created_at": lab.created_at,
        }
        for lab in encounter.lab_orders
    ] if hasattr(encounter, "lab_orders") and encounter.lab_orders else []

    return out

# GENERATE PDF FOR ENCOUNTER
@router.post("/{encounter_id}/generate-pdf", response_model=EncounterOut)
async def generate_encounter_pdf(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Get the encounter with all related data including hospital
    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),  # This loads the hospital relationship
            selectinload(Encounter.patient)
        )
        .where(Encounter.id == encounter_id)
    )
    
    encounter = result.unique().scalar_one_or_none()
    if not encounter:
        raise HTTPException(404, "Encounter not found")
    
    # Verify permissions
    if current_user.role == "doctor" and encounter.doctor.user_id != current_user.id:
        raise HTTPException(403, "Not authorized to access this encounter")
    if current_user.role == "patient" and encounter.patient.user_id != current_user.id:
        raise HTTPException(403, "Not authorized to access this encounter")
    
    # Get hospital information from the loaded relationship
    # The hospital object should have 'id' and 'name' attributes
    hospital_name = encounter.hospital.name if encounter.hospital else "CareIQ Medical Center"
    hospital_id = encounter.hospital.id if encounter.hospital else f"MC-{encounter_id:06d}"
    
    # For address, we might not have it in the Hospital model
    # Let's use a default or check if address exists
    hospital_address = ""
    if encounter.hospital:
        # Check if address attribute exists
        if hasattr(encounter.hospital, 'address') and encounter.hospital.address:
            hospital_address = encounter.hospital.address
        elif hasattr(encounter.hospital, 'location') and encounter.hospital.location:
            hospital_address = encounter.hospital.location
        else:
            hospital_address = "Healthcare Avenue, Medical District"
    else:
        hospital_address = "123 Healthcare Avenue, Medical District, City 12345"
    
    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    # Define custom styles
    styles = getSampleStyleSheet()
    
    # Custom styles for better appearance
    styles.add(ParagraphStyle(
        name='CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        alignment=1
    ))
    
    styles.add(ParagraphStyle(
        name='CustomHeading2',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2980b9'),
        spaceAfter=6,
        spaceBefore=12
    ))
    
    # Add style for wrapping text in tables
    styles.add(ParagraphStyle(
        name='TableContent',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.black,
        wordWrap='CJK'  # This enables text wrapping
    ))
    
    elements = []
    
    # Header Section with Logo and Hospital Info
    header_data = []
    
    # Add logo
    logo_found = False
    possible_paths = [
        os.path.join("static", "mylogo.jpg"),
        os.path.join("Patient360-Backend", "static", "mylogo.jpg"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "mylogo.jpg"))
    ]
    
    logo_path = None
    for path in possible_paths:
        if os.path.exists(path):
            logo_path = path
            logo_found = True
            break
    
    # Create header table using actual hospital data
    if logo_found and logo_path:
        logo = Image(logo_path, width=120, height=50)
        header_data = [
            [logo, 
             Paragraph(hospital_name, styles['Heading2']),
             Paragraph(f"Hospital ID: {hospital_id}", ParagraphStyle(name='HospitalInfo', fontSize=9, alignment=2))],
            ['', 
             Paragraph("Advanced Healthcare Solutions", styles['Italic']),
             Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle(name='HospitalInfo', fontSize=9, alignment=2))]
        ]
    else:
        header_data = [
            [Paragraph(hospital_name, styles['Heading1']),
             Paragraph(f"Hospital ID: {hospital_id}", ParagraphStyle(name='HospitalInfo', fontSize=9, alignment=2))],
            [Paragraph("Advanced Healthcare Solutions", styles['Italic']),
             Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle(name='HospitalInfo', fontSize=9, alignment=2))]
        ]
    
    header_table = Table(header_data, colWidths=[2*inch, 3*inch, 2*inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(header_table)
    elements.append(Spacer(1, 24))
    
    # Main Title
    elements.append(Paragraph("PATIENT ENCOUNTER REPORT", styles['CustomTitle']))
    elements.append(Spacer(1, 12))
    
    # Encounter Details - Directly remove HTML tags
    encounter_id_clean = str(encounter.id).replace('<b>', '').replace('</b>', '')
    encounter_type_clean = str(encounter.encounter_type).replace('<b>', '').replace('</b>', '')
    
    encounter_info = [
        ["Encounter Details", ""],
        ["Encounter ID:", encounter_id_clean],
        ["Date:", encounter.encounter_date.strftime('%B %d, %Y')],
        ["Type:", encounter_type_clean],
        ["Status:", "Completed"],
        ["Hospital:", hospital_name]
    ]
    
    encounter_table = Table(encounter_info, colWidths=[2*inch, 4*inch])
    encounter_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f8f9fa')),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 1), (0, -1), colors.HexColor('#495057')),
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    
    elements.append(KeepTogether([encounter_table, Spacer(1, 20)]))
    
    # Calculate age properly
    def calculate_age(birth_date):
        today = datetime.now().date()
        age = today.year - birth_date.year
        if today.month < birth_date.month or (today.month == birth_date.month and today.day < birth_date.day):
            age -= 1
        return age
    
    # Patient and Doctor Information - Directly remove HTML tags
    patient_age = calculate_age(encounter.patient.dob)
    
    # Clean patient data directly
    patient_first_name = str(encounter.patient.first_name).replace('<b>', '').replace('</b>', '')
    patient_last_name = str(encounter.patient.last_name).replace('<b>', '').replace('</b>', '')
    patient_public_id = str(encounter.patient.public_id).replace('<b>', '').replace('</b>', '')
    patient_gender = str(encounter.patient.gender).replace('<b>', '').replace('</b>', '').capitalize()
    
    patient_info = [
        ["PATIENT INFORMATION", ""],
        ["Patient Name:", f"{patient_first_name} {patient_last_name}"],
        ["Patient ID:", patient_public_id],
        ["Date of Birth:", encounter.patient.dob.strftime('%B %d, %Y')],
        ["Age:", f"{patient_age} years"],
        ["Gender:", patient_gender]
    ]
    
    # Clean doctor data directly
    doctor_first_name = str(encounter.doctor.first_name).replace('<b>', '').replace('</b>', '')
    doctor_last_name = str(encounter.doctor.last_name).replace('<b>', '').replace('</b>', '')
    doctor_specialty = str(encounter.doctor.specialty).replace('<b>', '').replace('</b>', '')
    
    doctor_info = [
        ["DOCTOR INFORMATION", ""],
        ["Doctor Name:", f"Dr. {doctor_first_name} {doctor_last_name}"],
        ["Specialty:", doctor_specialty],
        ["Doctor ID:", f"DR-{encounter.doctor.id:04d}"]
    ]
    
    # Create tables
    patient_table = Table(patient_info, colWidths=[2*inch, 2*inch])
    doctor_table = Table(doctor_info, colWidths=[2*inch, 2*inch])
    
    # Apply styles to both tables
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#ecf0f1')),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 1), (0, -1), colors.HexColor('#495057')),
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ('PADDING', (0, 0), (-1, -1), 6),
    ])
    
    patient_table.setStyle(table_style)
    doctor_table.setStyle(table_style)
    
    # Combine tables and keep together
    combined_table = Table([[patient_table, Spacer(0.5*inch, 0), doctor_table]], 
                          colWidths=[4*inch, 0.5*inch, 4*inch])
    elements.append(KeepTogether([combined_table, Spacer(1, 20)]))
    
    # Clinical Information - Clean data directly
    reason_clean = str(encounter.reason_for_visit).replace('<b>', '').replace('</b>', '') if encounter.reason_for_visit else "Not specified"
    diagnosis_clean = str(encounter.diagnosis).replace('<b>', '').replace('</b>', '') if encounter.diagnosis else "Not specified"
    notes_clean = str(encounter.notes).replace('<b>', '').replace('</b>', '') if encounter.notes else "No additional notes"
    
    clinical_section = []
    clinical_section.append(Paragraph("CLINICAL INFORMATION", styles['CustomHeading2']))
    
    # Use Paragraphs for text wrapping in the Details column
    clinical_data = [
        ["Category", "Details"],
        ["Reason for Visit:", Paragraph(reason_clean, styles['TableContent'])],
        ["Diagnosis:", Paragraph(diagnosis_clean, styles['TableContent'])],
        ["Clinical Notes:", Paragraph(notes_clean, styles['TableContent'])]
    ]
    
    clinical_table = Table(clinical_data, colWidths=[1.5*inch, 5*inch])
    clinical_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17a2b8')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#e3f2fd')),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#b3e0ff')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
    ]))
    
    clinical_section.append(clinical_table)
    clinical_section.append(Spacer(1, 20))
    elements.append(KeepTogether(clinical_section))
    
    # Vitals Section
    if encounter.vitals:
        vitals_section = []
        vitals_section.append(Paragraph("VITAL SIGNS", styles['CustomHeading2']))
        
        vitals = encounter.vitals[0]
        
        # Clean vitals data directly
        bp_clean = str(vitals.blood_pressure).replace('<b>', '').replace('</b>', '') if vitals.blood_pressure else "Not recorded"
        
        # Determine status for each vital
        bp_status = "Normal" if vitals.blood_pressure and "120/80" in str(vitals.blood_pressure) else "Review"
        hr_status = "Normal" if vitals.heart_rate and 60 <= vitals.heart_rate <= 100 else "Review"
        temp_status = "Normal" if vitals.temperature and 97 <= vitals.temperature <= 99 else "Review"
        oxy_status = "Normal" if vitals.oxygen_saturation and vitals.oxygen_saturation >= 95 else "Review"
        resp_status = "Normal" if vitals.respiration_rate and 12 <= vitals.respiration_rate <= 20 else "Review"
        bmi_status = "Normal" if vitals.bmi and 18.5 <= vitals.bmi <= 24.9 else "Review"
        
        vitals_data = [
            ["Measurement", "Value", "Status"],
            ["Blood Pressure", bp_clean, bp_status],
            ["Heart Rate", f"{vitals.heart_rate} bpm" if vitals.heart_rate else "Not recorded", hr_status],
            ["Temperature", f"{vitals.temperature} °F" if vitals.temperature else "Not recorded", temp_status],
            ["Oxygen Saturation", f"{vitals.oxygen_saturation}%" if vitals.oxygen_saturation else "Not recorded", oxy_status],
            ["Respiration Rate", f"{vitals.respiration_rate} /min" if vitals.respiration_rate else "Not recorded", resp_status],
            ["Height", f"{vitals.height} cm" if vitals.height else "Not recorded", ""],
            ["Weight", f"{vitals.weight} kg" if vitals.weight else "Not recorded", ""],
            ["BMI", f"{vitals.bmi:.1f}" if vitals.bmi else "Not calculated", bmi_status]
        ]
        
        vitals_table = Table(vitals_data, colWidths=[2*inch, 2*inch, 1.5*inch])
        vitals_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#28a745')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f1f8e9')),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),
            ('TEXTCOLOR', (2, 1), (2, -1), colors.green),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c8e6c9')),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        
        vitals_section.append(vitals_table)
        vitals_section.append(Spacer(1, 20))
        elements.append(KeepTogether(vitals_section))
    
    # Medications Section
    if encounter.medications:
        medications_section = []
        medications_section.append(Paragraph("PRESCRIBED MEDICATIONS", styles['CustomHeading2']))
        
        med_data = [["Medication", "Dosage", "Frequency", "Route", "Duration"]]
        for med in encounter.medications:
            # Clean medication data directly
            med_name = str(med.medication_name).replace('<b>', '').replace('</b>', '')
            dosage = str(med.dosage).replace('<b>', '').replace('</b>', '')
            frequency = str(med.frequency).replace('<b>', '').replace('</b>', '')
            route = str(med.route).replace('<b>', '').replace('</b>', '')
            
            duration = "Ongoing"
            if med.start_date and med.end_date:
                days = (med.end_date - med.start_date).days
                duration = f"{days} days"
            elif med.start_date:
                duration = "From " + med.start_date.strftime('%m/%d/%Y')
            
            med_data.append([med_name, dosage, frequency, route, duration])
        
        med_table = Table(med_data, colWidths=[1.8*inch, 1.2*inch, 1.2*inch, 1*inch, 1.3*inch])
        med_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6f42c1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0cffc')),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f0ff')]),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        
        medications_section.append(med_table)
        medications_section.append(Spacer(1, 20))
        elements.append(KeepTogether(medications_section))
    
    # Lab Tests if required
    if encounter.is_lab_test_required:
        lab_section = []
        lab_section.append(Paragraph("LABORATORY TESTS", styles['CustomHeading2']))
        lab_data = [
            ["Test Required", "Status", "Priority"],
            ["Laboratory Analysis", "Ordered", "Routine"]
        ]
        
        lab_table = Table(lab_data, colWidths=[3*inch, 2*inch, 2*inch])
        lab_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fd7e14')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ffe5d0')),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fff5e6')),
        ]))
        
        lab_section.append(lab_table)
        lab_section.append(Spacer(1, 20))
        elements.append(KeepTogether(lab_section))
    
    # Footer Section - Use hospital data
    elements.append(Spacer(1, 30))
    footer_data = [
        [Paragraph(hospital_name, ParagraphStyle(name='Footer', fontSize=10, textColor=colors.HexColor('#7f8c8d'), alignment=1))],
        [Paragraph(hospital_address, ParagraphStyle(name='Footer', fontSize=9, textColor=colors.HexColor('#95a5a6'), alignment=1))],
        [Paragraph(f"Report ID: ENC-{encounter.id}-{datetime.now().strftime('%Y%m%d')}", ParagraphStyle(name='Footer', fontSize=8, textColor=colors.HexColor('#bdc3c7'), alignment=1))],
        [Paragraph(f"Hospital ID: {hospital_id}", ParagraphStyle(name='Footer', fontSize=8, textColor=colors.HexColor('#bdc3c7'), alignment=1))],
        [Paragraph("CONFIDENTIAL - For Medical Use Only", ParagraphStyle(name='Footer', fontSize=8, textColor=colors.HexColor('#e74c3c'), alignment=1))],
    ]
    
    footer_table = Table(footer_data, colWidths=[7.5*inch])
    footer_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    
    elements.append(footer_table)
    
    # Build PDF
    doc.build(elements)
    
   
    # Get PDF data
    pdf_data = buffer.getvalue()
    buffer.close()
    
    # Create a temporary file-like object for S3 upload
    pdf_file = BytesIO(pdf_data)
    filename = f"encounter_{encounter_id}_summary.pdf"

    pdf_file.filename = filename  # required for S3 function
    pdf_file.name = filename      # optional but ok

    
    # Upload to S3
    file_path = await upload_encounter_document_to_s3(
        hospital_id=encounter.hospital_id,
        patient_id=encounter.patient_id,
        encounter_id=encounter.id,
        file=pdf_file
    )
    
    # Update encounter documents array
    current_docs = encounter.documents or []
    current_docs.append(file_path)
    encounter.documents = current_docs
    
    await db.commit()
    await db.refresh(encounter)
    
    # Return updated encounter
    return encounter

# GET ALL DOCTORS
@router.get("/doctors")
async def get_all_doctors(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ["doctor", "hospital"]:
        raise HTTPException(403, "Not allowed")

    result = await db.execute(select(Doctor))
    doctors = result.unique().scalars().all()

    return doctors


async def check_encounter_access(encounter, current_user, db):
    # PATIENT
    if current_user.role == "patient":
        r = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
        patient = r.unique().scalar_one_or_none()
        if not patient or patient.id != encounter.patient_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # DOCTOR
    elif current_user.role == "doctor":
        r = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
        doctor = r.unique().scalar_one_or_none()
        if not doctor or doctor.id != encounter.doctor_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # ONLY HOSPITAL USERS ALLOWED
    elif current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Access denied")

    return True

# View PDF securely (inline)
@router.get("/{encounter_id}/view/{doc_index}")
async def view_encounter_document(
    encounter_id: int,
    doc_index: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Fetch encounter
    q = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    
    encounter = q.unique().scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # RBAC
    await check_encounter_access(encounter, current_user, db)

    # Validate index
    if not encounter.documents or doc_index >= len(encounter.documents):
        raise HTTPException(404, "Document not found")

    file_key = encounter.documents[doc_index]

    # Create presigned URL for INLINE view
    presigned_url = generate_presigned_url(file_key, disposition="inline")

    # Fetch from S3
    async with aiohttp.ClientSession() as session:
        async with session.get(presigned_url) as resp:
            if resp.status != 200:
                raise HTTPException(resp.status, "Failed to fetch file from S3")
            file_data = BytesIO(await resp.read())

    filename = file_key.split("/")[-1]

    return StreamingResponse(
        file_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )

# Download PDF securely (attachment)
@router.get("{encounter_id}/download/{doc_index}")
async def download_encounter_document(
    encounter_id: int,
    doc_index: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Fetch encounter
    q = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    
    encounter = q.unique().scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # RBAC
    await check_encounter_access(encounter, current_user, db)

    # Validate index
    if not encounter.documents or doc_index >= len(encounter.documents):
        raise HTTPException(404, "Document not found")

    file_key = encounter.documents[doc_index]

    # Presigned URL for ATTACHMENT
    presigned_url = generate_presigned_url(file_key, disposition="attachment")

    # Stream from S3
    async with aiohttp.ClientSession() as session:
        async with session.get(presigned_url) as resp:
            if resp.status != 200:
                raise HTTPException(resp.status, "Failed to fetch file from S3")
            file_data = BytesIO(await resp.read())

    filename = file_key.split("/")[-1]

    return StreamingResponse(
        file_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# Function to generate care plan for an encounter
async def generate_care_plan_for_encounter(encounter_id: int, user_id: int, db: AsyncSession):
    """
    Background task to generate a care plan for a completed encounter
    """
    try:
        # Get the encounter with all related data
        result = await db.execute(
            select(Encounter)
            .options(
                selectinload(Encounter.vitals),
                selectinload(Encounter.medications),
                selectinload(Encounter.doctor),
                selectinload(Encounter.hospital),
                selectinload(Encounter.patient),
                selectinload(Encounter.lab_orders)
            )
            .where(Encounter.id == encounter_id)
        )
        encounter = result.unique().scalar_one_or_none()
        
        if not encounter:
            print(f"Encounter {encounter_id} not found for care plan generation")
            return
        
        # Get the user
        user_result = await db.execute(select(models.User).where(models.User.id == user_id))
        user = user_result.scalars().first()
        
        if not user:
            print(f"User {user_id} not found for care plan generation")
            return
        
        # Calculate patient age
        patient = encounter.patient
        today = datetime.now().date()
        age = today.year - patient.dob.year
        if today.month < patient.dob.month or (today.month == patient.dob.month and today.day < patient.dob.day):
            age -= 1
        
        # Prepare input data for care plan generation
        input_data = CarePlanGenerationInput(
            context_id=f"ctx_{encounter_id}",
            patient_profile=PatientProfile(
                age=age,
                gender=patient.gender,
                smoking_status=patient.smoking_status,
                alcohol_use=patient.alcohol_use,
                pregnancy_status=False  # Default value, could be updated based on patient data
            ),
            current_encounter=CurrentEncounter(
                encounter_id=str(encounter.id),
                encounter_type=encounter.encounter_type,
                reason_for_visit=encounter.reason_for_visit,
                diagnosis_text=encounter.diagnosis,
                icd_codes=[],  # Would need to extract from diagnosis if available
                encounter_date=encounter.encounter_date,
                follow_up_date=encounter.follow_up_date,
                clinical_notes=encounter.notes
            ),
            current_vitals=CurrentVitals(
                blood_pressure=encounter.vitals[0].blood_pressure if encounter.vitals else None,
                heart_rate=encounter.vitals[0].heart_rate if encounter.vitals else None,
                respiratory_rate=encounter.vitals[0].respiration_rate if encounter.vitals else None,
                temperature=encounter.vitals[0].temperature if encounter.vitals else None,
                bmi=encounter.vitals[0].bmi if encounter.vitals else None,
                oxygen_saturation=encounter.vitals[0].oxygen_saturation if encounter.vitals else None,
                height_cm=float(encounter.vitals[0].height) if encounter.vitals and encounter.vitals[0].height else None,
                weight_kg=float(encounter.vitals[0].weight) if encounter.vitals and encounter.vitals[0].weight else None
            ),
            current_medications=[
                MedicationInfo(
                    medication_name=med.medication_name,
                    dosage=med.dosage,
                    frequency=med.frequency,
                    route=med.route,
                    start_date=med.start_date,
                    stop_date=med.end_date
                )
                for med in encounter.medications
            ] if encounter.medications else [],
            lab_orders=[
                LabInfo(
                    lab_test=lab.test_name or lab.test_code,
                    status=lab.status,
                    result_value=None,
                    result_date=None,
                    lab_report_url=None
                )
                for lab in encounter.lab_orders
            ] if encounter.lab_orders else [],
            medical_history=MedicalHistory(
                chronic_conditions=[
                    ConditionInfo(
                        condition_name=encounter.diagnosis,
                        icd_code=None
                    )
                ] if encounter.diagnosis else [],
                medication_history=[],
                allergies=[
                    AllergyInfo(
                        allergen=allergy.name,
                        reaction=None,
                        severity=None
                    )
                    for allergy in patient.allergies
                ] if patient.allergies else []
            ),
            guideline_rules=GuidelineRulesInfo(
                condition_group=encounter.diagnosis.split()[0] if encounter.diagnosis else "General",
                guideline_source="Standard of Care",
                rules_version="2025-01",
                rules_json={
                    "standard_of_care": True,
                    "follow_up_required": encounter.follow_up_date is not None,
                    "lab_tests_required": encounter.is_lab_test_required
                }
            )
        )
        
        # Call the care plan API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://localhost:8000/api/care-plans/generate",
                json=input_data.dict(),
                headers={
                    "Authorization": f"Bearer {user.token if hasattr(user, 'token') else ''}"
                }
            )
            
            if response.status_code == 200:
                print(f"Care plan generated successfully for encounter {encounter_id}")
            else:
                print(f"Failed to generate care plan for encounter {encounter_id}: {response.text}")
    
    except Exception as e:
        print(f"Error generating care plan for encounter {encounter_id}: {str(e)}")

# Endpoint to manually trigger care plan generation
@router.post("/{encounter_id}/generate-care-plan", response_model=EncounterOut)
async def trigger_care_plan_generation(
    encounter_id: int,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger care plan generation for an encounter
    """
    # Get the encounter
    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.patient)
        )
        .where(Encounter.id == encounter_id)
    )
    encounter = result.unique().scalar_one_or_none()
    
    if not encounter:
        raise HTTPException(404, "Encounter not found")
    
    # Check permissions
    if current_user.role == "doctor":
        doctor_result = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
        doctor = doctor_result.unique().scalar_one_or_none()
        
        if not doctor or doctor.id != encounter.doctor_id:
            raise HTTPException(403, "Not authorized to generate care plan for this encounter")
    elif current_user.role != "admin":
        raise HTTPException(403, "Only doctors and admins can generate care plans")
    
    # Schedule care plan generation
    background_tasks.add_task(
        generate_care_plan_for_encounter,
        encounter_id=encounter.id,
        user_id=current_user.id,
        db=db
    )
    
    # Update encounter status if not already completed
    if encounter.status != "completed":
        encounter.status = "completed"
        await db.commit()
        await db.refresh(encounter)
    
    # Build response
    response = EncounterOut.from_orm(encounter)
    response.doctor_name = f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
    response.hospital_name = encounter.hospital.name
    response.patient_public_id = encounter.patient.public_id
    
    return response
