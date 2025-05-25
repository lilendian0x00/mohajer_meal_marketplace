import logging
import asyncio
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application
import config
from logging_config import setup_logging

# Configure logger
setup_logging()

# Now that logging is configured, get the logger for this module
logger = logging.getLogger(__name__)


from self_market.db import crud
from background_tasks import (
    check_pending_listings_timeout,
    update_meals_from_samad,
    cleanup_past_meal_listings
)
from config import (
    BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES,
    BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES,
    BACKGROUND_PAST_MEAL_LISTING_CLEANUP_INTERVAL_MINUTES
)
from bot import TelegramBot
from self_market.db.session import init_db, get_db_session

scheduler_ref: AsyncIOScheduler | None = None

async def synchronize_admin_permissions():
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
                logger.warning(f"Admin ID {tg_id} from config.py not found in DB. User needs to interact first.")
        current_db_admins = await crud.get_all_db_admin_users(db)
        for db_admin_user in current_db_admins:
            if db_admin_user.telegram_id not in config_admin_ids:
                await crud.set_user_admin_state(db, db_admin_user.telegram_id, False)
                revoked_count += 1
    if granted_count > 0 or revoked_count > 0:
        logger.info(f"Admin permissions sync complete. Granted: {granted_count}, Revoked: {revoked_count}.")
    else:
        logger.info("Admin permissions sync complete. No changes needed.")


async def perform_startup_tasks(ptb_app: Application):
    global scheduler_ref
    logger.info("Performing startup tasks...")
    logger.info(f"Using Database: {config.DATABASE_URL}")
    try:
        logger.info("Initializing database schema (delegating to Alembic, init_db may only seed).")
        await init_db()  # init_db should NOT call create_all if Alembic is used
    except Exception as e:
        logger.critical(f"Database initialization/seeding failed: {e}. Aborting.", exc_info=True)
        raise SystemExit("DB Init/Seed Failed")
    try:
        await synchronize_admin_permissions()
    except Exception as e:
        logger.error(f"Failed to sync admin permissions: {e}", exc_info=True)

    if scheduler_ref is None or not scheduler_ref.running:
        scheduler_ref = AsyncIOScheduler(timezone="UTC")  # Ensure timezone consistency
        logger.info("APScheduler instance created.")

        tasks_to_schedule = [
            (check_pending_listings_timeout, BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES, 'check_timeouts_job'),
            (update_meals_from_samad, BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES, 'update_meals_from_samad_job'),
            (cleanup_past_meal_listings, BACKGROUND_PAST_MEAL_LISTING_CLEANUP_INTERVAL_MINUTES,
             'cleanup_past_meal_listings_job')
        ]

        for task_func, interval_minutes, job_id in tasks_to_schedule:
            scheduler_ref.add_job(
                task_func,
                trigger='interval',
                next_run_time=datetime.now(timezone.utc),  # Run at startup
                minutes=interval_minutes,
                id=job_id,
                replace_existing=True,
                misfire_grace_time=300,  # Allow 5 mins grace for misfires
                kwargs={'app': ptb_app}
            )
            logger.info(f"Scheduled background task '{job_id}' to run every {interval_minutes} minutes.")

        if not scheduler_ref.running:
            scheduler_ref.start()
            logger.info("APScheduler started.")
    else:
        logger.info("APScheduler instance already exists and is running.")
    logger.info("Startup tasks complete.")


async def post_shutdown_tasks(app: Application | None = None):
    global scheduler_ref
    logger.info("Performing post-shutdown tasks...")
    if scheduler_ref and scheduler_ref.running:
        logger.info("Shutting down APScheduler...")
        scheduler_ref.shutdown(wait=True)
        logger.info("APScheduler shutdown complete.")
    logger.info("Post-shutdown tasks complete.")


def run_webhook_mode():
    logger.info("Configuring for webhook mode...")
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":  # Basic check
        logger.critical("FATAL: Telegram Bot Token missing. Cannot start.")
        return
    if not config.WEBHOOK_BASE_URL:
        logger.critical("FATAL: WEBHOOK_BASE_URL missing. Cannot start in webhook mode.")
        return

    webhook_url_path = f"/{config.TELEGRAM_BOT_TOKEN.strip('/')}"
    full_webhook_url_for_telegram = f"{config.WEBHOOK_BASE_URL.rstrip('/')}{webhook_url_path}"

    logger.info("Creating TelegramBot instance for webhook mode...")
    bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
    ptb_app = bot_instance.application
    ptb_app.post_init = perform_startup_tasks
    ptb_app.post_shutdown = post_shutdown_tasks

    logger.info(f"Webhook URL for Telegram: {full_webhook_url_for_telegram}")
    logger.info(
        f"PTB listening on IP: {config.WEBHOOK_LISTEN_IP}, Port: {config.WEBHOOK_LISTEN_PORT}, Path: {webhook_url_path}")

    ssl_args = {}
    if config.WEBHOOK_SSL_CERT and config.WEBHOOK_SSL_KEY:
        ssl_args['key'] = config.WEBHOOK_SSL_KEY
        ssl_args['cert'] = config.WEBHOOK_SSL_CERT
        logger.info(f"Using SSL: cert='{config.WEBHOOK_SSL_CERT}', key='{config.WEBHOOK_SSL_KEY}'")
    elif config.WEBHOOK_SSL_CERT or config.WEBHOOK_SSL_KEY:
        logger.warning("WEBHOOK_SSL_CERT or WEBHOOK_SSL_KEY is set, but not both. SSL will NOT be used.")

    ptb_app.run_webhook(
        listen=config.WEBHOOK_LISTEN_IP,
        port=config.WEBHOOK_LISTEN_PORT,
        secret_token=config.WEBHOOK_SECRET_TOKEN or None,
        webhook_url=full_webhook_url_for_telegram,
        url_path=webhook_url_path,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        **ssl_args
    )
    logger.info("PTB Webhook mode finished.")


def run_polling_mode():
    logger.info("Configuring for polling mode...")
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":  # Basic check
        logger.critical("FATAL: Telegram Bot Token missing. Cannot start.")
        return

    logger.info("Creating TelegramBot instance for polling mode...")
    bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
    ptb_app = bot_instance.application
    ptb_app.post_init = perform_startup_tasks
    ptb_app.post_shutdown = post_shutdown_tasks

    logger.info("Starting PTB Application in polling mode...")
    ptb_app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
    logger.info("PTB Polling mode finished.")


if __name__ == "__main__":
    # Logging is now set up by the call to setup_logging() above the module-level logger.
    # The logger for this __main__ module is obtained *after* that setup.

    logger.info(f"Starting application in {config.BOT_MODE.upper()} mode...")
    try:
        if config.BOT_MODE == "production":
            run_webhook_mode()
        elif config.BOT_MODE == "dev":
            run_polling_mode()
        else:
            logger.error(
                f"Invalid BOT_MODE '{config.BOT_MODE}'. Expected 'dev' or 'production'. Defaulting to dev (polling).")
            run_polling_mode()
    except (KeyboardInterrupt, SystemExit) as e:
        logger.info(f"Application shutdown initiated ({type(e).__name__}).")
    except Exception as e:
        logger.critical(f"Unhandled exception at top application level: {e}", exc_info=True)
    finally:
        logger.info("Application finished.")