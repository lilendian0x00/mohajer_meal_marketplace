import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import config
import handlers
from self_market.db.session import init_db

# Logging Setup
try:
    logging.basicConfig(
        format=config.LOG_FORMAT, level=config.LOG_LEVEL, force=True
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.debug("Logging setup complete.") # Optional: debug level log
except Exception as e:
    # Fallback logging if setup fails
    logging.basicConfig(level=logging.ERROR) # Basic config
    logger = logging.getLogger(__name__)
    logger.error(f"Logging setup failed: {e}", exc_info=True)


# --- Main Async Function ---
async def main() -> None:
    """Initializes DB, sets up and runs the bot application."""

    # --- Token Check ---
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: Telegram Bot Token missing.")
        return
    logger.debug("Token checked.")

    logger.info(f"Using Database: {config.DATABASE_URL}")

    # --- Application Setup ---
    try:
        logger.debug("Creating Application builder...")
        builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
        logger.debug("Building Application...")
        application = builder.build()
        logger.debug("Application built.")
    except Exception as e:
        logger.error(f"Application build failed: {e}", exc_info=True)
        return # Cannot continue without application object

    # --- Handler Registration ---
    try:
        logger.debug("Registering handlers...")
        application.add_handler(CommandHandler("start", handlers.start))
        application.add_handler(CommandHandler("help", handlers.help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.echo))

        # --- Register Handlers for Reply Keyboard Buttons ---
        application.add_handler(MessageHandler(
            filters.Text(["🛒 خرید غذا"]),
            handlers.handle_buy_food
        ))
        application.add_handler(MessageHandler(
            filters.Text(["🏷️ فروش غذا"]),
            handlers.handle_sell_food
        ))
        application.add_handler(MessageHandler(
            filters.Text(["⚙️ تنظیمات"]),
            handlers.handle_settings
        ))
        logger.debug("Handlers registered.")
    except Exception as e:
        logger.error(f"Handler registration failed: {e}", exc_info=True)
        return

    # DB initialization
    try:
        logger.info("Initializing database schema...")
        await init_db()
    except Exception as e:
        logger.error("Database initialization failed. Bot will not start.")
        return # Exit if DB init fails

    # Start the bot
    logger.info("Starting bot...")
    try:
        async with application:
            logger.debug("Initializing application...")
            await application.initialize()
            logger.debug("Starting application update handling...")
            await application.start()
            logger.debug("Starting polling...")
            await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

            logger.info("Bot is running. Press Ctrl+C to stop.")

            # Keep the application running
            stop_event = asyncio.Event()
            await stop_event.wait()

    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received.")
    except Exception as e:
        logger.error(f"An error occurred during bot execution: {e}", exc_info=True)
    finally:
        # Cleanup is handled by 'async with application:' context manager
        logger.info("Bot shutdown process initiating or completed.")


# Entry point
if __name__ == "__main__":
    try:
        logger.debug("Calling asyncio.run(main())")
        asyncio.run(main())
    except RuntimeError as e:
        # Suppress common "Event loop is closed" error on Windows during final cleanup
        if "Event loop is closed" in str(e) and "Win" in asyncio.ProactorEventLoop.__module__:
             logger.warning("Suppressed 'Event loop is closed' error during final Windows cleanup.")
             pass
        else:
             logger.exception("Application level RuntimeError:", exc_info=e)
    except KeyboardInterrupt:
        # Already handled within main() or by asyncio.run() exiting
        logger.debug("Application level KeyboardInterrupt caught.")
        pass
    finally:
        logger.info("Application finished.")