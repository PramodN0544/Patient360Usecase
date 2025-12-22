from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas

router = APIRouter(prefix="/api/patient-tasks", tags=["patient-tasks"])

@router.get("/", response_model=List[schemas.TaskOut])
async def get_patient_tasks(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all tasks for the current patient
    """
    if current_user.role != "patient":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can access their tasks"
        )
    
    # Get the patient record for the current user
    patient_result = await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )
    patient = patient_result.scalars().first()
    
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient record not found for current user"
        )
    
    # Get the latest care plan for the patient
    care_plan_result = await db.execute(
        select(models.CarePlan)
        .where(models.CarePlan.patient_id == patient.id)
        .order_by(models.CarePlan.created_at.desc())
    )
    latest_care_plan = care_plan_result.scalars().first()
    
    if not latest_care_plan:
        return []
    
    # Get all tasks for the latest care plan
    tasks_result = await db.execute(
        select(models.CarePlanTask)
        .where(models.CarePlanTask.careplan_id == latest_care_plan.careplan_id)
    )
    tasks = tasks_result.scalars().all()
    
    # Convert to TaskOut schema
    return [
        schemas.TaskOut(
            id=task.task_id,
            title=task.title,
            description=task.description or "",
            due_date=task.due_date.isoformat() if task.due_date else None,
            status=task.status,
            priority="normal",  # Default priority
            type=task.type,
            frequency=task.frequency,
            assigned_to=task.assigned_to,
            requires_clinician_review=task.requires_clinician_review
        )
        for task in tasks
    ]

@router.put("/{task_id}", response_model=schemas.TaskOut)
async def update_patient_task(
    task_id: int,
    task_update: schemas.TaskUpdate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a task status for the current patient
    """
    try:
        # Check if user is a patient
        if current_user.role != "patient":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only patients can update their tasks"
            )
        
        # Get the patient record for the current user
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient record not found for current user"
            )
        
        # Get the task
        task_result = await db.execute(
            select(models.CarePlanTask)
            .where(models.CarePlanTask.task_id == task_id)
        )
        task = task_result.scalars().first()
        
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task with ID {task_id} not found"
            )
        
        # Get the care plan to verify ownership
        care_plan_result = await db.execute(
            select(models.CarePlan)
            .where(models.CarePlan.careplan_id == task.careplan_id)
        )
        care_plan = care_plan_result.scalars().first()
        
        if not care_plan or care_plan.patient_id != patient.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this task"
            )
        
        # Patients can only update status
        if task_update.status is not None:
            task.status = task_update.status
        else:
            # If no status provided, return error
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status field is required"
            )
        
        # Update the updated_at timestamp
        task.updated_at = datetime.utcnow()
        
        # Create audit log
        audit = models.CarePlanAudit(
            careplan_id=care_plan.careplan_id,
            action="task_updated_by_patient",
            actor_id=current_user.id,
            notes=f"Task status updated to {task.status} by patient"
        )
        db.add(audit)
        
        await db.commit()
        await db.refresh(task)
        
        # Return the updated task
        return schemas.TaskOut(
            id=task.task_id,
            title=task.title,
            description=task.description or "",
            due_date=task.due_date.isoformat() if task.due_date else None,
            status=task.status,
            priority="normal",  # Default priority
            type=task.type or "other",
            frequency=task.frequency or "",
            assigned_to=task.assigned_to or "patient",
            requires_clinician_review=task.requires_clinician_review or False,
            created_at=task.created_at.date() if task.created_at else None
        )
    except Exception as e:
        # Log the error
        print(f"Error updating task: {str(e)}")
        # Rollback the transaction
        await db.rollback()
        # Raise a generic error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while updating the task: {str(e)}"
        )