from fastapi import APIRouter, Depends, HTTPException,status,Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Doctor, TreatmentPlanMaster
from app.auth import get_current_user
from app.config import JWT_SECRET, JWT_ALGORITHM
from app import schemas
from sqlalchemy import select, distinct,func
from fastapi.security import OAuth2PasswordBearer
from typing import List
from jose import jwt, JWTError
from typing import Optional
from app import models
from datetime import datetime, date

router = APIRouter(prefix="/assignments", tags=["Assignments"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_hospital(token: str = Depends(oauth2_scheme)) -> int:
    """
    Extract hospital_id from JWT token and return it as integer.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        hospital_id = payload.get("hospital_id")
        if hospital_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital not assigned or invalid token"
            )
        return int(hospital_id)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token"
        )
    
@router.post("/", response_model=schemas.AssignmentResponse)
async def assign_doctor_to_patient(
    assignment: schemas.AssignmentBase,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if current_user.role not in ("hospital", "admin"):
        raise HTTPException(status_code=403, detail="Not permitted to assign doctors")

    # Fetch patient
    result = await db.execute(
        select(models.Patient).filter(models.Patient.public_id == assignment.public_patient_id)
    )
    patient = result.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Validate doctor
    doctor = await db.get(models.Doctor, assignment.doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Validate treatment plan
    treatment_plan = None
    if assignment.treatment_plan_id:
        treatment_plan = await db.get(models.TreatmentPlanMaster, assignment.treatment_plan_id)
        if not treatment_plan:
            raise HTTPException(status_code=404, detail="Treatment plan not found")

    # Create assignment instance
    new_assignment = models.Assignment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        treatment_plan_id=treatment_plan.id if treatment_plan else None,
        specialty=assignment.specialty or doctor.specialty,
        medical_history=assignment.medical_history,
        reason=assignment.reason,
        old_medications=assignment.old_medications or [],
        hospital_id=current_user.hospital_id,
        created_by=current_user.id
    )

    db.add(new_assignment)

    # FIRST COMMIT + REFRESH HERE → So new_assignment.id gets generated
    await db.commit()
    await db.refresh(new_assignment)

    # Now add old medications (assignment_id now valid)
    if assignment.old_medications:
        try:
            for med in assignment.old_medications:
                start_date = (
                    datetime.strptime(med.get("start_date"), "%Y-%m-%d").date()
                    if med.get("start_date") else date.today()
                )
                end_date = (
                    datetime.strptime(med.get("end_date"), "%Y-%m-%d").date()
                    if med.get("end_date") else None
                )

                medication = models.Medication(
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    medication_name=med.get("name"),
                    dosage=med.get("dosage"),
                    frequency=med.get("frequency"),
                    notes=med.get("notes"),
                    status="active",
                    start_date=start_date,
                    end_date=end_date,
                    assignment_id=new_assignment.id
                )
                db.add(medication)

            await db.commit()

        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    return schemas.AssignmentResponse(
        id=new_assignment.id,
        message=f"Doctor {doctor.first_name} {doctor.last_name} assigned to patient {patient.first_name} {patient.last_name} successfully."
    )
#  Get all active treatment plans
@router.get("/treatment_plans",response_model=List[schemas.TreatmentPlanResponse])
async def get_treatment_plans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TreatmentPlanMaster).where(TreatmentPlanMaster.status == "Active")
    )
    plans = result.scalars().all()

    if not plans:
        raise HTTPException(status_code=404, detail="No active treatment plans found")

    return [
        {
            "id": plan.id,
            "name": plan.name,
            "description": plan.description
        }
        for plan in plans
    ]

@router.get("/doctors/available")
async def get_available_doctors(
    specialty: Optional[str] = None,                   
    hospital_id: int = Depends(get_current_hospital), 
    db: AsyncSession = Depends(get_db)
):
    query = select(Doctor).filter(Doctor.hospital_id == hospital_id)
    
    # Filter by specialty if provided (case-insensitive)
    if specialty:
        query = query.filter(func.lower(Doctor.specialty) == specialty.lower())
    
    result = await db.execute(query)
    doctors = result.scalars().all()
    
    # Serialize to JSON
    doctors_list = [
        {
            "id": doc.id,
            "first_name": doc.first_name,
            "last_name": doc.last_name,
            "specialty": doc.specialty,
        }
        for doc in doctors
    ]
    
    return {"hospital_id": hospital_id, "available_doctors": doctors_list}

# Get all specialties (distinct from Doctor table)
@router.get("/specialties",response_model=schemas.SpecialtyResponse)
async def get_all_specialties(db: AsyncSession = Depends(get_db)):
    """
    Get all distinct specialties from the Doctor table.
    """
    result = await db.execute(select(distinct(Doctor.specialty)))
    specialties = [row[0] for row in result.all() if row[0]]

    if not specialties:
        raise HTTPException(status_code=404, detail="No specialties found")

    return {"specialty": specialties} 