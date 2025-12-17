from datetime import datetime, timedelta
import os
import smtplib
import uuid
from email.mime.text import MIMEText
from sqlalchemy.orm import selectinload
from sqlalchemy import func,or_
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models import Notification, Appointment, Hospital, Doctor, Patient
from app import schemas, models
from app.schemas import AppointmentCreate, AppointmentPatientResponse
from app.auth import get_current_user
from datetime import date


router = APIRouter(prefix="/appointments", tags=["Appointments"])

# Dependency: Database session
async def get_db():
    from app.database import get_db
    async for session in get_db():
        yield session

# Helpers
def _time_to_str(t):
    if not t:
        return None
    try:
        return t.strftime("%H:%M")
    except Exception:
        return str(t)

# GET /appointments/doctors
# Filter doctors by hospital_id or specialty
@router.get("/doctors")
async def get_doctors(
    hospital_id: Optional[int] = Query(None, description="Filter by hospital id"),
    specialty: Optional[str] = Query(None, description="Filter by specialty (partial, case-insensitive)"),
    db: AsyncSession = Depends(get_db)
):
    query = select(Doctor).filter(func.lower(Doctor.status) == "active")

    # Optional: filter by hospital
    if hospital_id:
        hospital_result = await db.execute(select(Hospital).filter(Hospital.id == hospital_id))
        hospital = hospital_result.scalar_one_or_none()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")
        query = query.filter(Doctor.hospital_id == hospital_id)

    # Optional: filter by specialty
    if specialty and specialty.lower() != "all" and specialty.strip() != "":
        query = query.filter(func.lower(Doctor.specialty).contains(specialty.lower()))

    result = await db.execute(query)
    doctors = result.scalars().all()

    response = []
    for doc in doctors:
        # Fetch hospital per doctor to avoid undefined variable
        hosp_result = await db.execute(select(Hospital).filter(Hospital.id == doc.hospital_id))
        hosp = hosp_result.scalar_one_or_none()

        response.append({
            "id": doc.id,
            "doctor_id": doc.id,
            "first_name": doc.first_name,
            "last_name": doc.last_name,
            "name": f"Dr. {doc.first_name} {doc.last_name}",
            "specialty": doc.specialty,
            "qualification": doc.qualification,
            "hospital_id": doc.hospital_id,
            "hospital_name": hosp.name if hosp else "Unknown Hospital",
            "experience_years": doc.experience_years,
            "consultation_fee": float(hosp.consultation_fee) if hosp and hosp.consultation_fee else 0.0,
            "start_time": _time_to_str(doc.start_time) or "09:00",
            "end_time": _time_to_str(doc.end_time) or "17:00",
            "phone": doc.phone,
            "email": doc.email
        })

    return response

# GET /appointments/doctors/specialty/{specialty}
@router.get("/doctors/specialty/{specialty}")
async def get_doctors_by_specialty(
    specialty: str,
    db: AsyncSession = Depends(get_db)
):
    query = select(Doctor).filter(func.lower(Doctor.status) == "active")
    if specialty and specialty.lower() != "all":
        query = query.filter(func.lower(Doctor.specialty).contains(specialty.lower()))

    result = await db.execute(query)
    doctors = result.scalars().all()

    doctors_list = []
    for doc in doctors:
        hospital_result = await db.execute(select(Hospital).filter(Hospital.id == doc.hospital_id))
        hosp = hospital_result.scalar_one_or_none()
        doctors_list.append({
            "id": doc.id,
            "doctor_id": doc.id,
            "first_name": doc.first_name,
            "last_name": doc.last_name,
            "name": f"Dr. {doc.first_name} {doc.last_name}",
            "specialty": doc.specialty,
            "qualification": doc.qualification,
            "hospital_id": doc.hospital_id,
            "hospital_name": hosp.name if hosp else "Unknown Hospital",
            "experience_years": doc.experience_years,
            "consultation_fee": float(doc.consultation_fee) if doc.consultation_fee else 0.0,
            "start_time": _time_to_str(doc.start_time) or "09:00",
            "end_time": _time_to_str(doc.end_time) or "17:00",
            "phone": doc.phone,
            "email": doc.email
        })
    return doctors_list

