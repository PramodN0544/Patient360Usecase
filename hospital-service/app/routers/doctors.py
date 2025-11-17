# app/routers/doctors.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func
from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
from datetime import date

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

    # If DOCTOR → fetch assigned patients
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

    # If HOSPITAL → fetch all hospital's patients
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


    # Final response
    return {
        "total_patients": len(patients),
        "patients": patients
    }


@router.get("/patients/search", response_model=schemas.PatientsWithCount)
async def search_patients_for_doctor(
    status: str = "all",             # all | pending | in_progress | completed
    search: str = None,              
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Role validation
    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(403, "Not permitted")

    # Identify doctor
    doctor_result = await db.execute(
        select(models.Doctor).where(models.Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor record not found")

    # Base query — get only this doctor's patients
    stmt = (
        select(models.Patient)
        .join(
            models.Assignment,
            models.Patient.id == models.Assignment.patient_id
        )
        .where(models.Assignment.doctor_id == doctor.id)
        .options(
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.vitals),
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.medications),
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.doctor),
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.hospital),
        )
    )

    # APPLY SEARCH FILTER
    if search:
        search_filter = f"%{search.lower()}%"
        stmt = stmt.where(
            (models.Patient.first_name.ilike(search_filter)) |
            (models.Patient.last_name.ilike(search_filter)) |
            (models.Patient.email.ilike(search_filter)) |
            (models.Patient.phone.ilike(search_filter))
        )

    result = await db.execute(stmt)
    patients = result.scalars().unique().all()

    # CATEGORIZE PATIENTS BASED ON STATUS
    from datetime import date

    pending = []
    in_progress = []
    completed = []

    for p in patients:
        latest_enc = None
        if p.encounters:
            latest_enc = max(p.encounters, key=lambda e: e.encounter_date)

        if not latest_enc:
            pending.append(p)
            continue

        # COMPLETED
        if latest_enc.status == "completed":
            completed.append(p)
            continue

        # IN PROGRESS → has follow_up_date in future
        if latest_enc.follow_up_date and latest_enc.follow_up_date > date.today():
            in_progress.append(p)
            continue

        # Otherwise pending
        pending.append(p)

    # RETURN BASED ON FILTER
    if status == "pending":
        filtered = pending
    elif status == "in_progress":
        filtered = in_progress
    elif status == "completed":
        filtered = completed
    else:
        filtered = patients  # all

    # FINAL RESPONSE
    return {
        "total_patients": len(filtered),
        "status_counts": {
            "all": len(patients),
            "pending": len(pending),
            "in_progress": len(in_progress),
            "completed": len(completed)
        },
        "patients": filtered
    }

#  GET TODAY'S APPOINTMENT COUNT
@router.get("/appointments/today")
async def get_today_appointment_count(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Validate role
    if current_user.role not in ("doctor", "hospital"):
        raise HTTPException(status_code=403, detail="Not permitted")

    # Get today
    today = date.today()


    # CASE 1: DOCTOR LOGGED IN
    if current_user.role == "doctor":
        doctor_result = await db.execute(
            select(models.Doctor)
            .where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            raise HTTPException(404, "Doctor record not found")

        # Count appointments for this doctor
        count_result = await db.execute(
            select(func.count(models.Appointment.id))
            .where(
                models.Appointment.doctor_id == doctor.id,
                models.Appointment.appointment_date == today
            )
        )
        count = count_result.scalar()

        return {"today_appointments": count}

    # CASE 2: HOSPITAL LOGGED IN
    elif current_user.role == "hospital":
        count_result = await db.execute(
            select(func.count(models.Appointment.id))
            .where(
                models.Appointment.hospital_id == current_user.hospital_id,
                models.Appointment.appointment_date == today
            )
        )
        count = count_result.scalar()

        return {"today_appointments": count}
