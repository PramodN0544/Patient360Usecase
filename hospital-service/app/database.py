import ssl, os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from urllib.parse import urlparse, urlunparse

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found")

# Convert to asyncpg
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Clean URL
parsed = urlparse(DATABASE_URL)
clean_url = parsed._replace(query="")
DATABASE_URL = urlunparse(clean_url)

# SSL
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    DATABASE_URL, echo=True, future=True, connect_args={"ssl": ssl_ctx}
)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# Base
Base = declarative_base()
metadata = Base.metadata

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
