from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, or_
from typing import List, Optional, Dict, Any
from datetime import datetime, date
import json
import httpx
import os

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
from app.utils import send_email

router = APIRouter(prefix="/api/care-plans", tags=["care-plans"])

# LLM API configuration
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4")

async def generate_care_plan_with_llm(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a care plan using the LLM API
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }
    
    # Prepare the prompt for the LLM
    prompt = f"""
    You are a clinical decision support system that generates care plans based on patient data.
    Please analyze the following patient information and generate a comprehensive care plan.
    Do not hallucinate any information; only use the data provided.
    
    Patient Information:
    {json.dumps(input_data, indent=2)}
    
    Generate a care plan that includes:
    1. A list of tasks for the patient and healthcare providers
    2. A patient-friendly summary
    3. A clinical summary for healthcare providers
    
    Format your response as a JSON object with the following structure:
    {{
      "careplan_id": "cp_001",
      "status": "proposed",
      "generated_at": "2025-12-09T12:30:00Z",
      "condition_group": "Type 1 Diabetes",
      "icd_codes": ["E10.65"],
      "tasks": [
        {{
          "task_id": "task_001",
          "type": "lab_test",
          "title": "Repeat HbA1c",
          "description": "Repeat HbA1c test in 3 months to assess glycemic improvement.",
          "frequency": "once",
          "due_date": "2026-03-09",
          "assigned_to": "provider",
          "requires_clinician_review": false
        }},
        ...
      ],
      "patient_friendly_summary": "Your care plan focuses on improving blood sugar control...",
      "clinician_summary": "Careplan aligns with NICE NG17...",
      "metadata": {{
        "guideline_used": "NICE NG17",
        "rules_version": "2025-01",
        "llm_model": "gpt-5.1",
        "created_by": "system"
      }}
    }}
    """
    
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a clinical decision support system that generates care plans based on patient data."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 2000
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(LLM_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            llm_response = result["choices"][0]["message"]["content"]
            
            # Parse the JSON response from the LLM
            care_plan_data = json.loads(llm_response)
            return care_plan_data
    except Exception as e:
        print(f"Error generating care plan with LLM: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate care plan: {str(e)}"
        )

async def send_care_plan_notification(user_id: int, care_plan_id: int, db: AsyncSession):
    """
    Send a notification to the user about the new care plan
    """
    # Get the user
    user_result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = user_result.scalars().first()
    
    if not user:
        print(f"User {user_id} not found for notification")
        return
    
    # Get the care plan
    care_plan_result = await db.execute(select(models.CarePlan).where(models.CarePlan.careplan_id == care_plan_id))
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        print(f"Care plan {care_plan_id} not found for notification")
        return
    
    # Create notification
    notification = models.Notification(
        user_id=user_id,
        title="New Care Plan Available",
        desc="A new care plan has been created for you. Please review it.",
        type="care_plan",
        status="unread",
        data_id=str(care_plan_id),
        patient_id=care_plan.patient_id
    )
    
    db.add(notification)
    await db.commit()
    
    # Send email notification if user has email
    if user.email:
        send_email(
            user.email,
            "New Care Plan Available",
            f"""
            Dear {user.full_name},
            
            A new care plan has been created for you. Please log in to your account to review it.
            
            Regards,
            CareIQ Team
            """
        )

@router.post("/generate", response_model=schemas.CarePlanOut)
async def generate_care_plan(
    input_data: schemas.CarePlanGenerationInput,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a care plan for a patient based on encounter data
    """
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can generate care plans"
        )
    
    # Get the encounter
    encounter_id = input_data.current_encounter.encounter_id
    encounter_result = await db.execute(
        select(models.Encounter).where(models.Encounter.id == encounter_id)
    )
    encounter = encounter_result.scalars().first()
    
    if not encounter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Encounter with ID {encounter_id} not found"
        )
    
    # Get or create condition group based on diagnosis
    condition_name = input_data.guideline_rules.condition_group if input_data.guideline_rules else "General"
    
    condition_group_result = await db.execute(
        select(models.ConditionGroup).where(models.ConditionGroup.name == condition_name)
    )
    condition_group = condition_group_result.scalars().first()
    
    if not condition_group:
        # Create new condition group
        condition_group = models.ConditionGroup(
            name=condition_name,
            description=f"Condition group for {condition_name}"
        )
        db.add(condition_group)
        await db.commit()
        await db.refresh(condition_group)
    
    # Generate care plan using LLM
    care_plan_data = await generate_care_plan_with_llm(input_data.dict())
    
    # Create care plan in database
    care_plan = models.CarePlan(
        patient_id=encounter.patient_id,
        encounter_id=encounter.id,
        condition_group_id=condition_group.condition_group_id,
        status="proposed",
        patient_friendly_summary=care_plan_data.get("patient_friendly_summary", ""),
        clinician_summary=care_plan_data.get("clinician_summary", ""),
        plan_metadata=care_plan_data.get("metadata", {})
    )
    
    db.add(care_plan)
    await db.commit()
    await db.refresh(care_plan)
    
    # Create tasks for the care plan
    for task_data in care_plan_data.get("tasks", []):
        task = models.CarePlanTask(
            careplan_id=care_plan.careplan_id,
            type=task_data.get("type", "other"),
            title=task_data.get("title", ""),
            description=task_data.get("description", ""),
            frequency=task_data.get("frequency", ""),
            due_date=task_data.get("due_date"),
            assigned_to=task_data.get("assigned_to", "patient"),
            requires_clinician_review=task_data.get("requires_clinician_review", False),
            status="pending"
        )
        db.add(task)
    
    # Create audit log
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="created",
        actor_id=current_user.id,
        notes="Care plan generated automatically"
    )
    db.add(audit)
    
    await db.commit()
    
    # Get the patient's user ID for notification
    patient_result = await db.execute(
        select(models.Patient).where(models.Patient.id == encounter.patient_id)
    )
    patient = patient_result.scalars().first()
    
    if patient and patient.user_id:
        # Schedule notification in background
        background_tasks.add_task(
            send_care_plan_notification,
            patient.user_id,
            care_plan.careplan_id,
            db
        )
    
    # Refresh care plan to get tasks
    await db.refresh(care_plan)
    
    return care_plan

@router.get("/{careplan_id}", response_model=schemas.CarePlanOut)
async def get_care_plan(
    careplan_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a care plan by ID
    """
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan with ID {careplan_id} not found"
        )
    
    # Check if user is authorized to view this care plan
    if current_user.role == "patient":
        # Check if care plan belongs to this patient
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != care_plan.patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this care plan"
            )
    elif current_user.role == "doctor":
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this care plan"
            )
    
    return care_plan

