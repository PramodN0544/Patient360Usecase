from datetime import datetime, timedelta
import uuid
import os
import smtplib
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.schemas import AppointmentCreate, AppointmentResponse
from app.models import Appointment, Hospital, Doctor, Patient  # Your SQLAlchemy models


router = APIRouter(prefix="/appointments", tags=["Appointments"])


# ===============================
# Dependency: Database session
# ===============================
async def get_db():
    from app.database import get_db
    async for session in get_db():
        yield session


# ===============================
# 1️⃣ Get Doctors by Hospital + Specialty
# ===============================
@router.get("/doctors")
async def get_doctors(
    hospital_id: str,
    specialty: str,
    db: AsyncSession = Depends(get_db)
):
    hospital_result = await db.execute(select(Hospital).filter(Hospital.id == hospital_id))
    hospital = hospital_result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    doctor_result = await db.execute(
        select(Doctor).filter(
            Doctor.hospital_id == hospital_id,
            Doctor.specialty.ilike(f"%{specialty}%"),
            Doctor.status == "active"
        )
    )
    doctors = doctor_result.scalars().all()
    if not doctors:
        raise HTTPException(status_code=404, detail="No doctors found for this specialty")

    return [
        {
            "doctor_id": d.id,
            "name": f"Dr. {d.first_name} {d.last_name}",
            "specialty": d.specialty,
            "start_time": str(d.start_time),
            "end_time": str(d.end_time),
            "hospital_name": hospital.name
        }
        for d in doctors
    ]


# ===============================
# 2️⃣ Get Available Time Slots for Doctor
# ===============================
@router.get("/slots")
async def get_available_slots(
    doctor_id: str,
    date: str = Query(..., description="Appointment date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db)
):
    doctor_result = await db.execute(select(Doctor).filter(Doctor.id == doctor_id))
    doctor = doctor_result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    appointment_date = datetime.strptime(date, "%Y-%m-%d").date()
    result = await db.execute(
        select(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date
        )
    )
    existing_appointments = result.scalars().all()
    booked_times = {appt.appointment_time.strftime("%H:%M") for appt in existing_appointments}

    slots = []
    start = datetime.combine(appointment_date, doctor.start_time)
    end = datetime.combine(appointment_date, doctor.end_time)
    slot_duration = timedelta(minutes=30)
    current = start
    while current < end:
        slot_str = current.strftime("%H:%M")
        if slot_str not in booked_times:
            slots.append(slot_str)
        current += slot_duration

    return {"doctor_id": doctor_id, "date": date, "available_slots": slots}


# ===============================
# 3️⃣ Book Appointment
# ===============================
@router.post("/")
async def book_appointment(
    appointment: AppointmentCreate,
    db: AsyncSession = Depends(get_db)
):
    # Check hospital
    hospital_result = await db.execute(select(Hospital).filter(Hospital.id == appointment.hospital_id))
    hospital = hospital_result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Check doctor
    doctor_result = await db.execute(select(Doctor).filter(Doctor.id == appointment.doctor_id))
    doctor = doctor_result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Check patient
    patient_result = await db.execute(select(Patient).filter(Patient.id == appointment.patient_id))
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Check existing appointment
    result = await db.execute(
        select(Appointment).filter(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.appointment_date == appointment.appointment_date,
            Appointment.appointment_time == appointment.appointment_time
        )
    )
    exists = result.scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Slot already booked")

    # Create appointment ID
    appointment_id = f"APT-{uuid.uuid4().hex[:8].upper()}"

    new_appt = Appointment(
        appointment_id=appointment_id,
        hospital_id=appointment.hospital_id,
        doctor_id=appointment.doctor_id,
        patient_id=appointment.patient_id,
        appointment_date=appointment.appointment_date,
        appointment_time=appointment.appointment_time,
        reason=appointment.reason,
        mode=appointment.mode,
        status="Confirmed"
    )

    db.add(new_appt)
    await db.commit()
    await db.refresh(new_appt)

    # Send email
    try:
        if patient.email:
            send_email_confirmation(patient.email, new_appt, doctor, hospital)
    except Exception as e:
        print("⚠️ Email sending failed:", e)

    return {"message": "Appointment booked successfully", "appointment_id": appointment_id}


# ===============================
# Email confirmation
# ===============================
def send_email_confirmation(to_email, appointment, doctor, hospital):
    subject = f"Appointment Confirmation - {hospital.name}"
    body = f"""
Dear Patient,

Your appointment has been successfully booked.

🏥 Hospital: {hospital.name}
👨‍⚕️ Doctor: Dr. {doctor.first_name} {doctor.last_name} ({doctor.specialty})
📅 Date: {appointment.appointment_date}
⏰ Time: {appointment.appointment_time}
📝 Reason: {appointment.reason or "N/A"}

Appointment ID: {appointment.appointment_id}

Thank you,
Patient360 Team
"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("EMAIL_USER", "no-reply@patient360.com")
    msg["To"] = to_email

    EMAIL_USER = os.getenv("EMAIL_USER")
    EMAIL_PASS = os.getenv("EMAIL_PASS")

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)


# ===============================
# 4️⃣ Get Appointments by Patient
# ===============================
@router.get("/patient/{patient_id}")
async def get_appointments_by_patient(patient_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Appointment)
        .filter(Appointment.patient_id == patient_id)
        .order_by(Appointment.appointment_date.desc())
    )
    appointments = result.scalars().all()
    if not appointments:
        raise HTTPException(status_code=404, detail="No appointments found for this patient")

    return [
        {
            "appointment_id": a.appointment_id,
            "hospital_id": a.hospital_id,
            "doctor_id": a.doctor_id,
            "appointment_date": str(a.appointment_date),
            "appointment_time": str(a.appointment_time),
            "reason": a.reason,
            "status": a.status
        }
        for a in appointments
    ]


# ===============================
# 5️⃣ Get Appointments by Doctor
# ===============================
@router.get("/doctor/{doctor_id}")
async def get_appointments_by_doctor(doctor_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Appointment)
        .filter(Appointment.doctor_id == doctor_id)
        .order_by(Appointment.appointment_date.desc())
    )
    appointments = result.scalars().all()
    if not appointments:
        raise HTTPException(status_code=404, detail="No appointments found for this doctor")

    return [
        {
            "appointment_id": a.appointment_id,
            "patient_id": a.patient_id,
            "hospital_id": a.hospital_id,
            "appointment_date": str(a.appointment_date),
            "appointment_time": str(a.appointment_time),
            "reason": a.reason,
            "status": a.status
        }
        for a in appointments
    ]
