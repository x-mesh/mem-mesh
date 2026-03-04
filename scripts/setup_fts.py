
import asyncio
import logging
from app.core.database.base import Database
from app.core.database.initializer import DatabaseInitializer
from app.core.config import Settings

# 로깅 설정
logging.basicConfig(level=logging.INFO)

async def setup():
    settings = Settings()
    print(f"Connecting to database: {settings.database_path}")
    db = Database(settings.database_path)
    await db.connect()
    
    # Initializer 생성 (db._connection은 DatabaseConnection 객체)
    initializer = DatabaseInitializer(db._connection)
    
    print("Setting up FTS tables...")
    try:
        await initializer._create_fts_tables()
        db._connection.connection.commit()
        print("✅ FTS tables and triggers setup successfully.")
    except Exception as e:
        print(f"❌ Failed to setup FTS: {e}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(setup())
