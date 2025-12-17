import ast
import aiohttp
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import EncounterHistory, Hospital
from sqlalchemy import or_
from app.models import IcdCodeMaster, EncounterIcdCode  # Add these models
from app.models import EncounterHistory
from typing import List
from datetime import date, datetime, timedelta
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
from app.models import Encounter, Doctor, Patient, Vitals, Medication, Assignment, LabOrder, User
from app.schemas import EncounterCreate, EncounterOut, EncounterUpdate, LabTestDetail, CarePlanGenerationInput, PatientProfile, CurrentEncounter, CurrentVitals, MedicationInfo, LabInfo, MedicalHistory, ConditionInfo, MedicationHistoryInfo, AllergyInfo, GuidelineRulesInfo
from app.auth import get_current_user
from app.S3connection import generate_presigned_url, upload_encounter_document_to_s3

router = APIRouter(prefix="/encounters", tags=["Encounters"])

def calculate_status(enc):
    # If nothing filled yet → pending (doctor just opened encounter)
    if not (enc.diagnosis or enc.notes or enc.vitals):
        return "pending"

    # If follow-up given → encounter is still active
    if enc.follow_up_date:
        return "in-progress"

    # If details filled but no follow-up → completed
    return "completed"

def safe_parse(data: str):
    try:
        return json.loads(data)
    except:
        try:
            return ast.literal_eval(data)
        except:
            raise HTTPException(422, "Invalid encounter_in format")

# CREATE ENCOUNTER (FINAL FIXED VERSION)
@router.post("/", response_model=EncounterOut)
async def create_encounter(
    encounter_in: str = Form(...),
    files: List[UploadFile] | None = File(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    parsed_data = json.loads(encounter_in)
    encounter_in = EncounterCreate(**parsed_data)

    # ------------------ VALIDATE DOCTOR ------------------
    if current_user.role == "doctor":
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalar_one_or_none()

        if not doctor:
            raise HTTPException(403, "Doctor profile not found for this user")

    elif current_user.role == "hospital":
        if not parsed_data.get("doctor_id"):
            raise HTTPException(400, "doctor_id is required for hospital users")

        doctor_result = await db.execute(
            select(Doctor).where(
                Doctor.id == parsed_data["doctor_id"],
                Doctor.hospital_id == current_user.hospital_id
            )
        )
        doctor = doctor_result.scalar_one_or_none()

        if not doctor:
            raise HTTPException(404, "Doctor not found in your hospital")

    else:
        raise HTTPException(403, "Only doctors or hospitals can create encounters")

    # ------------------ VALIDATE PATIENT ------------------
    if not encounter_in.patient_public_id:
        raise HTTPException(400, "patient_public_id is required")

    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == encounter_in.patient_public_id)
    )
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Patient not found")

    # ------------------ VALIDATE ASSIGNMENT ------------------
    assign = await db.execute(
        select(Assignment).where(
            Assignment.patient_id == patient.id,
            Assignment.doctor_id == doctor.id
        )
    )
    assignment_record = assign.first()  # SAFE: even if duplicates exist

    if not assignment_record:
        raise HTTPException(403, "Doctor is not assigned to this patient")

    # ------------------ CREATE ENCOUNTER ------------------
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
        
        # ALWAYS start with pending
        status="pending",

        documents=[]
    )

    if encounter_in.primary_icd_code_id:
        icd_result = await db.execute(
            select(IcdCodeMaster).where(
                IcdCodeMaster.id == encounter_in.primary_icd_code_id,
                IcdCodeMaster.is_active == True
            )
        )
        if not icd_result.scalar_one_or_none():
            raise HTTPException(400, "Primary ICD code not found or inactive")

        new_encounter.primary_icd_code_id = encounter_in.primary_icd_code_id

    db.add(new_encounter)
    await db.flush()

    if encounter_in.icd_codes:
        for icd_data in encounter_in.icd_codes:

            icd_result = await db.execute(
                select(IcdCodeMaster).where(
                    IcdCodeMaster.id == icd_data.icd_code_id,
                    IcdCodeMaster.is_active == True
                )
            )
            icd = icd_result.scalar_one_or_none()
            if not icd:
                raise HTTPException(400, f"ICD {icd_data.icd_code_id} not found")

            db.add(EncounterIcdCode(
                encounter_id=new_encounter.id,
                icd_code_id=icd_data.icd_code_id,
                is_primary=icd_data.is_primary,
                notes=icd_data.notes
            ))

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
                notes=m.notes
            ))

    if files:
        docs = []
        for file in files:
            file_path = await upload_encounter_document_to_s3(
                hospital_id=doctor.hospital_id,
                patient_id=patient.id,
                encounter_id=new_encounter.id,
                file=file
            )
            docs.append(file_path)
        new_encounter.documents = docs

    # ------------------ CONTINUATION LOGIC ------------------
    if encounter_in.follow_up_date:
        prev_enc_result = await db.execute(
            select(Encounter)
            .where(
                Encounter.patient_id == patient.id,
                Encounter.id != new_encounter.id
            )
            .order_by(Encounter.encounter_date.desc())
        )
        previous_encounter = prev_enc_result.unique().scalars().first()

        new_encounter.previous_encounter_id = (
            previous_encounter.id if previous_encounter else None
        )

        db.add(EncounterHistory(
            encounter_id=new_encounter.id,
            status="FOLLOW_UP_SCHEDULED",
            updated_by=current_user.id,
            notes="Follow-up created"
        ))

    await db.commit()
    await db.refresh(new_encounter)

    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.patient),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.icd_codes).selectinload(EncounterIcdCode.icd_code),
            selectinload(Encounter.primary_icd_code),
        )
        .where(Encounter.id == new_encounter.id)
    )

    enc = result.unique().scalar_one()
    out = EncounterOut.from_orm(enc)
    out.doctor_name = f"{doctor.first_name} {doctor.last_name}"
    out.hospital_name = doctor.hospital.name
    out.patient_public_id = patient.public_id

    out.icd_codes = [
        {
            "id": ec.id,
            "icd_code_id": ec.icd_code_id,
            "code": ec.icd_code.code,
            "name": ec.icd_code.name,
            "is_primary": ec.is_primary,
            "notes": ec.notes,
            "created_at": ec.created_at
        }
        for ec in enc.icd_codes
    ]

    return out


