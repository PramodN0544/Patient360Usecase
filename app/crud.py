from datetime import datetime
from uuid import UUID
from sqlalchemy import select, insert, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from sqlalchemy.orm import aliased
from app import utils, models
from app.models import User, Patient, password_reset_otps_table, PasswordResetToken
from app import models, schemas, utils
from app.models import password_reset_otps_table  
from app.schemas import PatientCreate

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Fetch a user by email."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()

async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    role: str
) -> User:
    """Create a new user."""
    existing = await get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_pwd = utils.get_password_hash(password)
    new_user = User(email=email, hashed_password=hashed_pwd, full_name=full_name, role=role)

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    """Authenticate user credentials."""
    user = await get_user_by_email(db, email)
    if not user or not utils.verify_password(password, user.hashed_password):
        return None
    return user

async def update_user_password(db: AsyncSession, user: User, new_password: str) -> User:
    """Update user password."""
    user.hashed_password = utils.get_password_hash(new_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def create_hospital_record(db: AsyncSession, hospital_data: dict):
    new_hospital = models.Hospital(**hospital_data)
    db.add(new_hospital)
    await db.commit()
    await db.refresh(new_hospital)
    return new_hospital

async def create_doctor(db: AsyncSession, data: dict, hospital_id: UUID):
    """Create doctor and associated user account."""
    default_password = utils.generate_default_password()
    user = await create_user(
        db=db,
        email=data["email"],
        password=default_password,
        full_name=f"{data.get('first_name', '')} {data.get('last_name', '')}",
        role="doctor"
    )

    data["user_id"] = user.id
    data["hospital_id"] = hospital_id

    doctor = models.Doctor(**data)
    db.add(doctor)

    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        if "npi_number" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Doctor with this NPI already exists")
        raise HTTPException(status_code=400, detail="Could not create doctor")

    await db.refresh(doctor)
    return doctor, default_password, user.email

async def create_patient(db: AsyncSession, data: schemas.PatientCreate):

    # ----------------------------
    # Create user
    # ----------------------------
    default_password = utils.generate_default_password()
    user = await create_user(
        db=db,
        email=data.email,
        password=default_password,
        full_name=f"{data.first_name} {data.last_name}",
        role="patient"
    )

    # ----------------------------
    # Determine insurance status
    # ----------------------------
    has_medical = bool(data.patient_insurances)
    has_pharmacy = bool(data.pharmacy_insurances)

    insurance_status = "Insured" if (has_medical or has_pharmacy) else "Self-Pay"

    # ----------------------------
    # Create patient
    # ----------------------------
    patient_dict = data.dict(
        exclude={
            "allergies",
            "consents",
            "patient_insurances",
            "pharmacy_insurances"
        }
    )

    patient_dict["user_id"] = user.id
    patient_dict["insurance_status"] = insurance_status

    patient = models.Patient(**patient_dict)
    db.add(patient)
    await db.flush()   # 🔑 get patient.id

    # ----------------------------
    # Allergies
    # ----------------------------
    for allergy in data.allergies or []:
        db.add(models.Allergy(**allergy.dict(), patient_id=patient.id))

    # ----------------------------
    # Consents
    # ----------------------------
    db.add(models.PatientConsent(**data.consents.dict(), patient_id=patient.id))

    # ----------------------------
    # Medical Insurance
    # ----------------------------
    for insurance_data in data.patient_insurances or []:

        master = await db.get(models.InsuranceMaster, insurance_data.id)
        if not master:
            raise HTTPException(404, "Insurance master not found")

        db.add(models.PatientInsurance(
            patient_id=patient.id,
            insurance_id=master.id,
            provider_name=master.provider_name,
            plan_name=master.plan_name,
            plan_type=master.plan_type,
            coverage_percent=master.coverage_percent,
            policy_number=insurance_data.policy_number,
            group_number=insurance_data.group_number,
            subscriber_name=insurance_data.subscriber_name,
            subscriber_relationship=insurance_data.subscriber_relationship,
            subscriber_dob=insurance_data.subscriber_dob,
            payer_phone=insurance_data.payer_phone,
            effective_date=insurance_data.effective_date,
            expiry_date=insurance_data.expiry_date,
            insurance_type=insurance_data.insurance_type or "primary",
            benefits_verified=insurance_data.benefits_verified or False
        ))

    # ----------------------------
    # Pharmacy Insurance
    # ----------------------------
    for pharm_data in data.pharmacy_insurances or []:

        master = await db.get(models.PharmacyInsuranceMaster, pharm_data.id)
        if not master:
            raise HTTPException(404, "Pharmacy insurance master not found")

        db.add(models.PatientPharmacyInsurance(
            patient_id=patient.id,
            pharmacy_insurance_id=master.id,
            provider_name=master.provider_name,
            plan_name=master.plan_name,
            policy_number=pharm_data.policy_number,
            bin_number=pharm_data.bin_number,
            pcn_number=pharm_data.pcn_number,
            effective_date=pharm_data.effective_date,
            expiry_date=pharm_data.expiry_date,
            insurance_type=pharm_data.insurance_type or "primary",
            benefits_verified=pharm_data.benefits_verified or False,
            pharmacy_name=pharm_data.pharmacy_name,
            pharmacy_phone=pharm_data.pharmacy_phone,
            pharmacy_address=pharm_data.pharmacy_address,
            is_preferred=pharm_data.is_preferred
        ))

    # ----------------------------
    await db.commit()
    await db.refresh(patient)

    return patient, default_password, user.email, patient.public_id

async def get_patient_by_public_id(db: AsyncSession, public_id: str):
    result = await db.execute(
        select(models.Patient).where(models.Patient.public_id == public_id)
    )
    return result.scalars().first()


async def update_patient_by_public_id(
    db: AsyncSession,
    public_id: str,
    patient_in
):
    patient = await get_patient_by_public_id(db, public_id)
    
    if not patient:
        return None

    data = patient_in.dict(exclude_unset=True)

    ALLOWED_UPDATE_FIELDS = {
        # Contact
        "phone",
        "alternate_phone",
        "email",
        "preferred_contact",

        # Address
        "address",
        "city",
        "state",
        "zip_code",

        # Demographics
        "marital_status",
        "preferred_language",
        "race",
        "ethnicity",
        "interpreter_required",

        # PCP
        "pcp_name",
        "pcp_npi",
        "pcp_phone",

        # Physical
        "weight",
        "height",

        # Lifestyle
        "smoking_status",
        "alcohol_use",
        "diet",
        "exercise_frequency",

        # Caregiver
        "has_caregiver",
        "caregiver_name",
        "caregiver_relationship",
        "caregiver_phone",
        "caregiver_email",

        # Profile
        "photo_url",
    }
    # Only update allowed fields
    for field in ALLOWED_UPDATE_FIELDS:
        if field in data:
            setattr(patient, field, data[field])

    # Sync email with User table
    if "email" in data and patient.user_id:
        user = await db.get(models.User, patient.user_id)
        if user:
            user.email = data["email"]

    await db.commit()
    await db.refresh(patient)

    return patient

async def create_password_reset_token(db: AsyncSession, user_id: UUID, token: str, expires_at: datetime) -> PasswordResetToken:
    new_token = PasswordResetToken(user_id=user_id, token=token, expires_at=expires_at)
    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)
    return new_token


