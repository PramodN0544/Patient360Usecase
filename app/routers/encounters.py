import ast
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import EncounterHistory
from typing import List
from datetime import date, datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib import colors
from io import BytesIO
import os
import json

from app.database import get_db
from app.models import Encounter, Doctor, Patient, Vitals, Medication, Assignment
from app.schemas import EncounterCreate, EncounterOut, EncounterUpdate
from app.auth import get_current_user
from app.S3connection import upload_encounter_document_to_s3

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
    encounter_id: int,
    encounter_in: str = Form(...),
    files: List[UploadFile] | None = File(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Parse incoming JSON safely
    parsed_data = json.loads(encounter_in)
    print(f"📥 Incoming update payload: {parsed_data}")

    encounter_update = EncounterUpdate(**parsed_data)
    
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

    # Permission Check
    doctor_result = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
    doctor = doctor_result.unique().scalar_one_or_none()

    if not doctor and current_user.role != "hospital":
        raise HTTPException(403, "Not allowed")

    # ---------------- MAIN FIELD UPDATE ----------------
    for field, value in encounter_update.dict(exclude_unset=True).items():
        if field not in ["vitals", "medications", "lab_orders", "previous_encounter_id", "is_continuation"]:
            if value is not None:
                setattr(encounter, field, value)

    # ---------------- FOLLOW-UP LOGIC ----------------
    if encounter_update.follow_up_date:
        encounter.is_continuation = True
        encounter.status = "in_progress"

        # Auto-link to previous encounter if none supplied
        if not encounter_update.previous_encounter_id:
            prev = await db.execute(
                select(Encounter)
                .where(Encounter.patient_id == encounter.patient_id)
                .where(Encounter.id != encounter.id)
                .order_by(Encounter.encounter_date.desc())
            )
            encounter.previous_encounter_id = prev.scalars().first().id if prev else None

    else:
        encounter.is_continuation = False
        encounter.previous_encounter_id = None
        encounter.status = "completed"

    # ---------------- UPDATE VITALS IF SENT ----------------
    if encounter_update.vitals is not None:
        vitals_result = await db.execute(select(Vitals).where(Vitals.encounter_id == encounter.id))
        vitals = vitals_result.unique().scalar_one_or_none()

        if vitals:
            for key, val in encounter_update.vitals.dict(exclude_unset=True).items():
                setattr(vitals, key, val)
        else:
            db.add(Vitals(encounter_id=encounter.id, **encounter_update.vitals.dict()))

    # ---------------- UPDATE MEDICATIONS ----------------
    if encounter_update.medications is not None:
        await db.execute(Medication.__table__.delete().where(Medication.encounter_id == encounter.id))

        for m in encounter_update.medications:
            db.add(Medication(
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                **m.dict()
            ))

    # ---------------- LAB ORDERS (Only if required) ----------------
    if encounter_update.lab_orders is not None and encounter_update.is_lab_test_required:
        await db.execute(LabOrder.__table__.delete().where(LabOrder.encounter_id == encounter.id))

        for lab in encounter_update.lab_orders:
            db.add(LabOrder(
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                test_code=lab["test_code"],
                test_name=lab["test_name"],
                status="ordered"
            ))

    # ---------------- FILE UPLOAD ----------------
    if files:
        docs = encounter.documents or []
        for file in files:
            s3_url = await upload_encounter_document_to_s3(
                hospital_id=encounter.hospital_id,
                patient_id=encounter.patient_id,
                encounter_id=encounter.id,
                file=file
            )
            docs.append(s3_url)

        encounter.documents = docs

    # ---------------- HISTORY LOG ----------------
    db.add(EncounterHistory(
        encounter_id=encounter.id,
        status=encounter.status,
        updated_by=current_user.id,
        notes="Encounter updated"
    ))

    await db.commit()
    await db.refresh(encounter)

    # ---------------- RESPONSE ----------------
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
            if not assign.unique().scalar_one_or_none():
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
    if not assign.unique().scalar_one_or_none():
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
            selectinload(LabOrder)   # 👈 Added lab orders
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
    # Get the encounter with all related data
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
    
    # Verify permissions
    if current_user.role == "doctor" and encounter.doctor.user_id != current_user.id:
        raise HTTPException(403, "Not authorized to access this encounter")
    if current_user.role == "patient" and encounter.patient.user_id != current_user.id:
        raise HTTPException(403, "Not authorized to access this encounter")
    
    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []
    
    # Add CareIQ logo
    possible_paths = [
        os.path.join("static", "mylogo.jpg"),
        os.path.join("Patient360-Backend", "static", "mylogo.jpg"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "mylogo.jpg"))
    ]
    
    logo_found = False
    for logo_path in possible_paths:
        if os.path.exists(logo_path):
            elements.append(Image(logo_path, width=150, height=70))
            logo_found = True
            break
    
    if not logo_found:
        elements.append(Paragraph("CareIQ", styles['Heading1']))
        elements.append(Paragraph("Patient 360° Healthcare Platform", styles['Italic']))
    
    elements.append(Spacer(1, 12))
    
    # Add title
    elements.append(Paragraph("Patient Encounter Report", styles['Heading1']))
    elements.append(Spacer(1, 12))
    
    # Add encounter details
    elements.append(Paragraph(f"Encounter ID: {encounter.id}", styles['Heading3']))
    elements.append(Paragraph(f"Date: {encounter.encounter_date.strftime('%B %d, %Y')}", styles['Normal']))
    elements.append(Paragraph(f"Type: {encounter.encounter_type}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Add patient information
    elements.append(Paragraph("Patient Information", styles['Heading2']))
    elements.append(Paragraph(f"Name: {encounter.patient.first_name} {encounter.patient.last_name}", styles['Normal']))
    elements.append(Paragraph(f"ID: {encounter.patient.public_id}", styles['Normal']))
    elements.append(Paragraph(f"DOB: {encounter.patient.dob.strftime('%B %d, %Y')}", styles['Normal']))
    elements.append(Paragraph(f"Gender: {encounter.patient.gender}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Add doctor information
    elements.append(Paragraph("Doctor Information", styles['Heading2']))
    elements.append(Paragraph(f"Name: Dr. {encounter.doctor.first_name} {encounter.doctor.last_name}", styles['Normal']))
    elements.append(Paragraph(f"Specialty: {encounter.doctor.specialty}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Add reason for visit and diagnosis
    elements.append(Paragraph("Clinical Information", styles['Heading2']))
    elements.append(Paragraph(f"Reason for Visit: {encounter.reason_for_visit}", styles['Normal']))
    elements.append(Paragraph(f"Diagnosis: {encounter.diagnosis or 'None provided'}", styles['Normal']))
    elements.append(Paragraph(f"Notes: {encounter.notes or 'None provided'}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Add vitals if available
    if encounter.vitals:
        elements.append(Paragraph("Vitals", styles['Heading2']))
        vitals_data = [
            ["Measurement", "Value"],
            ["Height", f"{encounter.vitals[0].height} cm" if encounter.vitals[0].height else "Not recorded"],
            ["Weight", f"{encounter.vitals[0].weight} kg" if encounter.vitals[0].weight else "Not recorded"],
            ["BMI", f"{encounter.vitals[0].bmi}" if encounter.vitals[0].bmi else "Not calculated"],
            ["Blood Pressure", encounter.vitals[0].blood_pressure or "Not recorded"],
            ["Heart Rate", f"{encounter.vitals[0].heart_rate} bpm" if encounter.vitals[0].heart_rate else "Not recorded"],
            ["Temperature", f"{encounter.vitals[0].temperature} °F" if encounter.vitals[0].temperature else "Not recorded"],
            ["Respiration Rate", f"{encounter.vitals[0].respiration_rate} /min" if encounter.vitals[0].respiration_rate else "Not recorded"],
            ["Oxygen Saturation", f"{encounter.vitals[0].oxygen_saturation}%" if encounter.vitals[0].oxygen_saturation else "Not recorded"]
        ]
        
        vitals_table = Table(vitals_data, colWidths=[200, 300])
        vitals_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.lightblue),
            ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (1, 0), 12),
            ('BACKGROUND', (0, 1), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(vitals_table)
        elements.append(Spacer(1, 12))
    
    # Add medications if available
    if encounter.medications:
        elements.append(Paragraph("Medications", styles['Heading2']))
        
        med_data = [["Medication", "Dosage", "Frequency", "Route", "Start Date", "End Date"]]
        for med in encounter.medications:
            med_data.append([
                med.medication_name,
                med.dosage,
                med.frequency,
                med.route,
                med.start_date.strftime('%m/%d/%Y') if med.start_date else "N/A",
                med.end_date.strftime('%m/%d/%Y') if med.end_date else "Ongoing"
            ])
        
        med_table = Table(med_data, colWidths=[100, 80, 80, 80, 80, 80])
        med_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(med_table)
        elements.append(Spacer(1, 12))
    
    # Add lab tests if required
    if encounter.is_lab_test_required:
        elements.append(Paragraph("Lab Tests Ordered", styles['Heading2']))
        elements.append(Paragraph("Lab tests have been ordered for this patient.", styles['Normal']))
        elements.append(Spacer(1, 12))
    
    # Add footer with timestamp
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%B %d, %Y %H:%M:%S')}", styles['Normal']))
    elements.append(Paragraph("CareIQ Patient 360 - Confidential Medical Record", styles['Normal']))
    
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
    doctors = result.scalars().all()

    return doctors