@router.put("/{encounter_id}", response_model=EncounterOut)
async def update_encounter(
    encounter_id: int,
    encounter_in: str = Form(...),
    files: List[UploadFile] | None = File(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # -------------------------------------------------
    # 1. Parse JSON
    # -------------------------------------------------
    try:
        parsed = json.loads(encounter_in)
    except Exception:
        raise HTTPException(400, "Invalid JSON format in encounter_in")

    # -------------------------------------------------
    # 2. Normalize follow_up_date
    # -------------------------------------------------
    follow_up_raw = parsed.get("follow_up_date")
    if not follow_up_raw or str(follow_up_raw).strip() == "":
        parsed["follow_up_date"] = None
    else:
        try:
            parsed["follow_up_date"] = datetime.strptime(
                follow_up_raw, "%Y-%m-%d"
            ).date()
        except Exception:
            raise HTTPException(400, "Invalid follow_up_date format (YYYY-MM-DD)")

    # -------------------------------------------------
    # 3. Create EncounterUpdate FIRST (IMPORTANT)
    # -------------------------------------------------
    try:
        encounter_update = EncounterUpdate(**parsed)
    except Exception as e:
        raise HTTPException(400, f"Invalid encounter fields: {e}")

    # -------------------------------------------------
    # 4. Fetch Encounter
    # -------------------------------------------------
    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.lab_orders),
            selectinload(Encounter.patient),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
        )
        .where(Encounter.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # -------------------------------------------------
    # 5. Authorization
    # -------------------------------------------------
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()

    if not doctor or doctor.id != encounter.doctor_id:
        raise HTTPException(403, "You can update only your own encounters")

    if encounter.status == "completed":
        raise HTTPException(400, "Completed encounters cannot be modified")

    # -------------------------------------------------
    # 6. PRIMARY ICD CODE (ID + CODE)
    # -------------------------------------------------
    if encounter_update.primary_icd_code_id is not None:
        icd_result = await db.execute(
            select(IcdCodeMaster).where(
                IcdCodeMaster.id == encounter_update.primary_icd_code_id
            )
        )
        icd = icd_result.scalar_one_or_none()

        if not icd:
            raise HTTPException(400, "Invalid primary_icd_code_id")

        encounter.primary_icd_code_id = icd.id
        encounter.primary_icd_code_value = icd.code
    else:
        encounter.primary_icd_code_id = None
        encounter.primary_icd_code_value = None

    scalar_exclude = {"vitals", "medications", "lab_orders", "primary_icd_code_id"}

    for field, value in encounter_update.dict(exclude_none=True).items():
        if field in scalar_exclude:
            continue
        setattr(encounter, field, value)

    encounter.is_continuation = encounter.follow_up_date is not None
    encounter.status = "in-progress" if encounter.follow_up_date else "completed"

    if encounter_update.vitals:
        vitals_result = await db.execute(
            select(Vitals).where(Vitals.encounter_id == encounter.id)
        )
        vitals = vitals_result.scalar_one_or_none()

        if not vitals:
            vitals = Vitals(
                encounter_id=encounter.id,
                patient_id=encounter.patient_id
            )
            db.add(vitals)

        for k, v in encounter_update.vitals.dict(exclude_none=True).items():
            setattr(vitals, k, v)

        if vitals.height and vitals.weight:
            try:
                vitals.bmi = round(
                    vitals.weight / ((vitals.height / 100) ** 2), 2
                )
            except Exception:
                vitals.bmi = None

    if encounter_update.medications is not None:
        meds_result = await db.execute(
            select(Medication).where(Medication.encounter_id == encounter.id)
        )
        existing_meds = {m.id: m for m in meds_result.scalars().all()}

        for med in encounter_update.medications:
            data = med.dict(exclude_none=True)
            med_id = data.get("id")

            if med_id and med_id in existing_meds:
                for k, v in data.items():
                    setattr(existing_meds[med_id], k, v)
            else:
                db.add(Medication(
                    encounter_id=encounter.id,
                    patient_id=encounter.patient_id,
                    doctor_id=encounter.doctor_id,
                    **data
                ))

    if encounter_update.lab_orders is not None:
        orders_result = await db.execute(
            select(LabOrder).where(LabOrder.encounter_id == encounter.id)
        )
        existing_orders = {o.id: o for o in orders_result.scalars().all()}

        for order in encounter_update.lab_orders:
            data = order.dict(exclude_none=True)
            order_id = data.pop("id", None)

            if order_id and order_id in existing_orders:
                for k, v in data.items():
                    setattr(existing_orders[order_id], k, v)
            else:
                db.add(LabOrder(
                    encounter_id=encounter.id,
                    patient_id=encounter.patient_id,
                    doctor_id=encounter.doctor_id,
                    **data
                ))

    if files:
        docs = encounter.documents or []
        for f in files:
            url = await upload_encounter_document_to_s3(
                hospital_id=encounter.hospital_id,
                patient_id=encounter.patient_id,
                encounter_id=encounter.id,
                file=f
            )
            docs.append(url)
        encounter.documents = docs

    db.add(EncounterHistory(
        encounter_id=encounter.id,
        status=encounter.status,
        updated_by=current_user.id,
        notes="Encounter updated"
    ))

    await db.commit()

    # -------------------------------------------------
    # 13. Refresh & return
    # -------------------------------------------------
    refreshed = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.lab_orders),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.patient),
        )
        .where(Encounter.id == encounter.id)
    )

    return EncounterOut.from_orm(refreshed.scalar_one())


# GET ALL ENCOUNTERS FOR A PATIENT (BY PUBLIC ID) - For Patient Dashboard
@router.get("/patient/{public_id}")
async def get_patient_encounters(
    public_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == public_id)
    )
    patient = patient_result.unique().scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    # ----- Permission check -----
    if current_user.role == "doctor":
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
        if patient.user_id != current_user.id:
            raise HTTPException(403, "You can only view your own encounters")

    stmt = (
        select(Encounter)
        
        .where(Encounter.patient_id == patient.id)
        .order_by(Encounter.encounter_date.desc(), Encounter.created_at.desc())
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital)
        )
    )

    result = await db.execute(stmt)
    encounters = result.scalars().unique().all()

    response = []
    for e in encounters:
        response.append({
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
            "doctor_name": f"{e.doctor.first_name} {e.doctor.last_name}" if e.doctor else None,
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
        })

    return response

