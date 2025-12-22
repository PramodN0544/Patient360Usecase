from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.staticfiles import StaticFiles
from app import schemas, crud, utils
from app.cors import apply_cors, get_frontend_origins
from app.scheduled_tasks import start_scheduler
from app.database import get_db, engine, Base
from app.auth import get_current_user
from app.routers import appointment, searchPatientInHospital
from app.routers import reset_password
from app.routers import notifications
from app.routers import medications
from app.routers import encounters
from app.routers import assignments
from app.routers import insurance_master 
from app.routers import pharmacy_insurance_master
from app.routers import file_upload
from app.routers import lab_routes
from app.routers import hospitals
from app.routers import care_plan
from app.routers import chat_api
from app.routers import icd_codes
from fastapi import WebSocket, WebSocketDisconnect, Query
from app.web_socket import chat_manager, get_user_from_token, check_chat_access, process_websocket_message
from app.web_socket import socket_app, sio
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import tasks
from app.routers import admin_users
from app.routers import appointment,vitals,file_upload,assignments,insurance_master,pharmacy_insurance_master,doctors, tasks
from app.schemas import PatientUpdate
from app import crud as patient_crud
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app import models
from app.auth import router as auth_router
from .utils import create_access_token
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.routers.appointment_reminder import send_appointment_reminders
from app.routers.medication_reminder import send_medication_reminders
from app.database import AsyncSessionLocal as async_session

app = FastAPI(title="CareIQ Patient 360 API")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/socket.io", socket_app, name="socketio")

apply_cors(app)
app.include_router(medications.router)
app.include_router(care_plan.router)
app.include_router(notifications.router)
app.include_router(vitals.router)
app.include_router(file_upload.router)
app.include_router(assignments.router)
app.include_router(insurance_master.router)
app.include_router(pharmacy_insurance_master.router)
app.include_router(doctors.router)
app.include_router(lab_routes.router)
app.include_router(appointment.router)
app.include_router(reset_password.router)
app.include_router(searchPatientInHospital.router)
app.include_router(encounters.router)
app.include_router(auth_router)
app.include_router(hospitals.router)
app.include_router(chat_api.router)
app.include_router(tasks.router)
app.include_router(admin_users.router)
app.include_router(icd_codes.router)

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("interval", minutes=30)
async def reminder_job():
    async with async_session() as db:
        await send_appointment_reminders(db)
        await send_medication_reminders(db)

# SINGLE STARTUP EVENT - Combined all startup logic here
@app.on_event("startup")
async def startup():
    print("🚀 Starting up CareIQ Patient 360 API...")
    
    # 1. Create tables if they don't exist
    print("📊 Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created/verified")
    
    # 2. Sync schema (add missing columns to existing tables)
    print("🔄 Syncing database schema...")
    try:
        from app.database import sync_schema
        await sync_schema()  # This is where sync_schema() is called
        print("✅ Database schema synchronized successfully")
    except ImportError as e:
        print(f"⚠️ Cannot import sync_schema: {e}")
    except Exception as e:
        print(f"⚠️ Schema sync warning (non-critical): {e}")
        # Continue even if sync fails
    
    # 3. Start schedulers
    print("⏰ Starting reminder scheduler...")
    scheduler.start()
    print("✅ Reminder scheduler started")
    
    # 4. Start patient age update scheduler
    print("⏰ Starting patient age update scheduler...")
    patient_age_scheduler = start_scheduler()
    print("✅ Patient age update scheduler started")
    
    print("🎉 CareIQ Patient 360 API is ready!")

# STOP SCHEDULER ON SHUTDOWN
@app.on_event("shutdown")
async def shutdown_scheduler():
    scheduler.shutdown()
    print("Scheduler stopped.")

