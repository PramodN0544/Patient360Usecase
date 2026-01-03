from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
from datetime import date, timedelta, datetime
from typing import Optional, List

router = APIRouter(
    prefix="/doctor",
    tags=["Doctor"]
)

@router.get("/patients", response_model=schemas.PatientsWithCount)
async def get_patients_for_doctor(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(403, "Not permitted")

    if current_user.role == "doctor":
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            raise HTTPException(404, "Doctor record not found")

        stmt = (
            select(models.Patient)
            .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
            .where(models.Assignment.doctor_id == doctor.id)
            .options(
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.vitals),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.medications),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.doctor),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.hospital),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.previous_encounter),
            )
            .order_by(models.Patient.first_name.asc())
        )

        result = await db.execute(stmt)
        patients = result.scalars().unique().all()

    else:  # hospital
        stmt = (
            select(models.Patient)
            .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
            .where(models.Assignment.hospital_id == current_user.hospital_id)
            .options(
                selectinload(models.Patient.allergies),
                selectinload(models.Patient.consents),
                selectinload(models.Patient.patient_insurances),
                selectinload(models.Patient.pharmacy_insurances),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.vitals),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.medications),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.doctor),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.hospital),
                selectinload(models.Patient.encounters).selectinload(models.Encounter.previous_encounter),
            )
        )
        result = await db.execute(stmt)
        patients = result.scalars().unique().all()

    # ---------------------- FIXED SERIALIZER ----------------------
    def serialize_patient(p: models.Patient):
        return {
            "id": p.id,
            "public_id": p.public_id,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "full_name": f"{p.first_name} {p.last_name}".strip(),
            "gender": p.gender,
            "dob": p.dob.isoformat() if p.dob else None,
            "email": p.email,
            "phone": p.phone,
            "photo_url": p.photo_url,
            "address": p.address,
            "city": p.city,
            "state": p.state,
            "zip_code": p.zip_code,
            "country": p.country,
            "allergies": [{"id": a.id, "name": a.name} for a in p.allergies] if p.allergies else [],
            "insurance_count": len(p.patient_insurances) if p.patient_insurances else 0,
            "pharmacy_insurance_count": len(p.pharmacy_insurances) if p.pharmacy_insurances else 0,
            "total_encounters": len(p.encounters) if p.encounters else 0
        }

    return {
        "total_patients": len(patients),
        "patients": [serialize_patient(p) for p in patients]
    }


@router.get("/patients/search", response_model=schemas.PatientsWithCount)
async def search_patients_for_doctor(
    status: str = "all",
    search: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(403, "Not permitted")

    doctor_result = await db.execute(
        select(models.Doctor).where(models.Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404, "Doctor not found")

    stmt = (
        select(models.Patient)
        .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
        .where(models.Assignment.doctor_id == doctor.id)
        .options(selectinload(models.Patient.encounters))
    )

    if search:
        s = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                models.Patient.first_name.ilike(s),
                models.Patient.last_name.ilike(s),
                models.Patient.email.ilike(s),
                models.Patient.phone.ilike(s),
            )
        )

    result = await db.execute(stmt)
    patients = result.scalars().unique().all()

    return {"total_patients": len(patients), "patients": patients}


@router.get("/appointments/today")
async def get_today_appointments(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(403, "Not permitted")

    today = date.today()

    # doctor login
    if current_user.role == "doctor":
        doctor = (
            await db.execute(
                select(models.Doctor).where(models.Doctor.user_id == current_user.id)
            )
        ).scalar_one_or_none()

        if not doctor:
            raise HTTPException(404, "Doctor not found")

        stmt = (
            select(models.Appointment)
            .where(
                models.Appointment.doctor_id == doctor.id,
                models.Appointment.appointment_date == today
            )
            .order_by(models.Appointment.appointment_time.asc())
            .options(selectinload(models.Appointment.patient))
        )

    # hospital login
    else:
        stmt = (
            select(models.Appointment)
            .where(
                models.Appointment.hospital_id == current_user.hospital_id,
                models.Appointment.appointment_date == today
            )
            .order_by(models.Appointment.appointment_time.asc())
            .options(selectinload(models.Appointment.patient))
        )

    result = await db.execute(stmt)
    appointments = result.scalars().all()

    return {
        "today_appointments": [
            {
                "appointment_id": a.id,
                "patient_public_id": a.patient.public_id,
                "patient_name": f"{a.patient.first_name} {a.patient.last_name}",
                "date": a.appointment_date,
                "time": a.appointment_time,
                "reason": a.reason,
                "status": a.status,
            }
            for a in appointments
        ]
    }


@router.get("/appointments/upcoming")
async def get_upcoming_appointments(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(403, "Not permitted")

    today = date.today()

    # doctor login
    if current_user.role == "doctor":
        doctor = (
            await db.execute(
                select(models.Doctor).where(models.Doctor.user_id == current_user.id)
            )
        ).scalar_one_or_none()

        if not doctor:
            raise HTTPException(404, "Doctor not found")

        stmt = (
            select(models.Appointment)
            .where(
                models.Appointment.doctor_id == doctor.id,
                models.Appointment.appointment_date >= today
            )
            .order_by(models.Appointment.appointment_date.asc())
            .options(selectinload(models.Appointment.patient))
        )

    # hospital login
    else:
        stmt = (
            select(models.Appointment)
            .where(
                models.Appointment.hospital_id == current_user.hospital_id,
                models.Appointment.appointment_date >= today
            )
            .order_by(models.Appointment.appointment_date.asc())
            .options(selectinload(models.Appointment.patient))
        )

    result = await db.execute(stmt)
    appointments = result.scalars().all()

    return {
        "upcoming_appointments": [
            {
                "appointment_id": a.id,
                "patient_public_id": a.patient.public_id,
                "patient_name": f"{a.patient.first_name} {a.patient.last_name}",
                "date": a.appointment_date,
                "time": a.appointment_time,
                "reason": a.reason,
                "status": a.status,
            }
            for a in appointments
        ]
    }

