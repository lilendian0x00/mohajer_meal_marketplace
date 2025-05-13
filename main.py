import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import atexit
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


async def initial_setup(app_for_scheduler: Application):
    """Performs all async setup tasks before starting the bot's main loop."""
    global scheduler
    logger.info("Performing initial async setup...")

    # Initialize DB
    try:
        logger.info("Initializing database schema...")
        await init_db()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}. Bot will not start.", exc_info=True)
        raise  # Re-raise to stop startup

    # Synchronize Admin Permissions
    try:
        await synchronize_admin_permissions()
    except Exception as e:
        logger.error(f"Failed to synchronize admin permissions during startup: {e}", exc_info=True)
        # Continue even if this fails, but log it.

    # Scheduler Setup
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        check_pending_listings_timeout,
        trigger='interval',
        next_run_time=datetime.now(), # Start soon
        minutes=BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES,
        id='check_timeouts_job',
        replace_existing=True,
        kwargs={'app': app_for_scheduler} # Pass the PTB application
    )
    scheduler.add_job(
        update_meals_from_samad,
        trigger='interval',
        next_run_time=datetime.now(), # Start soon
        minutes=config.BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES,
        id='update_meals_from_samad',
        replace_existing=True,
        misfire_grace_time=None,
        kwargs={'app': app_for_scheduler} # Pass the PTB application
    )
    scheduler.start()
    logger.info("APScheduler started.")
    logger.info("Initial async setup complete.")


async def app_main():
    """Main coroutine to set up and run the bot."""
    global ptb_application_instance, scheduler

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
    bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
    ptb_application_instance = bot_instance.application # Store for potential shutdown signal

    # Perform initial async setup (DB, Scheduler)
    try:
        await initial_setup(ptb_application_instance)
    except Exception as e_setup:
        logger.error(f"Critical error during initial setup: {e_setup}. Aborting.", exc_info=True)
        # Ensure scheduler is stopped if it started
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
        return # Stop if initial setup fails

    # Now, run the bot's webhook server. This will block until stopped.
    try:
        logger.info("Starting bot's webhook server...")
        await bot_instance.run_webhook_server(
            webhook_url=webhook_url,
            listen_ip=config.WEBHOOK_LISTEN_IP,
            listen_port=config.WEBHOOK_LISTEN_PORT,
            secret_token=config.WEBHOOK_SECRET_TOKEN or None
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Webhook server interrupted. PTB's context manager should handle its cleanup.")
    except Exception as e_run:
        logger.error(f"Error running webhook server: {e_run}", exc_info=True)
    finally:
        logger.info("Webhook server has finished or been interrupted.")
        # PTB's `async with self.application` in `bot_instance.run_webhook_server`
        # handles PTB application shutdown (including webhook deletion).
        # We just need to ensure our scheduler is stopped.
        if scheduler and scheduler.running:
            logger.info("Shutting down APScheduler in app_main finally...")
            scheduler.shutdown(wait=False)
            logger.info("APScheduler shutdown call initiated.")

# Entry Point
if __name__ == "__main__":
    logger.info("Starting application...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(app_main())
    except KeyboardInterrupt:
        logger.info("Application received KeyboardInterrupt. Main loop exiting.")
    except Exception as e:
        logger.error(f"Unhandled exception at top level: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up event loop...")
        # Gracefully close remaining tasks, etc.
        # This part can be complex. For now, just close.
        # Further shutdown logic for the scheduler if it wasn't stopped.
        if scheduler and scheduler.running: # Double check
            logger.warning("Scheduler still running during final cleanup. Attempting shutdown.")
            scheduler.shutdown(wait=False)

        # A more robust loop cleanup:
        try:
            pending = asyncio.all_tasks(loop=loop)
            if pending:
                logger.info(f"Cancelling {len(pending)} outstanding tasks...")
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception as e_cancel:
            logger.error(f"Error cancelling pending tasks: {e_cancel}")
        finally:
            logger.info("Closing event loop.")
            loop.close()

        logger.info("Application finished.")