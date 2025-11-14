from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas

router = APIRouter(prefix="/doctor", tags=["Doctor"])

# GET PATIENTS UNDER CURRENT DOCTOR
@router.get("/patients", response_model=List[schemas.PatientOut])
async def get_patients_for_doctor(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Only doctor or hospital roles allowed
    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(status_code=403, detail="Not permitted")

    patients = []

    if current_user.role == "doctor":
        # Get the doctor record for this user
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()

        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor record not found")

        # Fetch patients assigned to this doctor from Assignment table
        result = await db.execute(
            select(models.Patient)
            .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
            .where(models.Assignment.doctor_id == doctor.id)
            .options(
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),
                selectinload(models.Patient.vitals),          # vitals
                selectinload(models.Patient.medications),     # medications
                selectinload(models.Patient.encounters),      # encounters

            )
            .order_by(models.Patient.first_name.asc(), models.Patient.last_name.asc())
        )
        patients = result.scalars().unique().all()  # remove duplicates if patient has multiple assignments

    elif current_user.role == "hospital":
        if not current_user.hospital_id:
            raise HTTPException(status_code=400, detail="Hospital ID not found for this user")

        # Fetch all patients under hospital
        result = await db.execute(
            select(models.Patient)
            .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
            .where(models.Assignment.hospital_id == current_user.hospital_id)
            .options(
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),
                selectinload(models.Patient.vitals),
                selectinload(models.Patient.medications),
                selectinload(models.Patient.encounters)
                # selectinload(models.Patient.care_plans),
            )
            .order_by(models.Patient.first_name.asc(), models.Patient.last_name.asc())
        )
        patients = result.scalars().unique().all()

    return patients