# GET /appointments/hospitals
@router.get("/hospitals")
async def get_all_hospitals(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Hospital).filter(func.lower(Hospital.status) == "active"))
    hospitals = result.scalars().all()
    return [
        {
            "id": h.id,
            "name": h.name,
            "address": f"{h.address}, {h.city}, {h.state} {h.zip_code}",
            "phone": h.phone,
            "email": h.email,
            "specialty": h.specialty,
            "website": h.website,
            "registration_no": h.registration_no,
            "license_number": h.license_number
        }
        for h in hospitals
    ]

# GET /appointments/hospitals/{hospital_id}
@router.get("/hospitals/{hospital_id}")
async def get_hospital_details(hospital_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Hospital).filter(Hospital.id == hospital_id, func.lower(Hospital.status) == "active")
    )
    hospital = result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    return {
        "id": hospital.id,
        "name": hospital.name,
        "registration_no": hospital.registration_no,
        "email": hospital.email,
        "phone": hospital.phone,
        "address": hospital.address,
        "city": hospital.city,
        "state": hospital.state,
        "zip_code": hospital.zip_code,
        "country": hospital.country,
        "specialty": hospital.specialty,
        "license_number": hospital.license_number,
        "qualification": hospital.qualification,
        "experience_years": hospital.experience_years,
        "availability_days": hospital.availability_days,
        "start_time": _time_to_str(hospital.start_time),
        "end_time": _time_to_str(hospital.end_time),
        "consultation_fee": float(hospital.consultation_fee) if hospital.consultation_fee else 0.0,
        "website": hospital.website,
        "status": hospital.status,
        "full_address": f"{hospital.address}, {hospital.city}, {hospital.state} {hospital.zip_code}, {hospital.country}"
    }

# GET /appointments/hospitals/doctors
@router.get("/hospitals/doctors")
async def get_hospitals_doctors(
    hospital_id: int = Query(..., description="Hospital ID"),
    db: AsyncSession = Depends(get_db)
):
    hospital_result = await db.execute(select(Hospital).filter(Hospital.id == hospital_id))
    hospital = hospital_result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    query = select(Doctor).filter(Doctor.hospital_id == hospital_id, func.lower(Doctor.status) == "active")
    doctor_result = await db.execute(query)
    doctors = doctor_result.scalars().all()

    doctors_list = []
    for doc in doctors:
        doctors_list.append({
            "id": doc.id,
            "doctor_id": doc.id,
            "first_name": doc.first_name,
            "last_name": doc.last_name,
            "name": f"Dr. {doc.first_name} {doc.last_name}",
            "specialty": doc.specialty,
            "qualification": doc.qualification,
            "hospital_id": doc.hospital_id,
            "hospital_name": hospital.name,
            "experience_years": doc.experience_years,
            "consultation_fee": float(doc.consultation_fee) if doc.consultation_fee else 0.0,
            "start_time": _time_to_str(doc.start_time) or "09:00",
            "end_time": _time_to_str(doc.end_time) or "17:00",
            "phone": doc.phone,
            "email": doc.email
        })

    return doctors_list

# GET /appointments/specialties
@router.get("/specialties")
async def get_all_specialties(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Doctor.specialty).distinct().filter(func.lower(Doctor.status) == "active"))
    specialties = result.scalars().all()
    return {"specialties": [spec for spec in specialties if spec]}

