from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional, List
from app.database import get_db
from app import models, schemas
from app.auth import get_current_user

router = APIRouter(prefix="/patients", tags=["Patients Search"])

@router.get("/search")
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
    patients = result.unique().scalars().all()

    if not patients:
        raise HTTPException(status_code=404, detail="No patients found")

    # RETURN SAFE DICTIONARY (NOT ORM OBJECTS)
    return [
        {
            "id": p.id,
            "public_id": p.public_id,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "email": p.email,
            "phone": p.phone,
            "dob": str(p.dob) if p.dob else None,
            "gender": p.gender,
            "ssn": p.ssn,
            "address": p.address,
            "city": p.city,
            "state": p.state,
            "zip_code": p.zip_code,
        }
        for p in patients
    ]
