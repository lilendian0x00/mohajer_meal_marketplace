import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import atexit

from telegram import Update
from telegram.ext import Application
import config
from self_market.db import crud
from background_tasks import check_pending_listings_timeout, update_meals_from_samad
from config import BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES, PENDING_TIMEOUT_MINUTES
from bot import TelegramBot
from self_market.db.session import init_db, get_db_session

logger = logging.getLogger(__name__)
scheduler: AsyncIOScheduler | None = None
ptb_application_instance: Application | None = None # To reference for shutdown


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

async def perform_startup_tasks(ptb_app: Application):
    """All async tasks that need to run before the bot starts listening."""
    global scheduler_ref
    logger.info("Performing startup tasks...")

    # Initialize DB
    try:
        logger.info("Initializing database schema...")
        await init_db()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}. Aborting startup.", exc_info=True)
        raise SystemExit("DB Init Failed") # Stop further execution

    # Synchronize Admin Permissions
    try:
        await synchronize_admin_permissions()
    except Exception as e:
        logger.error(f"Failed to synchronize admin permissions during startup: {e}", exc_info=True)
        # Non-fatal, bot can continue

    # Scheduler Setup
    scheduler_ref = AsyncIOScheduler(timezone="UTC")
    scheduler_ref.add_job(
        check_pending_listings_timeout,
        trigger='interval',
        next_run_time=datetime.now(),
        minutes=BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES,
        id='check_timeouts_job',
        replace_existing=True,
        kwargs={'app': ptb_app} # Pass the PTB application instance
    )
    scheduler_ref.add_job(
        update_meals_from_samad,
        trigger='interval',
        next_run_time=datetime.now(),
        minutes=config.BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES,
        id='update_meals_from_samad',
        replace_existing=True,
        misfire_grace_time=None,
        kwargs={'app': ptb_app} # Pass the PTB application instance
    )
    scheduler_ref.start()
    logger.info("APScheduler started.")
    logger.info("Startup tasks complete.")


async def post_shutdown_tasks(app: Application | None = None): # Add the app argument
    """Tasks to run after PTB application has shut down."""
    global scheduler_ref # Use the global reference
    logger.info("Performing post-shutdown tasks...")
    if scheduler_ref and scheduler_ref.running:
        logger.info("Shutting down APScheduler in post_shutdown_tasks...")
        scheduler_ref.shutdown(wait=False) # wait=False for async
        logger.info("APScheduler shutdown call initiated in post_shutdown_tasks.")
    logger.info("Post-shutdown tasks complete.")


async def run_application_webhook(bot_instance: TelegramBot, webhook_url: str):
    """
    The main async function to initialize, set webhook, and run the PTB application.
    This will be wrapped by `async with bot_instance.application:`
    """
    # `bot_instance.application.initialize()` is called by `async with bot_instance.application`
    await bot_instance.set_bot_webhook(webhook_url, config.WEBHOOK_SECRET_TOKEN or None)
    await bot_instance.run_ptb_webhook_server(
        listen_ip=config.WEBHOOK_LISTEN_IP,
        listen_port=config.WEBHOOK_LISTEN_PORT,
        secret_token=config.WEBHOOK_SECRET_TOKEN or None,
        webhook_url_for_ptb=webhook_url # Pass the full URL here
    )


def main_sync(): # Renamed to avoid confusion with async main
    """Synchronous entry point that sets up and runs the asyncio application."""

    # Token Check
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: Telegram Bot Token missing in config.")
        return

    # Webhook Specific Checks
    if not config.WEBHOOK_BASE_URL:
        logger.error("FATAL: WEBHOOK_BASE_URL is not set in config. Cannot start in webhook mode.")
        return
    webhook_url = f"{config.WEBHOOK_BASE_URL.rstrip('/')}/{config.TELEGRAM_BOT_TOKEN}"

    logger.info("Creating TelegramBot instance...")
    # Pass SSL cert/key to __init__ if PTB is to handle SSL.
    # Otherwise, for reverse proxy, these are not needed here.
    bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
    ptb_app = bot_instance.application

    # --- Configure PTB Application with startup/shutdown tasks ---
    # These run within the Application's own lifecycle management
    ptb_app.post_init = perform_startup_tasks  # PTB passes the application instance here automatically
    ptb_app.post_shutdown = post_shutdown_tasks  # PTB passes the application instance here automatically

    logger.info("Starting PTB Application with webhook server...")
    # `run_webhook` will block and manage its own loop interaction.
    # It also handles SIGINT/SIGTERM for graceful shutdown.
    # The post_init and post_shutdown tasks will be awaited by PTB.

    webhook_url_for_ptb_server = f"{config.WEBHOOK_BASE_URL.rstrip('/')}/"
    logger.info(f"PTB run_webhook will be called with webhook_url: {webhook_url}")
    bot_instance.application.run_webhook(
        listen=config.WEBHOOK_LISTEN_IP,
        port=config.WEBHOOK_LISTEN_PORT,
        secret_token=config.WEBHOOK_SECRET_TOKEN or None,
        webhook_url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        url_path=webhook_url_for_ptb_server,
    )
    logger.info("PTB Application run_webhook has finished.")


# Entry Point
if __name__ == "__main__":
    # Basic logging setup can happen before asyncio.run
    try:
        logging.basicConfig(
            format=config.LOG_FORMAT, level=config.LOG_LEVEL, force=True
        )
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
        logger.info("Logging setup complete.")
    except Exception as e:
        logging.basicConfig(level=logging.ERROR) # Fallback basic logging
        logger = logging.getLogger(__name__) # Ensure logger is defined
        logger.error(f"Logging setup failed: {e}", exc_info=True)

    logger.info("Starting application...")
    try:
        # PTB's run_webhook will create/manage the loop internally when called this way.
        # We don't use asyncio.run() around it.
        main_sync()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application received KeyboardInterrupt/SystemExit. Exiting.")
    except Exception as e:
        logger.error(f"Unhandled exception at top application level: {e}", exc_info=True)
    finally:
        logger.info("Application finished.")