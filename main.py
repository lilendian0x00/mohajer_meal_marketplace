import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application
import config
from self_market.db import crud
from background_tasks import check_pending_listings_timeout, update_meals_from_samad
from config import BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES, PENDING_TIMEOUT_MINUTES, BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES
from bot import TelegramBot
from self_market.db.session import init_db, get_db_session

logger = logging.getLogger(__name__)
scheduler_ref: AsyncIOScheduler | None = None # Renamed from 'scheduler' for clarity with global scope

async def synchronize_admin_permissions():
    """
    Synchronizes admin permissions in the database with the ADMIN_TELEGRAM_IDS from config.
    Grants admin to users in the config list and revokes from those not in it.
    """
    logger.info("Starting admin permissions synchronization with config...")
    config_admin_ids = set(config.ADMIN_TELEGRAM_IDS)
    granted_count = 0
    revoked_count = 0

    async with get_db_session() as db:
        if not config_admin_ids:
            logger.info(
                "ADMIN_TELEGRAM_IDS in config is empty. No users will be specifically granted admin status by this step.")

        for tg_id in config_admin_ids:
            user = await crud.get_user_by_telegram_id(db, tg_id)
            if user:
                if not user.is_admin:
                    await crud.set_user_admin_state(db, tg_id, True)
                    granted_count += 1
            else:
                logger.warning(f"Admin ID {tg_id} from config.py is not found in the database. "
                               f"User needs to interact with the bot first to be created. "
                               f"They will not be made admin by this sync until they exist in the DB.")

        current_db_admins = await crud.get_all_db_admin_users(db)
        for db_admin_user in current_db_admins:
            if db_admin_user.telegram_id not in config_admin_ids:
                await crud.set_user_admin_state(db, db_admin_user.telegram_id, False)
                revoked_count += 1

    if granted_count > 0 or revoked_count > 0:
        logger.info(
            f"Admin permissions synchronization complete. Granted new admin status: {granted_count}, Revoked existing admin status: {revoked_count}.")
    else:
        logger.info(
            "Admin permissions synchronization complete. No changes to admin statuses were needed based on the current config.")

async def perform_startup_tasks(ptb_app: Application):
    """All async tasks that need to run before the bot starts listening."""
    global scheduler_ref
    logger.info("Performing startup tasks...")

    logger.info(f"Using Database: {config.DATABASE_URL}") # Added from old main.py

    # Initialize DB
    try:
        logger.info("Initializing database schema...")
        await init_db()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}. Aborting startup.", exc_info=True)
        # PTB's post_init doesn't have a direct way to stop the bot launch if an error occurs here.
        # Raising SystemExit is a hard stop. Consider if a more graceful signal to PTB is possible
        # or if logging the error and letting PTB try to start (and likely fail if DB is crucial) is preferred.
        # For now, following the original intent of stopping.
        raise SystemExit("DB Init Failed")

    # Synchronize Admin Permissions
    try:
        await synchronize_admin_permissions()
    except Exception as e:
        logger.error(f"Failed to synchronize admin permissions during startup: {e}", exc_info=True)
        # Non-fatal, bot can continue

    # Scheduler Setup
    scheduler_ref = AsyncIOScheduler(timezone="UTC") # Use UTC or your preferred timezone

    # Add listing timeout checker job
    scheduler_ref.add_job(
        check_pending_listings_timeout,
        trigger='interval',
        next_run_time=datetime.now(), # Run immediately then interval
        minutes=BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES,
        id='check_timeouts_job',
        replace_existing=True,
        kwargs={'app': ptb_app}
    )
    logger.info( # Added from old main.py, corrected to use the actual interval variable
        f"Scheduled background task 'check_pending_listings_timeout' to run every {BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES} minutes.")

    # Add meal updater job
    scheduler_ref.add_job(
        update_meals_from_samad,
        trigger='interval',
        next_run_time=datetime.now(), # Run immediately then interval
        minutes=BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES, # Using the specific config for this job
        id='update_meals_from_samad',
        replace_existing=True,
        misfire_grace_time=None, # Or some appropriate value
        kwargs={'app': ptb_app}
    )
    logger.info( # Added logging for the second job for consistency
        f"Scheduled background task 'update_meals_from_samad' to run every {BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES} minutes.")

    scheduler_ref.start()
    logger.info("APScheduler started.")
    logger.info("Startup tasks complete.")


