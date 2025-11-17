# app/routers/doctors.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas

router = APIRouter(
    prefix="/doctor",
    tags=["Doctor"]
)


@router.get("/patients", response_model=schemas.PatientsWithCount)
async def get_patients_for_doctor(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Only doctors and hospitals are allowed
    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(status_code=403, detail="Not permitted")

    patients = []

    # =============================
    # If DOCTOR → fetch assigned patients
    # =============================
    if current_user.role == "doctor":

        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()

        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor record not found")

        stmt = (
            select(models.Patient)
            .join(
                models.Assignment,
                models.Patient.id == models.Assignment.patient_id
            )
            .where(models.Assignment.doctor_id == doctor.id)
            .options(
                # top-level patient relations
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),

                # Load encounters and nested relations (prevent lazy loads)
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.vitals),
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.medications),
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.doctor),
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.hospital),
            )
            .order_by(models.Patient.first_name.asc(),
                      models.Patient.last_name.asc())
        )

        result = await db.execute(stmt)
        patients = result.scalars().unique().all()

    # =============================
    # If HOSPITAL → fetch all hospital's patients
    # =============================
    elif current_user.role == "hospital":

        stmt = (
            select(models.Patient)
            .join(
                models.Assignment,
                models.Patient.id == models.Assignment.patient_id
            )
            .where(models.Assignment.hospital_id == current_user.hospital_id)
            .options(
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),

                # Ensure encounters and nested relations are loaded
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.vitals),
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.medications),
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.doctor),
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.hospital),
            )
            .order_by(models.Patient.first_name.asc(),
                      models.Patient.last_name.asc())
        )

        result = await db.execute(stmt)
        patients = result.scalars().unique().all()

    # =============================
    # Final response
    # =============================
    return {
        "total_patients": len(patients),
        "patients": patients
    }
