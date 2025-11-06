import asyncio
from app.database import engine
from sqlalchemy import text


async def show_rows():
    async with engine.begin() as conn:
        for table in ("hospitals", "doctors", "patients", "appointments"):
            print(f"\n--- {table} ---")
            result = await conn.run_sync(lambda sync_conn: sync_conn.execute(text(f"SELECT * FROM {table} LIMIT 5;")))
            rows = result.fetchall()
            if not rows:
                print("(no rows)")
            else:
                for r in rows:
                    print(dict(r))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(show_rows())