@router.get("/doctor/patient/{public_id}")
async def get_doctor_patient_encounters(
    public_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "doctor":
        raise HTTPException(403, "Only doctors can access this endpoint")

    # Get doctor
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.unique().scalar_one_or_none()
    
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    
    # Get patient
    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == public_id)
    )
    patient = patient_result.unique().scalar_one_or_none()
    
    if not patient:
        raise HTTPException(404, "Patient not found")

    # Check assignment
    assign = await db.execute(
        select(Assignment).where(
            Assignment.patient_id == patient.id,
            Assignment.doctor_id == doctor.id
        )
    )
    if not assign.scalars().first():
        raise HTTPException(403, "Doctor is not assigned to this patient")
    
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
            selectinload(Encounter.lab_orders)
        )
    )

    result = await db.execute(stmt)
    encounters = result.scalars().unique().all()

    return [
        {
            "id": e.id,
            "status": e.status,
            "encounter_date": e.encounter_date,
            "follow_up_date": e.follow_up_date,
            "previous_encounter_id": e.previous_encounter_id
        }
        for e in encounters
    ]


@router.get("/my-encounters")
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
            selectinload(Encounter.hospital),
            selectinload(Encounter.patient),
            selectinload(Encounter.lab_orders)  
        )
        .where(Encounter.patient_id == patient.id)
        .order_by(Encounter.encounter_date.desc())
    )

    encounters = result.scalars().unique().all()

    response = []
    for e in encounters:
        response.append({
            "id": e.id,
            "encounter_date": e.encounter_date,
            "encounter_type": e.encounter_type,
            "reason_for_visit": e.reason_for_visit,
            "status": e.status,
            "notes": e.notes,
            "diagnosis": e.diagnosis,
            "follow_up_date": e.follow_up_date,
            "patient_public_id": e.patient.public_id,
            "doctor_name": f"{e.doctor.first_name} {e.doctor.last_name}",
            "hospital_name": e.hospital.name,
            "vitals": e.vitals[0].__dict__ if e.vitals else None,
            "medications": [
                {
                    "id": m.id,
                    "medication_name": m.medication_name,
                    "dosage": m.dosage,
                    "route": m.route,
                    "frequency": m.frequency,
                    "start_date": m.start_date,
                }
                for m in e.medications
            ],
            "lab_orders": [
                {
                    "id": lab.id,
                    "test_code": lab.test_code,
                    "test_name": lab.test_name,
                    "status": lab.status,
                }
                for lab in getattr(e, "lab_orders", [])
            ]
        })

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

@router.get("/{encounter_id}")
async def get_encounter(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Load everything with eager loading so no MissingGreenlet error
    query = (
        select(Encounter)
        .where(Encounter.id == encounter_id)
        .options(
            selectinload(Encounter.patient),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.patient),
            selectinload(Encounter.hospital),
            selectinload(Encounter.doctor),
            selectinload(Encounter.lab_orders),  # 👈 Added lab orders
            selectinload(Encounter.lab_orders),
            selectinload(Encounter.previous_encounter),
            selectinload(Encounter.icd_codes).selectinload(EncounterIcdCode.icd_code),
            selectinload(Encounter.primary_icd_code) 
        )
    )

    result = await db.execute(query)
    encounter = result.unique().scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # ---------- ACCESS CONTROL ----------
    if current_user.role == "patient" and encounter.patient.user_id != current_user.id:
        raise HTTPException(403, "Not authorized")
    
    if current_user.role == "doctor" and encounter.doctor.user_id != current_user.id:
        raise HTTPException(403, "Not authorized")

    # ---------- PATIENT DETAILS ----------
    patient = encounter.patient

    patient_details = {
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "dob": patient.dob,
        "gender": patient.gender,
        "ssn": patient.ssn or "Not provided",
        "marital_status": patient.marital_status or "Not specified",
        "height": float(patient.height) if patient.height else "Not recorded",
        "weight": float(patient.weight) if patient.weight else "Not recorded",
        "phone": patient.phone,
        "email": patient.email,
        "address": patient.address or "N/A",
        "city": patient.city,
        "state": patient.state,
        "zip_code": patient.zip_code,
        "country": patient.country,
    }

    # ---------- RESPONSE BUILD ----------
    response = {
        "id": encounter.id,
        "patient_public_id": encounter.patient.public_id,
        "patient_details": patient_details,
        "encounter_date": encounter.encounter_date,
        "encounter_type": encounter.encounter_type,
        "reason_for_visit": encounter.reason_for_visit,
        "diagnosis": encounter.diagnosis,
        "notes": encounter.notes,
        "follow_up_date": encounter.follow_up_date,
        "status": encounter.status,
        "is_lab_test_required": encounter.is_lab_test_required,
         "icd_codes": [
            {
                "id": ec.id,
                "code": ec.icd_code.code,
                "name": ec.icd_code.name,
                "is_primary": ec.is_primary,
                "notes": ec.notes,
                "created_at": ec.created_at
            }
            for ec in encounter.icd_codes
        ],
        "primary_icd_code": {
            "id": encounter.primary_icd_code.id,
            "code": encounter.primary_icd_code.code,
            "name": encounter.primary_icd_code.name
        } if encounter.primary_icd_code else None,

        "doctor_name": f"{encounter.doctor.first_name} {encounter.doctor.last_name}" if encounter.doctor else None,
        "hospital_name": encounter.hospital.name if encounter.hospital else None,

        # Return list instead of model objects
        "vitals": [
            {
                "id": v.id,
                "blood_pressure": v.blood_pressure,
                "heart_rate": v.heart_rate,
                "temperature": v.temperature,
                "weight": v.weight,
                "height": v.height,
                "bmi": v.bmi,
                "recorded_at": v.recorded_at
            } for v in encounter.vitals
        ],

        "medications": [
            {
                "id": m.id,
                "name": m.medication_name,
                "dosage": m.dosage,
                "frequency": m.frequency,
                "route": m.route,
                "status": m.status,
                "start_date": m.start_date,
                "end_date": m.end_date,
            } for m in encounter.medications
        ],

        # 🔥 ONLY return lab orders linked to this encounter
        "lab_orders": [
            {
                "id": lab.id,
                "test_code": lab.test_code,
                "test_name": lab.test_name,
                "status": lab.status,
                "sample_type": lab.sample_type,
                "created_at": lab.created_at
            }
            for lab in encounter.lab_orders
        ],

        "previous_encounter": {
            "id": encounter.previous_encounter.id,
            "date": encounter.previous_encounter.encounter_date,
            "status": encounter.previous_encounter.status
        } if encounter.previous_encounter else None
    }

    return response


