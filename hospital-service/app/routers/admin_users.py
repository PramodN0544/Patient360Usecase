from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Hospital, Doctor, Patient
from app.schemas import AdminUserCreate, AdminUserUpdate, AdminUserOut
from app.utils import get_password_hash

router = APIRouter(prefix="/admin/users", tags=["Admin - Users"])


# ---------------------------
# Helper
# ---------------------------
def require_admin(user):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


# ---------------------------
# CREATE USER
# ---------------------------
@router.post("/", response_model=AdminUserOut)
async def create_user(
    user_in: AdminUserCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    require_admin(current_user)

    # Check email exists
    existing = await db.execute(select(User).where(User.email == user_in.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already exists")

    # Doctor must be linked to hospital
    if user_in.role == "doctor" and not user_in.hospital_id:
        raise HTTPException(400, "Doctor must be linked to a hospital")

    hashed = get_password_hash(user_in.password)

    # Create main User
    user = User(
        email=user_in.email,
        hashed_password=hashed,
        full_name=user_in.full_name,
        role=user_in.role,
        hospital_id=user_in.hospital_id,
        is_active=True
    )

    db.add(user)
    await db.flush()  # ✅ get user.id before related inserts

    # ---------------------------
    # Role based table inserts
    # ---------------------------
    if user_in.role == "hospital":
        hospital = Hospital(
            name=user_in.full_name,
            email=user_in.email,
            phone="9999999999",
            license_number=f"LIC-{user.id}",
            registration_certificate="default.pdf",
            status="active"
        )
        db.add(hospital)

    elif user_in.role == "doctor":
        doctor = Doctor(
            name=user_in.full_name,
            email=user_in.email,
            hospital_id=user_in.hospital_id
        )
        db.add(doctor)

    elif user_in.role == "patient":
        patient = Patient(
            name=user_in.full_name,
            email=user_in.email
        )
        db.add(patient)

    await db.commit()
    await db.refresh(user)

    return user


# ---------------------------
# LIST USERS
# ---------------------------
@router.get("/", response_model=list[AdminUserOut])
async def list_users(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    require_admin(current_user)

    result = await db.execute(select(User))
    return result.scalars().all()


# ---------------------------
# UPDATE USER
# ---------------------------
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

    # Cannot change own admin role
    if user.id == current_user.id and user_in.role and user_in.role != "admin":
        raise HTTPException(400, "You cannot change your own admin role")

    # Doctor validation
    if user_in.role == "doctor" and not user_in.hospital_id:
        raise HTTPException(400, "Doctor must be linked to a hospital")

    # Update fields dynamically
    for key, value in user_in.dict(exclude_unset=True).items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)

    return user


# ---------------------------
# DEACTIVATE USER
# ---------------------------
@router.delete("/{user_id}")
async def deactivate_user(
    user_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    require_admin(current_user)

    if current_user.id == user_id:
        raise HTTPException(400, "You cannot deactivate yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "User not found")

    user.is_active = False
    await db.commit()

    return {"message": "User deactivated successfully"}
