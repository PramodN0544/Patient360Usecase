from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Notification, User
from app.auth import get_current_user
from app.database import get_db

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/")
async def get_my_notifications(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetch all notifications of the logged-in user"""

    result = await db.execute(
        select(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )

    notifications = result.scalars().all()

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
        for n in notifications
    ]
