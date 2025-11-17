# app/routers/doctors.py
<<<<<<< HEAD
from fastapi import APIRouter, Depends, HTTPException, status
=======
from fastapi import APIRouter, Depends, HTTPException
>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List
 
from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
<<<<<<< HEAD
 
=======

>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
router = APIRouter(
    prefix="/doctor",
    tags=["Doctor"]
)
<<<<<<< HEAD
 
=======

>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
@router.get("/patients", response_model=schemas.PatientsWithCount)
async def get_patients_for_doctor(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Only doctors and hospitals allowed
    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(status_code=403, detail="Not permitted")
 
    patients = []
<<<<<<< HEAD
 
    # =============================
    # If DOCTOR → fetch patients assigned to them
    # =============================
=======

    # -------------------------------
    # Fetch patients for a doctor
    # -------------------------------
>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
    if current_user.role == "doctor":
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
 
        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor record not found")
<<<<<<< HEAD
 
        result = await db.execute(
=======

        stmt = (
>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
            select(models.Patient)
            .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
            .where(models.Assignment.doctor_id == doctor.id)
            .options(
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
<<<<<<< HEAD
               # selectinload(models.Patient.patient_insurances),
               # selectinload(models.Patient.pharmacy_insurances),
                # Load encounters and nested vitals & medications
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.vitals)
=======
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.vitals),
                selectinload(models.Patient.encounters)
>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
                    .selectinload(models.Encounter.medications),
            )
            .order_by(models.Patient.first_name.asc(), models.Patient.last_name.asc())
        )

        result = await db.execute(stmt)
        patients = result.scalars().unique().all()
<<<<<<< HEAD
 
    # =============================
    # If HOSPITAL → fetch all hospital’s patients
    # =============================
=======

    # -------------------------------
    # Fetch patients for a hospital
    # -------------------------------
>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
    elif current_user.role == "hospital":
        stmt = (
            select(models.Patient)
            .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
            .where(models.Assignment.hospital_id == current_user.hospital_id)
            .options(
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),
<<<<<<< HEAD
                # Load encounters and nested vitals & medications
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.vitals)
=======
                selectinload(models.Patient.encounters)
                    .selectinload(models.Encounter.vitals),
                selectinload(models.Patient.encounters)
>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
                    .selectinload(models.Encounter.medications),
            )
            .order_by(models.Patient.first_name.asc(), models.Patient.last_name.asc())
        )

        result = await db.execute(stmt)
        patients = result.scalars().unique().all()
<<<<<<< HEAD
 
    # Final response with count
    return {
        "total_patients": len(patients),
        "patients": patients
    }
 
=======

    # -------------------------------
    # Return response
    # -------------------------------
    return schemas.PatientsWithCount(
        total_patients=len(patients),
        patients=patients
    )
>>>>>>> ab262e5e79e94637ead2cf9c30b34b290faebd22
