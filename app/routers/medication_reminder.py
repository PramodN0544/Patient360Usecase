from datetime import datetime, timedelta, time as dt_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Medication, Patient, Notification, PatientConsent, User
import pytz

IST = pytz.timezone("Asia/Kolkata")

async def send_medication_reminders(db: AsyncSession):
    print("Running medication reminder job...")
    now = datetime.now(IST)
    today = now.date()

    # Fetch all medications with patients and users
    result = await db.execute(
        select(Medication, Patient, User)
        .join(Patient, Patient.id == Medication.patient_id)
        .join(User, User.id == Patient.user_id, isouter=True)
    )
    rows = result.unique().all()
    print("Checking medication reminders...")
    print(f"Schedules found: {len(rows)}")

    for med, patient, user in rows:
        # Skip inactive medications
        if med.start_date and med.start_date > today:
            continue
        if med.end_date and med.end_date < today:
            continue

        # Check patient consent
        consent_res = await db.execute(
            select(PatientConsent).filter(PatientConsent.patient_id == patient.id)
        )
        consent = consent_res.scalar_one_or_none()
        if consent and consent.text_messaging is False:
            continue

        async def maybe_create(title: str, desc: str, reminder_type: str, scheduled_for: datetime):
            # Prevent duplicate notifications
            q = select(Notification).filter(
                Notification.type == "medication",
                Notification.data_id == str(med.id),
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
                type="medication",
                reminder_type=reminder_type,
                status="unread",
                data_id=str(med.id),
                scheduled_for=scheduled_for
            )
            db.add(notif)
            print(f"Reminder scheduled: {title} for patient {patient.id}, medication {med.medication_name}")

        # DAILY REMINDERS
        reminder_times = getattr(med, "reminder_times", None)
        normalized_times = []
        if reminder_times:
            for t in reminder_times:
                if isinstance(t, str):
                    try:
                        normalized_times.append(datetime.strptime(t, "%H:%M").time())
                    except Exception:
                        continue
                else:
                    normalized_times.append(t)
        else:
            normalized_times = [dt_time(9, 0)]  
        
        for rt in normalized_times:
            rem_dt = IST.localize(datetime.combine(today, rt))
            if abs((rem_dt - now).total_seconds()) <= 1800:  
                title = "Medication Reminder"
                desc = f"Please take your medication: {med.medication_name} ({med.dosage})."
                await maybe_create(title, desc, "daily", rem_dt)

        # REFILL REMINDERS
        if med.end_date:
            refill_day = med.end_date - timedelta(days=5)
            if refill_day == today:
                scheduled_for = IST.localize(datetime.combine(today, dt_time(9, 0)))
                title = "Medication Refill Reminder"
                desc = f"Your medication '{med.medication_name}' will finish soon. Please request a refill."
                await maybe_create(title, desc, "refill", scheduled_for)

    await db.commit()
    print("Medication reminder job completed.\n")
