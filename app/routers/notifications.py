from fastapi import APIRouter, Depends,HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from datetime import datetime, timedelta
import pytz
from app.models import Notification, User, Medication, Appointment, Patient
from app.auth import get_current_user
from app.database import get_db

IST = pytz.timezone("Asia/Kolkata")

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/")
async def get_my_notifications(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetch all notifications of the logged-in user, including recent medication and appointment reminders"""

    # Existing notifications
    result = await db.execute(
        select(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )
    notifications = result.unique().scalars().all()

    # Include recent medication reminders (last 1 day)
    now = datetime.now(IST)
    today = now.date()
    one_day_ago = now - timedelta(days=1)

    med_result = await db.execute(
        select(Medication, Patient)
        .join(Patient, Patient.id == Medication.patient_id)
        .filter(Patient.user_id == current_user.id)
        .filter(
            or_(
                Medication.start_date >= one_day_ago.date(),
                Medication.end_date >= one_day_ago.date()
            )
        )
    )
    meds = med_result.unique().all()

    for med, patient in meds:
        notifications.append(Notification(
            id=f"med-{med.id}",
            title="Medication Reminder",
            desc=f"Please take your medication: {med.medication_name} ({med.dosage}).",
            type="medication",
            status="unread",
            data_id=str(med.id),
            created_at=datetime.utcnow(),
            user_id=current_user.id
        ))

    # Include upcoming appointment reminders (last 1 day or today)
    app_result = await db.execute(
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id)
        .filter(Patient.user_id == current_user.id)
        .filter(Appointment.appointment_date >= one_day_ago.date())
    )
    apps = app_result.unique().all()

    for appt, patient in apps:
        notifications.append(Notification(
            id=f"app-{appt.id}",
            title="Appointment Reminder",
            desc=f"You have an upcoming appointment on {appt.appointment_date} at {appt.appointment_time}.",
            type="appointment",
            status="unread",
            data_id=str(appt.id),
            created_at=datetime.utcnow(),
            user_id=current_user.id
        ))

    # Return all notifications sorted by created_at descending
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "desc": n.desc,
            "type": n.type,            # appointment | medication | alert
            "status": n.status,        # read | unread
            "created_at": n.created_at.isoformat() + "Z",
            "data_id": n.data_id       # appointment_id | medication_id
        }
        for n in sorted(notifications, key=lambda x: x.created_at, reverse=True)
    ]


@router.get("/doctor")
async def get_doctor_notifications(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch notifications for logged-in doctor only
    """
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors allowed")

    # fetch notifications assigned to this doctor (via user_id)
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )

    notifications = result.scalars().all()

    return [
        {
            "id": n.id,
            "title": n.title,
            "desc": n.desc,
            "type": n.type,              
            "status": n.status,          
            "data_id": n.data_id,         
            "patient_id": n.patient_id,
            "scheduled_for": n.scheduled_for,
            "created_at": n.created_at
        }
        for n in notifications
    ]