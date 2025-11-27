import asyncio
from app.database import engine, Base
from app import models  # important import

async def create_all_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("✅ Tables created successfully in NeonDB!")

if __name__ == "__main__":
    asyncio.run(create_all_tables())
