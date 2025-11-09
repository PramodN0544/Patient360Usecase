from datetime import datetime, timedelta
import uuid
import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional, List
from datetime import datetime, timedelta, time


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.schemas import AppointmentCreate, AppointmentResponse
from app.models import Appointment, Hospital, Doctor, Patient

router = APIRouter(prefix="/appointments", tags=["Appointments"])


# ---------------------------
# Dependency: Database session
# ---------------------------
async def get_db():
    from app.database import get_db
    async for session in get_db():
        yield session


# ---------------------------
# Helpers
# ---------------------------
def _time_to_str(t):
    if not t:
        return None
    # t may be datetime.time or str
    try:
        return t.strftime("%H:%M")
    except Exception:
        return str(t)


# ============================================================
# ✅ GET /appointments/doctors
# Single, robust endpoint with hospital + specialty filters
# ============================================================
@router.get("/doctors")
async def get_doctors(
    hospital_id: Optional[str] = Query(None, description="Filter by hospital id"),
    specialty: Optional[str] = Query(None, description="Filter by specialty (partial, case-insensitive)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Return doctors filtered by optional hospital_id and/or specialty.
    Uses case-insensitive matching for status and specialty.
    """

    # Base: active doctors (case-insensitive)
    query = select(Doctor).filter(func.lower(Doctor.status) == "active")

    # Filter by hospital if supplied (and ensure hospital exists)
    if hospital_id:
        hospital_result = await db.execute(select(Hospital).filter(Hospital.id == hospital_id))
        hospital = hospital_result.scalar_one_or_none()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")
        query = query.filter(Doctor.hospital_id == hospital_id)

    # Filter by specialty (case-insensitive partial match)
    if specialty and specialty.lower() != "all" and specialty.strip() != "":
        query = query.filter(func.lower(Doctor.specialty).contains(specialty.lower()))

    result = await db.execute(query)
    doctors = result.scalars().all()

    response = []
    for doc in doctors:
        hospital_result = await db.execute(select(Hospital).filter(Hospital.id == doc.hospital_id))
        hosp = hospital_result.scalar_one_or_none()
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
            "consultation_fee": float(hospital.consultation_fee) if hospital.consultation_fee else 0.0,
            "start_time": _time_to_str(doc.start_time) or "09:00",
            "end_time": _time_to_str(doc.end_time) or "17:00",
            "phone": doc.phone,
            "email": doc.email
        })

    return response


# ============================================================
# ✅ GET /appointments/doctors/specialty/{specialty}
# return doctors by specialty only (patient enrollment use-case)
# ============================================================
@router.get("/doctors/specialty/{specialty}")
async def get_doctors_by_specialty(
    specialty: str,
    db: AsyncSession = Depends(get_db)
):
    """Return all active doctors whose specialty matches (case-insensitive partial)"""
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


# ============================================================
# ✅ GET /appointments/hospitals
# return all active hospitals
# ============================================================
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


# ============================================================
# ✅ GET /appointments/hospitals/{hospital_id}
# return full hospital details
# ============================================================
@router.get("/hospitals/{hospital_id}")
async def get_hospital_details(hospital_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Hospital).filter(
            Hospital.id == hospital_id,
            func.lower(Hospital.status) == "active"
        )
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


# ============================================================
# ✅ GET /appointments/hospitals/doctors
# doctors for a specific hospital (patient accessible)
# ============================================================
@router.get("/hospitals/doctors")
async def get_hospitals_doctors(
    hospital_id: str = Query(..., description="Hospital ID"),
    db: AsyncSession = Depends(get_db)
):
    # Verify hospital exists
    hospital_result = await db.execute(select(Hospital).filter(Hospital.id == hospital_id))
    hospital = hospital_result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    query = select(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        func.lower(Doctor.status) == "active"
    )
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


# ============================================================
# ✅ GET /appointments/specialties
# return distinct specialties from active doctors
# ============================================================
@router.get("/specialties")
async def get_all_specialties(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Doctor.specialty).distinct().filter(func.lower(Doctor.status) == "active")
    )
    specialties = result.scalars().all()
    return {"specialties": [spec for spec in specialties if spec]}


# ============================================================
# ✅ GET /appointments/slots?doctor_id=...&date=YYYY-MM-DD
# available time slots for a doctor
# ============================================================
@router.get("/slots")
async def get_available_slots(
    doctor_id: str = Query(..., description="Doctor ID"),
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


# ============================================================
# ✅ POST /appointments/  (book appointment)
# ============================================================
@router.post("/")
async def book_appointment(
    appointment: AppointmentCreate,
    db: AsyncSession = Depends(get_db)
):
    # Validate hospital, doctor, patient presence
    hospital_result = await db.execute(select(Hospital).filter(Hospital.id == appointment.hospital_id))
    hospital = hospital_result.scalar_one_or_none()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    doctor_result = await db.execute(select(Doctor).filter(Doctor.id == appointment.doctor_id))
    doctor = doctor_result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    patient_result = await db.execute(select(Patient).filter(Patient.id == appointment.patient_id))
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Parse appointment_time
# ✅ Robust time parsing that accepts str or datetime.time
       # ✅ Robust time parsing that accepts str or datetime.time
    if isinstance(appointment.appointment_time, str):
        # Try HH:MM
        try:
            appointment_time = datetime.strptime(
                appointment.appointment_time, "%H:%M"
            ).time()
        except ValueError:
            # Try HH:MM:SS
            try:
                appointment_time = datetime.strptime(
                    appointment.appointment_time, "%H:%M:%S"
                ).time()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid time format. Use HH:MM or HH:MM:SS"
                )

    elif isinstance(appointment.appointment_time, time):
        appointment_time = appointment.appointment_time

    else:
        raise HTTPException(
            status_code=400,
            detail="appointment_time must be a string or a time object"
        )


    # Check slot availability
    result = await db.execute(
        select(Appointment).filter(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.appointment_date == appointment.appointment_date,
            Appointment.appointment_time == appointment_time,
            Appointment.status.in_(["Confirmed", "Pending"])
        )
    )
    exists = result.scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="This time slot is already booked")

    appointment_id = f"APT-{uuid.uuid4().hex[:8].upper()}"
    new_appt = Appointment(
        appointment_id=appointment_id,
        hospital_id=appointment.hospital_id,
        doctor_id=appointment.doctor_id,
        patient_id=appointment.patient_id,
        appointment_date=appointment.appointment_date,
        appointment_time=appointment_time,
        reason=appointment.reason,
        mode=appointment.mode,
        status="Confirmed"
    )

    db.add(new_appt)
    await db.commit()
    await db.refresh(new_appt)

    # Send email (best-effort)
    try:
        if patient.email:
            send_email_confirmation(patient.email, new_appt, doctor, hospital)
    except Exception as e:
        # don't block booking on email failure
        print("⚠️ Email sending failed:", e)

    return {
        "message": "Appointment booked successfully",
        "appointment_id": appointment_id,
        "appointment": {
            "appointment_id": appointment_id,
            "hospital_id": appointment.hospital_id,
            "doctor_id": appointment.doctor_id,
            "appointment_date": str(appointment.appointment_date),
            "appointment_time": appointment.appointment_time,
            "reason": appointment.reason,
            "mode": appointment.mode,
            "status": "Confirmed"
        }
    }


# ============================================================
# Email helper (best-effort)
# ============================================================
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

    if EMAIL_USER and EMAIL_PASS:
        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(EMAIL_USER, EMAIL_PASS)
                server.send_message(msg)
            print(f"✅ Confirmation email sent to {to_email}")
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {e}")
    else:
        print("ℹ️ Email credentials not configured, skipping email sending")


# ============================================================
# ✅ GET /appointments/patient/{patient_id}
# return appointments for a patient (enriched)
# ============================================================
@router.get("/patient/{patient_id}")
async def get_appointments_by_patient(patient_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Appointment)
        .filter(Appointment.patient_id == patient_id)
        .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
    )
    appointments = result.scalars().all()

    if not appointments:
        return []

    enriched = []
    for appt in appointments:
        doctor_result = await db.execute(select(Doctor).filter(Doctor.id == appt.doctor_id))
        doctor = doctor_result.scalar_one_or_none()

        hospital_result = await db.execute(select(Hospital).filter(Hospital.id == appt.hospital_id))
        hosp = hospital_result.scalar_one_or_none()

        enriched.append({
            "appointment_id": appt.appointment_id,
            "hospital_id": appt.hospital_id,
            "doctor_id": appt.doctor_id,
            "appointment_date": str(appt.appointment_date),
            "appointment_time": appt.appointment_time.strftime("%H:%M") if appt.appointment_time else None,
            "reason": appt.reason,
            "mode": appt.mode,
            "status": appt.status,
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "Unknown Doctor",
            "doctor_specialty": doctor.specialty if doctor else "Unknown Specialty",
            "hospital_name": hosp.name if hosp else "Unknown Hospital",
            "department": doctor.specialty if doctor else "General"
        })
    return enriched


# ============================================================
# ✅ GET /appointments/doctor/{doctor_id}
# return appointments for a doctor (enriched)
# ============================================================
@router.get("/doctor/{doctor_id}")
async def get_appointments_by_doctor(doctor_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Appointment)
        .filter(Appointment.doctor_id == doctor_id)
        .order_by(Appointment.appointment_date.desc())
    )
    appointments = result.scalars().all()
    if not appointments:
        return []

    enriched = []
    for appt in appointments:
        patient_result = await db.execute(select(Patient).filter(Patient.id == appt.patient_id))
        patient = patient_result.scalar_one_or_none()

        hosp_result = await db.execute(select(Hospital).filter(Hospital.id == appt.hospital_id))
        hosp = hosp_result.scalar_one_or_none()

        enriched.append({
            "appointment_id": appt.appointment_id,
            "patient_id": appt.patient_id,
            "hospital_id": appt.hospital_id,
            "appointment_date": str(appt.appointment_date),
            "appointment_time": appt.appointment_time.strftime("%H:%M") if appt.appointment_time else None,
            "reason": appt.reason,
            "status": appt.status,
            "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Unknown Patient",
            "hospital_name": hosp.name if hosp else "Unknown Hospital"
        })
    return enriched


# ============================================================
# ✅ Debug: GET /appointments/debug/specialty?specialty=cardiology
# returns all specialties and filtered results for debugging
# ============================================================
@router.get("/debug/specialty")
async def debug_specialty(specialty: str = Query(..., description="Specialty to debug"), db: AsyncSession = Depends(get_db)):
    # Get all doctor specialties (raw)
    all_result = await db.execute(select(Doctor))
    all_doctors = all_result.scalars().all()

    # Filtered (active + specialty partial match)
    filtered_result = await db.execute(
        select(Doctor).filter(
            func.lower(Doctor.status) == "active",
            func.lower(Doctor.specialty).contains(specialty.lower())
        )
    )
    filtered_doctors = filtered_result.scalars().all()

    return {
        "requested_specialty": specialty,
        "all_doctors_specialties": [{"id": d.id, "specialty": d.specialty, "status": d.status} for d in all_doctors],
        "filtered_doctors_count": len(filtered_doctors),
        "filtered_doctors": [{"id": d.id, "name": f"{d.first_name} {d.last_name}", "specialty": d.specialty, "status": d.status} for d in filtered_doctors]
    }


# ============================================================
# ✅ PUT /appointments/{appointment_id}/cancel
# Cancel appointment
# ============================================================
@router.put("/{appointment_id}/cancel")
async def cancel_appointment(appointment_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Appointment).filter(Appointment.appointment_id == appointment_id))
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if appointment.status.lower() == "cancelled" or appointment.status.lower() == "canceled":
        raise HTTPException(status_code=400, detail="Appointment is already cancelled")

    appointment.status = "cancelled"
    await db.commit()

    return {"message": "Appointment cancelled successfully", "appointment_id": appointment_id}
