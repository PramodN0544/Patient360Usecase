from fastapi import WebSocket, WebSocketDisconnect, Depends, HTTPException
from typing import Dict, List, Set, Optional, Any
import json
from datetime import datetime
import asyncio
from jose import jwt, JWTError
import socketio
from app.utils import JWT_SECRET, JWT_ALGORITHM
from app.database import AsyncSessionLocal
from sqlalchemy.future import select
from app import models
from fastapi import FastAPI


# Create a Socket.IO server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*', logger=True,  # Enable logging
    engineio_logger=True,  # Enable Engine.IO logging
    ping_timeout=60,  # Increase ping timeout
    ping_interval=25,  # Adjust ping interval
    max_http_buffer_size=1000000 ) # Increase buffer size for messages

socket_app = socketio.ASGIApp(sio, socketio_path='',  # Empty string means use the mount point as the path
    other_asgi_app=None) # No other ASGI app to serve on the same path

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Dict[int, WebSocket]] = {}
        self.user_chat_connections: Dict[int, Set[int]] = {}
        
    async def connect(self, websocket: WebSocket, chat_id: int, user_id: int):
    
        
        # Initialize dictionaries if they don't exist
        if chat_id not in self.active_connections:
            self.active_connections[chat_id] = {}
        
        if user_id not in self.user_chat_connections:
            self.user_chat_connections[user_id] = set()
        
        # Store the connection
        self.active_connections[chat_id][user_id] = websocket
        self.user_chat_connections[user_id].add(chat_id)
        
        # Update user status in database
        async with AsyncSessionLocal() as db:
            # Get existing status or create new one
            result = await db.execute(
                select(models.ChatUserStatus).where(
                    (models.ChatUserStatus.chat_id == chat_id) & 
                    (models.ChatUserStatus.user_id == user_id)
                )
            )
            status = result.scalars().first()
            
            if not status:
                status = models.ChatUserStatus(
                    chat_id=chat_id,
                    user_id=user_id,
                    online=True,
                    last_seen=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(status)
            else:
                status.online = True
                status.last_seen = datetime.utcnow()
                status.updated_at = datetime.utcnow()
                db.add(status)
            
            await db.commit()
        
        # Notify other users in this chat
        await self.broadcast_user_status(chat_id, user_id, True)
    
    async def disconnect(self, chat_id: int, user_id: int):
        # Remove the connection
        if chat_id in self.active_connections and user_id in self.active_connections[chat_id]:
            del self.active_connections[chat_id][user_id]
            
            # Clean up empty chat dictionaries
            if not self.active_connections[chat_id]:
                del self.active_connections[chat_id]
        
        # Remove from user_chat_connections
        if user_id in self.user_chat_connections:
            self.user_chat_connections[user_id].discard(chat_id)
            
            # Clean up empty user sets
            if not self.user_chat_connections[user_id]:
                del self.user_chat_connections[user_id]
        
        # Update user status in database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(models.ChatUserStatus).where(
                    (models.ChatUserStatus.chat_id == chat_id) & 
                    (models.ChatUserStatus.user_id == user_id)
                )
            )
            status = result.scalars().first()
            
            if status:
                status.online = False
                status.last_seen = datetime.utcnow()
                status.updated_at = datetime.utcnow()
                db.add(status)
                await db.commit()  # FIXED: Added parentheses
    
    async def send_message(self, chat_id: int, message: models.ChatMessage):  # FIXED: Indentation
        if chat_id not in self.active_connections:
            return
        
        # Format message for WebSocket
        message_data = {
            "type": "new_message",
            "data": {
                "id": message.id,
                "chat_id": message.chat_id,
                "sender_id": message.sender_id,
                "sender_type": message.sender_type,
                "message": message.message,
                "is_read": message.is_read,
                "sent_at": message.sent_at.isoformat()
            }
        }
        
        # Send to all connected users in this chat
        for user_id, connection in self.active_connections[chat_id].items():
            await connection.send_text(json.dumps(message_data))

    async def mark_message_read(self, chat_id: int, message_id: int):  # FIXED: Indentation
        if chat_id not in self.active_connections:
            return
        
        # Format read receipt for WebSocket
        read_data = {
            "type": "message_read",
            "data": {
                "chat_id": chat_id,
                "message_id": message_id
            }
        }
        
        # Send to all connected users in this chat
        for user_id, connection in self.active_connections[chat_id].items():
            await connection.send_text(json.dumps(read_data))

    async def broadcast_typing_indicator(self, chat_id: int, user_id: int, is_typing: bool):  # FIXED: Indentation
        if chat_id not in self.active_connections:
            return
        
        # Format typing indicator for WebSocket
        typing_data = {
            "type": "typing_indicator",
            "data": {
                "chat_id": chat_id,
                "user_id": user_id,
                "is_typing": is_typing
            }
        }
        
        # Send to all connected users in this chat except the typing user
        for conn_user_id, connection in self.active_connections[chat_id].items():
            if conn_user_id != user_id:
                await connection.send_text(json.dumps(typing_data))

    async def broadcast_user_status(self, chat_id: int, user_id: int, is_online: bool):  # FIXED: Indentation
        if chat_id not in self.active_connections:
            return
        
        # Format user status for WebSocket
        status_data = {
            "type": "user_status",
            "data": {
                "chat_id": chat_id,
                "user_id": user_id,
                "online": is_online,
                "last_seen": datetime.utcnow().isoformat()
            }
        }
        
        # Send to all connected users in this chat except the user themselves
        for conn_user_id, connection in self.active_connections[chat_id].items():
            if conn_user_id != user_id:
                await connection.send_text(json.dumps(status_data))

    async def update_typing_status(self, chat_id: int, user_id: int, is_typing: bool):  # FIXED: Indentation
        # Update typing status in database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(models.ChatUserStatus).where(
                    (models.ChatUserStatus.chat_id == chat_id) & 
                    (models.ChatUserStatus.user_id == user_id)
                )
            )
            status = result.scalars().first()
            
            if status:
                status.is_typing = is_typing
                status.updated_at = datetime.utcnow()
                db.add(status)
                await db.commit()
        
        # Broadcast to other users
        await self.broadcast_typing_indicator(chat_id, user_id, is_typing)
        
        
