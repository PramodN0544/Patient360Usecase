# app/routers/labs.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from app.database import get_db
from app.models import Encounter, LabMaster, LabOrder, LabResult, Patient, Doctor
from app.schemas import (
    LabOrderCreate, LabOrderResponse, LabTestCode, LabTestDetail, LabResultResponse
)
from app.auth import get_current_user
from app.S3connection import upload_lab_result_to_s3, generate_presigned_url
from fastapi.responses import StreamingResponse
import aiohttp
from io import BytesIO
router = APIRouter(prefix="/labs", tags=["Labs"])

async def check_encounter_access(encounter, current_user, db):
    # PATIENT
    if current_user.role == "patient":
        r = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
        patient = r.scalar_one_or_none()
        if not patient or patient.id != encounter.patient_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # DOCTOR
    elif current_user.role == "doctor":
        r = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
        doctor = r.scalar_one_or_none()
        if not doctor or doctor.id != encounter.doctor_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # ONLY HOSPITAL USERS ALLOWED
    elif current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Access denied")



# View PDF securely (inline)
@router.get("/encounter/{encounter_id}/view/{doc_index}")
async def view_encounter_document(
    encounter_id: int,
    doc_index: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Fetch encounter
    q = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    encounter = q.scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # RBAC
    await check_encounter_access(encounter, current_user, db)

    # Validate index
    if not encounter.documents or doc_index >= len(encounter.documents):
        raise HTTPException(404, "Document not found")

    file_key = encounter.documents[doc_index]

    # Create presigned URL for INLINE view
    presigned_url = generate_presigned_url(file_key, disposition="inline")

    # Fetch from S3
    async with aiohttp.ClientSession() as session:
        async with session.get(presigned_url) as resp:
            if resp.status != 200:
                raise HTTPException(resp.status, "Failed to fetch file from S3")
            file_data = BytesIO(await resp.read())

    filename = file_key.split("/")[-1]

    return StreamingResponse(
        file_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )

# Download PDF securely (attachment)
@router.get("/encounter/{encounter_id}/download/{doc_index}")
async def download_encounter_document(
    encounter_id: int,
    doc_index: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # Fetch encounter
    q = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    encounter = q.scalar_one_or_none()

    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # RBAC
    await check_encounter_access(encounter, current_user, db)

    # Validate index
    if not encounter.documents or doc_index >= len(encounter.documents):
        raise HTTPException(404, "Document not found")

    file_key = encounter.documents[doc_index]

    # Presigned URL for ATTACHMENT
    presigned_url = generate_presigned_url(file_key, disposition="attachment")

    # Stream from S3
    async with aiohttp.ClientSession() as session:
        async with session.get(presigned_url) as resp:
            if resp.status != 200:
                raise HTTPException(resp.status, "Failed to fetch file from S3")
            file_data = BytesIO(await resp.read())

    filename = file_key.split("/")[-1]

    return StreamingResponse(
        file_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
