from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import Medication
from app.schemas import MedicationCreate, MedicationOut
from uuid import UUID
from typing import List

router = APIRouter(prefix="/medications", tags=["Medications"])

# ✅ Create new medication
@router.post("/", response_model=MedicationOut)
async def create_medication(payload: MedicationCreate, db: AsyncSession = Depends(get_db)):
    new_med = Medication(**payload.dict())
    db.add(new_med)
    await db.commit()
    await db.refresh(new_med)
    return new_med

# ✅ Get all medications for a patient
@router.get("/patient/{patient_id}", response_model=List[MedicationOut])
async def get_medications_by_patient(patient_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Medication).where(Medication.patient_id == patient_id))
    meds = result.scalars().all()
    return meds

# ✅ Get current medications
@router.get("/patient/{patient_id}/current", response_model=List[MedicationOut])
async def get_current_medications(patient_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Medication).where(
            Medication.patient_id == patient_id,
            Medication.status == "active"
        )
    )
    return result.scalars().all()

# ✅ Get past medications
@router.get("/patient/{patient_id}/history", response_model=List[MedicationOut])
async def get_past_medications(patient_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Medication).where(
            Medication.patient_id == patient_id,
            Medication.status != "active"
        )
    )
    return result.scalars().all()

# ✅ Combined Dashboard API — current + past meds together
@router.get("/patient/{patient_id}/dashboard")
async def get_patient_medication_dashboard(patient_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Medication).where(Medication.patient_id == patient_id))
    all_meds = result.scalars().all()

    current_meds = []
    past_meds = []

    for med in all_meds:
        med_data = {
            "id": str(med.id),
            "medication_name": med.medication_name,
            "dosage": med.dosage,
            "frequency": med.frequency,
            "route": med.route,
            "start_date": med.start_date,
            "end_date": med.end_date,
            "status": med.status,
            "notes": med.notes,
            "doctor_id": str(med.doctor_id) if med.doctor_id else None,
            "appointment_id": str(med.appointment_id) if med.appointment_id else None,
            "created_at": med.created_at,
            "updated_at": med.updated_at
        }

        if med.status and med.status.lower() == "active":
            current_meds.append(med_data)
        else:
            past_meds.append(med_data)

    return {
        "patient_id": str(patient_id),
        "current_medications": current_meds,
        "past_medications": past_meds
    }
