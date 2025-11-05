import asyncio
from app.database import engine, Base

async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("✅ Tables created successfully!")

asyncio.run(init_models())
