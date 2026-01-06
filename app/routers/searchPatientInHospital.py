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
        filters.append(models.Patient.public_id == patient_id)

    if name:
        name = f"%{name.lower()}%"
        filters.append(
            or_(
                models.Patient.first_name.ilike(name),
                models.Patient.last_name.ilike(name),
                models.Patient.middle_name.ilike(name)
            )
        )

    if phone:
        filters.append(
            or_(
                models.Patient.phone.ilike(f"%{phone}%"),
                models.Patient.alternate_phone.ilike(f"%{phone}%")
            )
        )

    if ssn:
        filters.append(models.Patient.ssn.ilike(f"%{ssn}%"))

    if filters:
        stmt = stmt.where(*filters)

    result = await db.execute(stmt)
    patients = result.unique().scalars().all()

    return [
        {
            "id": p.id,
            "public_id": p.public_id,
            "user_id": p.user_id,
            "mrn": p.mrn,
            "first_name": p.first_name,
            "middle_name": p.middle_name,
            "last_name": p.last_name,
            "suffix": p.suffix,
            "dob": p.dob.isoformat() if p.dob else None,
            "age": p.age,
            "gender": p.gender,
            "marital_status": p.marital_status,

            "email": p.email,
            "phone": p.phone,
            "alternate_phone": p.alternate_phone,
            "preferred_contact": p.preferred_contact,
            "preferred_communication": p.preferred_communication,
            "phone_verified": p.phone_verified,
            "phone_verified_at": p.phone_verified_at.isoformat() if p.phone_verified_at else None,

            "address": p.address,
            "city": p.city,
            "state": p.state,
            "zip_code": p.zip_code,
            "country": p.country,
            "ssn": p.ssn,
            "citizenship_status": p.citizenship_status,
        
            "visa_type": p.visa_type,

            "photo_url": p.photo_url,
            "id_proof_document": p.id_proof_document,

            "height": float(p.height) if p.height else None,
            "weight": float(p.weight) if p.weight else None,
            "is_insured": p.is_insured,
            "insurance_status": p.insurance_status,

            "smoking_status": p.smoking_status,
            "alcohol_use": p.alcohol_use,
            "diet": p.diet,
            "exercise_frequency": p.exercise_frequency,

            "has_caregiver": p.has_caregiver,
            "caregiver_name": p.caregiver_name,
            "caregiver_relationship": p.caregiver_relationship,
            "caregiver_phone": p.caregiver_phone,
            "caregiver_email": p.caregiver_email,

            "emergency_contact_name": p.emergency_contact_name,
            "emergency_contact_relationship": p.emergency_contact_relationship,
            "emergency_phone": p.emergency_phone,
            "emergency_alternate_phone": p.emergency_alternate_phone,

            "pcp_name": p.pcp_name,
            "pcp_npi": p.pcp_npi,
            "pcp_phone": p.pcp_phone,
            "pcp_facility": p.pcp_facility,

            "preferred_pharmacy_name": p.preferred_pharmacy_name,
            "preferred_pharmacy_address": p.preferred_pharmacy_address,
            "preferred_pharmacy_phone": p.preferred_pharmacy_phone,

            "race": p.race,
            "ethnicity": p.ethnicity,
            "preferred_language": p.preferred_language,
            "interpreter_required": p.interpreter_required,

            "is_active": p.is_active,
            "deactivated_at": p.deactivated_at.isoformat() if p.deactivated_at else None,

            "created_at": p.created_at.isoformat() if hasattr(p, "created_at") else None,
            "updated_at": p.updated_at.isoformat() if hasattr(p, "updated_at") else None,
        }
        for p in patients
    ]
