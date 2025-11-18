from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from app.database import get_db
from app.auth import get_current_user
from app.models import Encounter, Doctor, ChatMessage, User, Patient
from app.schemas import ChatCreate, ChatOut
from datetime import datetime

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.get("/patient/recent-visits")
async def get_recent_doctor_visits(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 1️⃣ Fetch patient record using USER ID
    patient_result = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = patient_result.scalar()

    if not patient:
        return []   # User logged in but no patient profile found

    # 2️⃣ Use REAL patient_id from Patient table
    patient_id = patient.id

    # 3️⃣ Now fetch encounters correctly
    result = await db.execute(
        select(Encounter, Doctor)
        .join(Doctor, Doctor.id == Encounter.doctor_id)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.encounter_date.desc())
        .limit(10)
    )

    rows = result.all()

    visits = []
    for enc, doc in rows:
        visits.append({
            "chat_id": enc.id,
            "doctor_id": doc.id,
            "doctor_name": f"{doc.first_name} {doc.last_name}",
            "specialty": doc.specialty,
            "message": enc.reason_for_visit or "Doctor visit",
            "timestamp": enc.encounter_date
        })

    return visits



# Send message (patient ↔ doctor)
@router.post("/send", response_model=ChatOut)
async def send_message(
    payload: ChatCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    new_msg = ChatMessage(
        sender_id=current_user.id,
        receiver_id=payload.receiver_id,
        doctor_id=payload.doctor_id,
        patient_id=payload.patient_id,
        message=payload.message,
        timestamp=datetime.utcnow()
    )

    db.add(new_msg)
    await db.commit()
    await db.refresh(new_msg)

    return new_msg


# ----------------------------------------------------
# Get chat history between patient and doctor
# ----------------------------------------------------
@router.get("/history/{doctor_id}", response_model=list[ChatOut])
async def get_chat_history(
    doctor_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_id = current_user.id

    result = await db.execute(
        select(ChatMessage)
        .filter(
            or_(
                and_(ChatMessage.sender_id == patient_id, ChatMessage.receiver_id == doctor_id),
                and_(ChatMessage.sender_id == doctor_id, ChatMessage.receiver_id == patient_id)
            )
        )
        .order_by(ChatMessage.timestamp.asc())
    )

    messages = result.scalars().all()
    return messages
