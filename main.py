import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import atexit
import config
from self_market.db import crud
from background_tasks import check_pending_listings_timeout
from config import BACKGROUND_CHECK_INTERVAL_MINUTES, PENDING_TIMEOUT_MINUTES
from bot import TelegramBot
from self_market.db.session import init_db, get_db_session

# Logging Setup
try:
    logging.basicConfig(
        format=config.LOG_FORMAT, level=config.LOG_LEVEL, force=True
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.debug("Logging setup complete.")
except Exception as e:
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.error(f"Logging setup failed: {e}", exc_info=True)


async def synchronize_admin_permissions():
    """
    Synchronizes admin permissions in the database with the ADMIN_TELEGRAM_IDS from config.
    Grants admin to users in the config list and revokes from those not in it.
    """
    logger.info("Starting admin permissions synchronization with config...")
    # Ensure ADMIN_TELEGRAM_IDS is the list of integers
    config_admin_ids = set(config.ADMIN_TELEGRAM_IDS)
    granted_count = 0
    revoked_count = 0

    async with get_db_session() as db:  # Use your async session manager
        # Ensure users in ADMIN_TELEGRAM_IDS are admins
        if not config_admin_ids:
            logger.info(
                "ADMIN_TELEGRAM_IDS in config is empty. No users will be specifically granted admin status by this step.")

        for tg_id in config_admin_ids:
            user = await crud.get_user_by_telegram_id(db, tg_id)
            if user:
                if not user.is_admin:
                    await crud.set_user_admin_state(db, tg_id, True)
                    # The crud.set_user_admin_state function already logs the change
                    granted_count += 1
            else:
                # We only update existing users.
                logger.warning(f"Admin ID {tg_id} from config.py is not found in the database. "
                               f"User needs to interact with the bot first to be created. "
                               f"They will not be made admin by this sync until they exist in the DB.")

        # Revoke admin from users in DB who are NOT in ADMIN_TELEGRAM_IDS
        current_db_admins = await crud.get_all_db_admin_users(db)
        for db_admin_user in current_db_admins:
            if db_admin_user.telegram_id not in config_admin_ids:
                await crud.set_user_admin_state(db, db_admin_user.telegram_id, False)
                # The crud.set_user_admin_state function already logs the change
                revoked_count += 1

    if granted_count > 0 or revoked_count > 0:
        logger.info(
            f"Admin permissions synchronization complete. Granted new admin status: {granted_count}, Revoked existing admin status: {revoked_count}.")
    else:
        logger.info(
            "Admin permissions synchronization complete. No changes to admin statuses were needed based on the current config.")


async def main() -> None:
    """Initializes DB, creates Bot instance and runs it."""

    # Token Check
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: Telegram Bot Token missing in config.")
        return
    logger.debug("Token checked.")

    logger.info(f"Using Database: {config.DATABASE_URL}")

    # Initialize DB
    try:
        logger.info("Initializing database schema...")
        await init_db()
    except Exception as e:
        logger.error("Database initialization failed. Bot will not start.")
        return # Exit if DB init fails

    # Synchronize Admin Permissions
    try:
        await synchronize_admin_permissions()
    except Exception as e:
        logger.error(f"Failed to synchronize admin permissions during startup: {e}", exc_info=True)

    # Create and Run Bot Instance
    try:
        logger.info("Creating TelegramBot instance...")
        bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
        ptb_app = bot_instance.application

        # --- Scheduler Setup ---
        scheduler = AsyncIOScheduler(timezone="UTC")  # Use UTC or your preferred timezone

        # Add the job, passing the Application object via kwargs
        scheduler.add_job(
            check_pending_listings_timeout,
            trigger='interval',
            minutes=BACKGROUND_CHECK_INTERVAL_MINUTES,  # Use the constant
            id='check_timeouts_job',  # Assign an ID
            replace_existing=True,
            kwargs={'app': ptb_app}
        )
        logger.info(
            f"Scheduled background task 'check_pending_listings_timeout' to run every {PENDING_TIMEOUT_MINUTES} minutes.")

        # Register scheduler shutdown hook
        atexit.register(lambda: scheduler.shutdown())

        scheduler.start()
        logger.info("APScheduler started.")

        logger.info("Running bot instance...")
        await bot_instance.run() # Call the async run method

    except ValueError as e: # Catch potential token error from Bot __init__
         logger.error(f"Failed to create bot instance: {e}")
    except RuntimeError as e: # Catch potential handler registration error
        logger.error(f"Failed during bot setup: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred running the bot: {e}", exc_info=True)


# Entry Point
if __name__ == "__main__":
    logger.info("Starting application...")
    try:
        asyncio.run(main())
    except RuntimeError as e:
        # Suppress common "Event loop is closed" error on Windows during final cleanup
        if "Event loop is closed" in str(e) and "Win" in asyncio.ProactorEventLoop.__module__:
             logger.warning("Suppressed 'Event loop is closed' error during final Windows cleanup.")
             pass
        else:
             logger.exception("Application level RuntimeError:", exc_info=e)
    except KeyboardInterrupt:
        logger.debug("Application level KeyboardInterrupt caught.")
        pass
    finally:
        logger.info("Application finished.")