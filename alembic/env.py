# alembic/env.py
import asyncio
from logging.config import fileConfig
import os
import sys

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# This line makes sure your project root is in the Python path
# Adjust '..' if your project structure is different relative to the alembic dir
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..')))

# Import your project's config and Base from your models
# This assumes your models are loaded when Base is imported or when self_market.models is imported
import config as app_config # Your project's config.py
from self_market.db.base import Base
import self_market.models # Ensure all your models are imported here to be registered

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
alembic_cfg = context.config # Rename to avoid conflict with your app_config

# Interpret the config file for Python logging.
# This line needs to be configured LOGGER_NAME settings.
if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

# Set the sqlalchemy.url in the Alembic config object from your app's config
# This makes it dynamic based on your .env file
alembic_cfg.set_main_option('sqlalchemy.url', "sqlite+aiosqlite:///" + app_config.DATABASE_URL)


# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = alembic_cfg.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    # ... (rest of offline mode, no changes needed here) ...
    """
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True # Also good to have here for consistency
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Get the Alembic configuration section for SQLAlchemy settings
    # This section usually defaults to [alembic] in alembic.ini
    # or can be specified by config_ini_section
    configuration = alembic_cfg.get_section(alembic_cfg.config_ini_section)
    if configuration is None:
        # Fallback if the section isn't found by name, provide an empty dict
        # or ensure your alembic.ini has the [alembic] section with sqlalchemy.url
        # However, we set sqlalchemy.url above, so this might not be strictly necessary
        # if async_engine_from_config correctly picks up the main options.
        # For safety, let's ensure we pass a dictionary.
        configuration = {}

    # Override/ensure sqlalchemy.url is present from our dynamic setting
    configuration['sqlalchemy.url'] = alembic_cfg.get_main_option("sqlalchemy.url")


    connectable = async_engine_from_config(
        configuration, # Pass the configuration dictionary
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())