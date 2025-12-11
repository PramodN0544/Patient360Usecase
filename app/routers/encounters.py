import ast
import aiohttp
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy import or_
from app.models import IcdCodeMaster, EncounterIcdCode  # Add these models
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
from app.database import get_db
from app.models import Encounter, Doctor, Patient, Vitals, Medication, Assignment, LabOrder
from app.schemas import EncounterCreate, EncounterOut, EncounterUpdate,LabTestDetail
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
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()

    if current_user.role == "hospital":
        doctor_result = await db.execute(
            select(Doctor).where(
                Doctor.id == encounter_in.doctor_id,
                Doctor.hospital_id == current_user.hospital_id
            )
        )
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            raise HTTPException(404, "Doctor not found in hospital")

    elif not doctor:
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

    # ------------------ PRIMARY ICD CODE ------------------
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

    # ------------------ ICD CODES LIST ------------------
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

    # ------------------ VITALS ------------------
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

    # ------------------ MEDICATIONS ------------------
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

    # ------------------ FILE UPLOAD ------------------
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

    # ------------------ RETURN FULL OBJECT ------------------
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
    encounter_in: str = Form(None),
    files: List[UploadFile] | None = File(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not encounter_in:
        raise HTTPException(400, "Missing encounter data")

    # Parse JSON
    try:
        parsed = json.loads(encounter_in)
    except:
        raise HTTPException(400, "Invalid JSON format in encounter_in")

    # Build update schema
    try:
        encounter_update = EncounterUpdate(
            encounter_type=parsed.get("encounter_type"),
            reason_for_visit=parsed.get("reason_for_visit"),
            diagnosis=parsed.get("diagnosis"),
            notes=parsed.get("notes"),
            follow_up_date=parsed.get("follow_up_date"),
            is_lab_test_required=parsed.get("is_lab_test_required"),
            vitals=parsed.get("vitals"),
            medications=parsed.get("medications"),
            lab_orders=parsed.get("lab_orders"),
        )
    except Exception as e:
        raise HTTPException(400, f"Invalid encounter fields: {e}")

    # Fetch encounter
    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            selectinload(Encounter.lab_orders),
            selectinload(Encounter.patient),
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital)
        )
        .where(Encounter.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # Permission check
    doctor_result = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
    doctor = doctor_result.scalar_one_or_none()

    if not doctor or doctor.id != encounter.doctor_id:
        raise HTTPException(403, "You can update only your own encounters")

    # Prevent editing completed encounters
    if encounter.status == "completed":
        raise HTTPException(400, "Completed encounters cannot be modified")

    # -----------------------------
    # SIMPLE STATUS LOGIC (FINAL)
    # -----------------------------
    follow_up = encounter_update.follow_up_date

    if follow_up:
        encounter.status = "in-progress"
        encounter.is_continuation = True
    else:
        encounter.status = "completed"
        encounter.is_continuation = False

    # Update simple fields
    for field, value in encounter_update.dict(exclude_unset=True, exclude_none=True).items():
        if field not in ["vitals", "medications", "lab_orders"]:
            setattr(encounter, field, value)

    # -----------------------------
    # UPDATE VITALS
    # -----------------------------
    if encounter_update.vitals:
        vitals_result = await db.execute(
            select(Vitals).where(Vitals.encounter_id == encounter.id)
        )
        vitals = vitals_result.scalar_one_or_none()

        if not vitals:
            vitals = Vitals(encounter_id=encounter.id, patient_id=encounter.patient_id)
            db.add(vitals)

        for key, val in encounter_update.vitals.items():
            setattr(vitals, key, val)

        # Calculate BMI
        if vitals.height and vitals.weight:
            vitals.bmi = round(vitals.weight / ((vitals.height / 100) ** 2), 2)

    # -----------------------------
    # UPDATE MEDICATIONS
    # -----------------------------
    if encounter_update.medications is not None:
        await db.execute(
            Medication.__table__.delete().where(Medication.encounter_id == encounter.id)
        )
        for m in encounter_update.medications:
            db.add(Medication(
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                **m
            ))

    # -----------------------------
    # UPDATE LAB ORDERS
    # -----------------------------
    if encounter_update.lab_orders is not None:
        await db.execute(
            LabOrder.__table__.delete().where(LabOrder.encounter_id == encounter.id)
        )
        for l in encounter_update.lab_orders:
            db.add(LabOrder(
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                test_code=l["test_code"],
                test_name=l.get("test_name", ""),
                sample_type=l["sample_type"],
                status="Ordered"
            ))

    # -----------------------------
    # FILE UPLOAD
    # -----------------------------
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

    # Log history
    db.add(
        EncounterHistory(
            encounter_id=encounter.id,
            status=encounter.status,
            updated_by=current_user.id,
            notes=f"Encounter updated - status: {encounter.status}"
        )
    )

    await db.commit()
    await db.refresh(encounter)

    # Return response
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

            assignment_record = assign.scalars().first() 

            if not assignment_record:
                raise HTTPException(403, "Not authorized to view this patient’s encounters")

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
    assignment_record = assign.scalars().first()
    if not assignment_record:
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
@router.post("/{encounter_id}/generate-pdf", response_model=EncounterOut)
async def generate_encounter_pdf(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    
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
    
    if current_user.role == "doctor" and encounter.doctor.user_id != current_user.id:
        raise HTTPException(403, "Not authorized to access this encounter")
    if current_user.role == "patient" and encounter.patient.user_id != current_user.id:
        raise HTTPException(403, "Not authorized to access this encounter")
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
    elements.append(Paragraph("Patient Encounter Report", styles['Heading1']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Encounter ID: {encounter.id}", styles['Heading3']))
    elements.append(Paragraph(f"Date: {encounter.encounter_date.strftime('%B %d, %Y')}", styles['Normal']))
    elements.append(Paragraph(f"Type: {encounter.encounter_type}", styles['Normal']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Patient Information", styles['Heading2']))
    elements.append(Paragraph(f"Name: {encounter.patient.first_name} {encounter.patient.last_name}", styles['Normal']))
    elements.append(Paragraph(f"ID: {encounter.patient.public_id}", styles['Normal']))
    elements.append(Paragraph(f"DOB: {encounter.patient.dob.strftime('%B %d, %Y')}", styles['Normal']))
    elements.append(Paragraph(f"Gender: {encounter.patient.gender}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
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