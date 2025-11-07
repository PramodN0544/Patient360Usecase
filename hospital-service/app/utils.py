from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import string

# =========================================================
# ✅ JWT CONFIG
# =========================================================
JWT_SECRET = os.getenv("JWT_SECRET", "SUPER_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# =========================================================
# ✅ Password Hashing (PBKDF2)
# =========================================================
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto"
)

def get_password_hash(password: str):
    if not password:
        raise ValueError("Password cannot be empty")

    # bcrypt/pbkdf2 safe handling
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        pw_bytes = pw_bytes[:72]
        password = pw_bytes.decode("utf-8", errors="ignore")

    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# =========================================================
# ✅ JWT Token Generator
# =========================================================
def create_access_token(data: dict, expires_delta: int = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(
        minutes=expires_delta or ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

# =========================================================
# ✅ Email Sending Utility
# =========================================================
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USERNAME)


def send_email(to_email: str, subject: str, message: str):
    """
    Sends email (for doctor/patient credentials)
    Requires ENV variables:
    - SMTP_HOST
    - SMTP_PORT
    - SMTP_USERNAME
    - SMTP_PASSWORD
    """

    print("✨ Email Sent ✨")
    print("To:", to_email)
    print("Subject:", subject)
    print("Message:", message)

    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("❌ Email not sent — missing SMTP credentials in environment.")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()

        print(f"✅ Email sent to {to_email}")
        return True

    except Exception as e:
        print("❌ Email sending failed:", str(e))
        return False




# # app/utils.py  (append)

# from datetime import datetime, timedelta
from jose import jwt, JWTError
# import os
# import smtplib
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart

RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "60"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
EMAIL_FROM = os.getenv("EMAIL_FROM", "no-reply@example.com")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

def create_reset_token(email: str, expires_minutes: int | None = None) -> str:
    """Create a short-lived JWT intended for password reset."""
    expire = datetime.utcnow() + timedelta(minutes=(expires_minutes or RESET_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": email,
        "purpose": "password_reset",
        "exp": expire,
        "iat": datetime.utcnow().timestamp()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def verify_reset_token(token: str) -> str:
    """Verify reset token and return the email (sub). Raises JWTError on failure."""
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise e
    # ensure purpose
    if data.get("purpose") != "password_reset" or "sub" not in data:
        raise JWTError("Invalid token")
    return data["sub"]

def send_reset_email(to_email: str, token: str, fullname: str | None = None):
    """
    Send a password-reset email (synchronous). Uses SMTP.
    You can replace this with an async/3rd-party client if desired.
    """
    reset_link = f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"

    subject = "CareIQ — Reset your password"
    name_line = f"Hi {fullname}," if fullname else "Hello,"

    html = f"""
    <html>
      <body>
        <p>{name_line}</p>
        <p>You requested to reset your password. Click the link below (valid for {RESET_TOKEN_EXPIRE_MINUTES} minutes):</p>
        <p><a href="{reset_link}">Reset your password</a></p>
        <p>If the link does not open, copy and paste this URL into your browser:</p>
        <p>{reset_link}</p>
        <hr/>
        <p>If you did not request this, please ignore this email.</p>
        <p>— CareIQ</p>
      </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    part = MIMEText(html, "html")
    msg.attach(part)

    # Basic SMTP send (blocking). For production, use an async email service or background worker.
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        # In dev, just log and return
        print("Email not sent — SMTP not configured. Reset link:", reset_link)
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(EMAIL_FROM, [to_email], msg.as_string())


def generate_default_password(length: int = 10):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))


async def send_otp_email(to_email: str, otp: str, fullname: str):
    """
    Send OTP to user's email.
    """
    subject = "Your OTP Code"
    body = f"Hello {fullname},\n\nYour OTP code is: {otp}\nIt will expire in 5 minutes.\n\nIf you did not request this, please ignore this email."
    
    send_email(to_email, subject, body)
