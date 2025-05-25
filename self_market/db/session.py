import asyncio
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

engine = create_async_engine(
    "sqlite+aiosqlite:///"+DATABASE_URL,
    echo=False
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
    session: AsyncSession | None = None # Initialize session variable
    session_instance_id = None
    # Get the current asyncio task, handle cases where there might not be one
    current_task = asyncio.current_task()
    task_name = current_task.get_name() if current_task else "Unknown Task"
    try:
        # Use the session factory directly to create the session
        session = async_session_factory()
        session_instance_id = id(session) # Get a unique ID for this session instance
        logger.debug(f"[TASK: {task_name}] Acquiring session: {session_instance_id}")
        try:
            yield session # Yield the created session
        except Exception as e:
            logger.error(f"[TASK: {task_name}] Exception in session {session_instance_id}, rolling back: {e}", exc_info=True)
            if session: # Ensure session exists before rollback
                # Check if the session is still active before rolling back
                if session.is_active:
                   try:
                       await session.rollback()
                       logger.debug(f"[TASK: {task_name}] Rolled back session: {session_instance_id}")
                   except Exception as rb_exc:
                       logger.error(f"[TASK: {task_name}] Exception during rollback for session {session_instance_id}: {rb_exc}", exc_info=True)
                else:
                   logger.warning(f"[TASK: {task_name}] Session {session_instance_id} inactive during exception handling, cannot rollback.")
            raise # Re-raise the exception for the outer handler
    finally:
        # This outer finally block handles the closing
        if session: # Check if session was successfully created/assigned
            logger.debug(f"[TASK: {task_name}] Closing session: {session_instance_id}")
            try:
                await session.close()
                logger.debug(f"[TASK: {task_name}] Closed session: {session_instance_id}")
            except Exception as close_exc:
                logger.error(f"[TASK: {task_name}] Exception during close for session {session_instance_id}: {close_exc}", exc_info=True)
        else:
            logger.warning(f"[TASK: {task_name}] Attempted to close session in finally, but session was None.")


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
    """
    Initializes database aspects like seeding.
    Schema creation and migration are handled by Alembic.
    """
    logger.info(f"Database initialization routine started for: {DATABASE_URL}")

    # Log known tables by SQLAlchemy (good for debugging model registration)
    registered_tables = list(Base.metadata.tables.keys())
    logger.info(f"SQLAlchemy Base.metadata currently knows about tables: {registered_tables}")
    if not registered_tables:
        logger.warning("Warning: No tables found in Base.metadata when init_db called. "
                       "Ensure models are imported before Base is used by Alembic or other parts of the app.")


    logger.info("Schema management is handled by Alembic. Skipping Base.metadata.create_all().")
    logger.info("Ensure 'alembic upgrade head' has been run to set up the database schema.")

    # Proceed with seeding data if necessary
    try:
        async with async_session_factory() as session:  # Use your defined session factory
            await seed_database(session)
        logger.info("Database seeding process completed (if any seeds were pending).")
    except Exception as e:
        logger.error(f"EXCEPTION during database seeding in init_db: {e}", exc_info=True)
        raise