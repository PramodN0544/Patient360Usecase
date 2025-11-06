from dotenv import load_dotenv, find_dotenv
import os
from sqlalchemy import create_engine, text


def main():
    load_dotenv(find_dotenv())
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found in .env")
        return

    # Convert sync URL if asyncpg form used
    if db_url.startswith("postgresql+asyncpg://"):
        sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    else:
        sync_url = db_url

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        for table in ("hospitals", "doctors", "patients", "appointments"):
            print(f"\n--- {table} ---")
            try:
                res = conn.execute(text(f"SELECT * FROM {table} LIMIT 5"))
                rows = res.fetchall()
                if not rows:
                    print("(no rows)")
                else:
                    for r in rows:
                        # convert row to dict for pretty print
                        print(dict(r._mapping))
            except Exception as e:
                print("error querying", table, e)


if __name__ == "__main__":
    main()