# Add the WebSocket endpoint
@app.websocket("/api/ws/chat/{chat_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    chat_id: int,
    token: str = Query(None)
):
    if not token:
        await websocket.close(code=1008)
        return
    
    try:
        user = await get_user_from_token(token)
        if not user:
            await websocket.close(code=1008)
            return
        
        has_access = await check_chat_access(chat_id, user.id)
        if not has_access:
            await websocket.close(code=1008)
            return
        
        try:
            await websocket.accept()
            await chat_manager.connect(websocket, chat_id, user.id)
        except Exception as e:
            print(f"Error accepting WebSocket connection: {e}")
            await websocket.close(code=1011)
            return
        
        try:
            while True:
                data = await websocket.receive_json()
                await process_websocket_message(data, chat_id, user.id)
        except WebSocketDisconnect:
            await chat_manager.disconnect(chat_id, user.id)
        except Exception as e:
            print(f"Error in WebSocket message handling: {e}")
            await chat_manager.disconnect(chat_id, user.id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.close(code=1011)
        except:
            pass

ACCESS_TOKEN_EXPIRE_MINUTES = 60

@app.post("/auth/login")
async def login_json(credentials: schemas.LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await crud.authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token_data = {
        "sub": user.email,
        "email": user.email,
        "user_id": user.id,
        "role": user.role,
        "hospital_id": user.hospital_id
    }

    access_token = create_access_token(token_data)

    return {
        "access_token": access_token,
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "hospital_id": user.hospital_id
        }
    }

@app.post("/hospitals/signup", response_model=schemas.SignupResponse)
async def hospital_signup(
    data: schemas.HospitalSignupRequest,
    db: AsyncSession = Depends(get_db)
):
    user = await crud.create_user(
        db=db,
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role="hospital"
    )

    hospital = await crud.create_hospital_record(
        db=db,
        hospital_data=data.hospital.dict(),
    )

    user.hospital_id = hospital.id
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(hospital)
    return schemas.SignupResponse(
    user={
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "hospital_id": str(user.hospital_id),
    },
    hospital=hospital 
)

@app.get("/hospitals/profile", response_model=schemas.HospitalOut)
async def get_hospital_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the hospital profile for the current hospital user."""
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Only hospital users can access this endpoint")
    
    if not current_user.hospital_id:
        raise HTTPException(status_code=404, detail="Hospital not found")
    
    result = await db.execute(
        select(models.Hospital).where(models.Hospital.id == current_user.hospital_id)
    )
    hospital = result.scalars().first()
    
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    
    return hospital

@app.post("/doctors")
async def create_doctor(
    doctor_in: schemas.DoctorCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Only hospital can create doctors")
    doctor, password, email = await crud.create_doctor(
        db=db,
        data=doctor_in.dict(),
        hospital_id=current_user.hospital_id
    )

    utils.send_email(
        email,
        subject="Your Doctor Account Credentials",
        message=f"""
        Welcome Doctor,
        Login Email: {email}
        Temporary Password: {password}

        Please login and change your password.

        Regards,
        CareIQ
        """
    )
    return {
        "doctor_id": str(doctor.id),
        "message": "Doctor created and credentials emailed successfully"
    }


@app.post("/patients")
async def create_patient(
    patient_in: schemas.PatientCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("hospital", "admin", "doctor"):
        raise HTTPException(status_code=403, detail="Not permitted")
    
    patient, password, email, public_id = await crud.create_patient(db, patient_in)

    utils.send_email(
        email,
        subject="Your Patient Portal Login",
        message=f"""
        Welcome,
        Login Email: {email}
        Temporary Password: {password}

        You can now access your patient dashboard and update your password.

        Regards,
        CareIQ
        """
    )

    return {
        "patient_id": str(patient.id),
        "message": "Patient created and login credentials sent via email",
        "public_id": public_id
    }

@app.put("/patient/{public_id}")
async def update_patient(
    public_id: str,
    patient_in: schemas.PatientUpdate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("hospital", "admin", "doctor"):
        raise HTTPException(status_code=403, detail="Not permitted")

    patient = await patient_crud.update_patient_by_public_id(db, public_id, patient_in)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return {
      "message": "Patient updated successfully",
      "public_id": patient.public_id
    }

@app.post("/{public_id}/allergies")
async def add_allergy(
    public_id: str,
    allergy_in: schemas.AllergyCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("patient", "hospital", "admin", "doctor"):
        raise HTTPException(status_code=403, detail="Not permitted")

    patient = await patient_crud.get_patient_by_public_id(db, public_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    allergy = await patient_crud.add_allergy_for_patient(db, patient, allergy_in)

    return {
        "message": "Allergy added successfully",
        "allergy_id": allergy.id,
    }

# ---------- ADD MEDICAL INSURANCE (append-only) ----------
@app.post("/{public_id}/insurance")
async def add_medical_insurance(
    public_id: str,
    ins_in: schemas.PatientInsuranceCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("patient", "hospital", "admin"):
        raise HTTPException(status_code=403, detail="Not permitted")

    patient = await patient_crud.get_patient_by_public_id(db, public_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    new_ins = await patient_crud.add_patient_insurance(db, patient, ins_in)
    if not new_ins:
        raise HTTPException(status_code=404, detail="Insurance master not found")

    return {
        "message": "Patient medical insurance added",
        "patient_id": patient.public_id,
        "patient_insurance_id": new_ins.id
    }


# ---------- ADD PHARMACY INSURANCE (append-only) ----------
@app.post("/{public_id}/pharmacy-insurance")
async def add_pharmacy_insurance(
    public_id: str,
    ins_in: schemas.PatientPharmacyInsuranceCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("patient", "hospital", "admin"):
        raise HTTPException(status_code=403, detail="Not permitted")

    patient = await patient_crud.get_patient_by_public_id(db, public_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    new_ins = await patient_crud.add_patient_pharmacy_insurance(db, patient, ins_in)
    if not new_ins:
        raise HTTPException(status_code=404, detail="Pharmacy insurance master not found")

    return {
        "message": "Patient pharmacy insurance added",
        "patient_id": patient.public_id,
        "patient_pharmacy_insurance_id": new_ins.id
    }

@app.get("/users/me")
async def read_users_me(current_user=Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "hospital_id": str(current_user.hospital_id) if current_user.hospital_id else None
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}

@app.get("/config")
async def get_config():
    origins = get_frontend_origins()
    return {"cors_origins": origins}

@app.post("/admin/update-patient-ages")
async def update_patient_ages(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Admin endpoint to manually trigger the patient age update process.
    This is useful for testing or for immediate updates when needed.
    """
    if current_user.role not in ["admin", "hospital"]:
        raise HTTPException(status_code=403, detail="Only admins and hospital users can perform this action")
    
    from app.utils import update_patient_ages
    updated_count = await update_patient_ages(db)
    
    return {
        "message": "Patient ages updated successfully",
        "updated_count": updated_count
    }

@app.get("/")
def root():
    return {"message": "CareIQ Patient 360 API is running 🚀"}

# Get Doctor Profile — for doctor login
@app.get("/doctor", response_model=schemas.DoctorOut)
async def get_my_doctor_profile(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can access this")

    doctor = await crud.get_doctor_by_user_id(db, current_user.id)

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    return doctor

@app.get("/patient", response_model=schemas.PatientOut)
async def get_my_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(status_code=403, detail="Not permitted")

    result = await db.execute(
        select(models.Patient)
        .options(
            selectinload(models.Patient.patient_insurances),
            selectinload(models.Patient.pharmacy_insurances),
            selectinload(models.Patient.allergies),
            selectinload(models.Patient.consents),
        )
        .where(models.Patient.user_id == current_user.id)
    )

    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient record not found")

    return patient

# Admin Part – Get all patients
@app.get("/patients", response_model=list[schemas.PatientOut])
async def get_patients(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Patient)
        .options(
            selectinload(models.Patient.allergies),
            selectinload(models.Patient.consents),
            selectinload(models.Patient.patient_insurances),
            selectinload(models.Patient.pharmacy_insurances)
        )
    )
    patients = result.scalars().all()
    return patients

@app.post("/auth/logout")
async def logout(current_user=Depends(get_current_user)):
    return {"message": "Logged out successfully"}

# Add custom exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation error",
            "errors": exc.errors(),
            "body": exc.body
        },
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    print(f"HTTP exception: {exc.detail} (status_code={exc.status_code})")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )