from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.staticfiles import StaticFiles
from app import schemas, crud, utils
from app.cors import apply_cors, get_frontend_origins
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
from app.routers import chat_api
from fastapi import WebSocket, WebSocketDisconnect, Query
from app.web_socket import chat_manager, get_user_from_token, check_chat_access, process_websocket_message
from app.web_socket import socket_app, sio
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import tasks
from app.routers import admin_users

# SQLAlchemy utilities and models used in route handlers
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
app.include_router(hospitals.router)
app.include_router(chat_api.router)
app.include_router(tasks.router)
app.include_router(admin_users.router)

# Auto-create tables

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database schema synchronized successfully")

# Add the WebSocket endpoint
@app.websocket("/api/ws/chat/{chat_id}")  # Changed path to avoid conflict
async def websocket_endpoint(
    websocket: WebSocket,
    chat_id: int,
    token: str = Query(None)
):
    if not token:
        await websocket.close(code=1008)  # Policy violation
        return
    
    try:
        # Validate the token
        user = await get_user_from_token(token)
        if not user:
            await websocket.close(code=1008)
            return
        
        # Check if user has access to this chat
        has_access = await check_chat_access(chat_id, user.id)
        if not has_access:
            await websocket.close(code=1008)
            return
        
        # Accept the connection - this was missing proper error handling
        try:
            await websocket.accept()  # Ensure this happens before any other WebSocket operations
            await chat_manager.connect(websocket, chat_id, user.id)
        except Exception as e:
            print(f"Error accepting WebSocket connection: {e}")
            await websocket.close(code=1011)
            return
        
        try:
            # Keep the connection open and handle messages
            while True:
                data = await websocket.receive_json()
                await process_websocket_message(data, chat_id, user.id)
        except WebSocketDisconnect:
            # Handle disconnection
            await chat_manager.disconnect(chat_id, user.id)
        except Exception as e:
            print(f"Error in WebSocket message handling: {e}")
            await chat_manager.disconnect(chat_id, user.id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.close(code=1011)  # Internal error
        except:
            pass  # Already closed
        
ACCESS_TOKEN_EXPIRE_MINUTES = 60

@app.post("/auth/login")
async def login_json(credentials: schemas.LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await crud.authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    # Build JWT payload
    token_data = {
        "sub": user.email,
        "email": user.email,
        "user_id": user.id,
        "role": user.role,
        "hospital_id": user.hospital_id
    }

    # Create access token
    access_token = create_access_token(token_data)

    # RETURN FULL PROFILE DIRECTLY
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

# CREATE PATIENT (User + Patient)
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
        "public_id": public_id  # <-- include public patient ID here
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
    return {"status": "ok"}

@app.get("/config")
async def get_config():
    """Return runtime configuration useful for frontend diagnostics."""
    origins = get_frontend_origins()
    return {"cors_origins": origins}

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

# For patient login — only their own data
@app.get("/patient", response_model=schemas.PatientOut)
async def get_my_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(status_code=403, detail="Not permitted")

    result = await db.execute(
        select(models.Patient)
        .where(models.Patient.user_id == current_user.id)
        .options(
            # BASIC DETAILS
            selectinload(models.Patient.allergies),
            selectinload(models.Patient.consents),
            selectinload(models.Patient.patient_insurances)
    .selectinload(models.PatientInsurance.insurance_master),

            selectinload(models.Patient.pharmacy_insurances),

            # ADD THESE TO PREVENT LAZY LOAD ERRORS
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.vitals),
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.medications),
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.doctor),
            selectinload(models.Patient.encounters)
                .selectinload(models.Encounter.hospital),
        )
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
    """
    Stateless logout – the frontend must delete the token.
    """
    return {"message": "Logged out successfully"}

# Add custom exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """
    Handle validation errors with more detailed information
    """
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
    """
    Handle HTTP exceptions with more information
    """
    print(f"HTTP exception: {exc.detail} (status_code={exc.status_code})")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
# Create scheduler (global)
scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("interval", minutes=30)
async def reminder_job():
    async with async_session() as db:
        await send_appointment_reminders(db)
        await send_medication_reminders(db)

def start_scheduler():
    scheduler.start()
    

# REGISTER REMINDER JOB (runs every 30 min)
@scheduler.scheduled_job("interval", minutes=1)
async def reminder_job():
    async with async_session() as db:
        await send_appointment_reminders(db)
        await send_medication_reminders(db)

# START SCHEDULER WHEN FASTAPI START
@app.on_event("startup")
async def start_scheduler():
    scheduler.start()
    print("Reminder scheduler started.")

# STOP SCHEDULER ON SHUTDOWN
@app.on_event("shutdown")
async def shutdown_scheduler():
    scheduler.shutdown()
    print("Scheduler stopped.")
