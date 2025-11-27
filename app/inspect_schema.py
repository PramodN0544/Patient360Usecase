import asyncio
from sqlalchemy import inspect, MetaData, Table
from app.database import engine

async def inspect_table_schema():
    """
    Inspect the schema of the chat_messages table to see the actual column names.
    """
    async with engine.begin() as conn:
        # Use run_sync to get an inspector from the sync connection
        inspector = await conn.run_sync(lambda sync_conn: inspect(sync_conn))
        
        # Get all table names
        tables = await conn.run_sync(lambda sync_conn: inspector.get_table_names())
        print(f"Tables in database: {tables}")
        
        # Check if chat_messages table exists
        if "chat_messages" in tables:
            # Get columns for chat_messages table
            columns = await conn.run_sync(lambda sync_conn: inspector.get_columns("chat_messages"))
            print("\nColumns in chat_messages table:")
            for column in columns:
                print(f"  - {column['name']} ({column['type']})")
        else:
            print("\nchat_messages table does not exist!")
            
        # Check if chats table exists
        if "chats" in tables:
            # Get columns for chats table
            columns = await conn.run_sync(lambda sync_conn: inspector.get_columns("chats"))
            print("\nColumns in chats table:")
            for column in columns:
                print(f"  - {column['name']} ({column['type']})")
        else:
            print("\nchats table does not exist!")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(inspect_table_schema())