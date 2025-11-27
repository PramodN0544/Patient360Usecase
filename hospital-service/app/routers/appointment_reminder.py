# appointment_reminder.py
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Appointment, Patient, Notification, PatientConsent, User
import pytz

IST = pytz.timezone("Asia/Kolkata")


async def send_appointment_reminders(db: AsyncSession):
    print("🔔 Running appointment reminder job...")
    now = datetime.now(IST)

    # Fetch upcoming appointments
    result = await db.execute(
        select(Appointment, Patient, User)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(User, User.id == Patient.user_id, isouter=True)
        .filter(Appointment.status.in_(["Confirmed", "Pending"]))
    )
    rows = result.unique().all()
    print("Checking upcoming appointments...")
    print(f"Found appointments: {len(rows)}")

    for appt, patient, user in rows:
        appt_dt = IST.localize(datetime.combine(appt.appointment_date, appt.appointment_time))
        if appt_dt < now:
            continue

        # Consent check
        consent_res = await db.execute(
            select(PatientConsent).filter(PatientConsent.patient_id == patient.id)
        )
        consent = consent_res.scalar_one_or_none()
        if consent and consent.text_messaging is False:
            continue

        # Reminder times
        one_day_before = appt_dt - timedelta(days=1)
        two_hours_before = appt_dt - timedelta(hours=2)

        async def maybe_create(title: str, desc: str, reminder_type: str, scheduled_for: datetime):
            q = select(Notification).filter(
                Notification.type == "appointment",
                Notification.data_id == str(appt.id),
                Notification.reminder_type == reminder_type
            )
            existing = (await db.execute(q)).scalars().first()
            if existing:
                return
            notif = Notification(
                user_id=user.id if user else None,
                patient_id=patient.id,
                title=title,
                desc=desc,
                type="appointment",
                reminder_type=reminder_type,
                status="unread",
                data_id=str(appt.id),
                scheduled_for=scheduled_for
            )
            db.add(notif)
            print(f"✅ Reminder scheduled: {title} for patient {patient.id}, appointment {appt.id}")

        # 1 day before
        if one_day_before.date() == now.date() and abs((one_day_before - now).total_seconds()) <= 1800:
            title = "Appointment Reminder (Tomorrow)"
            desc = f"You have an appointment tomorrow at {appt.appointment_time.strftime('%H:%M')}."
            await maybe_create(title, desc, "1_day_before", one_day_before)

        # 2 hours before
        if appt_dt.date() == now.date() and abs((two_hours_before - now).total_seconds()) <= 1800:
            title = "Appointment Reminder (2 Hours Left)"
            desc = f"You have an appointment at {appt.appointment_time.strftime('%H:%M')}. Please be prepared."
            await maybe_create(title, desc, "2_hours_before", two_hours_before)

    await db.commit()
    print("🔔 Appointment reminder job completed.\n")