# Create a global connection manager
chat_manager = ConnectionManager()

async def get_user_from_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            return None
        
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(models.User).where(models.User.id == user_id))
            user = result.scalars().first()
            return user
    except JWTError:
        return None

async def check_chat_access(chat_id: int, user_id: int):
    async with AsyncSessionLocal() as db:
        # Get the chat
        result = await db.execute(select(models.Chat).where(models.Chat.id == chat_id))
        chat = result.scalars().first()
        
        if not chat:
            return False
        
        # Get the user
        user_result = await db.execute(select(models.User).where(models.User.id == user_id))
        user = user_result.scalars().first()
        
        if not user:
            return False
        
        # Check if user is a participant in this chat
        if user.role == "patient":
            patient_result = await db.execute(
                select(models.Patient).where(models.Patient.user_id == user_id)
            )
            patient = patient_result.scalars().first()
            
            if not patient or patient.id != chat.patient_id:
                return False
        
        elif user.role == "doctor":
            doctor_result = await db.execute(
                select(models.Doctor).where(models.Doctor.user_id == user_id)
            )
            doctor = doctor_result.scalars().first()
            
            if not doctor or doctor.id != chat.doctor_id:
                return False
        
        else:
            return False
        
        return True

async def broadcast_notification(self, user_id: int, notification: dict):
    """Send a notification to a specific user across all their connections."""
    if user_id in self.user_chat_connections:
        for chat_id in self.user_chat_connections[user_id]:
            if chat_id in self.active_connections and user_id in self.active_connections[chat_id]:
                websocket = self.active_connections[chat_id][user_id]
                notification_data = {
                    "type": "notification",
                    "data": notification
                }
                try:
                    await websocket.send_text(json.dumps(notification_data))
                except Exception as e:
                    print(f"Error sending notification to user {user_id}: {e}")
                    
