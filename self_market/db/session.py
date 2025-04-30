import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy import text
from config import DATABASE_URL
from .base import Base
from .. import models

# Logger instance for this module
logger = logging.getLogger(__name__)

# Create the async engine using the URL from config
engine = create_async_engine(
    DATABASE_URL,
    echo=False, # Keep echo False for cleaner logs now
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

async def init_db():
    """Initializes the database by creating tables based on Base metadata."""
    registered_tables = list(Base.metadata.tables.keys())
    logger.info(f"SQLAlchemy Base.metadata knows about tables: {registered_tables}")

    if not registered_tables:
        logger.error("CRITICAL: No tables found in Base.metadata! Check model definitions and imports in models.py and session.py.")
        raise RuntimeError("No models registered with SQLAlchemy Base, cannot initialize database.")

    logger.info(f"Attempting to create tables in database: {DATABASE_URL}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("SQLAlchemy Base.metadata.create_all execution completed.")
    except Exception as e:
        logger.error(f"EXCEPTION during database initialization (init_db): {e}", exc_info=True)
        raise