async def get_password_reset_record(db: AsyncSession, token: str) -> PasswordResetToken | None:
    result = await db.execute(select(PasswordResetToken).where(PasswordResetToken.token == token))
    return result.scalars().first()

async def mark_reset_token_used(db: AsyncSession, token: str):
    stmt = update(PasswordResetToken).where(PasswordResetToken.token == token).values(used=True)
    await db.execute(stmt)
    await db.commit()

async def create_password_reset_otp(db: AsyncSession, user_id: UUID, otp: str, expires_at: datetime):
    stmt = insert(password_reset_otps_table).values(
        user_id=user_id,
        otp=otp,
        expires_at=expires_at,
        used=False,
        created_at=datetime.utcnow()
    )
    await db.execute(stmt)
    await db.commit()


async def get_password_reset_otp(db: AsyncSession, email: str, otp: str):
    user_alias = aliased(User)
    query = (
        select(password_reset_otps_table)
        .join(user_alias, user_alias.id == password_reset_otps_table.c.user_id)
        .where(user_alias.email == email)
        .where(password_reset_otps_table.c.otp == otp)
    )
    result = await db.execute(query)
    record = result.mappings().first() 
    return record

async def mark_otp_used(db: AsyncSession, email: str, otp: str):
    user_alias = aliased(User)
    result = await db.execute(
        select(user_alias.id).where(user_alias.email == email)
    )
    user_id = result.scalar()
    if not user_id:
        return  

    stmt = (
        update(password_reset_otps_table)
        .where(password_reset_otps_table.c.user_id == user_id)
        .where(password_reset_otps_table.c.otp == otp)
        .values(used=True)
    )
    await db.execute(stmt)
    await db.commit()

async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    """Fetch a user by their ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()

async def get_patient_by_user_id(db: AsyncSession, user_id: UUID):
    result = await db.execute(
        select(models.Patient).where(models.Patient.user_id == user_id)
    )
    return result.scalars().first()

async def get_doctor_by_user_id(db: AsyncSession, user_id: UUID):
    result = await db.execute(
        select(models.Doctor).where(models.Doctor.user_id == user_id)
    )
    return result.scalars().first()

async def get_hospital_by_id(db: AsyncSession, hospital_id: UUID):
    result = await db.execute(
        select(models.Hospital).where(models.Hospital.id == hospital_id)
    )
    return result.scalars().first()

async def get_patients_by_hospital(db: AsyncSession, hospital_id: str):
    """Get all patients for a specific hospital"""
    try:
        result = await db.execute(
            select(Patient)
            .join(User, Patient.user_id == User.id)
            .where(User.hospital_id == hospital_id)
        )
        patients = result.scalars().all()
        return patients
    except Exception as e:
        print(f"Error fetching patients for hospital {hospital_id}: {e}")
        raise

async def get_doctors_by_hospital(db: AsyncSession, hospital_id: str):
    """
    Get all doctors that belong to a specific hospital.
    """
    result = await db.execute(
        select(models.Doctor).where(models.Doctor.hospital_id == hospital_id)
    )
    doctors = result.scalars().all()
    return doctors
