import os
import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
import logging
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found")

# Convert to asyncpg
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Remove unsupported Neon params (sslmode, channel_binding)
if "sslmode=" in DATABASE_URL or "channel_binding=" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split("?")[0]

# Windows-safe SSL for Neon (No verification)
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE   

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": ssl_ctx},  
    pool_pre_ping=True,          
    pool_recycle=1800,           
    pool_size=10,                
    max_overflow=20             
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()
metadata = Base.metadata

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def sync_schema():
    """Add missing columns to existing tables based on SQLAlchemy models"""
    logger.info("Starting schema synchronization...")
    
    # Get metadata
    metadata = Base.metadata
    
    # Sync each table
    async with engine.begin() as conn:
        # We need to use run_sync for inspection
        await conn.run_sync(_sync_schema_sync, metadata)
    
    logger.info("Schema synchronization completed!")

def _sync_schema_sync(conn, metadata):
    """Synchronous version for run_sync"""
    inspector = inspect(conn)
    
    # Sync each table
    for table_name, table in metadata.tables.items():
        _sync_table_sync(conn, inspector, table_name, table)

def _sync_table_sync(conn, inspector, table_name, table):
    """Sync a single table (synchronous)"""
    logger.info(f"Checking table: {table_name}")
    
    # Check if table exists
    if not inspector.has_table(table_name):
        logger.info(f"Table {table_name} doesn't exist, skipping...")
        return
        
    # Get existing columns from database
    existing_columns = inspector.get_columns(table_name)
    existing_column_names = {col['name'] for col in existing_columns}
    
    # Get columns from model
    model_columns = {column.name for column in table.columns}
    
    # Find missing columns (in model but not in database)
    missing_columns = model_columns - existing_column_names
    
    # Add missing columns
    for column_name in missing_columns:
        _add_column_sync(conn, table_name, table.columns[column_name])

def _add_column_sync(conn, table_name, column):
    """Add a column to an existing table (SAFE for existing data)"""
    try:
        column_type = str(column.type)

        if 'VARCHAR' in column_type and hasattr(column.type, 'length'):
            column_type = f"VARCHAR({column.type.length})"
        elif 'INTEGER' in column_type:
            column_type = "INTEGER"
        elif 'BOOLEAN' in column_type.upper():
            column_type = "BOOLEAN"
        elif 'TEXT' in column_type.upper():
            column_type = "TEXT"
        elif 'TIMESTAMP' in column_type.upper():
            column_type = "TIMESTAMP"
        elif 'DATE' in column_type.upper():
            column_type = "DATE"
        elif 'NUMERIC' in column_type.upper():
            column_type = "NUMERIC"

        # ✅ ALWAYS add column as NULLABLE first
        sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {column_type}'

        # ✅ Only add DEFAULT (safe)
        if column.server_default is not None:
            default_value = str(column.server_default.arg)
            if column.type.python_type == bool:
                default_value = default_value.upper()
            elif column.type.python_type == str:
                default_value = f"'{default_value}'"
            sql += f" DEFAULT {default_value}"

        logger.info(f"Adding column safely: {sql}")
        conn.execute(text(sql))

        logger.info(f"Column '{column.name}' added to table '{table_name}' safely")

    except SQLAlchemyError as e:
        logger.error(f"Failed to add column '{column.name}' to '{table_name}': {e}")

# Export everything
__all__ = [
    'engine', 
    'Base', 
    'AsyncSessionLocal', 
    'get_db', 
    'sync_schema'
]