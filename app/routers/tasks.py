from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app import models
from app.schemas import TaskCreate, TaskUpdate, TaskOut
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/tasks", tags=["Patient Tasks"])

# CREATE TASK
@router.post("/", response_model=TaskOut)
async def create_task(
    task_in: TaskCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can create tasks")

    # find patient by user_id
    patient = (await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )).unique().scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    new_task = models.PatientTask(
        patient_id=patient.id,
        title=task_in.title,
        description=task_in.description,
        due_date=task_in.due_date,
        priority=task_in.priority,
    )

    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    return new_task


# GET ALL TASKS FOR LOGGED IN PATIENT
@router.get("/", response_model=list[TaskOut])
async def get_my_tasks(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can view tasks")

    patient = (await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )).unique().scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    result = await db.execute(
        select(models.PatientTask)
        .where(models.PatientTask.patient_id == patient.id)
        .order_by(models.PatientTask.created_at.desc())
    )

    tasks = result.scalars().all()
    return tasks

# UPDATE TASK
@router.put("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can update tasks")

    patient = (await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )).unique().scalar_one_or_none()

    result = await db.execute(
        select(models.PatientTask)
        .where(models.PatientTask.id == task_id,
               models.PatientTask.patient_id == patient.id)
    )
    task = result.unique().scalar_one_or_none()

    if not task:
        raise HTTPException(404, "Task not found")

    for field, value in task_in.dict(exclude_unset=True).items():
        setattr(task, field, value)

    await db.commit()
    await db.refresh(task)

    return task

# DELETE TASK
@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can delete tasks")

    patient = (await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )).unique().scalar_one_or_none()

    result = await db.execute(
        select(models.PatientTask)
        .where(models.PatientTask.id == task_id,
               models.PatientTask.patient_id == patient.id)
    )
    task = result.unique().scalar_one_or_none()

    if not task:
        raise HTTPException(404, "Task not found")

    await db.delete(task)
    await db.commit()

    return {"message": "Task deleted successfully"}


# GET DOCTOR NOTES FOR LOGGED IN PATIENT
@router.get("/notes", tags=["Doctor Notes"])
async def get_doctor_notes(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can view notes")

    # Find patient by user
    patient = (
        await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
    ).unique().scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    # Fetch encounters WITH doctor details
    result = await db.execute(
        select(models.Encounter)
        .options(selectinload(models.Encounter.doctor))
        .where(
            models.Encounter.patient_id == patient.id,
            models.Encounter.notes != None
        )
        .order_by(models.Encounter.created_at.desc())
    )

    encounters = result.unique().scalars().all()

    notes = []
    for e in encounters:
        doctor_name = None
        if e.doctor:
            doctor_name = f"{e.doctor.first_name} {e.doctor.last_name}"

        notes.append({
            "id": e.id,
            "doctor_name": doctor_name,
            "note": e.notes,
            "date": e.encounter_date,
        })

    return notes