async def process_websocket_message(data: dict, chat_id: int, user_id: int):
    message_type = data.get("type")
    
    if message_type == "typing":
        is_typing = data.get("is_typing", False)
        await chat_manager.update_typing_status(chat_id, user_id, is_typing)
    
    elif message_type == "read_messages":
        async with AsyncSessionLocal() as db:
            # Get the user
            user_result = await db.execute(select(models.User).where(models.User.id == user_id))
            user = user_result.scalars().first()
            
            if not user:
                return
            
            # Determine sender type based on reader's role
            if user.role == "patient":
                sender_type = "doctor"
            elif user.role == "doctor":
                sender_type = "patient"
            else:
                return
            
            # Mark messages as read
            result = await db.execute(
                select(models.ChatMessage).where(
                    (models.ChatMessage.chat_id == chat_id) &
                    (models.ChatMessage.sender_type == sender_type) &
                    (models.ChatMessage.is_read == False)
                )
            )
            unread_messages = result.scalars().all()
            
            for message in unread_messages:
                message.is_read = True
                db.add(message)
            
            await db.commit()
            
            # Notify connected clients
            for message in unread_messages:
                await chat_manager.mark_message_read(chat_id, message.id)

# Socket.IO event handlers
@sio.event
async def connect(sid, environ):
    print(f"Socket.IO connection attempt with SID: {sid}")
    try:
        # Extract token from query parameters
        query = environ.get('QUERY_STRING', '')
        token = None
        params = {}
        for param in query.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                params[key] = value
        
        token = params.get('token')
        
        if not token:
            print(f"No token provided for SID {sid}")
            return False
        
        # Verify token
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_id = payload.get("user_id")
            if not user_id:
                print(f"No user_id in token payload for SID {sid}")
                return False
            print(f"Token decoded successfully for user_id {user_id}")
        except Exception as e:
            print(f"Token validation error for SID {sid}: {e}")
            return False
        
        if not user_id:
            print(f"No user_id in token payload for SID {sid}")
            return False
        
        # Store user info in session
        await sio.save_session(sid, {'user_id': user_id, 'role': payload.get('role')})
        print(f"User {user_id} connected successfully with SID {sid}")
        return True
    except Exception as e:
        print(f"Socket.IO connection error for SID {sid}: {e}")
        return False

@sio.event
async def disconnect(sid):
    print(f"Socket.IO client disconnected: {sid}")
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        if user_id:
            print(f"User {user_id} disconnected")
    except Exception as e:
        print(f"Error handling disconnect: {e}")

@sio.event
async def join_chat(sid, data):
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        chat_id = data.get('chat_id')
        
        if not user_id or not chat_id:
            return {'success': False, 'error': 'Missing user_id or chat_id'}
        
        # Check if user has access to this chat
        has_access = await check_chat_access(chat_id, user_id)
        if not has_access:
            return {'success': False, 'error': 'Access denied'}
        
        # Join the room
        sio.enter_room(sid, f"chat_{chat_id}")
        print(f"User {user_id} joined chat {chat_id}")
        
        # Update user status in database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(models.ChatUserStatus).where(
                    (models.ChatUserStatus.chat_id == chat_id) & 
                    (models.ChatUserStatus.user_id == user_id)
                )
            )
            status = result.scalars().first()
            
            if not status:
                status = models.ChatUserStatus(
                    chat_id=chat_id,
                    user_id=user_id,
                    online=True,
                    last_seen=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(status)
            else:
                status.online = True
                status.last_seen = datetime.utcnow()
                status.updated_at = datetime.utcnow()
                db.add(status)
            
            await db.commit()
        
        # Broadcast user status to room
        await sio.emit('user_status', {
            'user_id': user_id,
            'chat_id': chat_id,
            'online': True,
            'last_seen': datetime.utcnow().isoformat()
        }, room=f"chat_{chat_id}", skip_sid=sid)
        
        return {'success': True}
    except Exception as e:
        print(f"Error joining chat: {e}")
        return {'success': False, 'error': str(e)}

@sio.event
async def leave_chat(sid, data):
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        chat_id = data.get('chat_id')
        
        if not user_id or not chat_id:
            return {'success': False, 'error': 'Missing user_id or chat_id'}
        
        # Leave the room
        sio.leave_room(sid, f"chat_{chat_id}")
        print(f"User {user_id} left chat {chat_id}")
        
        # Update user status in database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(models.ChatUserStatus).where(
                    (models.ChatUserStatus.chat_id == chat_id) & 
                    (models.ChatUserStatus.user_id == user_id)
                )
            )
            status = result.scalars().first()
            
            if status:
                status.online = False
                status.last_seen = datetime.utcnow()
                status.updated_at = datetime.utcnow()
                db.add(status)
                await db.commit()
        
        # Broadcast user status to room
        await sio.emit('user_status', {
            'user_id': user_id,
            'chat_id': chat_id,
            'online': False,
            'last_seen': datetime.utcnow().isoformat()
        }, room=f"chat_{chat_id}")
        
        return {'success': True}
    except Exception as e:
        print(f"Error leaving chat: {e}")
        return {'success': False, 'error': str(e)}