@router.get("/patient/{patient_id}", response_model=List[schemas.CarePlanOut])
async def get_patient_care_plans(
    patient_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all care plans for a patient
    """
    # Check if user is authorized to view this patient's care plans
    if current_user.role == "patient":
        # Check if patient_id matches the current user's patient ID
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this patient's care plans"
            )
    elif current_user.role == "doctor":
        # Check if doctor has treated this patient
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Doctor record not found"
            )
        
        # Check if doctor has any encounters with this patient
        encounter_result = await db.execute(
            select(models.Encounter).where(
                and_(
                    models.Encounter.patient_id == patient_id,
                    models.Encounter.doctor_id == doctor.id
                )
            )
        )
        encounters = encounter_result.scalars().all()
        
        if not encounters:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this patient's care plans"
            )
    
    # Get all care plans for the patient
    care_plans_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.patient_id == patient_id)
    )
    care_plans = care_plans_result.scalars().all()
    
    return care_plans

@router.put("/{careplan_id}", response_model=schemas.CarePlanOut)
async def update_care_plan(
    careplan_id: int,
    care_plan_update: schemas.CarePlanUpdate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a care plan
    """
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can update care plans"
        )
    
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan with ID {careplan_id} not found"
        )
    
    # Check if doctor is authorized to update this care plan
    if current_user.role == "doctor":
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this care plan"
            )
    
    # Update care plan fields
    if care_plan_update.status is not None:
        care_plan.status = care_plan_update.status
    
    if care_plan_update.patient_friendly_summary is not None:
        care_plan.patient_friendly_summary = care_plan_update.patient_friendly_summary
    
    if care_plan_update.clinician_summary is not None:
        care_plan.clinician_summary = care_plan_update.clinician_summary
    
    if care_plan_update.plan_metadata is not None:
        care_plan.plan_metadata = care_plan_update.plan_metadata
    
    # Update the updated_at timestamp
    care_plan.updated_at = datetime.utcnow()
    
    # Create audit log
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="updated",
        actor_id=current_user.id,
        notes="Care plan updated"
    )
    db.add(audit)
    
    await db.commit()
    await db.refresh(care_plan)
    
    # If status changed to "active", send notification to patient
    if care_plan_update.status == "active":
        # Get the patient's user ID for notification
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.id == care_plan.patient_id)
        )
        patient = patient_result.scalars().first()
        
        if patient and patient.user_id:
            # Schedule notification in background
            background_tasks.add_task(
                send_care_plan_notification,
                patient.user_id,
                care_plan.careplan_id,
                db
            )
    
    return care_plan

