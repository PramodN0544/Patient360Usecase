from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from app.database import get_db
from app.models import LabMaster, LabOrder, LabResult, Patient
from app.schemas import LabOrderCreate, LabOrderResponse, LabTestCode, LabTestDetail
from app.auth import get_current_user
from app.S3connection import upload_lab_result_to_s3
from app.models import Doctor
router = APIRouter(prefix="/labs", tags=["Labs"])

# ------------------------------------------------------------
# 1️⃣ Get all test codes
# ------------------------------------------------------------
@router.get("/testcodes", response_model=List[LabTestCode])
async def get_all_test_codes(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in ["doctor", "hospital", "labassistant"]:
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.execute(select(LabMaster).where(LabMaster.is_active == True))
    tests = result.scalars().all()
    return [{"test_code": t.test_code} for t in tests]

# ------------------------------------------------------------
# 2️⃣ Get full test detail
# ------------------------------------------------------------
@router.get("/test/{test_code}", response_model=LabTestDetail)
async def get_test_details(test_code: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in ["doctor", "hospital", "labassistant"]:
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.execute(select(LabMaster).where(LabMaster.test_code == test_code, LabMaster.is_active == True))
    test = result.scalar_one_or_none()
    if not test:
        raise HTTPException(status_code=404, detail="Test code not found")
    return test

# ------------------------------------------------------------
# 3️⃣ Create Lab Orders
# ------------------------------------------------------------
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
        result = await db.execute(select(LabMaster).where(LabMaster.test_code == o.test_code))
        test = result.scalar_one_or_none()
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

# ------------------------------------------------------------
# 4️⃣ Add Lab Result + Upload PDF (Hospital ID auto-detected)
# ------------------------------------------------------------
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

    # ---------------------------
    # 1️⃣ Fetch Lab Order
    # ---------------------------
    result_db = await db.execute(
        select(LabOrder).where(LabOrder.id == lab_order_id)
    )
    lab_order = result_db.scalar_one_or_none()

    if not lab_order:
        raise HTTPException(status_code=404, detail="Lab order not found")

    patient_id = lab_order.patient_id
    encounter_id = lab_order.encounter_id
    doctor_id = lab_order.doctor_id

    # ---------------------------
    # 2️⃣ Fetch Hospital ID from Doctor table
    # ---------------------------
    doctor_query = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = doctor_query.scalar_one_or_none()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    hospital_id = doctor.hospital_id  # ✅ Now we have hospital ID

    # ---------------------------
    # 3️⃣ Upload PDF to S3
    # ---------------------------
    s3_url = await upload_lab_result_to_s3(
        file=file,
        patient_id=patient_id,
        lab_order_id=lab_order_id,
        hospital_id=hospital_id,
        encounter_id=encounter_id
    )

    # ---------------------------
    # 4️⃣ Store Lab Result
    # ---------------------------
    lab_result = LabResult(
        lab_order_id=lab_order_id,
        result_value=result_value,
        notes=notes,
        pdf_url=s3_url
    )

    db.add(lab_result)

    # mark lab order as completed
    lab_order.status = "Completed"

    await db.commit()
    await db.refresh(lab_result)

    return {
        "message": "Lab result saved successfully",
        "lab_result_id": lab_result.id,
        "pdf_url": s3_url
    }

# ------------------------------------------------------------
# 5️⃣ Get Lab Orders for Encounter
# ------------------------------------------------------------
@router.get("/orders/{encounter_id}", response_model=List[LabOrderResponse])
async def get_lab_orders(encounter_id: int, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in ["doctor", "hospital", "labassistant", "patient"]:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(select(LabOrder).where(LabOrder.encounter_id == encounter_id))
    lab_orders = result.scalars().all()
    return lab_orders

##------------------------------------------------------------
# 6️⃣ Patient: Get My Lab Results

@router.get("/my-results")
async def get_my_lab_results(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(status_code=403, detail="Access denied")

    # 1️⃣ Fetch patient record using user_id
    patient_query = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = patient_query.scalar_one_or_none()

    if not patient:
        print("❌ No patient entry found for user_id:", current_user.id)
        raise HTTPException(status_code=404, detail="Patient profile not found")

    patient_id = patient.id
    print("PATIENT ID USED FOR QUERY:", patient_id)

    # 2️⃣ Fetch Lab Orders + Results
    query = await db.execute(
        select(LabOrder, LabResult)
        .join(LabResult, LabResult.lab_order_id == LabOrder.id, isouter=True)
        .where(LabOrder.patient_id == patient_id)
    )

    rows = query.all()
    print("ROWS RETURNED:", len(rows))
    print("===== PATIENT RESULTS DEBUG END =====\n")

    # 3️⃣ Build response
    response = [
        {
            "lab_order_id": order.id,
            "test_name": order.test_name,
            "status": order.status,
            "result_value": result.result_value if result else None,
            "pdf_url": result.pdf_url if result else None,
            "notes": result.notes if result else None
        }
        for order, result in rows
    ]

    return response

# ------------------------------------------------------------
# 7️⃣ Doctor: Get Lab Results for My Patients

@router.get("/doctor-results")
async def get_doctor_lab_results(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Access denied")

    # 🔥 Step 1: Get doctor record from doctor table
    doctor_query = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_query.scalar_one_or_none()

    print("DOCTOR TABLE RECORD:", doctor)

    if not doctor:
        print("❌ Doctor not found for user_id:", current_user.id)
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    doctor_id = doctor.id

    # 🔥 Step 2: Fetch lab results
    query = await db.execute(
        select(LabOrder, LabResult, Patient)
        .join(LabResult, LabResult.lab_order_id == LabOrder.id, isouter=True)
        .join(Patient, Patient.id == LabOrder.patient_id)
        .where(LabOrder.doctor_id == doctor_id)
    )

    rows = query.all()


    # 🔥 Step 3: Prepare response
    response = [
        {
            "patient_name": patient.first_name + " " + patient.last_name,
            "patient_id": patient.id,
            "lab_order_id": order.id,
            "test_name": order.test_name,
            "status": order.status,
            "result_value": result.result_value if result else None,
            "pdf_url": result.pdf_url if result else None
        }
        for order, result, patient in rows
    ]

    return response

# ------------------------------------------------------------
# 8️⃣ Hospital: Get Lab Results for All Patients in My Hospital


@router.get("/hospital-results")
async def get_hospital_lab_results(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Access denied")

    hospital_id = current_user.hospital_id

    query = await db.execute(
        select(LabOrder, LabResult, Patient, Doctor)
        .join(LabResult, LabResult.lab_order_id == LabOrder.id, isouter=True)
        .join(Patient, Patient.id == LabOrder.patient_id)
        .join(Doctor, Doctor.id == LabOrder.doctor_id)
        .where(Doctor.hospital_id == hospital_id)
    )

    rows = query.all()

    response = [
        {
            "patient_name": patient.first_name + " " + patient.last_name,
            "doctor_name": doctor.first_name + " " + doctor.last_name,
            "test_name": order.test_name,
            "status": order.status,
            "result_value": result.result_value if result else None,
            "pdf_url": result.pdf_url if result else None
        }
        for order, result, patient, doctor in rows
    ]

    return response
