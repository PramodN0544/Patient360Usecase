from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from app.database import get_db
from app.models import Encounter, Doctor, Patient, Vitals, Medication, PatientDoctorAssignment
from app.schemas import EncounterCreate, EncounterOut
from app.auth import get_current_user

router = APIRouter(prefix="/encounters", tags=["Encounters"])

# ===============================
# CREATE ENCOUNTER
# ===============================
@router.post("/", response_model=EncounterOut)
async def create_encounter(
    encounter_in: EncounterCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # -------------------------------
    # Determine doctor
    # -------------------------------
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()

    if current_user.role == "hospital":
        # Hospital creating encounter → doctor must be passed
        doctor_id = encounter_in.doctor_id
        doctor_result = await db.execute(
            select(Doctor).where(
                Doctor.id == doctor_id,
                Doctor.hospital_id == current_user.hospital_id
            )
        )
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            raise HTTPException(404, "Doctor not found in your hospital")
    elif not doctor:
        raise HTTPException(403, "Only doctors or hospitals can create encounters")

    # -------------------------------
    # Fetch patient by public_id
    # -------------------------------
    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == encounter_in.patient_public_id)
    )
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Patient not found")

    # -------------------------------
    # Optional: check doctor assigned to patient
    # -------------------------------
    assignment_result = await db.execute(
        select(PatientDoctorAssignment)
        .where(
            PatientDoctorAssignment.patient_id == patient.id,
            PatientDoctorAssignment.doctor_id == doctor.id
        )
    )
    assignment = assignment_result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(403, "Doctor is not assigned to this patient")

    # -------------------------------
    # Create encounter
    # -------------------------------
    new_encounter = Encounter(
        patient_id=patient.id,
        doctor_id=doctor.id,
        hospital_id=doctor.hospital_id,
        encounter_date=encounter_in.encounter_date,
        encounter_type=encounter_in.encounter_type,
        reason_for_visit=encounter_in.reason_for_visit,
        diagnosis=encounter_in.diagnosis,
        notes=encounter_in.notes,
        follow_up_date=encounter_in.follow_up_date,
        status="open"
    )
    db.add(new_encounter)
    await db.flush()  # get new_encounter.id for foreign keys

    # -------------------------------
    # Save vitals
    # -------------------------------
    if encounter_in.vitals:
        v = encounter_in.vitals
        bmi = None
        if v.height and v.weight:
            height_m = v.height / 100
            bmi = round(v.weight / (height_m ** 2), 2)
        vitals_obj = Vitals(
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
        )
        db.add(vitals_obj)

    # -------------------------------
    # Save medications
    # -------------------------------
    if encounter_in.medications:
        for m in encounter_in.medications:
            med_obj = Medication(
                patient_id=patient.id,
                doctor_id=doctor.id,
                encounter_id=new_encounter.id,
                medication_name=m.medication_name,
                icd_code=m.icd_code,
                ndc_code=m.ndc_code,
                dosage=m.dosage,
                frequency=m.frequency,
                route=m.route,
                start_date=m.start_date,
                end_date=m.end_date,
                status=m.status or "active",
                notes=m.notes,
            )
            db.add(med_obj)

    await db.commit()
    await db.refresh(new_encounter)

    # -------------------------------
    # Return encounter with relations
    # -------------------------------
    final_result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications)
        )
        .where(Encounter.id == new_encounter.id)
    )
    return final_result.scalar_one()


# ===============================
# GET PATIENT'S ENCOUNTERS
# ===============================
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
        .options(selectinload(Encounter.vitals), selectinload(Encounter.medications))
        .where(Encounter.patient_id == patient.id)
        .order_by(Encounter.encounter_date.desc())
    )
    return result.scalars().all()


# ===============================
# GET SINGLE ENCOUNTER
# ===============================
@router.get("/{encounter_id}", response_model=EncounterOut)
async def get_encounter(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Encounter)
        .options(selectinload(Encounter.vitals), selectinload(Encounter.medications))
        .where(Encounter.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # If patient → ensure they own the encounter
    patient_result = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = patient_result.scalar_one_or_none()
    if patient and encounter.patient_id != patient.id:
        raise HTTPException(403, "You can only see your own encounters")

    return encounter