# GET /appointments/slots
@router.get("/slots")
async def get_available_slots(
    doctor_id: int = Query(..., description="Doctor ID"),
    date: str = Query(..., description="Appointment date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db)
):
    doctor_result = await db.execute(select(Doctor).filter(Doctor.id == doctor_id))
    doctor = doctor_result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    try:
        appointment_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if appointment_date < datetime.now().date():
        raise HTTPException(status_code=400, detail="Cannot book appointments in the past")

    result = await db.execute(
        select(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status.in_(["Confirmed", "Pending"])
        )
    )
    existing_appointments = result.scalars().all()
    booked_times = {appt.appointment_time.strftime("%H:%M") for appt in existing_appointments if appt.appointment_time}

    slots = []
    start_time = doctor.start_time if doctor.start_time else datetime.strptime("09:00", "%H:%M").time()
    end_time = doctor.end_time if doctor.end_time else datetime.strptime("17:00", "%H:%M").time()

    start = datetime.combine(appointment_date, start_time)
    end = datetime.combine(appointment_date, end_time)
    slot_duration = timedelta(minutes=30)
    current = start

    while current < end:
        slot_str = current.strftime("%H:%M")
        slots.append({
            "time": slot_str,
            "available": slot_str not in booked_times,
            "slot_id": f"slot_{current.hour}_{current.minute}"
        })
        current += slot_duration

    return {
        "doctor_id": doctor_id,
        "date": date,
        "available_slots": slots,
        "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}"
    }

@router.post("/")
async def book_appointment(
    appointment: AppointmentCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from datetime import date

    # Prevent booking for past dates
    if appointment.appointment_date < date.today():
        raise HTTPException(
            status_code=400,
            detail="Cannot book appointments for past dates"
        )

    user_id = current_user.id

    # Fetch patient
    patient_result = await db.execute(select(Patient).filter(Patient.user_id == user_id))
    patient = patient_result.unique().scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient_id = patient.id

    # Fetch hospital
    hospital_result = await db.execute(select(Hospital).filter(Hospital.id == appointment.hospital_id))
    hospital = hospital_result.unique().scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Fetch doctor
    doctor_result = await db.execute(select(Doctor).filter(Doctor.id == appointment.doctor_id))
    doctor = doctor_result.unique().scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Parse appointment time
    if isinstance(appointment.appointment_time, str):
        try:
            appointment_time = datetime.strptime(appointment.appointment_time, "%H:%M").time()
        except:
            try:
                appointment_time = datetime.strptime(appointment.appointment_time, "%H:%M:%S").time()
            except:
                raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM or HH:MM:SS")
    else:
        appointment_time = appointment.appointment_time

    # Check if slot is already booked
    existing_result = await db.execute(
        select(Appointment).filter(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.appointment_date == appointment.appointment_date,
            Appointment.appointment_time == appointment_time,
            Appointment.status.in_(["Confirmed", "Pending"])
        )
    )
    exists = existing_result.scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="This time slot is already booked")

    # Create appointment
    new_appt = Appointment(
        appointment_id=str(uuid.uuid4()),
        hospital_id=appointment.hospital_id,
        doctor_id=appointment.doctor_id,
        patient_id=patient_id,
        appointment_date=appointment.appointment_date,
        appointment_time=appointment_time,
        reason=appointment.reason,
        mode=appointment.mode,
        status="Confirmed"
    )
    db.add(new_appt)
    await db.commit()
    await db.refresh(new_appt)  # Populate ID

    # Create notification
    notif = Notification(
        user_id=current_user.id,
        title="Appointment Confirmed",
        desc=f"Your visit with Dr. {doctor.first_name} {doctor.last_name} "
             f"is confirmed for {appointment.appointment_date} at {appointment_time.strftime('%H:%M')}",
        type="appointment",
        status="unread",
    )

    db.add(notif)
    await db.commit()
    await db.refresh(notif)

    # Send email confirmation (best-effort)
    try:
        if patient.email:
            send_email_confirmation(patient.email, new_appt, doctor, hospital)
    except Exception as e:
        print("⚠️ Email sending failed:", e)

    # Response
    return {
        "message": "Appointment booked successfully",
        "appointment_id": new_appt.id,
        "appointment": {
            "id": new_appt.id,
            "hospital_id": new_appt.hospital_id,
            "doctor_id": new_appt.doctor_id,
            "appointment_date": str(new_appt.appointment_date),
            "appointment_time": appointment_time.strftime("%H:%M"),
            "reason": new_appt.reason,
            "mode": new_appt.mode,
            "status": "Confirmed"
        }
    }


def send_email_confirmation(to_email, appointment, doctor, hospital):
    subject = f"Appointment Confirmation - {hospital.name}"
    body = f"""
Dear Patient,

Your appointment has been successfully booked.

🏥 Hospital: {hospital.name}
👨‍⚕️ Doctor: Dr. {doctor.first_name} {doctor.last_name} ({doctor.specialty})
📅 Date: {appointment.appointment_date}
⏰ Time: {appointment.appointment_time.strftime('%H:%M') if hasattr(appointment.appointment_time, 'strftime') else appointment.appointment_time}
📝 Reason: {appointment.reason or "N/A"}
💻 Mode: {appointment.mode}

Appointment ID: {appointment.id}

Thank you,
Patient360 Team
"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("FROM_EMAIL", "no-reply@patient360.com")
    msg["To"] = to_email

    EMAIL_USER = os.getenv("SMTP_USERNAME")
    EMAIL_PASS = os.getenv("SMTP_PASSWORD")
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

    if EMAIL_USER and EMAIL_PASS:
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(EMAIL_USER, EMAIL_PASS)
                server.send_message(msg)
            print(f"✅ Confirmation email sent to {to_email}")
            print("User Mail is :", to_email)
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {e}")
    else:
        print("ℹ️ Email credentials not configured, skipping email sending")

# In your appointment.py router, add this endpoint
@router.get("/patient", response_model=List[schemas.AppointmentPatientResponse])
async def get_my_appointments(
    status: Optional[str] = Query(None),
    date_filter: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user=Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    """
    Get appointments for the current patient.
    This is the endpoint that React is calling.
    """
    # Validate role - only patients can access this endpoint
    if current_user.role != "patient":
        raise HTTPException(status_code=403, detail="Only patients can access this endpoint")

    # Fetch patient by user_id
    patient_result = await db.execute(select(models.Patient).filter(models.Patient.user_id == current_user.id))
    patient = patient_result.unique().scalar_one_or_none()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    # Base query for patient's appointments
    stmt = (
        select(models.Appointment)
        .filter(models.Appointment.patient_id == patient.id)
        .options(
            selectinload(models.Appointment.patient),
            selectinload(models.Appointment.doctor),
            selectinload(models.Appointment.hospital)
        )
    )

    # Apply status filter
    if status and status != "all":
        stmt = stmt.where(models.Appointment.status == status)

    # Apply date filter
    today = date.today()
    if date_filter:
        if date_filter == "today":
            stmt = stmt.where(models.Appointment.appointment_date == today)
        elif date_filter == "week":
            week_end = today + timedelta(days=7)
            stmt = stmt.where(
                models.Appointment.appointment_date >= today,
                models.Appointment.appointment_date <= week_end
            )
        elif date_filter == "month":
            month_end = today + timedelta(days=30)
            stmt = stmt.where(
                models.Appointment.appointment_date >= today,
                models.Appointment.appointment_date <= month_end
            )
        elif date_filter == "past":
            stmt = stmt.where(models.Appointment.appointment_date < today)

    # Apply search filter
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                models.Appointment.doctor.has(
                    or_(
                        models.Doctor.first_name.ilike(search_term),
                        models.Doctor.last_name.ilike(search_term)
                    )
                ),
                models.Appointment.reason.ilike(search_term)
            )
        )

    # Order by date and time (newest first)
    stmt = stmt.order_by(
        models.Appointment.appointment_date.desc(),
        models.Appointment.appointment_time.desc().nullslast()
    )

    # Execute query
    result = await db.execute(stmt)
    appointments = result.unique().scalars().all()

    # Format response to match your existing format
    enriched = []
    for appt in appointments:
        # Get doctor details
        doctor_result = await db.execute(
            select(models.Doctor).filter(models.Doctor.id == appt.doctor_id)
        )
        doctor = doctor_result.unique().scalar_one_or_none()

        # Get hospital details
        hosp_result = await db.execute(
            select(models.Hospital).filter(models.Hospital.id == appt.hospital_id)
        )
        hosp = hosp_result.unique().scalar_one_or_none()

        enriched.append({
            "appointment_id": appt.id,
            "hospital_id": appt.hospital_id,
            "hospital_name": hosp.name if hosp else "Unknown Hospital",
            "doctor_id": appt.doctor_id,
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "Unknown Doctor",
            "doctor_specialty": doctor.specialty if doctor else "General",
            "appointment_date": str(appt.appointment_date),
            "appointment_time": appt.appointment_time.strftime("%H:%M") if appt.appointment_time else None,
            "reason": appt.reason,
            "mode": appt.mode,
            "status": appt.status
        })

    return enriched