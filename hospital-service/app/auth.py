from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import JWTError, jwt

from .database import get_db
from . import models
from .utils import JWT_SECRET, JWT_ALGORITHM

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ---------------------------------------------------------
# ✅ EXISTING LOGIC — DO NOT TOUCH (You asked to keep same)
# ---------------------------------------------------------
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        email = payload.get("sub")
        role = payload.get("role")
        hospital_id = payload.get("hospital_id")
        user_id = payload.get("user_id")

        if email is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    result = await db.execute(
        select(models.User).where(models.User.email == email)
    )
    user = result.scalars().first()

    if not user:
        raise credentials_exception

    # Attach JWT fields to user object
    user.role = role
    user.hospital_id = hospital_id
    user.token_user_id = user_id

    return user



# ---------------------------------------------------------
# ✅ NEW LOGIC — validate-token API (FastAPI version of Flask code)
# ---------------------------------------------------------
@router.get("/api/auth/validate-token")
async def validate_token(request: Request, db: AsyncSession = Depends(get_db)):

    # Step 1: Read Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication token is missing")

    # Step 2: Extract token
    if auth_header.startswith("Bearer "):
        token = auth_header.split("Bearer ")[1].strip()
    else:
        token = auth_header.strip()

    try:
        # Step 3: Decode JWT
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        email_or_id = payload.get("sub")

        if not email_or_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        # Step 4: Find user in DB (email OR ID)
        if isinstance(email_or_id, str) and "@" in email_or_id:
            query = select(models.User).where(models.User.email == email_or_id)
        else:
            query = select(models.User).where(models.User.id == int(email_or_id))

        result = await db.execute(query)
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # Step 5: Return user details
        return {
            "id": user.id,
            "email": user.email,
            "role": payload.get("role"),
            "hospital_id": payload.get("hospital_id"),
            "user_id": payload.get("user_id"),
            "full_name": user.full_name,
            "is_active": user.is_active,
        }

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        print("Token validation error:", e)
        raise HTTPException(status_code=500, detail="Internal server error")
