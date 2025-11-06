from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from app import schemas, crud, utils
from app.cors import apply_cors, get_frontend_origins
from app.database import get_db, engine, Base
from app.auth import get_current_user

from app.routers import medications


# ✅ Import appointment router
from app.routers import appointment



app = FastAPI(title="CareIQ Patient 360 API")

app.include_router(medications.router)

# Configure CORS for frontend integration. Configure origins via
# FRONTEND_ORIGINS (comma-separated) or FRONTEND_URL environment variables.
apply_cors(app)

# ✅ Include the appointment routes
app.include_router(appointment.router)  # no need to repeat prefix; it's already defined inside appointment.py


# ✅ Create tables automatically on startup
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        # This ensures that ONLY missing tables (like Appointment) are created
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database schema synchronized successfully")


# ✅ LOGIN → JWT Token
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


# Optional JSON-based login for clients that send JSON instead of form data
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


# ✅ Signup
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
        role=data.role
    )

    hospital_dict = data.hospital.dict()
    hospital = await crud.create_hospital_record(db, hospital_dict)

    user.hospital_id = hospital.id
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Return plain serializable dicts to avoid pydantic v1/v2 orm_mode incompat
    user_out = {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "hospital_id": str(user.hospital_id) if user.hospital_id else None,
    }

    hospital_out = {
        "id": str(hospital.id),
        "name": hospital.name,
        "email": hospital.email,
        "phone": hospital.phone,
        "specialty": hospital.specialty,
        "city": hospital.city,
        "state": hospital.state,
        "license_number": hospital.license_number,
        "consultation_fee": float(hospital.consultation_fee) if hospital.consultation_fee is not None else None,
    }

    return {"user": user_out, "hospital": hospital_out}


# ✅ Create Hospital (Protected)
@app.post("/hospitals", response_model=schemas.HospitalOut)
async def create_hospital(
    hospital_in: schemas.HospitalBase,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("hospital", "admin"):
        raise HTTPException(status_code=403, detail="Not permitted")
    return await crud.create_hospital(db, hospital_in)


# ✅ Create Doctor
@app.post("/doctors", response_model=schemas.DoctorOut)
async def create_doctor(
    doctor_in: schemas.DoctorCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # current_user is provided by get_current_user (ORM User instance).
    # We avoid forcing a Pydantic validation of the dependency return value
    # here because that can raise conversion errors if fields are missing.
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Only hospital can create doctors")

    doctor_data = doctor_in.dict()
    doctor_data["hospital_id"] = current_user.hospital_id
    doctor = await crud.create_doctor(db, doctor_data)
    return doctor


# ✅ Create Patient
@app.post("/patients", response_model=schemas.PatientOut)
async def create_patient(
    patient_in: schemas.PatientCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("hospital", "admin", "doctor"):
        raise HTTPException(status_code=403, detail="Not permitted")
    return await crud.create_patient(db, patient_in)


# ✅ Health Check
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
