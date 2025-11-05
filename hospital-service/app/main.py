from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas, crud, utils
from app.database import get_db
from app.auth import get_current_user

app = FastAPI()


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


@app.post("/hospitals/signup", response_model=schemas.SignupResponse)
async def hospital_signup(
    data: schemas.HospitalSignupRequest,
    db: AsyncSession = Depends(get_db)
):
    # ✅ Step 1: Create User
    user = await crud.create_user(
        db=db,
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role=data.role
    )

    # ✅ Step 2: Create Hospital
    hospital_dict = data.hospital.dict()
    hospital = await crud.create_hospital_record(db, hospital_dict)

    # ✅ Step 3: Link User → Hospital
    user.hospital_id = hospital.id
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # ✅ Step 4: Return structured response
    return schemas.SignupResponse(
        user=user,
        hospital=hospital
    )



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


@app.post("/doctors", response_model=schemas.DoctorOut)
async def create_doctor(
    doctor_in: schemas.DoctorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):
    # ✅ Ensure logged-in user is a hospital
    if current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Only hospital can create doctors")

    # ✅ Build updated payload
    doctor_data = doctor_in.dict()
    doctor_data["hospital_id"] = current_user.hospital_id

    # ✅ Save in DB
    doctor = await crud.create_doctor(db, doctor_data)
    return doctor


@app.post("/patients", response_model=schemas.PatientOut)
async def create_patient(
    patient_in: schemas.PatientCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ("hospital", "admin", "doctor"):
        raise HTTPException(status_code=403, detail="Not permitted")

    return await crud.create_patient(db, patient_in)


# ✅ Health
@app.get("/health")
async def health():
    return {"status": "ok"}
