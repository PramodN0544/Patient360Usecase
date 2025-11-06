import asyncio
from app.database import engine
from sqlalchemy import text


async def check_tables():
    async with engine.begin() as conn:
        result = await conn.run_sync(
            lambda sync_conn: sync_conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public';"))
        )
        tables = [row[0] for row in result]
        print("\n📋 Tables in NeonDB:")
        if not tables:
            print(" - (no tables found)")
        for t in tables:
            print(" -", t)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_tables())
