# app/routers/labs.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from app.database import get_db
from app.models import LabMaster, LabOrder, LabResult, Patient, Doctor
from app.schemas import (
    LabOrderCreate, LabOrderResponse, LabTestCode, LabTestDetail, LabResultResponse
)
from app.auth import get_current_user
from app.S3connection import upload_lab_result_to_s3, generate_presigned_url
from fastapi.responses import StreamingResponse
import aiohttp
from io import BytesIO
router = APIRouter(prefix="/labs", tags=["Labs"])


# 1 - testcodes
@router.get("/testcodes", response_model=List[LabTestCode])
async def get_all_test_codes(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in ["doctor", "hospital", "labassistant"]:
        raise HTTPException(status_code=403, detail="Access denied")
    r = await db.execute(select(LabMaster).where(LabMaster.is_active == True))
    tests = r.scalars().all()
    return [{"test_code": t.test_code} for t in tests]


# 2 - test detail
@router.get("/test/{test_code}", response_model=LabTestDetail)
async def get_test_details(test_code: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in ["doctor", "hospital", "labassistant"]:
        raise HTTPException(status_code=403, detail="Access denied")
    r = await db.execute(select(LabMaster).where(LabMaster.test_code == test_code, LabMaster.is_active == True))
    test = r.scalar_one_or_none()
    if not test:
        raise HTTPException(status_code=404, detail="Test code not found")
    return test


# 3 - create lab orders
@router.post("/orders/{encounter_id}", response_model=List[LabOrderResponse])
async def create_lab_orders(
    encounter_id: int,
    orders: List[LabOrderCreate],
    patient_id: int,
    doctor_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ["doctor", "hospital"]:
        raise HTTPException(status_code=403, detail="Access denied")
    lab_orders = []
    for o in orders:
        r = await db.execute(select(LabMaster).where(LabMaster.test_code == o.test_code))
        test = r.scalar_one_or_none()
        if not test:
            raise HTTPException(status_code=404, detail=f"Test code {o.test_code} not found")
        lab_order = LabOrder(
            encounter_id=encounter_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            test_code=o.test_code,
            test_name=test.test_name,
            sample_type=test.sample_type,
            status="Pending"
        )
        db.add(lab_order)
        await db.flush()
        lab_orders.append(lab_order)
    await db.commit()
    return lab_orders


# 4 - upload lab result (store file_key)
@router.post("/results")
async def add_lab_result(
    lab_order_id: int = Form(...),
    result_value: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ["labassistant", "doctor", "hospital"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # fetch lab order
    r = await db.execute(select(LabOrder).where(LabOrder.id == lab_order_id))
    lab_order = r.scalar_one_or_none()
    if not lab_order:
        raise HTTPException(status_code=404, detail="Lab order not found")

    # fetch doctor to find hospital_id
    r = await db.execute(select(Doctor).where(Doctor.id == lab_order.doctor_id))
    doctor = r.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    hospital_id = doctor.hospital_id

    # upload to S3 -> file_key
    file_key = await upload_lab_result_to_s3(
        file=file,
        patient_id=lab_order.patient_id,
        lab_order_id=lab_order_id,
        hospital_id=hospital_id,
        encounter_id=lab_order.encounter_id
    )

    # save lab result
    lab_result = LabResult(
        lab_order_id=lab_order_id,
        result_value=result_value,
        notes=notes,
        file_key=file_key
    )
    db.add(lab_result)
    lab_order.status = "Completed"
    await db.commit()
    await db.refresh(lab_result)

    # return file_key only; presigned urls can be fetched via /view & /download endpoints
    return {
        "message": "Lab result saved successfully",
        "lab_result_id": lab_result.id,
        "file_key": file_key
    }


# 5 - list orders for encounter
@router.get("/orders/{encounter_id}", response_model=List[LabOrderResponse])
async def get_lab_orders(encounter_id: int, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in ["doctor", "hospital", "labassistant", "patient"]:
        raise HTTPException(status_code=403, detail="Access denied")
    r = await db.execute(select(LabOrder).where(LabOrder.encounter_id == encounter_id))
    lab_orders = r.scalars().all()
    return lab_orders


# 6 - patient: my results (includes presigned URLs)
@router.get("/my-results", response_model=List[LabResultResponse])
async def get_my_lab_results(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "patient":
        raise HTTPException(status_code=403, detail="Access denied")

    r = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = r.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    q = await db.execute(
        select(LabOrder, LabResult)
        .join(LabResult, LabResult.lab_order_id == LabOrder.id, isouter=True)
        .where(LabOrder.patient_id == patient.id)
    )
    rows = q.all()

    out = []
    for order, result in rows:
        if result and result.file_key:
            view_url = generate_presigned_url(result.file_key, disposition="inline")
            download_url = generate_presigned_url(result.file_key, disposition="attachment")
        else:
            view_url = download_url = None

        out.append({
            "lab_order_id": order.id,
            "result_value": result.result_value if result else None,
            "notes": result.notes if result else None,
            "view_url": view_url,
            "download_url": download_url,
            "file_key": result.file_key if result else None,
            "created_at": result.created_at if result else None
        })
    return out


# 7 - doctor: results for my patients (includes presigned URLs)
@router.get("/doctor-results", response_model=List[LabResultResponse])
async def get_doctor_lab_results(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Access denied")

    r = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
    doctor = r.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    doctor_id = doctor.id

    q = await db.execute(
        select(LabOrder, LabResult, Patient)
        .join(LabResult, LabResult.lab_order_id == LabOrder.id, isouter=True)
        .join(Patient, Patient.id == LabOrder.patient_id)
        .where(LabOrder.doctor_id == doctor_id)
    )
    rows = q.all()

    out = []
    for order, result, patient in rows:
        if result and result.file_key:
            view_url = generate_presigned_url(result.file_key, disposition="inline")
            download_url = generate_presigned_url(result.file_key, disposition="attachment")
        else:
            view_url = download_url = None

        out.append({
            "lab_order_id": order.id,
            "result_value": result.result_value if result else None,
            "notes": result.notes if result else None,
            "view_url": view_url,
            "download_url": download_url,
            "file_key": result.file_key if result else None,
            "created_at": result.created_at if result else None
        })
    return out


# 8 - hospital: all results for hospital
@router.get("/hospital-results", response_model=List[LabResultResponse])
async def get_hospital_lab_results(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Access denied")

    hospital_id = current_user.hospital_id

    q = await db.execute(
        select(LabOrder, LabResult, Patient, Doctor)
        .join(LabResult, LabResult.lab_order_id == LabOrder.id, isouter=True)
        .join(Patient, Patient.id == LabOrder.patient_id)
        .join(Doctor, Doctor.id == LabOrder.doctor_id)
        .where(Doctor.hospital_id == hospital_id)
    )
    rows = q.all()

    out = []
    for order, result, patient, doctor in rows:
        if result and result.file_key:
            view_url = generate_presigned_url(result.file_key, disposition="inline")
            download_url = generate_presigned_url(result.file_key, disposition="attachment")
        else:
            view_url = download_url = None

        out.append({
            "lab_order_id": order.id,
            "result_value": result.result_value if result else None,
            "notes": result.notes if result else None,
            "view_url": view_url,
            "download_url": download_url,
            "file_key": result.file_key if result else None,
            "created_at": result.created_at if result else None
        })
    return out


# ------------------------------------------------------------
# 9 - Redirect endpoints (optional) — hide presigned URL from client
# ------------------------------------------------------------
# -----------------------------
# View PDF (inline)
# -----------------------------

# View PDF securely


# View PDF securely (inline)
@router.get("/view/{lab_result_id}")
async def view_lab_result(lab_result_id: int, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 1️⃣ Fetch the lab result
    r = await db.execute(select(LabResult).where(LabResult.id == lab_result_id))
    result = r.scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Lab result not found")

    # 2️⃣ RBAC
    if current_user.role == "patient":
        r = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
        patient = r.scalar_one_or_none()
        if not patient or patient.id != result.lab_order.patient_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role == "doctor":
        r = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
        doctor = r.scalar_one_or_none()
        if not doctor or doctor.id != result.lab_order.doctor_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Access denied")

    # 3️⃣ Generate presigned URL internally
    presigned_url = generate_presigned_url(result.file_key, disposition="inline")

    # 4️⃣ Stream content from S3 to client
    async with aiohttp.ClientSession() as session:
        async with session.get(presigned_url) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail="Failed to fetch file from S3")
            file_data = BytesIO(await resp.read())

    return StreamingResponse(file_data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{result.file_key.split("/")[-1]}"'
    })


# Download PDF securely (attachment)
@router.get("/download/{lab_result_id}")
async def download_lab_result(lab_result_id: int, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(LabResult).where(LabResult.id == lab_result_id))
    result = r.scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Lab result not found")

    # RBAC (reuse same as view)
    if current_user.role == "patient":
        r = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
        patient = r.scalar_one_or_none()
        if not patient or patient.id != result.lab_order.patient_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role == "doctor":
        r = await db.execute(select(Doctor).where(Doctor.user_id == current_user.id))
        doctor = r.scalar_one_or_none()
        if not doctor or doctor.id != result.lab_order.doctor_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Access denied")

    presigned_url = generate_presigned_url(result.file_key, disposition="attachment")

    async with aiohttp.ClientSession() as session:
        async with session.get(presigned_url) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail="Failed to fetch file from S3")
            file_data = BytesIO(await resp.read())

    return StreamingResponse(file_data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{result.file_key.split("/")[-1]}"'
    })