async def post_shutdown_tasks(app: Application | None = None): # app argument provided by PTB
    """Tasks to run after PTB application has shut down."""
    global scheduler_ref
    logger.info("Performing post-shutdown tasks...")
    if scheduler_ref and scheduler_ref.running:
        logger.info("Shutting down APScheduler in post_shutdown_tasks...")
        scheduler_ref.shutdown(wait=True) # wait=True is fine for async def if PTB awaits this properly
        logger.info("APScheduler shutdown complete in post_shutdown_tasks.")
    # If ptb_app instance was needed here, the 'app' argument should be used.
    logger.info("Post-shutdown tasks complete.")


def main_sync():
    """Synchronous entry point that sets up and runs the asyncio application for webhook."""

    # Token Check
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: Telegram Bot Token missing in config. Bot will not start.")
        return

    # Webhook Specific Checks (from new version)
    if not config.WEBHOOK_BASE_URL:
        logger.error("FATAL: WEBHOOK_BASE_URL is not set in config. Cannot start in webhook mode.")
        return

    # The full webhook URL for Telegram will be set via set_webhook.
    webhook_url_path = f"/{config.TELEGRAM_BOT_TOKEN.strip('/')}" # Ensure leading slash, no trailing
    full_webhook_url_for_telegram = f"{config.WEBHOOK_BASE_URL.rstrip('/')}{webhook_url_path}"

    logger.info("Creating TelegramBot instance...")
    try:
        bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
        ptb_app = bot_instance.application
    except ValueError as e: # Catch potential token error from Bot __init__
         logger.error(f"Failed to create bot instance (ValueError): {e}", exc_info=True)
         return
    except Exception as e: # Catch any other error during bot instantiation
        logger.error(f"Failed to create bot instance (Exception): {e}", exc_info=True)
        return


    # --- Configure PTB Application with startup/shutdown tasks ---
    ptb_app.post_init = perform_startup_tasks
    ptb_app.post_shutdown = post_shutdown_tasks

    logger.info("Starting PTB Application with webhook server...")
    logger.info(f"Webhook: Telegram will be told to send updates to: {full_webhook_url_for_telegram}")
    logger.info(f"Webhook: PTB will listen on IP: {config.WEBHOOK_LISTEN_IP}, Port: {config.WEBHOOK_LISTEN_PORT}, Path: {webhook_url_path}")

    try:
        ptb_app.run_webhook(
            listen=config.WEBHOOK_LISTEN_IP,
            port=config.WEBHOOK_LISTEN_PORT,
            secret_token=config.WEBHOOK_SECRET_TOKEN or None,
            webhook_url=full_webhook_url_for_telegram,
            url_path=webhook_url_path,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )
    except RuntimeError as e: # Catch potential handler registration or other PTB setup error
        logger.error(f"Failed during PTB run_webhook setup: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred running the PTB webhook: {e}", exc_info=True)

    logger.info("PTB Application run_webhook has finished.")


# Entry Point
if __name__ == "__main__":
    # Basic logging setup can happen before asyncio.run or PTB's own loop starts
    try:
        logging.basicConfig(
            format=config.LOG_FORMAT, level=config.LOG_LEVEL, force=True
        )
        logging.getLogger("httpx").setLevel(logging.WARNING) # From old
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING) # From old
        # Define logger here if not already defined at module level, but it is.
        logger.info("Logging setup complete.")
    except Exception as e:
        # Fallback basic logging if setup fails
        logging.basicConfig(level=logging.ERROR)
        logger = logging.getLogger(__name__) # Re-ensure logger is defined
        logger.error(f"Logging setup failed: {e}", exc_info=True)

    logger.info("Starting application...")
    try:
        # PTB's run_webhook/run_polling creates and manages the asyncio loop.
        # We don't need asyncio.run() around main_sync() for this PTB setup.
        main_sync()
    except (KeyboardInterrupt, SystemExit) as e:
        logger.info(f"Application received {type(e).__name__}. Exiting gracefully.")
    except Exception as e: # Catch any other unexpected errors at the top level
        logger.error(f"Unhandled exception at top application level: {e}", exc_info=True)
    finally:
        # This will be reached after main_sync() completes (i.e., PTB stops)
        # or if an exception causes an exit from the try block.
        logger.info("Application finished.")