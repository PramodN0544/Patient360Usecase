from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from app.models import Medication, Patient, Notification
from app.database import get_db
from app.schemas import MedicationCreate, MedicationOut
from app.auth import get_current_user

router = APIRouter(prefix="/medications", tags=["Medications"])

# Helper — get patient by current user
async def get_logged_in_patient(current_user, db):
    result = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return patient

# CREATE MEDICATION
@router.post("/", response_model=MedicationOut)
async def create_medication(payload: MedicationCreate, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await get_logged_in_patient(current_user, db)

    new_med = Medication(
        patient_id=patient.id,
        doctor_id=payload.doctor_id,        # int
        appointment_id=payload.appointment_id,  # int
        medication_name=payload.medication_name,
        dosage=payload.dosage,
        frequency=payload.frequency,
        icd_code=payload.icd_code,
        ndc_code=payload.ndc_code,
        route=payload.route,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status or "active",
        notes=payload.notes,
    )

    db.add(new_med)
    await db.commit()
    await db.refresh(new_med)

    # Notification
    notif = Notification(
        user_id=patient.user_id,
        title="New Medication Prescribed",
        desc=f"You have been prescribed {payload.medication_name} ({payload.dosage}).",
        type="medication",
        status="unread",
        data_id=str(new_med.id) 
    )
    db.add(notif)
    await db.commit()

    return new_med

# GET ALL MEDICATIONS
@router.get("/", response_model=List[MedicationOut])
async def get_all_medications(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await get_logged_in_patient(current_user, db)
    result = await db.execute(select(Medication).where(Medication.patient_id == patient.id))
    return result.scalars().all()

# GET CURRENT MEDICATIONS
@router.get("/current", response_model=List[MedicationOut])
async def get_current_medications(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await get_logged_in_patient(current_user, db)
    result = await db.execute(select(Medication).where(Medication.patient_id == patient.id, Medication.status == "active"))
    return result.scalars().all()

# GET PAST MEDICATIONS
@router.get("/history", response_model=List[MedicationOut])
async def get_past_medications(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await get_logged_in_patient(current_user, db)
    result = await db.execute(select(Medication).where(Medication.patient_id == patient.id, Medication.status != "active"))
    return result.scalars().all()

# DASHBOARD VIEW
@router.get("/dashboard")
async def get_medication_dashboard(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await get_logged_in_patient(current_user, db)
    result = await db.execute(select(Medication).where(Medication.patient_id == patient.id))
    all_meds = result.scalars().all()

    current_meds, past_meds = [], []
    for med in all_meds:
        med_data = {
            "id": med.id,
            "medication_name": med.medication_name,
            "dosage": med.dosage,
            "frequency": med.frequency,
            "route": med.route,
            "start_date": med.start_date,
            "end_date": med.end_date,
            "status": med.status,
            "notes": med.notes,
            "doctor_id": med.doctor_id,
            "appointment_id": med.appointment_id,
            "created_at": med.created_at,
            "updated_at": med.updated_at
        }
        (current_meds if med.status.lower() == "active" else past_meds).append(med_data)

    return {
        "patient_id": patient.id,
        "current_medications": current_meds,
        "past_medications": past_meds
    }
