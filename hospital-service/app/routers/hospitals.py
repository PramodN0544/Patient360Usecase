

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import case, literal_column, select, func, String
from sqlalchemy.orm import selectinload
from datetime import date

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
from app import crud
from app.schemas import HospitalPatientOut
from sqlalchemy import func
# ROUTER
router = APIRouter(prefix="/hospitals", tags=["Hospital"])


# GET MY HOSPITAL PROFILE (Hospital Login)
@router.get("/", response_model=schemas.HospitalOut)
async def get_my_hospital_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    hospital = await crud.get_hospital_by_id(db, current_user.hospital_id)
    if not hospital:
        raise HTTPException(404, "Hospital profile not found")

    return hospital

# GET ALL DOCTORS FOR THIS HOSPITAL
@router.get("/doctors", response_model=list[schemas.DoctorOut])
async def get_all_doctors(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospital can view doctors")

    doctors = await crud.get_doctors_by_hospital(db, current_user.hospital_id)
    return doctors

# GET ALL PATIENTS ASSIGNED TO THIS HOSPITAL


@router.get("/patients", response_model=list[HospitalPatientOut])
async def get_hospital_patients(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    hospital_id = current_user.hospital_id

    query = (
        select(
            models.Patient.id.label("patient_id"),  # Keep as patient_id
            models.Patient.first_name,
            models.Patient.last_name,
            models.Patient.email,
            models.Patient.city,
            models.Patient.state,
            models.Patient.zip_code,
            models.Patient.citizenship_status,
            models.Patient.created_at,

            # ✅ Calculate age using DOB
            func.date_part(
                'year',
                func.age(func.now(), models.Patient.dob)
            ).label("age"),

            models.Patient.dob,
            models.Patient.gender,
            models.Patient.phone,

            # Set default values for frontend
            literal_column("'Active'").label("admission_status"),
            literal_column("'MRN001'").label("mrn"),
            literal_column("'Room 101'").label("room_bed"),

            models.Encounter.created_at.label("last_visit_date"),
            models.Encounter.diagnosis.label("diagnosis"),

            (models.Patient.first_name + " " + models.Patient.last_name)
                .label("patient_name"),

            (models.Doctor.first_name + " " + models.Doctor.last_name)
                .label("assigned_doctor"),

            # Insurance info
            models.PatientInsurance.policy_number.label("policy_number"),
            models.PatientPharmacyInsurance.policy_number.label("pharma_policy_number"),
            
            # Add insurance status based on policy existence
            case(
                (models.PatientInsurance.policy_number.isnot(None), "Insured"),
                else_="Not Insured"
            ).label("insurance_status"),
        )
        .join(models.Assignment, models.Assignment.patient_id == models.Patient.id)
        .join(models.Encounter, models.Encounter.patient_id == models.Patient.id, isouter=True)
        .join(models.Doctor, models.Doctor.id == models.Encounter.doctor_id, isouter=True)
        .join(
            models.PatientInsurance,
            models.PatientInsurance.patient_id == models.Patient.id,
            isouter=True
        )
        .join(
            models.PatientPharmacyInsurance,
            models.PatientPharmacyInsurance.patient_id == models.Patient.id,
            isouter=True
        )
        .where(models.Assignment.hospital_id == hospital_id)
        .distinct()
    )

    try:
        result = await db.execute(query)
        rows = result.mappings().all()
        return [HospitalPatientOut(**row) for row in rows]

    except Exception as e:
        print("ERROR:", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Internal Error: {e}")

# TODAY'S APPOINTMENT COUNT
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

    return {"today_appointments": count_result.scalar()}

# UPCOMING APPOINTMENTS LIST
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

# HOSPITAL DASHBOARD METRICS
@router.get("/dashboard")
async def hospital_dashboard(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospitals can access this")

    hospital_id = current_user.hospital_id

    # Total Patients assigned
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

# SEARCH DOCTORS BY NAME / ID
@router.get("/search/doctors", response_model=list[schemas.DoctorOut])
async def search_doctors(
    query: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospital can search doctors")

    like_query = f"%{query.lower()}%"

    stmt = (
        select(models.Doctor)
        .where(models.Doctor.hospital_id == current_user.hospital_id)
        .where(
            (models.Doctor.first_name.ilike(like_query)) |
            (models.Doctor.last_name.ilike(like_query)) |
            (func.cast(models.Doctor.id, String).ilike(like_query))
        )
        .options(selectinload(models.Doctor.user))
    )

    result = await db.execute(stmt)
    return result.scalars().all()