# GENERATE PDF FOR ENCOUNTER
# GENERATE PDF FOR ENCOUNTER
@router.post("/{encounter_id}/generate-pdf", response_model=EncounterOut)
async def generate_encounter_pdf(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        print(f"🔄 PDF Generation called for encounter {encounter_id}")
        
        # Fetch encounter with ALL necessary relationships including lab_tests
        result = await db.execute(
            select(Encounter)
            .options(
                selectinload(Encounter.vitals),
                selectinload(Encounter.medications),
                selectinload(Encounter.lab_orders),  # ADD THIS for lab tests
                selectinload(Encounter.doctor),
                selectinload(Encounter.hospital),  
                selectinload(Encounter.patient)
            )
            .where(Encounter.id == encounter_id)
        )
        
        encounter = result.unique().scalar_one_or_none()
        if not encounter:
            raise HTTPException(404, "Encounter not found")
        
        # Permission check
        if current_user.role == "doctor" and encounter.doctor.user_id != current_user.id:
            raise HTTPException(403, "Not authorized to access this encounter")
        if current_user.role == "patient" and encounter.patient.user_id != current_user.id:
            raise HTTPException(403, "Not authorized to access this encounter")
        
        # Extract hospital details
        hospital_name = encounter.hospital.name if encounter.hospital else "Medical Center"
        hospital_id = encounter.hospital.id if encounter.hospital else "N/A"
        hospital_address = getattr(encounter.hospital, 'address', 'Address not available')
        hospital_phone = getattr(encounter.hospital, 'phone', 'Phone not available')
        
        print(f"🏥 Hospital: {hospital_name}, ID: {hospital_id}")
        print(f"📋 Lab Tests Required: {encounter.is_lab_test_required}")
        print(f"🔬 Lab Orders Count: {len(encounter.lab_orders) if encounter.lab_orders else 0}")
        
        buffer = BytesIO()
        # Reduce margins to create more space
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=50,  # Reduced from 72
            leftMargin=50,   # Reduced from 72
            topMargin=60,    # Reduced from 72
            bottomMargin=60  # Reduced from 72
        )
        
        # Define custom styles
        styles = getSampleStyleSheet()
        
        # Custom styles
        styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,  # Reduced from 20
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=10,
            alignment=1
        ))
        
        styles.add(ParagraphStyle(
            name='CustomHeading2',
            parent=styles['Heading2'],
            fontSize=12,  # Reduced from 14
            textColor=colors.HexColor('#2980b9'),
            spaceAfter=4,
            spaceBefore=8
        ))
        
        styles.add(ParagraphStyle(
            name='TableContent',
            parent=styles['Normal'],
            fontSize=8,  # Reduced from 9
            textColor=colors.black,
            wordWrap='CJK'
        ))
        
        styles.add(ParagraphStyle(
            name='SmallTableContent',
            parent=styles['Normal'],
            fontSize=7,  # Smaller font for tables
            textColor=colors.black,
            wordWrap='CJK'
        ))
        
        elements = []
        
        # Find logo
        possible_paths = [
            os.path.join("static", "mylogo.jpg"),
            os.path.join("Patient360-Backend", "static", "mylogo.jpg"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "mylogo.jpg"))
        ]
        
        logo_path = None
        logo_found = False
        for path in possible_paths:
            if os.path.exists(path):
                logo_path = path
                logo_found = True
                break
        
        print(f"🖼️ Logo found: {logo_found}, Path: {logo_path}")
        
        # Create header table
        if logo_found and logo_path:
            logo = Image(logo_path, width=100, height=40)  # Reduced size
            header_data = [
                [logo, 
                 Paragraph(hospital_name, ParagraphStyle(name='HospitalTitle', fontSize=14, alignment=0)),  # Reduced font
                 Paragraph(f"Hospital ID: {hospital_id}", ParagraphStyle(name='HospitalInfo', fontSize=8, alignment=2))],
                ['', 
                 Paragraph("Advanced Healthcare Solutions", ParagraphStyle(name='HospitalSub', fontSize=10, alignment=0, fontName='Helvetica-Oblique')),
                 Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle(name='HospitalInfo', fontSize=8, alignment=2))]
            ]
            col_widths = [1.5*inch, 3.5*inch, 2*inch]  # Adjusted widths
        else:
            header_data = [
                [Paragraph(hospital_name, ParagraphStyle(name='HospitalTitle', fontSize=16, alignment=0)),
                 Paragraph(f"Hospital ID: {hospital_id}", ParagraphStyle(name='HospitalInfo', fontSize=8, alignment=2))],
                [Paragraph("Advanced Healthcare Solutions", ParagraphStyle(name='HospitalSub', fontSize=10, alignment=0, fontName='Helvetica-Oblique')),
                 Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle(name='HospitalInfo', fontSize=8, alignment=2))]
            ]
            col_widths = [4.5*inch, 2*inch]
        
        header_table = Table(header_data, colWidths=col_widths)
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('SPAN', (0, 1), (-1, 1)),
        ]))
        
        elements.append(header_table)
        elements.append(Spacer(1, 16))  # Reduced space
        
        # Main Title
        elements.append(Paragraph("PATIENT ENCOUNTER REPORT", styles['CustomTitle']))
        elements.append(Spacer(1, 8))  # Reduced space
        
        # Get or calculate patient age
        def calculate_age(birth_date):
            today = datetime.now().date()
            age = today.year - birth_date.year
            if today.month < birth_date.month or (today.month == birth_date.month and today.day < birth_date.day):
                age -= 1
            return age
        
        # Check if patient has age field in database
        if encounter.patient.age is not None:
            patient_age = encounter.patient.age
            print(f"🖨️ Using stored patient age from database for PDF: {patient_age}")
        else:
            patient_age = calculate_age(encounter.patient.dob)
            # Store the calculated age in the database for future use
            encounter.patient.age = patient_age
            await db.commit()
            print(f"🖨️ Patient age calculated and stored in database for PDF: {patient_age}")
        
        # Patient and Doctor Information - Fixed to fit within page
        patient_info = [
            ["PATIENT INFORMATION", ""],
            ["Patient Name:", f"{encounter.patient.first_name} {encounter.patient.last_name}"],
            ["Patient ID:", encounter.patient.public_id],
            ["Date of Birth:", encounter.patient.dob.strftime('%Y-%m-%d')],  # Shorter date format
            ["Age:", f"{patient_age} years"],
            ["Gender:", encounter.patient.gender.capitalize()],
            ["Phone:", encounter.patient.phone or "N/A"],
            ["Email:", Paragraph(encounter.patient.email or "N/A", ParagraphStyle(name='WrappedText', fontSize=8))]
        ]
        
        doctor_info = [
            ["DOCTOR INFORMATION", ""],
            ["Doctor Name:", f"Dr. {encounter.doctor.first_name} {encounter.doctor.last_name}"],
            ["Specialty:", encounter.doctor.specialty],
            ["Doctor ID:", f"DR-{encounter.doctor.id:04d}"],
            ["License No:", Paragraph(encounter.doctor.license_number or "N/A", ParagraphStyle(name='WrappedText', fontSize=8))],
            ["Phone:", encounter.doctor.phone or "N/A"]
        ]
        
        # Create tables with adjusted widths
        patient_table = Table(patient_info, colWidths=[2*inch, 2*inch])  # Reduced widths
        doctor_table = Table(doctor_info, colWidths=[2*inch, 2*inch])  # Reduced widths
        
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#ecf0f1')),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TEXTCOLOR', (0, 1), (0, -1), colors.HexColor('#495057')),
            ('FONTNAME', (1, 1), (1, -1), 'Helvetica'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('PADDING', (0, 0), (-1, -1), 4),
        ])
        
        patient_table.setStyle(table_style)
        doctor_table.setStyle(table_style)
        
        # Stack tables vertically instead of side by side for better fit
        elements.append(patient_table)
        elements.append(Spacer(1, 12))
        elements.append(doctor_table)
        elements.append(Spacer(1, 16))
        
        # Encounter Details
        elements.append(Paragraph("ENCOUNTER DETAILS", styles['CustomHeading2']))
        
        encounter_details = [
            ["Category", "Details"],
            ["Encounter ID:", f"ENC-{encounter.id:06d}"],
            ["Encounter Date:", encounter.encounter_date.strftime('%Y-%m-%d %H:%M')],  # Shorter format
            ["Encounter Type:", encounter.encounter_type],
            ["Status:", encounter.status.upper()],
            ["Reason for Visit:", Paragraph(encounter.reason_for_visit or "Not specified", styles['SmallTableContent'])],
            ["Diagnosis:", Paragraph(encounter.diagnosis or "Not specified", styles['SmallTableContent'])],
            ["Clinical Notes:", Paragraph(encounter.notes or "No additional notes", styles['SmallTableContent'])],
        ]
        
        if encounter.follow_up_date:
            encounter_details.append(["Follow-up Date:", encounter.follow_up_date.strftime('%Y-%m-%d')])
        
        encounter_table = Table(encounter_details, colWidths=[1.5*inch, 4.5*inch])  # Adjusted widths
        encounter_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17a2b8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#e3f2fd')),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#b3e0ff')),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        
        elements.append(encounter_table)
        elements.append(Spacer(1, 16))
        
        # Vitals Section
        if encounter.vitals:
            vitals_section = []
            vitals_section.append(Paragraph("VITAL SIGNS", styles['CustomHeading2']))
            
            vitals = encounter.vitals[0]
            
            # Determine status for each vital
            bp_status = "Normal" if vitals.blood_pressure and "120/80" in str(vitals.blood_pressure) else "Review"
            hr_status = "Normal" if vitals.heart_rate and 60 <= vitals.heart_rate <= 100 else "Review"
            temp_status = "Normal" if vitals.temperature and 97 <= vitals.temperature <= 99 else "Review"
            oxy_status = "Normal" if vitals.oxygen_saturation and vitals.oxygen_saturation >= 95 else "Review"
            resp_status = "Normal" if vitals.respiration_rate and 12 <= vitals.respiration_rate <= 20 else "Review"
            bmi_status = "Normal" if vitals.bmi and 18.5 <= vitals.bmi <= 24.9 else "Review"
            
            vitals_data = [
                ["Measurement", "Value", "Status", "Normal Range"],
                ["Blood Pressure", vitals.blood_pressure or "N/A", bp_status, "120/80 mmHg"],
                ["Heart Rate", f"{vitals.heart_rate} bpm" if vitals.heart_rate else "N/A", hr_status, "60-100 bpm"],
                ["Temperature", f"{vitals.temperature} °F" if vitals.temperature else "N/A", temp_status, "97-99 °F"],
                ["Oxygen Saturation", f"{vitals.oxygen_saturation}%" if vitals.oxygen_saturation else "N/A", oxy_status, "95-100%"],
                ["Respiration Rate", f"{vitals.respiration_rate} /min" if vitals.respiration_rate else "N/A", resp_status, "12-20 /min"],
                ["Height", f"{vitals.height} cm" if vitals.height else "N/A", "", ""],
                ["Weight", f"{vitals.weight} kg" if vitals.weight else "N/A", "", ""],
                ["BMI", f"{vitals.bmi:.1f}" if vitals.bmi else "N/A", bmi_status, "18.5-24.9"]
            ]
            
            vitals_table = Table(vitals_data, colWidths=[1.5*inch, 1.2*inch, 0.8*inch, 1.5*inch])  # Adjusted widths
            vitals_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#28a745')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f1f8e9')),
                ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('ALIGN', (2, 1), (2, -1), 'CENTER'),
                ('TEXTCOLOR', (2, 1), (2, -1), colors.green if bp_status == "Normal" else colors.red),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c8e6c9')),
                ('PADDING', (0, 0), (-1, -1), 3),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ]))
            
            vitals_section.append(vitals_table)
            vitals_section.append(Spacer(1, 16))
            elements.append(KeepTogether(vitals_section))
        
        # Medications Section
        if encounter.medications:
            medications_section = []
            medications_section.append(Paragraph("PRESCRIBED MEDICATIONS", styles['CustomHeading2']))
            
            # Modified table - removed instructions column for more space
            med_data = [["Medication", "Dosage", "Frequency", "Route", "Duration"]]
            for med in encounter.medications:
                duration = "Ongoing"
                if med.start_date and med.end_date:
                    days = (med.end_date - med.start_date).days
                    duration = f"{days} days"
                elif med.start_date:
                    duration = "From " + med.start_date.strftime('%Y-%m-%d')
                
                # Clean up any HTML tags in medication data
                med_name = str(med.medication_name).replace('<b>', '').replace('</b>', '')
                dosage = str(med.dosage).replace('<b>', '').replace('</b>', '') if med.dosage else ""
                frequency = str(med.frequency).replace('<b>', '').replace('</b>', '') if med.frequency else ""
                route = str(med.route).replace('<b>', '').replace('</b>', '') if med.route else ""
                
                med_data.append([
                    Paragraph(med_name[:30] + "..." if len(med_name) > 30 else med_name, styles['SmallTableContent']),
                    Paragraph(dosage[:15] if dosage else "", styles['SmallTableContent']),
                    Paragraph(frequency[:15] if frequency else "", styles['SmallTableContent']),
                    Paragraph(route[:10] if route else "", styles['SmallTableContent']),
                    Paragraph(duration, styles['SmallTableContent'])
                ])
            
            med_table = Table(med_data, colWidths=[1.8*inch, 1*inch, 1.2*inch, 0.8*inch, 1.2*inch])  # Adjusted widths
            med_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6f42c1')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0cffc')),
                ('PADDING', (0, 0), (-1, -1), 3),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f0ff')]),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            
            medications_section.append(med_table)
            medications_section.append(Spacer(1, 16))
            elements.append(KeepTogether(medications_section))
        else:
            # Show message if no medications
            elements.append(Paragraph("PRESCRIBED MEDICATIONS", styles['CustomHeading2']))
            elements.append(Paragraph("No medications prescribed for this encounter.", styles['SmallTableContent']))
            elements.append(Spacer(1, 16))
        
        # Lab Tests Section - FIXED: Removed Order Date and Instructions columns
        lab_section = []
        lab_section.append(Paragraph("LABORATORY TESTS", styles['CustomHeading2']))
        
        if encounter.lab_orders and len(encounter.lab_orders) > 0:
            # Modified table - only 4 columns now
            lab_data = [["Test Name", "Test Code", "Status", "Sample Type"]]
            
            for lab_order in encounter.lab_orders:
                lab_data.append([
                    Paragraph(lab_order.test_name or "Not specified", styles['SmallTableContent']),
                    Paragraph(lab_order.test_code or "N/A", styles['SmallTableContent']),
                    Paragraph(lab_order.status or "Pending", styles['SmallTableContent']),
                    Paragraph(lab_order.sample_type or "N/A", styles['SmallTableContent']),
                ])
            
            lab_table = Table(lab_data, colWidths=[2.5*inch, 1.2*inch, 1.2*inch, 1.1*inch])  # Adjusted for 4 columns
            lab_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fd7e14')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ffe5d0')),
                ('PADDING', (0, 0), (-1, -1), 3),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fff5e6')]),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            
            lab_section.append(lab_table)
        elif encounter.is_lab_test_required:
            # Show generic lab test requirement
            lab_data = [
                ["Test Required", "Status", "Priority"],
                ["Laboratory Analysis Required", "Order Pending", "Routine"]
            ]
            
            lab_table = Table(lab_data, colWidths=[2.5*inch, 1.5*inch, 1*inch])
            lab_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fd7e14')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ffe5d0')),
                ('PADDING', (0, 0), (-1, -1), 4),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fff5e6')),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
            ]))
            
            lab_section.append(lab_table)
            lab_section.append(Paragraph("* Specific lab tests to be determined by the lab department.", 
                                         ParagraphStyle(name='ItalicNote', fontSize=7, fontName='Helvetica-Oblique')))
        else:
            lab_section.append(Paragraph("No laboratory tests required for this encounter.", styles['SmallTableContent']))
        
        lab_section.append(Spacer(1, 16))
        elements.append(KeepTogether(lab_section))
        
        # Footer Section
        elements.append(Spacer(1, 20))
        footer_data = [
            [Paragraph(hospital_name, ParagraphStyle(name='Footer', fontSize=9, textColor=colors.HexColor('#7f8c8d'), alignment=1))],
            [Paragraph(hospital_address, ParagraphStyle(name='Footer', fontSize=8, textColor=colors.HexColor('#95a5a6'), alignment=1))],
            [Paragraph(f"Phone: {hospital_phone}", ParagraphStyle(name='Footer', fontSize=8, textColor=colors.HexColor('#95a5a6'), alignment=1))],
            [Paragraph(f"Report ID: ENC-{encounter.id}-{datetime.now().strftime('%Y%m%d')}", ParagraphStyle(name='Footer', fontSize=7, textColor=colors.HexColor('#bdc3c7'), alignment=1))],
            [Paragraph("CONFIDENTIAL - For Medical Use Only", ParagraphStyle(name='Footer', fontSize=7, textColor=colors.HexColor('#e74c3c'), alignment=1))],
            [Paragraph("This document contains protected health information (PHI) under HIPAA regulations", 
                       ParagraphStyle(name='Footer', fontSize=6, textColor=colors.HexColor('#bdc3c7'), alignment=1))],
        ]
        
        footer_table = Table(footer_data, colWidths=[6*inch])  # Reduced width
        footer_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        elements.append(footer_table)
        
        # Build PDF
        print("📄 Building PDF...")
        doc.build(elements)
        
        # Get PDF data
        pdf_data = buffer.getvalue()
        buffer.close()
        
        
        # Create a temporary file-like object for S3 upload
        pdf_file = BytesIO(pdf_data)
        filename = f"encounter_{encounter_id}_summary.pdf"
        pdf_file.filename = filename  # required for S3 function
        pdf_file.name = filename      # optional but ok
        
        print(f"📤 Uploading PDF to S3: {filename}")
        
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
        
        print("✅ PDF generated and uploaded successfully")
        
        # Return updated encounter
        return encounter
        
    except Exception as e:
        print(f"❌ Error generating PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")
    
    
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
        raise HTTPException(status_code=404, detail="Encounter not found")

    # RBAC
    await check_encounter_access(encounter, current_user, db)

    # Validate document index
    if not encounter.documents or doc_index >= len(encounter.documents):
        raise HTTPException(status_code=404, detail="Document not found")

    file_key = encounter.documents[doc_index]
    filename = file_key.split("/")[-1]

    # Generate presigned URL (INLINE view)
    presigned_url = generate_presigned_url(
        file_key=file_key,
        disposition="inline",
        expiration=3600
    )

    return {
        "url": presigned_url,
        "filename": filename,
        "expires_in": 3600
    }


