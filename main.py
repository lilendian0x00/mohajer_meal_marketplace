import logging
import asyncio
import config
from bot import TelegramBot
from self_market.db.session import init_db

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

    # Create and Run Bot Instance
    try:
        logger.info("Creating TelegramBot instance...")
        bot_instance = TelegramBot(token=config.TELEGRAM_BOT_TOKEN)
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