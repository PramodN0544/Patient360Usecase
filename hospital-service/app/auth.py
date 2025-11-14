from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .database import get_db
from . import models
from .utils import JWT_SECRET, JWT_ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

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

    # Attach JWT fields
    user.role = role
    user.hospital_id = hospital_id
    user.token_user_id = user_id

    return user