# Download PDF securely (attachment)
@router.get("/{encounter_id}/download/{doc_index}")
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
    Generate a care plan for a completed encounter
    """
    try:
        print(f"🔄 Starting care plan generation for encounter {encounter_id}")
        
        # Get the encounter with all related data including ICD codes
        result = await db.execute(
            select(Encounter)
            .options(
                selectinload(Encounter.vitals),
                selectinload(Encounter.medications),
                selectinload(Encounter.doctor),
                selectinload(Encounter.hospital),
                selectinload(Encounter.patient),
                selectinload(Encounter.lab_orders),
                selectinload(Encounter.icd_codes).selectinload(EncounterIcdCode.icd_code),
                selectinload(Encounter.primary_icd_code)
            )
            .where(Encounter.id == encounter_id)
        )
        encounter = result.unique().scalar_one_or_none()
        
        if not encounter:
            print(f"❌ Encounter {encounter_id} not found for care plan generation")
            return
        
        print(f"✅ Found encounter {encounter_id} with {len(encounter.medications) if encounter.medications else 0} medications and {len(encounter.lab_orders) if encounter.lab_orders else 0} lab orders")
        
        # Get the user
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalars().first()
        
        if not user:
            print(f"❌ User {user_id} not found for care plan generation")
            return
        
        print(f"✅ Found user {user_id} for care plan generation")
        
        # Get or calculate patient age
        patient = encounter.patient
        
        # Check if patient has age field in database
        if patient.age is not None:
            age = patient.age
            print(f"📊 Using stored patient age from database: {age}")
        else:
            # Calculate age from DOB
            today = datetime.now().date()
            age = today.year - patient.dob.year
            if today.month < patient.dob.month or (today.month == patient.dob.month and today.day < patient.dob.day):
                age -= 1
            
            # Store the calculated age in the database for future use
            patient.age = age
            await db.commit()
            print(f"📊 Patient age calculated and stored in database: {age}")
            
        # Extract ICD codes from the encounter
        icd_codes = []
        condition_group = "General"  # Default condition group
        
        if encounter.icd_codes:
            print(f"🔍 Found {len(encounter.icd_codes)} ICD codes for encounter {encounter_id}")
            
            # Get primary ICD code first
            primary_icd = next((icd for icd in encounter.icd_codes if icd.is_primary), None)
            
            for icd in encounter.icd_codes:
                if icd.icd_code:
                    icd_codes.append({
                        "code": icd.icd_code.code,
                        "name": icd.icd_code.name,
                        "description": icd.icd_code.description if hasattr(icd.icd_code, 'description') else None,
                        "is_primary": icd.is_primary
                    })
                    
                    # If this is the primary ICD code, use it for condition group mapping
                    if icd.is_primary and icd.icd_code:
                        print(f"✅ Using primary ICD code for condition group: {icd.icd_code.code} - {icd.icd_code.name}")
                        
                        # Look up condition group mapping for this ICD code
                        icd_mapping_result = await db.execute(
                            select(models.ICDConditionMap)
                            .where(
                                or_(
                                    models.ICDConditionMap.icd_code == icd.icd_code.code,
                                    # Also check for pattern matches if is_pattern is True
                                    and_(
                                        models.ICDConditionMap.is_pattern == True,
                                        func.substring(icd.icd_code.code, 1, func.length(models.ICDConditionMap.icd_code)) == models.ICDConditionMap.icd_code
                                    )
                                )
                            )
                            .options(selectinload(models.ICDConditionMap.condition_group))
                        )
                        icd_mapping = icd_mapping_result.scalars().first()
                        
                        if icd_mapping and icd_mapping.condition_group:
                            print(f"✅ Found condition group mapping: {icd_mapping.condition_group.name}")
                            condition_group = icd_mapping.condition_group.name
                        else:
                            # If no mapping found, use the first part of the ICD code as a generic condition group
                            code_prefix = icd.icd_code.code.split('.')[0]
                            condition_group = f"ICD-{code_prefix}"
                            print(f"⚠️ No condition group mapping found, using generic: {condition_group}")
        
        # Prepare input data for care plan generation
        input_data = CarePlanGenerationInput(
            context_id=f"ctx_{encounter_id}",
            patient_profile=PatientProfile(
                age=age,
                gender=patient.gender,
                smoking_status=patient.smoking_status or "unknown",
                alcohol_use=patient.alcohol_use or "unknown",
                pregnancy_status=False  # Default value, could be updated based on patient data
            ),
            current_encounter=CurrentEncounter(
                encounter_id=str(encounter.id),
                encounter_type=encounter.encounter_type or "consultation",
                reason_for_visit=encounter.reason_for_visit or "General checkup",
                diagnosis_text=encounter.diagnosis or "",
                icd_codes=icd_codes,  # Use the extracted ICD codes
                encounter_date=encounter.encounter_date,
                follow_up_date=encounter.follow_up_date,
                clinical_notes=encounter.notes or ""
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
                        condition_name=encounter.diagnosis or "General checkup",
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
                ] if hasattr(patient, 'allergies') and patient.allergies else []
            ),
            guideline_rules=GuidelineRulesInfo(
                condition_group=condition_group,  # Use the condition group determined from ICD codes
                guideline_source="Standard of Care",
                rules_version="2025-01",
                rules_json={
                    "standard_of_care": True,
                    "follow_up_required": encounter.follow_up_date is not None,
                    "lab_tests_required": encounter.is_lab_test_required
                }
            )
        )
        
        print(f"📋 Prepared input data for care plan generation")
        print(f"📡 Calling care plan API for encounter {encounter_id}")
        
        # Call the care plan API
        async with httpx.AsyncClient(timeout=120.0) as client:  # Increased timeout to 2 minutes
            api_url = "http://localhost:8000/api/care-plans/generate"
            print(f"🔗 API URL: {api_url}")
            
            # Use the current user's token from the auth system
            from app.utils import create_access_token
            
            # Create a token for the API call
            token_data = {
                "sub": user.email if hasattr(user, 'email') else f"user_{user_id}",
                "user_id": user_id,
                "role": user.role if hasattr(user, 'role') else "system",
                "exp": datetime.utcnow() + timedelta(minutes=30)  # Short-lived token
            }
            token = create_access_token(token_data)
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            print(f"🔑 Using generated token for API call")
            
            try:
                # Convert the input_data to a dict and handle date serialization
                input_dict = input_data.dict()
                
                # Convert date objects to ISO format strings
                if 'encounter_date' in input_dict['current_encounter'] and input_dict['current_encounter']['encounter_date']:
                    input_dict['current_encounter']['encounter_date'] = input_dict['current_encounter']['encounter_date'].isoformat()
                
                if 'follow_up_date' in input_dict['current_encounter'] and input_dict['current_encounter']['follow_up_date']:
                    input_dict['current_encounter']['follow_up_date'] = input_dict['current_encounter']['follow_up_date'].isoformat()
                
                # Handle dates in medications
                for med in input_dict.get('current_medications', []):
                    if 'start_date' in med and med['start_date']:
                        med['start_date'] = med['start_date'].isoformat()
                    if 'stop_date' in med and med['stop_date']:
                        med['stop_date'] = med['stop_date'].isoformat()
                
                response = await client.post(
                    api_url,
                    json=input_dict,
                    headers=headers
                )
                
                print(f"📊 API Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    print(f"✅ Care plan generated successfully for encounter {encounter_id}")
                    print(f"📄 Response: {response.text[:200]}... (truncated)")
                else:
                    print(f"❌ Failed to generate care plan for encounter {encounter_id}")
                    print(f"📄 Error Response: {response.text}")
            except httpx.TimeoutException:
                print(f"⏱️ API request timed out after 60 seconds")
            except httpx.RequestError as e:
                print(f"🌐 Request error: {str(e)}")
    
    except Exception as e:
        print(f"❌ Error generating care plan for encounter {encounter_id}: {str(e)}")
        import traceback
        traceback.print_exc()

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
    print(f"🔄 Received request to generate care plan for encounter {encounter_id}")
    
    # Get the encounter
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
        print(f"❌ Encounter {encounter_id} not found")
        raise HTTPException(404, "Encounter not found")
    
    print(f"✅ Found encounter {encounter_id} for patient {encounter.patient_id}")
    
    # Check permissions
    if current_user.role == "doctor":
        doctor_result = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
        doctor = doctor_result.unique().scalar_one_or_none()
        
        if not doctor or doctor.id != encounter.doctor_id:
            print(f"❌ Doctor {current_user.id} not authorized for encounter {encounter_id}")
            raise HTTPException(403, "Not authorized to generate care plan for this encounter")
        
        print(f"✅ Doctor {doctor.id} authorized for encounter {encounter_id}")
    elif current_user.role != "admin":
        print(f"❌ User role {current_user.role} not authorized to generate care plans")
        raise HTTPException(403, "Only doctors and admins can generate care plans")
    
    try:
        # Try to generate care plan directly instead of using background task
        print(f"🔄 Generating care plan for encounter {encounter_id} directly")
        await generate_care_plan_for_encounter(
            encounter_id=encounter.id,
            user_id=current_user.id,
            db=db
        )
        print(f"✅ Care plan generation completed for encounter {encounter_id}")
    except Exception as e:
        print(f"❌ Error generating care plan: {str(e)}")
        import traceback
        traceback.print_exc()
        # Continue execution even if care plan generation fails
        # We'll still update the encounter status and return a response
    # Keep the encounter status as is - we now support care plans for in-progress encounters
    print(f"ℹ️ Keeping encounter {encounter_id} status as '{encounter.status}'")
    await db.refresh(encounter)
    
    # Build response
    response = EncounterOut.from_orm(encounter)
    response.doctor_name = f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
    response.hospital_name = encounter.hospital.name
    response.patient_public_id = encounter.patient.public_id
    
    print(f"✅ Returning response for encounter {encounter_id}")
    return response

# ===== ICD CODE ENDPOINTS =====

@router.get("/icd-codes/search")
async def search_icd_codes(
    search: str = None,
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Search ICD codes for dropdown/autocomplete
    """
    query = select(IcdCodeMaster).where(IcdCodeMaster.is_active == True)
    
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                IcdCodeMaster.code.ilike(search_term),
                IcdCodeMaster.name.ilike(search_term)
            )
        )
    
    query = query.order_by(IcdCodeMaster.code).limit(limit)
    
    result = await db.execute(query)
    icd_codes = result.scalars().all()
    
    return [
        {
            "id": icd.id,
            "code": icd.code,
            "name": icd.name,
            "description": icd.description,
            "category": icd.category
        }
        for icd in icd_codes
    ]


