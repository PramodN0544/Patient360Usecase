from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from app import models, utils
from uuid import UUID


# # ✅ Create Hospital
# async def create_hospital(db: AsyncSession, hospital_in):
#     hospital = models.Hospital(**hospital_in.dict())
#     db.add(hospital)
#     await db.commit()
#     await db.refresh(hospital)
#     return hospital


# ✅ Link User to Hospital (After Signup)
async def link_user_hospital(db: AsyncSession, user, hospital):
    # If you want to store hospital.id inside user:
    user.hospital_id = hospital.id if hasattr(user, "hospital_id") else None

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return hospital


# ✅ Get Hospital
async def get_hospital(db: AsyncSession, hospital_id: UUID):
    query = select(models.Hospital).where(models.Hospital.id == hospital_id)
    result = await db.execute(query)
    return result.scalars().first()


# ✅ Create Doctor (Correct)
async def create_doctor(db: AsyncSession, data: dict):
    # Prevent inserting duplicate NPI numbers — surface a clear 409 Conflict
    npi = data.get("npi_number")
    if npi:
        q = select(models.Doctor).where(models.Doctor.npi_number == npi)
        res = await db.execute(q)
        if res.scalars().first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Doctor with this NPI already exists")

    doctor = models.Doctor(**data)
    db.add(doctor)
    try:
        await db.commit()
    except IntegrityError as e:
        # In case of a race or other constraint violation, map to a sane HTTP error
        await db.rollback()
        # If it's a unique constraint on npi_number, return a conflict
        if "npi_number" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Doctor with this NPI already exists")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create doctor")

    await db.refresh(doctor)
    return doctor



# ✅ Create Patient
async def create_patient(db: AsyncSession, data):
    patient = models.Patient(**data.dict())
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return patient


# ✅ Create User
# ✅ Create User (CORRECTED)
async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    role: str
):
    # ✅ Correct hashing
    hashed_pwd = utils.get_password_hash(password)

    new_user = models.User(
        email=email,
        hashed_password=hashed_pwd,
        full_name=full_name,
        role=role,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


async def create_hospital_record(db: AsyncSession, hospital_data):
    new_hospital = models.Hospital(**hospital_data)

    db.add(new_hospital)
    await db.commit()
    await db.refresh(new_hospital)
    return new_hospital

# ✅ Authenticate User (Login)
async def authenticate_user(db: AsyncSession, email: str, password: str):
    query = select(models.User).where(models.User.email == email)
    result = await db.execute(query)
    user = result.scalars().first()

    if not user:
        return None

    if not utils.verify_password(password, user.hashed_password):
        return None

    return user