@sio.event
async def send_message(sid, data):
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        chat_id = data.get('chat_id')
        message_text = data.get('message')
        
        if not user_id or not chat_id or not message_text:
            return {'success': False, 'error': 'Missing required fields'}
        
        # Check if user has access to this chat
        has_access = await check_chat_access(chat_id, user_id)
        if not has_access:
            return {'success': False, 'error': 'Access denied'}
        
        # Get user role
        async with AsyncSessionLocal() as db:
            user_result = await db.execute(select(models.User).where(models.User.id == user_id))
            user = user_result.scalars().first()
            
            if not user:
                return {'success': False, 'error': 'User not found'}
            
            # Determine sender type
            sender_type = user.role
            
            # Get the chat to set doctor_id and patient_id
            chat_result = await db.execute(select(models.Chat).where(models.Chat.id == chat_id))
            chat = chat_result.scalars().first()
            
            if not chat:
                return {'success': False, 'error': 'Chat not found'}
                
            try:
                # Validate that chat has valid doctor_id and patient_id
                if not chat.doctor_id or not chat.patient_id:
                    return {'success': False, 'error': 'Chat has invalid doctor_id or patient_id'}
                
                # Create message in database with proper doctor_id and patient_id
                new_message = models.ChatMessage(
                    chat_id=chat_id,
                    sender_id=user_id,
                    message=message_text,
                    timestamp=datetime.utcnow(),
                    doctor_id=chat.doctor_id,
                    patient_id=chat.patient_id
                )
                
                # Set sender_type and is_read using the new setters
                new_message.sender_type = sender_type
                new_message.is_read = False
                
                # Chat is already retrieved above
                
                db.add(new_message)
                await db.commit()
                await db.refresh(new_message)
                
                # Broadcast to room
                await sio.emit('new_message', {
                    'id': new_message.id,
                    'chat_id': new_message.chat_id,
                    'sender_id': new_message.sender_id,
                    'sender_type': new_message.sender_type,
                    'message': new_message.message,
                    'is_read': new_message.is_read,
                    'sent_at': new_message.sent_at.isoformat()
                }, room=f"chat_{chat_id}")
                
                return {'success': True, 'message_id': new_message.id}
            except Exception as e:
                await db.rollback()
                print(f"Error creating message in send_message: {e}")
                
                # Provide more detailed error message
                error_message = str(e)
                if "violates not-null constraint" in error_message.lower():
                    if "doctor_id" in error_message.lower():
                        return {'success': False, 'error': 'Doctor ID is required but was not provided'}
                    elif "patient_id" in error_message.lower():
                        return {'success': False, 'error': 'Patient ID is required but was not provided'}
                
                return {'success': False, 'error': f"Error creating message: {error_message}"}
    except Exception as e:
        print(f"Error sending message: {e}")
        return {'success': False, 'error': str(e)}

