# bot.py
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
)
import handlers # Bot Handlers


logger = logging.getLogger(__name__)

class TelegramBot:
    """Encapsulates the Telegram Bot Application and its execution."""

    def __init__(self, token: str):
        """Initializes the bot with the Telegram token."""
        if not token or token == "YOUR_BOT_TOKEN_HERE":
            raise ValueError("Invalid Telegram Bot Token provided.")
        logger.info("Initializing Telegram Bot Class...")
        self.token = token
        logger.debug("Creating Application builder...")
        builder = Application.builder().token(self.token)
        logger.debug("Building Application...")
        self.application = builder.build()
        logger.debug("Application built.")
        # Handlers are registered just before running
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Registers all command, message, and callback query handlers."""
        try:
            logger.debug("Registering handlers...")

            # Command Handlers
            self.application.add_handler(CommandHandler("start", handlers.start))
            self.application.add_handler(CommandHandler("help", handlers.help_command))
            # Add other command handlers...

            # Reply Keyboard Button Handlers (as MessageHandlers)
            self.application.add_handler(MessageHandler(
                filters.Text(["🛒 خرید غذا"]), handlers.handle_buy_food
            ))
            self.application.add_handler(MessageHandler(
                filters.Text(["🏷️ فروش غذا"]), handlers.handle_sell_food
            ))
            self.application.add_handler(MessageHandler(
                filters.Text(["⚙️ تنظیمات"]), handlers.handle_settings
            ))

            # Callback Query Handler (for potential Inline Keyboards)
            # Uncomment if you add inline keyboards and a handler function for them
            # self.application.add_handler(CallbackQueryHandler(handlers.button_handler))

            # Generic Text Handler (Must come AFTER specific text handlers)
            self.application.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND, handlers.echo
            ))

            logger.debug("Handlers registered successfully.")

        except Exception as e:
            logger.error(f"Handler registration failed: {e}", exc_info=True)
            # Depending on severity, you might want to raise this
            raise RuntimeError(f"Failed to register handlers: {e}")


    async def run(self) -> None:
        """Starts the bot's polling loop and waits for termination."""
        logger.info("Starting bot execution via TelegramBot class...")
        try:
            # --- Run the bot using Application's async context manager ---
            # The context manager handles initialize(), start(), stop(), shutdown().
            async with self.application:
                logger.debug("Initializing application...")
                await self.application.initialize()
                logger.debug("Starting application update handling...")
                await self.application.start()
                logger.debug("Starting polling...")
                await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

                logger.info("Bot is running via class. Press Ctrl+C to stop.")

                # Keep the application running indefinitely
                stop_event = asyncio.Event()
                await stop_event.wait()

        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received by bot class.")
        except Exception as e:
            logger.error(f"An error occurred during bot execution in class: {e}", exc_info=True)
        finally:
            logger.info("Bot class shutdown process initiating or completed.")