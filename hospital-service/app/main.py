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
from app.routers import appointment,vitals,file_upload,assignments,insurance_master,pharmacy_insurance_master,doctors, tasks

# SQLAlchemy utilities and models used in route handlers
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app import models
from app.auth import router as auth_router
from app.routers import patient_message_with_doctor,admin_users
from .utils import create_access_token

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.routers.appointment_reminder import send_appointment_reminders
from app.routers.medication_reminder import send_medication_reminders
from app.database import AsyncSessionLocal as async_session


app = FastAPI(title="CareIQ Patient 360 API")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
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
app.include_router(patient_message_with_doctor.router)
app.include_router(hospitals.router)
app.include_router(tasks.router)
app.include_router(admin_users.router)

# app.include_router(patients.router)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database schema synchronized successfully")


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
    # Step 1 – create user (role = hospital)
    user = await crud.create_user(
        db=db,
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role="hospital"
    )

    # Step 2 – create hospital (NO user_id)
    hospital = await crud.create_hospital_record(
        db=db,
        hospital_data=data.hospital.dict(),
        # user_id=user.id
    )

    # Step 3 – link user to hospital
    user.hospital_id = hospital.id
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(hospital)
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "hospital_id": str(user.hospital_id),
        },
        "hospital": {
            "id": str(hospital.id),
            "name": hospital.name,
            "email": hospital.email,
            "phone": hospital.phone,
            "specialty": hospital.specialty,
            "city": hospital.city,
            "state": hospital.state,
            "license_number": hospital.license_number,
            "consultation_fee": float(hospital.consultation_fee),
        }
    }

# CREATE DOCTOR (User + Doctor)
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

    # Email send (pseudo function — integrate your email library)
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

    # Unpack all 4 values returned from crud
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

@app.get("/users/me")
async def read_users_me(current_user=Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "hospital_id": str(current_user.hospital_id) if current_user.hospital_id else None
    }


# Health Check
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



# ----------------------------------------
# Create scheduler (global)
# ----------------------------------------

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("interval", minutes=30)
async def reminder_job():
    async with async_session() as db:
        await send_appointment_reminders(db)
        await send_medication_reminders(db)

def start_scheduler():
    scheduler.start()
    



# ----------------------------------------
# REGISTER REMINDER JOB (runs every 30 min)
# ----------------------------------------
@scheduler.scheduled_job("interval", minutes=1)
async def reminder_job():
    async with async_session() as db:
        await send_appointment_reminders(db)
        await send_medication_reminders(db)


# ----------------------------------------
# START SCHEDULER WHEN FASTAPI STARTS
# ----------------------------------------
@app.on_event("startup")
async def start_scheduler():
    scheduler.start()
    print("⏰ Reminder scheduler started.")


# ----------------------------------------
# (Optional) STOP SCHEDULER ON SHUTDOWN
# ----------------------------------------
@app.on_event("shutdown")
async def shutdown_scheduler():
    scheduler.shutdown()
    print("⏹ Scheduler stopped.")