@router.post("/{careplan_id}/tasks", response_model=schemas.CarePlanTaskOut)
async def add_care_plan_task(
    careplan_id: int,
    task: schemas.CarePlanTaskCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a task to a care plan
    """
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can add tasks to care plans"
        )
    
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan with ID {careplan_id} not found"
        )
    
    # Check if doctor is authorized to update this care plan
    if current_user.role == "doctor":
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this care plan"
            )
    
    # Create new task
    new_task = models.CarePlanTask(
        careplan_id=care_plan.careplan_id,
        type=task.type,
        title=task.title,
        description=task.description,
        frequency=task.frequency,
        due_date=task.due_date,
        assigned_to=task.assigned_to,
        requires_clinician_review=task.requires_clinician_review,
        status=task.status or "pending"
    )
    
    db.add(new_task)
    
    # Create audit log
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="task_added",
        actor_id=current_user.id,
        notes=f"Task added: {task.title}"
    )
    db.add(audit)
    
    await db.commit()
    await db.refresh(new_task)
    
    return new_task

@router.put("/tasks/{task_id}", response_model=schemas.CarePlanTaskOut)
async def update_care_plan_task(
    task_id: int,
    task_update: schemas.CarePlanTaskUpdate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a care plan task
    """
    # Get the task
    task_result = await db.execute(
        select(models.CarePlanTask).where(models.CarePlanTask.task_id == task_id)
    )
    task = task_result.scalars().first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found"
        )
    
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == task.careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan for task {task_id} not found"
        )
    
    # Check if user is authorized
    if current_user.role == "patient":
        # Patients can only update status of tasks assigned to them
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != care_plan.patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this task"
            )
        
        # Patients can only update status
        if task.assigned_to != "patient":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update tasks assigned to patients"
            )
        
        # Only allow status update
        if task_update.status is not None:
            task.status = task_update.status
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patients can only update task status"
            )
    elif current_user.role == "doctor":
        # Check if doctor is authorized to update this care plan
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this task"
            )
        
        # Doctors can update all fields
        if task_update.title is not None:
            task.title = task_update.title
        
        if task_update.description is not None:
            task.description = task_update.description
        
        if task_update.frequency is not None:
            task.frequency = task_update.frequency
        
        if task_update.due_date is not None:
            task.due_date = task_update.due_date
        
        if task_update.status is not None:
            task.status = task_update.status
        
        if task_update.requires_clinician_review is not None:
            task.requires_clinician_review = task_update.requires_clinician_review
    elif current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to update this task"
        )
    else:
        # Admins can update all fields
        if task_update.title is not None:
            task.title = task_update.title
        
        if task_update.description is not None:
            task.description = task_update.description
        
        if task_update.frequency is not None:
            task.frequency = task_update.frequency
        
        if task_update.due_date is not None:
            task.due_date = task_update.due_date
        
        if task_update.status is not None:
            task.status = task_update.status
        
        if task_update.requires_clinician_review is not None:
            task.requires_clinician_review = task_update.requires_clinician_review
    
    # Update the updated_at timestamp
    task.updated_at = datetime.utcnow()
    
    # Create audit log
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="task_updated",
        actor_id=current_user.id,
        notes=f"Task updated: {task.title}"
    )
    db.add(audit)
    
    await db.commit()
    await db.refresh(task)
    
    return task

@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_care_plan_task(
    task_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a care plan task
    """
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can delete tasks"
        )
    
    # Get the task
    task_result = await db.execute(
        select(models.CarePlanTask).where(models.CarePlanTask.task_id == task_id)
    )
    task = task_result.scalars().first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found"
        )
    
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == task.careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan for task {task_id} not found"
        )
    
    # Check if doctor is authorized to update this care plan
    if current_user.role == "doctor":
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to delete tasks from this care plan"
            )
    
    # Create audit log before deleting
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="task_deleted",
        actor_id=current_user.id,
        notes=f"Task deleted: {task.title}"
    )
    db.add(audit)
    
    # Delete the task
    await db.delete(task)
    await db.commit()
    
    return None