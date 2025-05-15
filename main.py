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


def run_webhook_mode():
    """Configures and runs the bot in webhook mode."""
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: Telegram Bot Token missing in config. Bot will not start in webhook mode.")
        return
    if not config.WEBHOOK_BASE_URL:
        logger.error("FATAL: WEBHOOK_BASE_URL is not set in config. Cannot start in webhook mode.")
        return

    webhook_url_path = f"/{config.TELEGRAM_BOT_TOKEN.strip('/')}"
    full_webhook_url_for_telegram = f"{config.WEBHOOK_BASE_URL.rstrip('/')}{webhook_url_path}"

    logger.info("Creating TelegramBot instance for webhook mode...")
    try:
        bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
        ptb_app = bot_instance.application
    except Exception as e:
        logger.error(f"Failed to create bot instance for webhook: {e}", exc_info=True)
        return

    ptb_app.post_init = perform_startup_tasks
    ptb_app.post_shutdown = post_shutdown_tasks

    logger.info("Starting PTB Application with webhook server...")
    logger.info(f"Webhook URL for Telegram: {full_webhook_url_for_telegram}")
    logger.info(f"PTB listening on IP: {config.WEBHOOK_LISTEN_IP}, Port: {config.WEBHOOK_LISTEN_PORT}, Path: {webhook_url_path}")

    # SSL certificate and key are passed if configured
    ssl_context = None
    if config.WEBHOOK_SSL_CERT and config.WEBHOOK_SSL_KEY:
        ssl_context = (config.WEBHOOK_SSL_CERT, config.WEBHOOK_SSL_KEY)
        logger.info(f"Using SSL certificate: {config.WEBHOOK_SSL_CERT} and key: {config.WEBHOOK_SSL_KEY}")
    elif config.WEBHOOK_SSL_CERT or config.WEBHOOK_SSL_KEY:
        logger.warning("WEBHOOK_SSL_CERT or WEBHOOK_SSL_KEY is set, but not both. SSL will not be used.")


    ptb_app.run_webhook(
        listen=config.WEBHOOK_LISTEN_IP,
        port=config.WEBHOOK_LISTEN_PORT,
        secret_token=config.WEBHOOK_SECRET_TOKEN or None,
        webhook_url=full_webhook_url_for_telegram, # URL Telegram will send updates to
        url_path=webhook_url_path, # Path PTB will listen on
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True, # Recommended to drop when starting webhook
        key=config.WEBHOOK_SSL_KEY if ssl_context else None,
        cert=config.WEBHOOK_SSL_CERT if ssl_context else None,
    )
    logger.info("PTB Webhook mode has finished.")


def run_polling_mode():
    """Configures and runs the bot in polling mode."""
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: Telegram Bot Token missing in config. Bot will not start in polling mode.")
        return

    logger.info("Creating TelegramBot instance for polling mode...")
    try:
        bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
        ptb_app = bot_instance.application
    except Exception as e:
        logger.error(f"Failed to create bot instance for polling: {e}", exc_info=True)
        return

    ptb_app.post_init = perform_startup_tasks
    ptb_app.post_shutdown = post_shutdown_tasks

    logger.info("Starting PTB Application in polling mode...")
    # run_polling will internally call bot.delete_webhook() if drop_pending_updates=True
    ptb_app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True # Recommended to drop when starting polling
    )
    logger.info("PTB Polling mode has finished.")


# Entry Point
if __name__ == "__main__":
    try:
        logging.basicConfig(
            format=config.LOG_FORMAT, level=config.LOG_LEVEL, force=True
        )
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger('apscheduler').setLevel(logging.WARNING) # Quiet down APScheduler INFO logs
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
        logger.info("Logging setup complete.")
    except Exception as e:
        # Fallback basic logging if setup fails
        logging.basicConfig(level=logging.ERROR)
        logger = logging.getLogger(__name__) # Re-ensure logger is defined
        logger.error(f"Logging setup failed: {e}", exc_info=True)

    logger.info(f"Starting application in {config.BOT_MODE.upper()} mode...")

    try:
        if config.BOT_MODE == "dev":
            run_webhook_mode()
        elif config.BOT_MODE == "production":
            run_polling_mode()
        else:
            # This case should be caught by config.py, but as a safeguard:
            logger.error(f"Invalid BOT_MODE '{config.BOT_MODE}' at runtime. Set to 'polling' or 'webhook'. Defaulting to polling.")
            run_polling_mode()

    except (KeyboardInterrupt, SystemExit) as e:
        logger.info(f"Application received {type(e).__name__}. Exiting gracefully.")
    except Exception as e: # Catch any other unexpected errors at the top level
        logger.error(f"Unhandled exception at top application level: {e}", exc_info=True)
    finally:
        # PTB's run_webhook/run_polling will manage and clean up its own asyncio loop.
        logger.info("Application finished.")