@router.get("/{encounter_id}/icd-codes")
async def get_encounter_icd_codes(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all ICD codes for a specific encounter
    """
    # Check if encounter exists and user has access
    enc_result = await db.execute(
        select(Encounter).where(Encounter.id == encounter_id)
    )
    encounter = enc_result.scalar_one_or_none()
    
    if not encounter:
        raise HTTPException(404, "Encounter not found")
    
    # Get ICD codes for this encounter
    result = await db.execute(
        select(EncounterIcdCode)
        .options(selectinload(EncounterIcdCode.icd_code))
        .where(EncounterIcdCode.encounter_id == encounter_id)
        .order_by(EncounterIcdCode.is_primary.desc(), EncounterIcdCode.created_at)
    )
    
    icd_codes = result.scalars().all()
    
    return [
        {
            "id": ec.id,
            "icd_code_id": ec.icd_code_id,
            "code": ec.icd_code.code,
            "name": ec.icd_code.name,
            "is_primary": ec.is_primary,
            "notes": ec.notes,
            "created_at": ec.created_at
        }
        for ec in icd_codes
    ]


@router.post("/{encounter_id}/icd-codes")
async def add_icd_code_to_encounter(
    encounter_id: int,
    icd_data: dict,  # { "icd_code_id": 1, "is_primary": false, "notes": "optional" }
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add an ICD code to an existing encounter
    """
    # Check if encounter exists and user has access
    enc_result = await db.execute(
        select(Encounter).where(Encounter.id == encounter_id)
    )
    encounter = enc_result.scalar_one_or_none()
    
    if not encounter:
        raise HTTPException(404, "Encounter not found")
    
    # Validate ICD code exists and is active
    icd_result = await db.execute(
        select(IcdCodeMaster).where(
            IcdCodeMaster.id == icd_data["icd_code_id"],
            IcdCodeMaster.is_active == True
        )
    )
    icd_code = icd_result.scalar_one_or_none()
    
    if not icd_code:
        raise HTTPException(400, "ICD code not found or inactive")
    
    # Check for duplicate
    existing = await db.execute(
        select(EncounterIcdCode).where(
            EncounterIcdCode.encounter_id == encounter_id,
            EncounterIcdCode.icd_code_id == icd_data["icd_code_id"]
        )
    )
    duplicate = existing.scalar_one_or_none()
    
    if duplicate:
        raise HTTPException(400, "ICD code already added to this encounter")
    
    # Create encounter ICD code
    db_encounter_icd = EncounterIcdCode(
        encounter_id=encounter_id,
        icd_code_id=icd_data["icd_code_id"],
        is_primary=icd_data.get("is_primary", False),
        notes=icd_data.get("notes")
    )
    db.add(db_encounter_icd)
    await db.commit()
    
    return {"message": "ICD code added successfully", "icd_code": icd_code.code}


@router.delete("/{encounter_id}/icd-codes/{encounter_icd_id}")
async def remove_icd_code_from_encounter(
    encounter_id: int,
    encounter_icd_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove an ICD code from an encounter
    """
    # Check if encounter ICD code exists
    result = await db.execute(
        select(EncounterIcdCode).where(
            EncounterIcdCode.id == encounter_icd_id,
            EncounterIcdCode.encounter_id == encounter_id
        )
    )
    encounter_icd = result.scalar_one_or_none()
    
    if not encounter_icd:
        raise HTTPException(404, "ICD code not found in this encounter")
    
    await db.delete(encounter_icd)
    await db.commit()
    
    return {"message": "ICD code removed successfully"}