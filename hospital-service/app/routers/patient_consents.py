# app/routers/patient_consents.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import PatientConsents, Patient
from app.auth import get_current_user

router = APIRouter(prefix="/patient-consents", tags=["Patient Consents"])

class PatientConsentCreate(BaseModel):
    patient_id: int
    hipaa: bool = False
    text_messaging: bool = False
    marketing: bool = False
    copay: bool = False
    treatment: bool = False
    financial: bool = False
    research: bool = False

@router.post("/")
async def create_patient_consent(
    consent_data: PatientConsentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Save patient consent forms"""
    # Check if patient exists
    patient_result = await db.execute(select(Patient).where(Patient.id == consent_data.patient_id))
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Patient not found")

    # Create consent record
    consent = PatientConsents(**consent_data.dict())
    db.add(consent)
    await db.commit()
    await db.refresh(consent)

    return {"message": "Patient consents saved successfully", "consent_id": consent.id}