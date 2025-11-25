import asyncio
from sqlalchemy import select
from passlib.context import CryptContext
from app.utils import get_password_hash
from app.database import AsyncSessionLocal
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN_EMAIL = "admin@careiq.com"
ADMIN_PASSWORD = "Admin@123"
ADMIN_NAME = "Super Admin"

async def seed_admin():
    async with AsyncSessionLocal() as session:

        result = await session.execute(
            select(User).where(User.email == ADMIN_EMAIL)
        )
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            print("Admin already exists")
            return

        hashed_password = get_password_hash(ADMIN_PASSWORD)

        admin = User(
            email=ADMIN_EMAIL,
            hashed_password=hashed_password,
            full_name=ADMIN_NAME,
            role="admin",
            hospital_id=None,
            is_active=True
        )

        session.add(admin)
        await session.commit()
        print("Admin created successfully")

if __name__ == "__main__":
    asyncio.run(seed_admin())