@sio.event
async def typing_indicator(sid, data):
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        chat_id = data.get('chat_id')
        is_typing = data.get('is_typing', False)
        
        if not user_id or not chat_id:
            return {'success': False, 'error': 'Missing user_id or chat_id'}
        
        # Update typing status in database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(models.ChatUserStatus).where(
                    (models.ChatUserStatus.chat_id == chat_id) & 
                    (models.ChatUserStatus.user_id == user_id)
                )
            )
            status = result.scalars().first()
            
            if status:
                status.is_typing = is_typing
                status.updated_at = datetime.utcnow()
                db.add(status)
                await db.commit()
        
        # Broadcast to room except sender
        await sio.emit('typing_indicator', {
            'user_id': user_id,
            'chat_id': chat_id,
            'is_typing': is_typing
        }, room=f"chat_{chat_id}", skip_sid=sid)
        
        return {'success': True}
    except Exception as e:
        print(f"Error with typing indicator: {e}")
        return {'success': False, 'error': str(e)}

@sio.event
async def mark_messages_read(sid, data):
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        chat_id = data.get('chat_id')
        
        if not user_id or not chat_id:
            return {'success': False, 'error': 'Missing user_id or chat_id'}
        
        # Get user role
        async with AsyncSessionLocal() as db:
            user_result = await db.execute(select(models.User).where(models.User.id == user_id))
            user = user_result.scalars().first()
            
            if not user:
                return {'success': False, 'error': 'User not found'}
            
            # Determine sender type based on reader's role
            if user.role == "patient":
                sender_type = "doctor"
            elif user.role == "doctor":
                sender_type = "patient"
            else:
                return {'success': False, 'error': 'Invalid user role'}
            
            # Mark messages as read
            result = await db.execute(
                select(models.ChatMessage).where(
                    (models.ChatMessage.chat_id == chat_id) &
                    (models.ChatMessage.sender_type == sender_type) &
                    (models.ChatMessage.is_read == False)
                )
            )
            unread_messages = result.scalars().all()
            
            message_ids = []
            for message in unread_messages:
                message.is_read = True
                db.add(message)
                message_ids.append(message.id)
            
            await db.commit()
            
            # Broadcast to room
            for message_id in message_ids:
                await sio.emit('message_read', {
                    'chat_id': chat_id,
                    'message_id': message_id
                }, room=f"chat_{chat_id}")
            
            return {'success': True, 'read_count': len(message_ids)}
    except Exception as e:
        print(f"Error marking messages as read: {e}")
        return {'success': False, 'error': str(e)}
    
@sio.event
async def notification(sid, data):
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        recipient_id = data.get('recipient_id')
        
        if not user_id or not recipient_id:
            return {'success': False, 'error': 'Missing user_id or recipient_id'}
        
        # Emit notification to recipient
        await sio.emit('new_notification', {
            'sender_id': user_id,
            'title': data.get('title', 'New Message'),
            'message': data.get('message', 'You have a new message'),
            'type': data.get('type', 'chat'),
            'data_id': data.get('data_id')
        }, room=f"user_{recipient_id}")
        
        return {'success': True}
    except Exception as e:
        print(f"Error sending notification: {e}")
        return {'success': False, 'error': str(e)}

