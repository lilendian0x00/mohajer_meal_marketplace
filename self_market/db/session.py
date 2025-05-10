import logging
import unicodedata

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from typing import AsyncGenerator, List, Dict, Any
from sqlalchemy import text, select
from datetime import date
from config import DATABASE_URL
from .base import Base
from .. import models

# Logger instance for this module
logger = logging.getLogger(__name__)


# Simple extraction assuming the DSN format is consistent
dsn_prefix = "sqlite+aiosqlite:///"
db_file_path_from_config = ""
if DATABASE_URL.startswith(dsn_prefix):
    db_file_path_from_config = DATABASE_URL[len(dsn_prefix):]
else:
    # Fallback or raise error if DSN format is unexpected
    logger.error(f"Unexpected DATABASE_URL format from config: {DATABASE_URL!r}. Expected to start with '{dsn_prefix}'. Using hardcoded fallback /data/self_market.db")
    db_file_path_from_config = "/data/self_market.db" # Fallback, not ideal

# Optional: Aggressive cleaning for the extracted path (if you still suspect issues with it)
# cleaned_path_str = str(db_file_path_from_config)
# normalized_path = unicodedata.normalize('NFKC', cleaned_path_str)
# printable_chars_path = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-. রবি/" # Only path chars
# reconstructed_path_parts = [char for char in normalized_path if char in printable_chars_path]
# final_db_file_path = "".join(reconstructed_path_parts).strip()
# For now, let's assume the extracted path is clean after stripping in config.py
final_db_file_path = db_file_path_from_config.strip() # Ensure it's stripped too

logger.info(f"DEBUG SESSION.PY: Extracted DB file path for connect_args: '{final_db_file_path!r}'")

engine = create_async_engine(
    "sqlite+aiosqlite:///", # Minimal base URL, path is provided by connect_args
    connect_args={"database": final_db_file_path}, # Pass ONLY the file path here
    echo=True
)

# Create the async session maker
async_session_factory = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional scope around a series of operations."""
    # This function remains the same
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Seed Data
# List of dictionaries, each representing a meal
# Using specific dates for example, adjust as needed
SEED_MEALS: List[Dict[str, Any]] = [
    # {
    #     "date": date(2025, 5, 15), "meal_type": "ناهار",
    #     "description": "عدس پلو با گوشت", "price": 12000.0, "price_limit": 20000.0
    # },
    # {
    #     "date": date(2025, 5, 15), "meal_type": "ناهار",
    #     "description": "چلو کباب کوبیده", "price": 15000.0, "price_limit": 25000.0
    #  },
    # {
    #     "date": date(2025, 5, 16), "meal_type": "ناهار",
    #     "description": "چلو خورشت قورمه سبزی", "price": 12000.0, "price_limit": 25000.0
    # },
    # {
    #     "date": date(2025, 5, 16), "meal_type": "ناهار",
    #     "description": "کلم پلو با گوشت", "price": 12000.0, "price_limit": 23000.0
    # },
    # {
    #     "date": date(2025, 5, 16), "meal_type": "ناهار",
    #     "description": "چلو جوجه کباب بدون استخوان", "price": 15000.0, "price_limit": 25000.0
    # },
]

async def seed_database(session: AsyncSession):
    """Inserts predefined meals into the database if they don't already exist."""
    logger.info("Starting database seeding for Meals...")
    inserted_count = 0
    for meal_data in SEED_MEALS:
        # Check if a meal with the same description, date, and type already exists
        stmt = select(models.Meal).where(
            models.Meal.description == meal_data["description"],
            models.Meal.date == meal_data["date"],
            models.Meal.meal_type == meal_data["meal_type"]
        )
        result = await session.execute(stmt)
        existing_meal = result.scalar_one_or_none()

        if existing_meal:
            logger.debug(f"Meal '{meal_data['description']}' on {meal_data['date']} ({meal_data['meal_type']}) already exists. Skipping.")
        else:
            # Create and add the new meal
            new_meal = models.Meal(
                date=meal_data["date"],
                meal_type=meal_data["meal_type"],
                description=meal_data["description"],
                price=meal_data.get("price"), # Use .get for optional fields
                price_limit=meal_data.get("price_limit")
            )
            session.add(new_meal)
            inserted_count += 1
            logger.debug(f"Adding seed meal: {meal_data['description']} on {meal_data['date']}")

    if inserted_count > 0:
        try:
            await session.commit()
            logger.info(f"Successfully inserted {inserted_count} new seed meals.")
        except Exception as e:
            await session.rollback()
            logger.error(f"Error committing seed data: {e}", exc_info=True)
    else:
        logger.info("No new seed meals needed.")

async def init_db():
    """Initializes the database by creating tables based on Base metadata."""
    registered_tables = list(Base.metadata.tables.keys())
    logger.info(f"SQLAlchemy Base.metadata knows about tables: {registered_tables}")

    if not registered_tables:
        logger.error("CRITICAL: No tables found in Base.metadata! Check model definitions and imports in models.py and session.py.")
        raise RuntimeError("No models registered with SQLAlchemy Base, cannot initialize database.")

    logger.info(f"Attempting to create tables in database: {IMPORTED_DATABASE_URL}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("SQLAlchemy Base.metadata.create_all execution completed.")

        # Seed the database
        async with async_session_factory() as session:
            await seed_database(session)
    except Exception as e:
        logger.error(f"EXCEPTION during database initialization (init_db): {e}", exc_info=True)
        raise