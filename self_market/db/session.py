import logging
import unicodedata

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from typing import AsyncGenerator, List, Dict, Any
from sqlalchemy import text, select, NullPool
from datetime import date
from config import DATABASE_URL as IMPORTED_DATABASE_URL
from .base import Base
from .. import models

# Logger instance for this module
logger = logging.getLogger(__name__)


# --- Debugging the IMPORTED_DATABASE_URL ---
print(f"DEBUG SESSION.PY: IMPORTED_DATABASE_URL raw from config: '{IMPORTED_DATABASE_URL!r}'")
print(f"DEBUG SESSION.PY: Length of IMPORTED_DATABASE_URL: {len(IMPORTED_DATABASE_URL)}")

# Aggressively clean and reconstruct the URL
# 1. Ensure it's a string (should be)
cleaned_url_str = str(IMPORTED_DATABASE_URL)

# 2. Normalize unicode, remove control characters, and strip again
# This helps get rid of really weird invisible characters
normalized_url = unicodedata.normalize('NFKC', cleaned_url_str)
# Keep only printable ASCII characters + common URL characters (/, :, +) for the scheme and path
# This is VERY aggressive; if your path had other valid non-ASCII chars, this would break it,
# but for "sqlite+aiosqlite:///data/self_market.db" it's fine.
printable_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.+/:~" # Added ~ for home dir if used, though not here
reconstructed_url_parts = [char for char in normalized_url if char in printable_chars]
final_reconstructed_url = "".join(reconstructed_url_parts).strip()


print(f"DEBUG SESSION.PY: Final Reconstructed URL for engine: '{final_reconstructed_url!r}'")
print(f"DEBUG SESSION.PY: Length of Final Reconstructed URL: {len(final_reconstructed_url)}")

# The known good string
known_good_url = "sqlite+aiosqlite:///data/self_market.db"
print(f"DEBUG SESSION.PY: Known Good URL for comparison: '{known_good_url!r}'")
print(f"DEBUG SESSION.PY: Length of Known Good URL: {len(known_good_url)}")

if final_reconstructed_url != known_good_url:
    logger.warning("WARNING: The aggressively cleaned URL still differs from the known good URL!")
    logger.warning(f"Final Reconstructed: {final_reconstructed_url}")
    logger.warning(f"Known Good:          {known_good_url}")
    # To be extra safe, you could even force it here if they don't match after cleaning,
    # though the goal is to understand why the imported one is problematic.
    # final_reconstructed_url = known_good_url # Uncomment for a forceful override if debugging fails

# Create the async engine using the aggressively cleaned and reconstructed URL

engine = create_async_engine(
    final_reconstructed_url, # USE THE MOST CLEANED VERSION
    echo=True,
    poolclass=NullPool,
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
    print("Starting database seeding for Meals...")
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
            print(f"Successfully inserted {inserted_count} new seed meals.")
        except Exception as e:
            await session.rollback()
            logger.error(f"Error committing seed data: {e}", exc_info=True)
    else:
        print("No new seed meals needed.")

async def init_db():
    """Initializes the database by creating tables based on Base metadata."""
    registered_tables = list(Base.metadata.tables.keys())
    print(f"SQLAlchemy Base.metadata knows about tables: {registered_tables}")

    if not registered_tables:
        logger.error("CRITICAL: No tables found in Base.metadata! Check model definitions and imports in models.py and session.py.")
        raise RuntimeError("No models registered with SQLAlchemy Base, cannot initialize database.")

    print(f"Attempting to create tables in database: {IMPORTED_DATABASE_URL}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("SQLAlchemy Base.metadata.create_all execution completed.")

        # Seed the database
        async with async_session_factory() as session:
            await seed_database(session)
    except Exception as e:
        logger.error(f"EXCEPTION during database initialization (init_db): {e}", exc_info=True)
        raise