from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, or_
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
from app.web_socket import chat_manager
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/api/chat", tags=["chat"])

IST = timezone(timedelta(hours=5, minutes=30))
# Get all chats for the current patient
@router.get("/patient-chats", response_model=List[schemas.ChatSummary])
async def get_patient_chats(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        if current_user.role != "patient":
            raise HTTPException(status_code=403, detail="Only patients can access this endpoint")
        
        # Get the patient record
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient:
            raise HTTPException(status_code=404, detail="Patient record not found")
    except Exception as e:
        print(f"Error in get_patient_chats (initial checks): {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching patient data: {str(e)}"
        )
    
    try:
        chats_result = await db.execute(
            select(models.Chat).where(models.Chat.patient_id == patient.id)
        )
        chats = chats_result.scalars().all()
        
        chat_summaries = []
        for chat in chats:
            try:
                doctor_result = await db.execute(
                    select(models.Doctor).where(models.Doctor.id == chat.doctor_id)
                )
                doctor = doctor_result.scalars().first()
                
                if not doctor:
                    print(f"Doctor not found for chat {chat.id}")
                    continue
                
                last_message_result = await db.execute(
                    select(models.ChatMessage)
                    .where(models.ChatMessage.chat_id == chat.id)
                    .order_by(models.ChatMessage.timestamp.desc())
                    .limit(1)
                )
                last_message = last_message_result.scalars().first()
                
                unread_count_result = await db.execute(
                    select(func.count())
                    .where(
                        and_(
                            models.ChatMessage.chat_id == chat.id,
                            models.ChatMessage.sender_type == "doctor",
                            models.ChatMessage.is_read == False
                        )
                    )
                )
                unread_count = unread_count_result.scalar()
                
                doctor_user_result = await db.execute(
                    select(models.User).where(models.User.id == doctor.user_id)
                )
                doctor_user = doctor_user_result.scalars().first()
                
                # 🔥 JUST ADDED specialty here
                doctor_info = schemas.ChatParticipantInfo(
                    id=doctor.id,
                    public_id=doctor.public_id or "",
                    name=f"{doctor.first_name} {doctor.last_name}",
                    role="doctor",
                    photo_url=doctor.license_url,
                    specialty=doctor.specialty  # 👈 ADDED LINE
                )
                
                patient_info = schemas.ChatParticipantInfo(
                    id=patient.id,
                    public_id=patient.public_id,
                    name=f"{patient.first_name} {patient.last_name}",
                    role="patient",
                    photo_url=patient.photo_url
                )
                
                chat_summary = schemas.ChatSummary(
                    id=chat.id,
                    patient=patient_info,
                    doctor=doctor_info,
                    last_message=last_message,
                    unread_count=unread_count,
                    created_at=chat.created_at,
                    updated_at=chat.updated_at
                )
                
                chat_summaries.append(chat_summary)
            except Exception as e:
                print(f"Error processing chat {chat.id}: {str(e)}")
                continue
        
        return chat_summaries
    except Exception as e:
        print(f"Error in get_patient_chats (processing chats): {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while processing chats: {str(e)}"
        )

# Get all chats for the current doctor
@router.get("/doctor-chats", response_model=List[schemas.ChatSummary])
async def get_doctor_chats(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can access this endpoint")
    
    # Get the doctor record
    doctor_result = await db.execute(
        select(models.Doctor).where(models.Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalars().first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor record not found")
    
    chats_result = await db.execute(
        select(models.Chat).where(models.Chat.doctor_id == doctor.id)
    )
    chats = chats_result.scalars().all()
    
    chat_summaries = []
    for chat in chats:
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.id == chat.patient_id)
        )
        patient = patient_result.scalars().first()
        
        last_message_result = await db.execute(
            select(models.ChatMessage)
            .where(models.ChatMessage.chat_id == chat.id)
            .order_by(models.ChatMessage.timestamp.desc())  
            .limit(1)
        )
        last_message = last_message_result.scalars().first()
        
        unread_count_result = await db.execute(
            select(func.count())
            .where(
                and_(
                    models.ChatMessage.chat_id == chat.id,
                    models.ChatMessage.sender_type == "patient",
                    models.ChatMessage.is_read == False
                )
            )
        )
        unread_count = unread_count_result.scalar()

        doctor_info = schemas.ChatParticipantInfo(
            id=doctor.id,
            public_id=doctor.public_id or "",
            name=f"{doctor.first_name} {doctor.last_name}",
            role="doctor",
            photo_url=doctor.license_url
        )
    
        patient_info = schemas.ChatParticipantInfo(
            id=patient.id,
            public_id=patient.public_id,
            name=f"{patient.first_name} {patient.last_name}",
            role="patient",
            photo_url=patient.photo_url,
            dob=patient.dob,  
            gender=patient.gender  
        )
        
        chat_summary = schemas.ChatSummary(
            id=chat.id,
            patient=patient_info,
            doctor=doctor_info,
            last_message=last_message,
            unread_count=unread_count,
            created_at=chat.created_at,
            updated_at=chat.updated_at
        )
        
        chat_summaries.append(chat_summary)
    
    return chat_summaries

# Get or create a chat by doctor's public_id
@router.get("/by-doctor/{doctor_public_id}", response_model=schemas.ChatOut)
async def get_chat_by_doctor(
    doctor_public_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(status_code=403, detail="Only patients can access this endpoint")
    
    # Get the patient record
    patient_result = await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )
    patient = patient_result.scalars().first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient record not found")
    
    # Get the doctor by public_id
    doctor_result = await db.execute(
        select(models.Doctor).where(models.Doctor.public_id == doctor_public_id)
    )
    doctor = doctor_result.scalars().first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    # Check if a chat already exists
    chat_result = await db.execute(
        select(models.Chat).where(
            and_(
                models.Chat.patient_id == patient.id,
                models.Chat.doctor_id == doctor.id
            )
        )
    )
    chat = chat_result.scalars().first()
    
    # If no chat exists, create one
    if not chat:
        chat = models.Chat(
            patient_id=patient.id,
            doctor_id=doctor.id
        )
        db.add(chat)
        await db.commit()
        await db.refresh(chat)
    
    # Get all messages for this chat
    messages_result = await db.execute(
        select(models.ChatMessage)
        .where(models.ChatMessage.chat_id == chat.id)
        .order_by(models.ChatMessage.timestamp)  # Changed from sent_at to timestamp
    )
    messages = messages_result.scalars().all()
    
    return schemas.ChatOut(
        id=chat.id,
        patient_id=chat.patient_id,
        doctor_id=chat.doctor_id,
        encounter_id=chat.encounter_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=messages
    )

# Get or create a chat by patient's public_id
@router.get("/by-patient/{patient_public_id}", response_model=schemas.ChatOut)
async def get_chat_by_patient(
    patient_public_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can access this endpoint")
    
    # Get the doctor record
    doctor_result = await db.execute(
        select(models.Doctor).where(models.Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalars().first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor record not found")
    
    # Get the patient by public_id
    patient_result = await db.execute(
        select(models.Patient).where(models.Patient.public_id == patient_public_id)
    )
    patient = patient_result.scalars().first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    # Check if a chat already exists
    chat_result = await db.execute(
        select(models.Chat).where(
            and_(
                models.Chat.patient_id == patient.id,
                models.Chat.doctor_id == doctor.id
            )
        )
    )
    chat = chat_result.scalars().first()
    
    # If no chat exists, create one
    if not chat:
        chat = models.Chat(
            patient_id=patient.id,
            doctor_id=doctor.id
        )
        db.add(chat)
        await db.commit()
        await db.refresh(chat)
    
    # Get all messages for this chat
    messages_result = await db.execute(
        select(models.ChatMessage)
        .where(models.ChatMessage.chat_id == chat.id)
        .order_by(models.ChatMessage.timestamp)  # Changed from sent_at to timestamp
    )
    messages = messages_result.scalars().all()
    
    return schemas.ChatOut(
        id=chat.id,
        patient_id=chat.patient_id,
        doctor_id=chat.doctor_id,
        encounter_id=chat.encounter_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=messages
    )

# Get or create a chat by encounter ID
@router.get("/by-encounter/{encounter_id}", response_model=schemas.ChatOut)
async def get_chat_by_encounter(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Get the encounter
    encounter_result = await db.execute(
        select(models.Encounter).where(models.Encounter.id == encounter_id)
    )
    encounter = encounter_result.scalars().first()
    
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")
    
    # Check if the user is a participant in this encounter
    if current_user.role == "patient":
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != encounter.patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this encounter")
        
        # Check if a chat already exists for this encounter
        chat_result = await db.execute(
            select(models.Chat).where(models.Chat.encounter_id == encounter_id)
        )
        chat = chat_result.scalars().first()
        
        # If no chat exists, create one
        if not chat:
            chat = models.Chat(
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                encounter_id=encounter.id
            )
            db.add(chat)
            await db.commit()
            await db.refresh(chat)
    
    elif current_user.role == "doctor":
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or doctor.id != encounter.doctor_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this encounter")
        
        # Check if a chat already exists for this encounter
        chat_result = await db.execute(
            select(models.Chat).where(models.Chat.encounter_id == encounter_id)
        )
        chat = chat_result.scalars().first()
        
        # If no chat exists, create one
        if not chat:
            chat = models.Chat(
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                encounter_id=encounter.id
            )
            db.add(chat)
            await db.commit()
            await db.refresh(chat)
    
    else:
        raise HTTPException(status_code=403, detail="Only patients and doctors can access chats")
    
    # Get all messages for this chat
    messages_result = await db.execute(
        select(models.ChatMessage)
        .where(models.ChatMessage.chat_id == chat.id)
        .order_by(models.ChatMessage.timestamp)  # Changed from sent_at to timestamp
    )
    messages = messages_result.scalars().all()
    
    return schemas.ChatOut(
        id=chat.id,
        patient_id=chat.patient_id,
        doctor_id=chat.doctor_id,
        encounter_id=chat.encounter_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=messages
    )
# Send a message (DEPRECATED - Use WebSockets instead)
# This endpoint is kept for backward compatibility but new code should use WebSockets
# See web_socket.py for the WebSocket implementation of send_message
@router.post("/send-message", response_model=schemas.ChatMessageOut)
@router.post("/send-message", response_model=schemas.ChatMessageOut)
async def send_message(
    message: schemas.ChatMessageCreate,
    chat_id: int = Query(..., description="ID of the chat"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Get the chat
    chat_result = await db.execute(
        select(models.Chat).where(models.Chat.id == chat_id)
    )
    chat = chat_result.scalars().first()
    
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Determine sender type and check authorization
    sender_type = None
    if current_user.role == "patient":
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != chat.patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to send messages in this chat")
        
        sender_type = "patient"
    
    elif current_user.role == "doctor":
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or doctor.id != chat.doctor_id:
            raise HTTPException(status_code=403, detail="You are not authorized to send messages in this chat")
        
        sender_type = "doctor"
    
    else:
        raise HTTPException(status_code=403, detail="Only patients and doctors can send messages")
    
    try:
        # Validate that chat has valid doctor_id and patient_id
        if not chat.doctor_id or not chat.patient_id:
            raise HTTPException(
                status_code=400,
                detail="Chat has invalid doctor_id or patient_id"
            )
            
        # Create the message
        new_message = models.ChatMessage(
            chat_id=chat.id,
            sender_id=current_user.id,
            message=message.message,
            timestamp=datetime.now(IST),
            doctor_id=chat.doctor_id,
            patient_id=chat.patient_id
        )
        
        # Set sender_type and is_read using the new setters
        new_message.sender_type = sender_type
        new_message.is_read = False
        db.add(new_message)
        
        # Update the chat's updated_at timestamp
        chat.updated_at = datetime.utcnow()
        db.add(chat)
        
        await db.commit()
        await db.refresh(new_message)
        
        # Notify connected WebSocket clients
        await chat_manager.send_message(chat.id, new_message)
        
        return new_message
    except Exception as e:
        await db.rollback()
        print(f"Error creating message in REST API: {e}")
        
        # Provide more detailed error message
        error_message = str(e)
        if "violates not-null constraint" in error_message.lower():
            if "doctor_id" in error_message.lower():
                raise HTTPException(
                    status_code=400,
                    detail="Doctor ID is required but was not provided"
                )
            elif "patient_id" in error_message.lower():
                raise HTTPException(
                    status_code=400,
                    detail="Patient ID is required but was not provided"
                )
        
        raise HTTPException(
            status_code=500,
            detail=f"Error creating message: {error_message}"
        )

# Mark messages as read
@router.post("/{chat_id}/mark-read", response_model=Dict[str, Any])
async def mark_messages_as_read(
    chat_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Get the chat
    chat_result = await db.execute(
        select(models.Chat).where(models.Chat.id == chat_id)
    )
    chat = chat_result.scalars().first()
    
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Determine reader type and check authorization
    reader_type = None
    if current_user.role == "patient":
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != chat.patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this chat")
        
        reader_type = "patient"
        sender_type = "doctor"
    
    elif current_user.role == "doctor":
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or doctor.id != chat.doctor_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this chat")
        
        reader_type = "doctor"
        sender_type = "patient"
    
    else:
        raise HTTPException(status_code=403, detail="Only patients and doctors can access chats")
    
    # Mark all messages from the other party as read
    result = await db.execute(
        select(models.ChatMessage)
        .where(
            and_(
                models.ChatMessage.chat_id == chat.id,
                models.ChatMessage.sender_type == sender_type,
                models.ChatMessage.is_read == False
            )
        )
    )
    unread_messages = result.scalars().all()
    
    for message in unread_messages:
        message.is_read = True
        db.add(message)
    
    await db.commit()
    
    # Notify connected WebSocket clients
    for message in unread_messages:
        await chat_manager.mark_message_read(chat.id, message.id)
    
    return {"success": True, "marked_count": len(unread_messages)}

# Send message to a recipient (DEPRECATED - Use WebSockets instead)
# This endpoint is kept for backward compatibility but new code should use WebSockets
# See web_socket.py for the WebSocket implementation of send_message_to_recipient
@router.post("/send-to-recipient")
async def send_message_to_recipient(
    request: schemas.SendToRecipientRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        print(f"Received send-to-recipient request: recipient_id={request.recipient_id}, message={request.message}")
        print(f"Current user: id={current_user.id}, role={current_user.role}")
        
        recipient_id = request.recipient_id
        message_text = request.message
        
        # Determine sender type and get sender record
        sender_type = None
        sender_id = None
        recipient_type = None
        
        if current_user.role == "patient":
            sender_type = "patient"
            recipient_type = "doctor"
            
            # Get patient record
            patient_result = await db.execute(
                select(models.Patient).where(models.Patient.user_id == current_user.id)
            )
            patient = patient_result.scalars().first()
            
            if not patient:
                raise HTTPException(status_code=404, detail="Patient record not found")
            
            sender_id = patient.id
            
            # Get doctor record
            doctor_result = await db.execute(
                select(models.Doctor).where(models.Doctor.id == recipient_id)
            )
            doctor = doctor_result.scalars().first()
            
            if not doctor:
                raise HTTPException(status_code=404, detail="Doctor not found")
            
            recipient_id = doctor.id
            
            # Check if a chat already exists
            chat_result = await db.execute(
                select(models.Chat).where(
                    and_(
                        models.Chat.patient_id == patient.id,
                        models.Chat.doctor_id == doctor.id
                    )
                )
            )
            chat = chat_result.scalars().first()
            
            # If no chat exists, create one
            if not chat:
                chat = models.Chat(
                    patient_id=patient.id,
                    doctor_id=doctor.id
                )
                db.add(chat)
                await db.commit()
                await db.refresh(chat)
        
        elif current_user.role == "doctor":
            sender_type = "doctor"
            recipient_type = "patient"
            
            # Get doctor record
            doctor_result = await db.execute(
                select(models.Doctor).where(models.Doctor.user_id == current_user.id)
            )
            doctor = doctor_result.scalars().first()
            
            if not doctor:
                raise HTTPException(status_code=404, detail="Doctor record not found")
            
            sender_id = doctor.id
            
            # Get patient record
            patient_result = await db.execute(
                select(models.Patient).where(models.Patient.id == recipient_id)
            )
            patient = patient_result.scalars().first()
            
            if not patient:
                raise HTTPException(status_code=404, detail="Patient not found")
            
            recipient_id = patient.id
            
            # Check if a chat already exists
            chat_result = await db.execute(
                select(models.Chat).where(
                    and_(
                        models.Chat.patient_id == patient.id,
                        models.Chat.doctor_id == doctor.id
                    )
                )
            )
            chat = chat_result.scalars().first()
            
            # If no chat exists, create one
            if not chat:
                chat = models.Chat(
                    patient_id=patient.id,
                    doctor_id=doctor.id
                )
                db.add(chat)
                await db.commit()
                await db.refresh(chat)
        
        else:
            raise HTTPException(status_code=403, detail="Only patients and doctors can send messages")
        
        # Create the message
        new_message = models.ChatMessage(
            chat_id=chat.id,
            sender_id=current_user.id,
            message=message_text,
            timestamp=datetime.utcnow()
        )
        
        # Set sender_type and is_read using the new setters
        new_message.sender_type = sender_type
        new_message.is_read = False
        db.add(new_message)
        
        # Update the chat's updated_at timestamp
        chat.updated_at = datetime.utcnow()
        db.add(chat)
        await db.commit()
        await db.refresh(new_message)
        
        # Notify connected WebSocket clients
        try:
            await chat_manager.send_message(chat.id, new_message)
            print(f"Successfully sent WebSocket notification for chat {chat.id}")
        except Exception as ws_error:
            print(f"Warning: Failed to send WebSocket notification: {str(ws_error)}")
            # Continue even if WebSocket notification fails
        
        
        # Return both the message and chat info for better WebSocket integration
        # Use a simpler response format to avoid potential serialization issues
        return {
            "message": {
                "id": new_message.id,
                "chat_id": new_message.chat_id,
                "sender_id": new_message.sender_id,
                "sender_type": new_message.sender_type,
                "message": new_message.message,
                "is_read": False,
                "sent_at": new_message.sent_at.isoformat()
            },
            "chat": {
                "id": chat.id,
                "patient_id": int(chat.patient_id),
                "doctor_id": int(chat.doctor_id),
                "encounter_id": None if chat.encounter_id is None else int(chat.encounter_id),
                "created_at": chat.created_at.isoformat(),
                "updated_at": chat.updated_at.isoformat()
            },
            "success": True
        }
    except Exception as e:
        print(f"Error in send_message_to_recipient: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/doctors-from-encounters", response_model=List[schemas.DoctorBasicInfo])
async def get_doctors_from_encounters(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    patient_result = await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )
    patient = patient_result.scalars().first()

    if not patient:
        raise HTTPException(403, "Only patients can access this endpoint")

    result = await db.execute(
        select(models.Encounter)
        .options(selectinload(models.Encounter.doctor))
        .where(models.Encounter.patient_id == patient.id)
    )

    # 🔥 THIS FIXES THE ERROR
    encounters = result.unique().scalars().all()

    doctors = []
    seen = set()

    for e in encounters:
        if e.doctor and e.doctor.id not in seen:
            seen.add(e.doctor.id)

            doctor = e.doctor
            doctors.append(
                schemas.DoctorBasicInfo(
                    id=doctor.id,
                    public_id=doctor.public_id or "",
                    name=f"{doctor.first_name} {doctor.last_name}",
                    email=doctor.email,
                    specialty=doctor.specialty,
                    role="doctor",
                    encounter_id=e.id,
                    photo_url=doctor.license_url
                )
            )

    return doctors

    
@router.get("/patients-from-encounters", response_model=List[schemas.PatientBasicInfo])
async def get_patients_from_encounters(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Doctor check
    if current_user.role != "doctor":
        raise HTTPException(403, "Only doctors can access this endpoint")

    # Get doctor using SAME logic as working encounters API
    doctor_result = await db.execute(
        select(models.Doctor).where(models.Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.unique().scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor record not found")

    # Load encounters + patient relationship
    result = await db.execute(
        select(models.Encounter)
        .options(selectinload(models.Encounter.patient))
        .where(models.Encounter.doctor_id == doctor.id)
    )

    encounters = result.unique().scalars().all()

    seen = set()
    patients = []

    # Extract unique patients
    for e in encounters:
        if e.patient and e.patient.id not in seen:
            seen.add(e.patient.id)

            patient = e.patient

            patients.append(
                schemas.PatientBasicInfo(
                    id=patient.id,
                    public_id=patient.public_id or "",
                    name=f"{patient.first_name} {patient.last_name}",
                    email=patient.email,
                    role="patient",
                    encounter_id=e.id,
                    photo_url=patient.photo_url
                )
            )

    return patients

# Get chat by ID
@router.get("/{chat_id}", response_model=schemas.ChatOut)
async def get_chat_by_id(
    chat_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        # Get the chat
        chat_result = await db.execute(
            select(models.Chat).where(models.Chat.id == chat_id)
        )
        chat = chat_result.scalars().first()
        
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # Check if the user is a participant in this chat
        if current_user.role == "patient":
            patient_result = await db.execute(
                select(models.Patient).where(models.Patient.user_id == current_user.id)
            )
            patient = patient_result.scalars().first()
            
            if not patient or patient.id != chat.patient_id:
                raise HTTPException(status_code=403, detail="You are not authorized to access this chat")
        
        elif current_user.role == "doctor":
            doctor_result = await db.execute(
                select(models.Doctor).where(models.Doctor.user_id == current_user.id)
            )
            doctor = doctor_result.scalars().first()
            
            if not doctor or doctor.id != chat.doctor_id:
                raise HTTPException(status_code=403, detail="You are not authorized to access this chat")
        
        else:
            raise HTTPException(status_code=403, detail="Only patients and doctors can access chats")
        
        try:
            # Get all messages for this chat
            messages_result = await db.execute(
                select(models.ChatMessage)
                .where(models.ChatMessage.chat_id == chat.id)
                .order_by(models.ChatMessage.timestamp)  # Changed back to timestamp (actual column name)
            )
            messages = messages_result.scalars().all()
            
            # Return the chat with messages
            return schemas.ChatOut(
                id=chat.id,
                patient_id=chat.patient_id,
                doctor_id=chat.doctor_id,
                encounter_id=chat.encounter_id,
                created_at=chat.created_at,
                updated_at=chat.updated_at,
                messages=messages
            )
        except Exception as e:
            print(f"Error fetching messages for chat {chat_id}: {str(e)}")
            # Return the chat without messages if there's an error
            return schemas.ChatOut(
                id=chat.id,
                patient_id=chat.patient_id,
                doctor_id=chat.doctor_id,
                encounter_id=chat.encounter_id,
                created_at=chat.created_at,
                updated_at=chat.updated_at,
                messages=[]
            )
    except Exception as e:
        print(f"Error in get_chat_by_id: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching the chat: {str(e)}"
        )