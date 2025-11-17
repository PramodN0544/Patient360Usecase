# app/routers/encounters.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload
from typing import List
from datetime import date

from app.database import get_db
from app.models import Encounter, Doctor, Patient, Vitals, Medication, Assignment
from app.schemas import EncounterCreate, EncounterOut, EncounterUpdate
from app.auth import get_current_user

router = APIRouter(prefix="/encounters", tags=["Encounters"])

def calculate_status(enc):
    # If anything missing → Pending
    if (
        not enc.diagnosis
        or not enc.notes
        or not enc.vitals
    ):
        return "Pending"

    # If follow up OR lab test → In Progress
    if enc.follow_up_date or enc.is_lab_test_required:
        return "In Progress"

    return "Completed"

@router.post("/", response_model=EncounterOut)
async def create_encounter(
    encounter_in: EncounterCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # -------- DOCTOR / HOSPITAL VALIDATION ----------
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
            raise HTTPException(404, "Doctor not found")
    elif not doctor:
        raise HTTPException(403, "Only doctors or hospitals can create encounters")

    # -------- FETCH PATIENT USING PUBLIC ID ----------
    if not encounter_in.patient_public_id:
        raise HTTPException(400, "patient_public_id is required")

    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == encounter_in.patient_public_id)
    )
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Patient not found")

    # -------- ASSIGNMENT CHECK ----------
    assign = await db.execute(
        select(Assignment).where(
            Assignment.patient_id == patient.id,
            Assignment.doctor_id == doctor.id
        )
    )
    if not assign.scalar_one_or_none():
        raise HTTPException(403, "Doctor not assigned to this patient")

    # -------- CREATE ENCOUNTER ----------
    new_encounter = Encounter(
        patient_id=patient.id,
        doctor_id=doctor.id,
        hospital_id=doctor.hospital_id,
        encounter_date=encounter_in.encounter_date or date.today(),
        encounter_type=encounter_in.encounter_type,
        reason_for_visit=encounter_in.reason_for_visit,
        diagnosis=encounter_in.diagnosis,
        notes=encounter_in.notes,
        follow_up_date=encounter_in.follow_up_date,
        is_lab_test_required=encounter_in.is_lab_test_required,
        status=calculate_status(encounter_in)
    )

    db.add(new_encounter)
    await db.flush()

    # -------- SAVE VITALS ----------
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

    # -------- SAVE MEDICATIONS ----------
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

    await db.commit()
    await db.refresh(new_encounter)

    # -------- RESPONSE WITH PUBLIC ID ----------
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

    e = final.scalar_one()
    out = EncounterOut.from_orm(e)

    out.doctor_name = f"{doctor.first_name} {doctor.last_name}"
    out.hospital_name = e.hospital.name
    out.patient_public_id = e.patient.public_id

    return out


@router.get("/patient/{public_id}", response_model=List[EncounterOut])
async def get_patient_encounters(
    public_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # 🔍 Fetch patient using public_id (safe)
    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == public_id)
    )
    patient = patient_result.scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    # 🔒 Check doctor assignment
    if current_user.role == "doctor":
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalar_one_or_none()

        if not doctor:
            raise HTTPException(404, "Doctor record not found")

        assignment_result = await db.execute(
            select(Assignment).where(
                Assignment.patient_id == patient.id,
                Assignment.doctor_id == doctor.id
            )
        )
        assignment = assignment_result.scalar_one_or_none()

        if not assignment:
            raise HTTPException(403, "Doctor is not assigned to this patient")

    # 📄 Fetch encounters
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

    encounters = result.scalars().all()

    return [EncounterOut.from_orm(e) for e in encounters]



# Get logged-in patient's encounters - In Patient Dashboard
@router.get("/patient", response_model=List[EncounterOut])
async def get_my_encounters(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_result = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = patient_result.scalar_one_or_none()

    if not patient:
        raise HTTPException(403, "Only patients can view encounters")

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
        encounter_data = EncounterOut.from_orm(e)
        encounter_data.doctor_name = (
            f"{e.doctor.first_name} {e.doctor.last_name}" if e.doctor else None
        )
        encounter_data.hospital_name = e.hospital.name if e.hospital else None
        response.append(encounter_data)

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
            selectinload(Encounter.doctor),
            selectinload(Encounter.hospital),
            selectinload(Encounter.patient)
        )
        .where(Encounter.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # Patient can see only their encounter
    if current_user.role == "patient":
        if encounter.patient.user_id != current_user.id:
            raise HTTPException(403, "You can only see your own encounters")

    out = EncounterOut.from_orm(encounter)
    out.doctor_name = f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
    out.hospital_name = encounter.hospital.name
    out.patient_public_id = encounter.patient.public_id

    return out

@router.put("/{encounter_id}", response_model=EncounterOut)
async def update_encounter(
    encounter_id: int,
    encounter_in: EncounterUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # FETCH ENCOUNTER
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
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # PERMISSIONS
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()
    if not doctor and current_user.role != "hospital":
        raise HTTPException(403, "Not allowed")

    # UPDATE FIELDS
    for field, value in encounter_in.dict(exclude_unset=True).items():
        if field not in ("vitals", "medications"):
            setattr(encounter, field, value)

    # UPDATE STATUS
    encounter.status = calculate_status(encounter_in)

    # UPDATE VITALS
    if encounter_in.vitals:
        vitals_result = await db.execute(
            select(Vitals).where(Vitals.encounter_id == encounter.id)
        )
        vitals = vitals_result.scalar_one_or_none()
        if vitals:
            for f, val in encounter_in.vitals.dict(exclude_unset=True).items():
                setattr(vitals, f, val)

    # UPDATE MEDICATIONS
    if encounter_in.medications:
        await db.execute(
            Medication.__table__.delete().where(Medication.encounter_id == encounter.id)
        )
        for m in encounter_in.medications:
            db.add(Medication(
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                encounter_id=encounter.id,
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

    await db.commit()
    await db.refresh(encounter)

    out = EncounterOut.from_orm(encounter)
    out.doctor_name = f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
    out.hospital_name = encounter.hospital.name
    out.patient_public_id = encounter.patient.public_id

    return out