@sio.event
async def send_message_to_recipient(sid, data):
    """
    Send a message to a recipient, creating a new chat if needed.
    This is used when starting a new conversation.
    """
    try:
        session = await sio.get_session(sid)
        user_id = session.get('user_id')
        recipient_id = data.get('recipient_id')
        message_text = data.get('message')
        
        if not user_id or not recipient_id or not message_text:
            return {'success': False, 'error': 'Missing required fields'}
        
        # Get user information
        async with AsyncSessionLocal() as db:
            # Get current user
            user_result = await db.execute(select(models.User).where(models.User.id == user_id))
            user = user_result.scalars().first()
            
            if not user:
                return {'success': False, 'error': 'User not found'}
            
            # Determine sender type and get sender record
            sender_type = None
            sender_id = None
            recipient_type = None
            
            if user.role == "patient":
                sender_type = "patient"
                recipient_type = "doctor"
                
                # Get patient record
                patient_result = await db.execute(
                    select(models.Patient).where(models.Patient.user_id == user_id)
                )
                patient = patient_result.scalars().first()
                
                if not patient:
                    return {'success': False, 'error': 'Patient record not found'}
                
                sender_id = patient.id
                
                # Get doctor record
                doctor_result = await db.execute(
                    select(models.Doctor).where(models.Doctor.id == recipient_id)
                )
                doctor = doctor_result.scalars().first()
                
                if not doctor:
                    return {'success': False, 'error': 'Doctor not found'}
                
                recipient_id = doctor.id
                
                # Check if a chat already exists
                chat_result = await db.execute(
                    select(models.Chat).where(
                        (models.Chat.patient_id == patient.id) &
                        (models.Chat.doctor_id == doctor.id)
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
            
            elif user.role == "doctor":
                sender_type = "doctor"
                recipient_type = "patient"
                
                # Get doctor record
                doctor_result = await db.execute(
                    select(models.Doctor).where(models.Doctor.user_id == user_id)
                )
                doctor = doctor_result.scalars().first()
                
                if not doctor:
                    return {'success': False, 'error': 'Doctor record not found'}
                
                sender_id = doctor.id
                
                # Get patient record
                patient_result = await db.execute(
                    select(models.Patient).where(models.Patient.id == recipient_id)
                )
                patient = patient_result.scalars().first()
                
                if not patient:
                    return {'success': False, 'error': 'Patient not found'}
                
                recipient_id = patient.id
                
                # Check if a chat already exists
                chat_result = await db.execute(
                    select(models.Chat).where(
                        (models.Chat.patient_id == patient.id) &
                        (models.Chat.doctor_id == doctor.id)
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
                return {'success': False, 'error': 'Only patients and doctors can send messages'}
            
            # Create the message
            try:
                # Validate that chat has valid doctor_id and patient_id
                if not chat.doctor_id or not chat.patient_id:
                    return {'success': False, 'error': 'Chat has invalid doctor_id or patient_id'}
                
                new_message = models.ChatMessage(
                    chat_id=chat.id,
                    sender_id=user_id,
                    message=message_text,
                    timestamp=datetime.utcnow(),
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
                
                # Join the room for this chat
                sio.enter_room(sid, f"chat_{chat.id}")
                
                # Broadcast to room
                await sio.emit('new_message', {
                    'id': new_message.id,
                    'chat_id': new_message.chat_id,
                    'sender_id': new_message.sender_id,
                    'sender_type': new_message.sender_type,
                    'message': new_message.message,
                    'is_read': new_message.is_read,
                    'sent_at': new_message.sent_at.isoformat()
                }, room=f"chat_{chat.id}")
                
                # Return both the message and chat info
                return {
                    'success': True,
                    'message': {
                        'id': new_message.id,
                        'chat_id': new_message.chat_id,
                        'sender_id': new_message.sender_id,
                        'sender_type': new_message.sender_type,
                        'message': new_message.message,
                        'is_read': new_message.is_read,
                        'sent_at': new_message.sent_at.isoformat()
                    },
                    'chat': {
                        'id': chat.id,
                        'patient_id': chat.patient_id,
                        'doctor_id': chat.doctor_id,
                        'encounter_id': chat.encounter_id,
                        'created_at': chat.created_at.isoformat(),
                        'updated_at': chat.updated_at.isoformat()
                    }
                }
            except Exception as e:
                print(f"Error creating message in send_message_to_recipient: {e}")
                await db.rollback()
                # Provide more detailed error message
                error_message = str(e)
                if "violates not-null constraint" in error_message.lower():
                    if "doctor_id" in error_message.lower():
                        return {'success': False, 'error': 'Doctor ID is required but was not provided'}
                    elif "patient_id" in error_message.lower():
                        return {'success': False, 'error': 'Patient ID is required but was not provided'}
                
                return {'success': False, 'error': f'Error creating message: {error_message}'}
                
    except Exception as e:
        print(f"Error in send_message_to_recipient: {e}")
        return {'success': False, 'error': str(e)}