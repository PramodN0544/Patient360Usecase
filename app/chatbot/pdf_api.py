"""
API endpoints for PDF knowledge base management.

This module provides FastAPI endpoints for uploading PDFs to the knowledge base.
"""

import os
import shutil
import uuid
import json
import logging
import time
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models import User
from app.chatbot.rag import rag_pipeline

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/api/knowledge",
    tags=["knowledge"],
    responses={404: {"description": "Not found"}},
)
# Import background tasks from task_store
from app.chatbot.task_store import background_tasks, save_background_tasks, load_background_tasks

# The tasks are already loaded in task_store.py when it's imported
async def process_pdf_in_background(
    task_id: str,
    pdf_path: str,
    source: str,
    topic: str,
    audience: str,
    chunk_size: int,
    chunk_overlap: int
):
    """
    Process a PDF file in the background.
    
    Args:
        task_id: The ID of the background task.
        pdf_path: Path to the PDF file.
        source: The source of the knowledge.
        topic: The topic of the knowledge.
        audience: The target audience.
        chunk_size: The size of each chunk.
        chunk_overlap: The overlap between chunks.
    """
    try:
        # Initialize task status
        background_tasks[task_id] = {
            "status": "initializing",
            "progress": 0,
            "chunks_added": 0,
            "file_name": os.path.basename(pdf_path),
            "message": "Starting PDF processing",
            "start_time": time.time(),
            "file_size": os.path.getsize(pdf_path),
            "last_updated": time.time()
        }
        
        # Save tasks to file
        save_background_tasks()
        
        # Process the PDF with task_id for progress tracking
        chunks_added, chunk_ids = await rag_pipeline.process_pdf(
            pdf_path=pdf_path,
            source=source,
            topic=topic,
            audience=audience,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            task_id=task_id
        )
        
        # Update task status to completed
        background_tasks[task_id].update({
            "status": "completed",
            "progress": 100,
            "chunks_added": chunks_added,
            "chunk_ids": chunk_ids,
            "source": source,
            "topic": topic,
            "audience": audience,
            "message": "Processing completed successfully",
            "end_time": time.time(),
            "last_updated": time.time()
        })
        
        # Save tasks to file
        save_background_tasks()
        
        logger.info(f"Background task {task_id} completed: added {chunks_added} chunks")
    
    except Exception as e:
        logger.error(f"Error in background task {task_id}: {e}")
        background_tasks[task_id] = {
            "status": "failed",
            "progress": 0,
            "error": str(e),
            "file_name": os.path.basename(pdf_path),
            "message": f"Error: {str(e)}",
            "end_time": time.time(),
            "last_updated": time.time()
        }
        
        # Save tasks to file
        save_background_tasks()


@router.post("/upload-pdf")
async def upload_pdf_knowledge(
    background_task_manager: BackgroundTasks,
    file: UploadFile = File(...),
    source: str = Form(...),
    topic: str = Form(...),
    audience: str = Form("clinician"),
    chunk_size: int = Form(1000),
    chunk_overlap: int = Form(200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a PDF file and add its content to the knowledge base.
    
    Args:
        background_task_manager: FastAPI background tasks.
        file: The PDF file to upload.
        source: The source of the knowledge (e.g., book title).
        topic: The topic of the knowledge.
        audience: The target audience (patient or clinician).
        chunk_size: The size of each chunk.
        chunk_overlap: The overlap between chunks.
        current_user: The current user.
        db: The database session.
        
    Returns:
        Information about the upload.
    """
    try:
        # Check permissions - only hospital admins can add knowledge
        if current_user.role != "hospital":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only hospital administrators can add knowledge"
            )
        
        # Check file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF files are allowed"
            )
        
        # Create uploads directory if it doesn't exist
        upload_dir = os.path.join(os.getcwd(), "uploads", "knowledge_base")
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save the file with a unique name to avoid conflicts
        file_name = f"{uuid.uuid4().hex}_{file.filename}"
        file_path = os.path.join(upload_dir, file_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Check file size
        file_size = os.path.getsize(file_path)
        
        # For large files (>10MB), process in background
        if file_size > 10 * 1024 * 1024:  # 10MB
            task_id = f"pdf-{uuid.uuid4().hex}"
            
            # Initialize task info in our global dictionary
            background_tasks[task_id] = {
                "status": "started",
                "progress": 0,
                "file_name": file.filename,
                "source": source,
                "topic": topic,
                "audience": audience,
                "message": "Task queued for processing",
                "start_time": time.time(),
                "last_updated": time.time(),
                "file_size": file_size
            }
            
            # Save tasks to file
            save_background_tasks()
            
            # Start background task
            background_task_manager.add_task(
                process_pdf_in_background,
                task_id=task_id,
                pdf_path=file_path,
                source=source,
                topic=topic,
                audience=audience,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            return {
                "filename": file.filename,
                "source": source,
                "topic": topic,
                "audience": audience,
                "status": "processing",
                "task_id": task_id,
                "message": "Large file is being processed in the background"
            }
        
        # For smaller files, process immediately
        chunks_added, chunk_ids = await rag_pipeline.process_pdf(
            pdf_path=file_path,
            source=source,
            topic=topic,
            audience=audience,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
        return {
            "filename": file.filename,
            "source": source,
            "topic": topic,
            "audience": audience,
            "chunks_added": chunks_added,
            "status": "success"
        }
    
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing PDF: {str(e)}"
        )


@router.get("/task-status/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get the status of a background knowledge processing task.
    
    Args:
        task_id: The ID of the background task.
        current_user: The current user.
        
    Returns:
        The task status.
    """
    try:
        # Check permissions
        if current_user.role != "hospital":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only hospital administrators can check task status"
            )
        
        task_status = background_tasks.get(task_id)
        
        if not task_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )
        
        # Create a response with cache control headers to prevent browser caching
        from fastapi.responses import JSONResponse
        
        response = JSONResponse(content=task_status)
        
        # Add cache control headers to prevent caching
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        # Log the task status for debugging
        logger.debug(f"Returning task status for {task_id}: progress={task_status.get('progress', 'N/A')}%")
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking task status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking task status: {str(e)}"
        )


@router.get("/stats")
async def get_knowledge_stats(
    current_user: User = Depends(get_current_user)
):
    """
    Get statistics about the knowledge base.
    
    Args:
        current_user: The current user.
        
    Returns:
        Statistics about the knowledge base.
    """
    try:
        # Check permissions
        if current_user.role != "hospital":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only hospital administrators can view knowledge stats"
            )
        
        stats = await rag_pipeline.get_knowledge_stats()
        return stats
    
    except Exception as e:
        logger.error(f"Error getting knowledge stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting knowledge stats: {str(e)}"
        )