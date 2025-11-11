from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, date
from uuid import uuid4
from typing import List
from fastapi import APIRouter
from app.database import get_db
from app.models import Encounter, Medication, Doctor
from app.schemas import EncounterCreate, EncounterOut, MedicationOut

router = APIRouter(prefix="/encounters", tags=["Encounters"])

# ------------------- Create Encounter -------------------
@router.post("/", response_model=EncounterOut)
async def create_encounter(
    encounter_in: EncounterCreate,
    db: AsyncSession = Depends(get_db)
):
    doctor_result = await db.execute(select(Doctor).where(Doctor.id == encounter_in.doctor_id))
    doctor = doctor_result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    new_encounter = Encounter(
        id=uuid4(),
        patient_id=encounter_in.patient_id,
        doctor_id=encounter_in.doctor_id,
        hospital_id=encounter_in.hospital_id,
        encounter_date=encounter_in.encounter_date or date.today(),
        encounter_type=encounter_in.encounter_type,
        reason_for_visit=encounter_in.reason_for_visit,
        diagnosis=encounter_in.diagnosis,
        notes=encounter_in.notes,
        vitals=encounter_in.vitals,
        lab_tests_ordered=encounter_in.lab_tests_ordered,
        follow_up_date=encounter_in.follow_up_date,
        status="open",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(new_encounter)
    await db.commit()
    await db.refresh(new_encounter)

    # Add medications
    for med_in in encounter_in.medications:
        new_med = Medication(
            id=uuid4(),
            patient_id=encounter_in.patient_id,
            doctor_id=encounter_in.doctor_id,
            encounter_id=new_encounter.id,
            medication_name=med_in.medication_name,
            dosage=med_in.dosage,
            frequency=med_in.frequency,
            route=med_in.route,
            start_date=med_in.start_date,
            end_date=med_in.end_date,
            status=med_in.status or "active",
            notes=med_in.notes,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(new_med)
    await db.commit()

    result = await db.execute(
        select(Encounter)
        .options(selectinload(Encounter.medications))
        .where(Encounter.id == new_encounter.id)
    )
    encounter_with_meds = result.scalar_one()

    encounter_out = EncounterOut(
        id=encounter_with_meds.id,
        patient_id=encounter_with_meds.patient_id,
        doctor_id=encounter_with_meds.doctor_id,
        hospital_id=encounter_with_meds.hospital_id,
        encounter_date=encounter_with_meds.encounter_date,
        encounter_type=encounter_with_meds.encounter_type,
        reason_for_visit=encounter_with_meds.reason_for_visit,
        diagnosis=encounter_with_meds.diagnosis,
        notes=encounter_with_meds.notes,
        vitals=encounter_with_meds.vitals,
        lab_tests_ordered=encounter_with_meds.lab_tests_ordered,
        follow_up_date=encounter_with_meds.follow_up_date,
        status=encounter_with_meds.status,
        medications=[
            MedicationOut.from_orm(m) for m in encounter_with_meds.medications
        ]
    )

    return encounter_out

# ------------------- Get Encounter by ID -------------------
@router.get("/{encounter_id}", response_model=EncounterOut)
async def get_encounter(encounter_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Encounter)
        .options(selectinload(Encounter.medications))
        .where(Encounter.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    return EncounterOut(
        id=encounter.id,
        patient_id=encounter.patient_id,
        doctor_id=encounter.doctor_id,
        hospital_id=encounter.hospital_id,
        encounter_date=encounter.encounter_date,
        encounter_type=encounter.encounter_type,
        reason_for_visit=encounter.reason_for_visit,
        diagnosis=encounter.diagnosis,
        notes=encounter.notes,
        vitals=encounter.vitals,
        lab_tests_ordered=encounter.lab_tests_ordered,
        follow_up_date=encounter.follow_up_date,
        status=encounter.status,
        medications=[MedicationOut.from_orm(m) for m in encounter.medications]
    )

# ------------------- Get All Encounters by Patient (Dashboard) -------------------
@router.get("/patient/{patient_id}/dashboard", response_model=List[EncounterOut])
async def get_patient_encounters_dashboard(patient_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Encounter)
        .where(Encounter.patient_id == patient_id)
        .order_by(Encounter.encounter_date.desc())
    )
    encounters = result.scalars().all()

    # Return only main fields for dashboard
    dashboard_list = [
        EncounterOut(
            id=e.id,
            patient_id=e.patient_id,
            doctor_id=e.doctor_id,
            hospital_id=e.hospital_id,
            encounter_date=e.encounter_date,
            encounter_type=e.encounter_type,
            reason_for_visit=e.reason_for_visit,
            diagnosis=e.diagnosis,
            notes="",  # hide notes
            vitals={},  # hide vitals
            lab_tests_ordered={},  # hide labs
            follow_up_date=e.follow_up_date,
            status=e.status,
            medications=[]  # hide medications in dashboard
        )
        for e in encounters
    ]
    return dashboard_list

# ------------------- Get All Encounters by Patient (Detail) -------------------
@router.get("/patient/{patient_id}/detail", response_model=List[EncounterOut])
async def get_patient_encounters_detail(patient_id: str, db: AsyncSession = Depends(get_db)):
    # Fetch all encounters with medications
    result = await db.execute(
        select(Encounter)
        .options(selectinload(Encounter.medications))
        .where(Encounter.patient_id == patient_id)
        .order_by(Encounter.encounter_date.desc())
    )
    encounters = result.scalars().all()

    if not encounters:
        raise HTTPException(status_code=404, detail="No encounters found for this patient")

    # Convert each encounter with medications
    detailed_list = [
        EncounterOut(
            id=e.id,
            patient_id=e.patient_id,
            doctor_id=e.doctor_id,
            hospital_id=e.hospital_id,
            encounter_date=e.encounter_date,
            encounter_type=e.encounter_type,
            reason_for_visit=e.reason_for_visit,
            diagnosis=e.diagnosis,
            notes=e.notes,
            vitals=e.vitals,
            lab_tests_ordered=e.lab_tests_ordered,
            follow_up_date=e.follow_up_date,
            status=e.status,
            medications=[MedicationOut.from_orm(m) for m in e.medications]
        )
        for e in encounters
    ]

    return detailed_list
