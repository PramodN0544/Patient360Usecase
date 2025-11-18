

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import String, select, func
from sqlalchemy.orm import selectinload
from datetime import date

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas

router = APIRouter(
    prefix="/hospital",
    tags=["Hospital"]
)

# -----------------------------------------------------------
# 1️GET LOGGED-IN HOSPITAL PROFILE
# -----------------------------------------------------------
@router.get("/profile", response_model=schemas.HospitalOut)
async def get_hospital_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    result = await db.execute(
        select(models.Hospital)
        .where(models.Hospital.id == current_user.hospital_id)
    )
    hospital = result.scalar_one_or_none()

    if not hospital:
        raise HTTPException(404, "Hospital not found")

    return hospital


# -----------------------------------------------------------
# 2️ GET ALL DOCTORS UNDER THIS HOSPITAL
# -----------------------------------------------------------
@router.get("/doctors", response_model=list[schemas.DoctorOut])
async def get_hospital_doctors(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    stmt = (
        select(models.Doctor)
        .where(models.Doctor.hospital_id == current_user.hospital_id)
        .options(
            selectinload(models.Doctor.user)  # load doctor user info
        )
        .order_by(models.Doctor.first_name.asc())
    )

    result = await db.execute(stmt)
    doctors = result.scalars().all()

    return doctors


# -----------------------------------------------------------
# 3️ GET ALL PATIENTS OF THIS HOSPITAL
# -----------------------------------------------------------
@router.get("/patients", response_model=schemas.PatientsWithCount)
async def get_hospital_patients(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "hospital":
        raise HTTPException(403, "Not permitted")

    stmt = (
        select(models.Patient)
        .join(models.Assignment, models.Patient.id == models.Assignment.patient_id)
        .where(models.Assignment.hospital_id == current_user.hospital_id)
        .options(
            selectinload(models.Patient.allergies),
            selectinload(models.Patient.consents),
            selectinload(models.Patient.patient_insurances),
            selectinload(models.Patient.pharmacy_insurances),
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.doctor),
        )
    )

    result = await db.execute(stmt)
    patients = result.scalars().unique().all()

    return {
        "total_patients": len(patients),
        "patients": patients
    }


# -----------------------------------------------------------
# 4️ TODAY'S APPOINTMENTS COUNT
# -----------------------------------------------------------
@router.get("/appointments/today")
async def get_today_appointment_count(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    today = date.today()

    count_result = await db.execute(
        select(func.count(models.Appointment.id))
        .where(
            models.Appointment.hospital_id == current_user.hospital_id,
            models.Appointment.appointment_date == today
        )
    )
    count = count_result.scalar()

    return {"today_appointments": count}


# -----------------------------------------------------------
# 5️UPCOMING APPOINTMENTS FOR HOSPITAL
# -----------------------------------------------------------
@router.get("/appointments/upcoming")
async def get_upcoming_appointments(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    today = date.today()

    stmt = (
        select(models.Appointment)
        .where(
            models.Appointment.hospital_id == current_user.hospital_id,
            models.Appointment.appointment_date >= today
        )
        .options(
            selectinload(models.Appointment.patient),
            selectinload(models.Appointment.doctor)
        )
        .order_by(models.Appointment.appointment_date.asc())
    )

    result = await db.execute(stmt)
    appts = result.scalars().all()

    formatted = []
    for a in appts:
        formatted.append({
            "appointment_id": a.id,
            "patient_name": f"{a.patient.first_name} {a.patient.last_name}",
            "doctor_name": f"{a.doctor.first_name} {a.doctor.last_name}",
            "date": a.appointment_date,
            "time": a.appointment_time,
            "reason": a.reason,
            "status": a.status,
        })

    return {"upcoming_appointments": formatted}


# -----------------------------------------------------------
# 6️HOSPITAL DASHBOARD METRICS
# -----------------------------------------------------------
@router.get("/dashboard")
async def hospital_dashboard(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    hospital_id = current_user.hospital_id

    # Total Patients
    patient_count = (
        await db.execute(
            select(func.count(models.Assignment.id))
            .where(models.Assignment.hospital_id == hospital_id)
        )
    ).scalar()

    # Total Doctors
    doctor_count = (
        await db.execute(
            select(func.count(models.Doctor.id))
            .where(models.Doctor.hospital_id == hospital_id)
        )
    ).scalar()

    # Total Encounters
    encounter_count = (
        await db.execute(
            select(func.count(models.Encounter.id))
            .where(models.Encounter.hospital_id == hospital_id)
        )
    ).scalar()

    return {
        "total_patients": patient_count,
        "total_doctors": doctor_count,
        "total_encounters": encounter_count
    }


# -----------------------------------------------------------
# 7️ SEARCH DOCTORS IN HOSPITAL
# -----------------------------------------------------------
@router.get("/search/doctors", response_model=list[schemas.DoctorOut])
async def search_doctors(
    query: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospital can search doctors")

    search_filter = f"%{query.lower()}%"

    stmt = (
        select(models.Doctor)
        .where(models.Doctor.hospital_id == current_user.hospital_id)
        .where(
            (models.Doctor.first_name.ilike(search_filter)) |
            (models.Doctor.last_name.ilike(search_filter)) |
            (func.cast(models.Doctor.id, String).ilike(search_filter))
        )
        .options(selectinload(models.Doctor.user))
    )

    result = await db.execute(stmt)
    doctors = result.scalars().all()

    return doctors
