import logging
import asyncio
import re

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
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
        builder = Application.builder().token(self.token)
        self.application = builder.build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Registers all command, message, and callback query handlers."""
        try:
            logger.debug("Registering handlers...")

            # Verification Conversation Handler (Group 0)
            verification_conv_handler = ConversationHandler(
                entry_points=[CommandHandler("start", handlers.start)],  # Start command triggers it
                states={
                    handlers.ASK_EDU_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_education_number)],
                    handlers.ASK_ID_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_identity_number)],
                    handlers.ASK_PHONE: [MessageHandler(filters.CONTACT, handlers.receive_phone_number)],
                },
                fallbacks=[CommandHandler("cancel", handlers.cancel_verification)],
                # Optional: Add conversation timeout, persistence, etc.
                conversation_timeout=600, # 10 minutes timeout
                allow_reentry = True,
            )
            self.application.add_handler(verification_conv_handler, group=0)

            # Sell Food Conversation Handler (Group 0)
            # Needs to be defined before the MessageHandler that triggers it
            sell_conv_handler = ConversationHandler(
                entry_points=[
                    # Entry point is the "Sell Food" button text
                    MessageHandler(filters.Text(["🏷️ فروش غذا"]) & (~filters.COMMAND), handlers.handle_sell_food)],
                states={
                    handlers.SELL_ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_reservation_code)],
                    handlers.SELL_ASK_MEAL: [CallbackQueryHandler(handlers.receive_meal_selection, pattern=r'^sell_select_meal_\d+$')],
                    handlers.SELL_ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_price)],
                    handlers.SELL_CONFIRM: [
                        CallbackQueryHandler(handlers.confirm_listing, pattern='^confirm_listing_yes$'),
                        CallbackQueryHandler(handlers.cancel_listing_creation, pattern='^confirm_listing_no$')
                    ],
                },
                fallbacks=[
                    CommandHandler("cancel", handlers.cancel_sell_conversation),
                    CallbackQueryHandler(handlers.handle_inline_cancel_sell,
                                         pattern=f'^{handlers.CALLBACK_CANCEL_SELL_FLOW}$')
                ],
                allow_reentry=True
            )
            self.application.add_handler(sell_conv_handler, group=0)

            # Settings - Update Card Conversation Handler (Group 0)
            settings_card_conv_handler = ConversationHandler(
                # Entry point is the callback query from the button in handle_settings
                entry_points=[CallbackQueryHandler(handlers.handle_settings_update_card_button,
                                                   pattern='^settings_update_card$')],
                states={
                    handlers.SETTINGS_ASK_CARD: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_settings_card_number)]
                },
                fallbacks=[CommandHandler('cancel', handlers.cancel_settings_card_update)],
                allow_reentry=True,
                conversation_timeout=300,  # 5 minutes timeout for entering card
                # name="settings_card_update_conversation", # Optional
                # persistent=True # Optional
            )
            self.application.add_handler(settings_card_conv_handler, group=0)

            # Other Command Handlers (Group 1)
            self.application.add_handler(CommandHandler("help", handlers.help_command), group=1)

            # These handlers react to the main menu button texts if NOT captured by a conversation entry point.
            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_BUY_FOOD)}$') & (~filters.COMMAND),
                               handlers.handle_buy_food), group=1)

            # "My Listing" button
            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_MY_LISTINGS)}$') & (~filters.COMMAND),
                               handlers.handle_my_listings), group=1)  # ADD THIS

            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_SETTINGS)}$') & (~filters.COMMAND),
                               handlers.handle_settings), group=1)  # This shows the settings menu with inline buttons

            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_HISTORY)}$') & (~filters.COMMAND),
                               handlers.handle_history), group=1)  # ADD THIS

            # Callback Query Handler (for potential Inline Keyboards)
            # Initial Buy Button press
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_purchase_button, pattern=r'^buy_listing_\d+$'
            ), group=1)

            # Buyer Confirmation
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_confirm_purchase, pattern=r'^confirm_buy_\d+$'
            ), group=1)

            # Buyer Cancellation
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_cancel_purchase, pattern=r'^cancel_buy$'
            ), group=1)

            # Seller Confirmation
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_seller_confirmation, pattern=r'^seller_confirm_\d+$'
            ), group=1)

            # Settings Flow Callback
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_settings_back_main, pattern=r'^settings_back_main$'
            ), group=1)

            # Listing
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_cancel_available_listing_button, pattern=r'^cancel_listing_\d+$'
            ), group=1)

            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_history_view, pattern=r'^history_(purchases|sales)_\d+$'
            ), group=1)
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_history_back_select, pattern=r'^history_back_select$'
            ), group=1)
            # Handler for no-operation page number button
            self.application.add_handler(CallbackQueryHandler(
                lambda update, context: update.callback_query.answer(), pattern=r'^history_noop$'
            ), group=1)

            # Generic Text Handler (Group 2)
            # self.application.add_handler(MessageHandler(
            #     filters.TEXT & ~filters.COMMAND, handlers.echo
            # ), group=2)

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
                async with self.application:
                    await self.application.initialize()
                    await self.application.start()
                    await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
                    logger.info("Bot is running via class. Press Ctrl+C to stop.")
                    stop_event = asyncio.Event()
                    await stop_event.wait()

        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received by bot class.")
        except Exception as e:
            logger.error(f"Error during bot execution: {e}", exc_info=True)
        finally:
            logger.info("Bot class shutdown process initiating or completed.")