from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update as sqlalchemy_update
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Hospital, Doctor, Patient
from app.schemas import AdminUserCreate, AdminUserUpdate, AdminUserOut
from app.utils import get_password_hash
from datetime import datetime

router = APIRouter(prefix="/admin/users", tags=["Admin - Users"])

# Helper
def require_admin(user):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


# CREATE USER
@router.post("/", response_model=AdminUserOut)
async def create_user(
    user_in: AdminUserCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    require_admin(current_user)

    # 1. Check if email already exists
    existing = await db.execute(select(User).where(User.email == user_in.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already exists")

    # 2. Doctor must have hospital
    if user_in.role == "doctor" and not user_in.hospital_id:
        raise HTTPException(400, "Doctor must be linked to a hospital")

    # 3. Hash password
    hashed = get_password_hash(user_in.password)

    # 4. Create user
    user = User(
        email=user_in.email,
        hashed_password=hashed,
        full_name=user_in.full_name,
        role=user_in.role,
        hospital_id=user_in.hospital_id,
        is_active=True
    )
    db.add(user)
    await db.flush()  # get user.id

    # 5. Split name safely
    name_parts = (user_in.full_name or "").strip().split(" ", 1)
    first_name = name_parts[0] if len(name_parts) > 0 else "User"
    last_name = name_parts[1] if len(name_parts) > 1 else "User"

    phone = user_in.phone or "9999999999"

    # HOSPITAL
    if user_in.role == "hospital":
        hospital = Hospital(
            name=user_in.full_name,
            email=user_in.email,
            phone=phone,
            license_number=f"LIC-{user.id}",
            registration_certificate="default.pdf",
            status="active"
        )
        db.add(hospital)

    # DOCTOR
    elif user_in.role == "doctor":
        doctor = Doctor(
            user_id=user.id,
            email=user_in.email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            hospital_id=user_in.hospital_id,
            license_number=f"LIC-{user.id}",
            license_document="default.pdf",
            is_active=True
        )
        db.add(doctor)

    # PATIENT
    elif user_in.role == "patient":
        patient = Patient(
            user_id=user.id,
            first_name=first_name,
            last_name=last_name,
            email=user_in.email,
            phone=phone,
            country="USA",
            weight=0,
            height=0,
            id_proof_document="default.pdf",
            is_active=True
        )
        db.add(patient)

    # 6. Commit
    await db.commit()
    await db.refresh(user)

    return user

# LIST USERS
@router.get("/", response_model=list[AdminUserOut])
async def list_users(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    require_admin(current_user)

    result = await db.execute(select(User))
    return result.scalars().all()


@router.put("/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int,
    user_in: AdminUserUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    require_admin(current_user)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "User not found")

    data = user_in.dict(exclude_unset=True)

    # Protect self admin role
    if "role" in data:
        if user.id == current_user.id and data["role"] != "admin":
            raise HTTPException(400, "You cannot change your own admin role")

    #  Doctor validation only when role changes
    if "role" in data and data["role"] == "doctor":
        if not data.get("hospital_id") and not user.hospital_id:
            raise HTTPException(400, "Doctor must be linked to hospital")

    # Apply updates
    for key, value in data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)

    return user

# ACTIVATE / DEACTIVATE USER
@router.put("/{user_id}/status")
async def toggle_user_status(
    user_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    require_admin(current_user)

    if current_user.id == user_id:
        raise HTTPException(400, "You cannot change your own status")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "User not found")

    now = datetime.utcnow()
    new_status = not user.is_active

    # Update USER
    user.is_active = new_status
    user.deactivated_at = None if new_status else now

    # Update PATIENT
    await db.execute(
        sqlalchemy_update(Patient)
        .where(Patient.user_id == user_id)
        .values(
            is_active=new_status,
            deactivated_at=None if new_status else now
        )
    )

    # Update DOCTOR
    await db.execute(
        sqlalchemy_update(Doctor)
        .where(Doctor.user_id == user_id)
        .values(
            is_active=new_status,
            deactivated_at=None if new_status else now
        )
    )

    # Update HOSPITAL
    if user.role == "hospital":
        await db.execute(
            sqlalchemy_update(Hospital)
            .where(Hospital.email == user.email)
            .values(
                status="active" if new_status else "inactive",
                deactivated_at=None if new_status else now
            )
        )

    await db.commit()

    return {
        "message": f"User {'activated' if new_status else 'deactivated'} successfully"
    }
