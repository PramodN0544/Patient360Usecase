"""
API endpoints for the Patient360 Chatbot.

This module provides FastAPI endpoints for interacting with the chatbot.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.auth import get_current_user
from app.models import User
from app.chatbot.orchestrator import ChatOrchestrator, Message, ChatResponse
from app.chatbot.rag import rag_pipeline
from app.chatbot.rbac import get_data_scope
from app.chatbot.audit import log_chat_interaction
from app.chatbot.streaming import StreamingChatProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/api/chatbot",
    tags=["chatbot"],
    responses={404: {"description": "Not found"}},
)


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    previous_messages: Optional[List[Message]] = []


class ChatResponseModel(BaseModel):
    """Chat response model."""
    response: str
    query_type: str
    data_accessed: Optional[List[str]] = None


# Create chat orchestrator and streaming processor
chat_orchestrator = ChatOrchestrator(rag_pipeline)
streaming_processor = StreamingChatProcessor(chat_orchestrator)


@router.post("/chat", response_model=ChatResponseModel)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Chat with the chatbot.
    
    Args:
        request: The chat request.
        current_user: The current user.
        db: The database session.
        
    Returns:
        The chatbot's response.
    """
    try:
        # Get data scope for the user
        data_scope = await get_data_scope(current_user, db)
        
        # Log the request
        logger.info(f"Chat request from user {current_user.id} ({current_user.role})")
        
        # Process the request
        response = await chat_orchestrator.process_chat_request(
            user=current_user,
            message=request.message,
            previous_messages=request.previous_messages,
            data_scope=data_scope,
            db=db
        )
        
        # Get the context from the orchestrator
        context = await chat_orchestrator._build_context(
            user=current_user,
            message=request.message,
            previous_messages=request.previous_messages,
            query_type=response.query_type,
            data={},  # We don't need to rebuild the data
            data_scope=data_scope
        )
        
        # Log the interaction
        await log_chat_interaction(
            user_id=current_user.id,
            message=request.message,
            response=response.response,
            query_type=response.query_type,
            data_accessed=response.data_accessed,
            context=context,
            db=db
        )
        
        return response
    
    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing chat request"
        )


@router.post("/chat-stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Chat with the chatbot with streaming response.
    
    Args:
        request: The chat request.
        current_user: The current user.
        db: The database session.
        
    Returns:
        A streaming response with progress updates and the final response.
    """
    try:
        # Get data scope for the user
        data_scope = await get_data_scope(current_user, db)
        
        # Log the request
        logger.info(f"Streaming chat request from user {current_user.id} ({current_user.role})")
        
        # Create async generator for streaming response
        async def response_generator():
            async for chunk in streaming_processor.process_chat_request_stream(
                user=current_user,
                message=request.message,
                previous_messages=request.previous_messages,
                data_scope=data_scope,
                db=db
            ):
                yield chunk + "\n"
        
        # Return streaming response
        return StreamingResponse(
            response_generator(),
            media_type="application/x-ndjson"
        )
    
    except Exception as e:
        logger.error(f"Error processing streaming chat request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing streaming chat request"
        )

@router.get("/suggested-prompts")
async def get_suggested_prompts(
    current_user: User = Depends(get_current_user)
):
    """
    Get suggested prompts for the user.
    
    Args:
        current_user: The current user.
        
    Returns:
        A list of suggested prompts.
    """
    try:
        # Get suggested prompts based on user role
        if current_user.role == "patient":
            return {
                "prompts": [
                    "What are my recent lab results?",
                    "What medications am I currently taking?",
                    "When is my next appointment?",
                    "What does my blood pressure reading mean?",
                    "Can you explain my diagnosis in simple terms?"
                ]
            }
        
        elif current_user.role == "doctor":
            return {
                "prompts": [
                    "Show me the latest labs for patient [name]",
                    "What medications is patient [name] taking?",
                    "What is the treatment protocol for hypertension?",
                    "Explain the side effects of metformin",
                    "What are the latest guidelines for diabetes management?"
                ]
            }
        
        elif current_user.role == "hospital":
            return {
                "prompts": [
                    "How many patients were seen this month?",
                    "What's the average length of stay?",
                    "What are the most common diagnoses in our hospital?",
                    "Show me the readmission rates for the past quarter",
                    "What's the current bed occupancy rate?"
                ]
            }
        
        else:
            return {
                "prompts": [
                    "How can I help you today?",
                    "What would you like to know?",
                    "What information are you looking for?",
                    "How can I assist you with your healthcare needs?",
                    "What questions do you have about your health?"
                ]
            }
    
    except Exception as e:
        logger.error(f"Error getting suggested prompts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error getting suggested prompts"
        )