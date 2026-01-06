import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.utils import update_patient_ages

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("scheduled_tasks")

async def run_daily_tasks(db: AsyncSession):
    """
    Run tasks that should be executed daily
    """
    logger.info("🔄 Starting daily scheduled tasks")
    
    # Update patient ages
    try:
        updated_count = await update_patient_ages(db)
        logger.info(f"✅ Patient age update completed. Updated {updated_count} records.")
    except Exception as e:
        logger.error(f"❌ Error updating patient ages: {str(e)}")
    
    logger.info("✅ Daily scheduled tasks completed")

async def scheduler():
    """
    Main scheduler function that runs tasks at specified intervals
    """
    logger.info("🚀 Starting scheduler")
    
    # Calculate time until next midnight (when daily tasks should run)
    now = datetime.now()
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    seconds_until_midnight = (tomorrow - now).total_seconds()
    
    logger.info(f"⏰ Next scheduled run in {seconds_until_midnight:.2f} seconds")
    
    while True:
        try:
            # Wait until midnight
            await asyncio.sleep(seconds_until_midnight)
            
            # Get a new database session
            async for db in get_db():
                await run_daily_tasks(db)
                break  # Exit after first iteration
            
            # Recalculate time until next midnight
            now = datetime.now()
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            seconds_until_midnight = (tomorrow - now).total_seconds()
            
            logger.info(f"⏰ Next scheduled run in {seconds_until_midnight:.2f} seconds")
            
        except Exception as e:
            logger.error(f"❌ Scheduler error: {str(e)}")
            # Wait a bit before retrying
            await asyncio.sleep(60)

# Function to start the scheduler
def start_scheduler():
    """
    Start the scheduler in a background task
    """
    loop = asyncio.get_event_loop()
    task = loop.create_task(scheduler())
    return task