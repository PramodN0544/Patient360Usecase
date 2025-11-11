from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app import schemas, crud, utils
from app.cors import apply_cors, get_frontend_origins
from app.database import get_db, engine, Base
from app.auth import get_current_user
from app.routers import appointment, searchPatientInHospital
from app.routers import reset_password
from app.routers import notifications
from app.routers import medications
from app.routers import encounters

# ✅ Import appointment router
from app.routers import appointment



app = FastAPI(title="CareIQ Patient 360 API")

app.include_router(medications.router)
app.include_router(notifications.router)


apply_cors(app)

# Include the appointment routes
app.include_router(appointment.router)  # no need to repeat prefix; it's already defined inside appointment.py

app.include_router(reset_password.router)

app.include_router(searchPatientInHospital.router)
app.include_router(encounters.router)
# Auto-create tables

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database schema synchronized successfully")


# LOGIN — JWT Token
@app.post("/auth/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    user = await crud.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    token = utils.create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}



@app.get("/users/me")
async def read_users_me(current_user=Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "hospital_id": str(current_user.hospital_id) if current_user.hospital_id else None
    }

# JSON Login (Optional)
@app.post("/auth/login", response_model=schemas.Token)
async def login_json(
    credentials: schemas.LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    user = await crud.authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    token = utils.create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


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

    patient, password, email = await crud.create_patient(db, patient_in)

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
        "message": "Patient created and login credentials sent via email"
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


@app.get("/doctors", response_model=schemas.DoctorOut)
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



@app.get("/hospitals/doctors", response_model=list[schemas.DoctorOut])
async def get_all_doctors(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Only hospital can view doctors")
    doctors = await crud.get_doctors_by_hospital(db, current_user.hospital_id)
    return doctors


@app.get("/patients", response_model=schemas.PatientOut)
async def get_my_profile(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "patient":
        raise HTTPException(status_code=403, detail="Only patients can access this endpoint")

    # Fetch patient linked to this user
    patient = await crud.get_patient_by_user_id(db, current_user.id)

    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    return patient


@app.get("/hospitals/patients", response_model=list[schemas.PatientOut])
async def get_all_patients(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("hospital", "admin"):
        raise HTTPException(status_code=403, detail="Not permitted")
    patients = await crud.get_patients_by_hospital(db, current_user.hospital_id)
    return patients


@app.get("/hospitals", response_model=schemas.HospitalOut)
async def get_my_hospital_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Only hospitals can access this")

    hospital = await crud.get_hospital_by_id(db, current_user.hospital_id)

    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital profile not found")

    return hospital


