from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional, List

from app.database import get_db
from app import models, schemas
from app.auth import get_current_user

router = APIRouter(prefix="/patients", tags=["Patients Search"])


@router.get("/search", response_model=List[schemas.PatientOut])
async def search_patients(
    patient_id: Optional[str] = None,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    ssn: Optional[str] = None,                   
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):

    stmt = select(models.Patient)
    filters = []

    if patient_id:
        filters.append(models.Patient.id == patient_id)

    if name:
        name = f"%{name.lower()}%"
        filters.append(
            or_(
                models.Patient.first_name.ilike(name),
                models.Patient.last_name.ilike(name)
            )
        )

    if phone:
        filters.append(models.Patient.phone.ilike(f"%{phone}%"))

    if ssn:
        filters.append(models.Patient.ssn.ilike(f"%{ssn}%")) 

    if filters:
        stmt = stmt.where(*filters)

    result = await db.execute(stmt)
    patients = result.scalars().all()

    if not patients:
        raise HTTPException(status_code=404, detail="No patients found")

    return patients
