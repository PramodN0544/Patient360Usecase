from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
import os
JWT_SECRET = os.getenv('JWT_SECRET')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '60'))


# Use bcrypt_sha256 to avoid bcrypt's 72-byte input limit; it pre-hashes
# long passwords with SHA-256 so callers don't need to manually truncate.
# Use PBKDF2-SHA256 to avoid external bcrypt dependency issues on some
# environments. It's secure and portable for this project.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def get_password_hash(password: str):
    # ✅ bcrypt max limit = 72 bytes
    if not password:
        raise ValueError("Password must not be empty")

    # bcrypt has a 72-byte input limit; truncate safely if user provides longer
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        pw_bytes = pw_bytes[:72]
        # decode back to string ignoring partial multi-byte char if any
        password = pw_bytes.decode("utf-8", errors="ignore")

    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: int = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES if expires_delta is None else expires_delta)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

