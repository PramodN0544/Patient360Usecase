from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
import random
from app import crud, utils
from app.database import get_db

router = APIRouter(tags=["auth"])

# Schemas
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str

# Generate OTP for forgot password
@router.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = await crud.get_user_by_email(db, payload.email)
    if not user:
        # return generic response to avoid exposing email existence
        return {"detail": "If the email exists, an OTP has been sent."}

    # Generate 6-digit OTP
    otp = f"{random.randint(100000, 999999)}"
    expires_at = datetime.utcnow() + timedelta(minutes=5)  # OTP valid for 5 min

    # Store OTP in DB
    await crud.create_password_reset_otp(db, user.id, otp, expires_at)

    # Send OTP via email (for dev, print it)
    try:
        await utils.send_otp_email(user.email, otp, fullname=user.full_name)
    except Exception as e:
        print("Failed to send OTP:", e)

    return {"detail": "If the email exists, an OTP has been sent."}

# Reset password using OTP
@router.post("/auth/reset-password")
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    # Get OTP record from DB
    record = await crud.get_password_reset_otp(db, payload.email, payload.otp)
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")

    user_id = record["user_id"]
    expires_at = record["expires_at"]
    used = record["used"]

    if used:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP already used")
    if expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired")

    # Fetch user by ID
    user = await crud.get_user_by_id(db, user_id)

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found")

    # Update password
    await crud.update_user_password(db, user, payload.new_password)

    # Mark OTP as used
    await crud.mark_otp_used(db, payload.email, payload.otp)

    return {"detail": "Password has been reset successfully."}
