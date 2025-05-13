import html
import logging
import asyncio
import re
import traceback
from urllib.parse import urlparse

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, ContextTypes,
    PicklePersistence
)

import config
import handlers # Bot Handlers

logger = logging.getLogger(__name__)

# --- Global Error Handler ---
async def ptb_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Log Errors caused by Updates and send detailed message to admin users.
    """
    # Log the error before we do anything else
    logger.error(f"PTB Exception while handling an update:", exc_info=context.error)

    # Optionally ignore common errors like MessageNotModified if desired
    # if isinstance(context.error, telegram.error.BadRequest) and \
    #    context.error.message == "Message is not modified":
    #     logger.info("Ignoring MessageNotModified error.")
    #     return

    # Prepare traceback
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Get update type and user info (if available)
    update_type = "N/A"
    user_info = "N/A"
    chat_info = "N/A"
    effective_update = None

    if isinstance(update, Update):
        effective_update = update
        update_type = update.__class__.__name__
        if update.effective_user:
            user = update.effective_user
            user_info = f"ID: {user.id}"
            if user.username: user_info += f" | @{user.username}"
            if user.first_name: user_info += f" | Name: {user.first_name}"
        if update.effective_chat:
            chat_info = f"ID: {update.effective_chat.id}"
            if update.effective_chat.title: chat_info += f" | Title: {update.effective_chat.title}"
            if update.effective_chat.username: chat_info += f" | @{update.effective_chat.username}"
            if update.effective_chat.type: chat_info += f" | Type: {update.effective_chat.type}"

    # Format the message for admins using HTML
    # Escape everything going into the message
    escaped_error_str = html.escape(str(context.error))
    escaped_update_type = html.escape(update_type)
    escaped_user_info = html.escape(user_info)
    escaped_chat_info = html.escape(chat_info)

    # Limit traceback length to avoid hitting Telegram message limits (4096 chars)
    # Leave space for other text (~300-400 chars)
    max_tb_length = 3600
    escaped_traceback_snippet = html.escape(tb_string[-max_tb_length:])
    if len(tb_string) > max_tb_length:
        escaped_traceback_snippet = "...\n" + escaped_traceback_snippet # Indicate truncation

    message = (
        f"<b>⚠ BOT ERROR ENCOUNTERED ⚠</b>\n\n"
        f"<b>Error:</b>\n<pre>{escaped_error_str}</pre>\n\n"
        f"<b>Update Type:</b> {escaped_update_type}\n"
        f"<b>User:</b> {escaped_user_info}\n"
        f"<b>Chat:</b> {escaped_chat_info}\n\n"
        f"<b>Traceback (last {max_tb_length} chars):</b>\n<pre>{escaped_traceback_snippet}</pre>"
    )

    # Send message to all admins configured in config.py
    if config.ADMIN_TELEGRAM_IDS:
        for admin_id in config.ADMIN_TELEGRAM_IDS:
            try:
                # Use context.bot to send the message
                await context.bot.send_message(
                    chat_id=admin_id, text=message, parse_mode=ParseMode.HTML
                )
                logger.debug(f"Sent error notification to admin {admin_id}")
            except Exception as e_notify:
                # Log failure to notify admin, but don't raise further errors
                logger.error(f"Failed to send error notification to admin {admin_id}: {e_notify}")
    else:
        logger.warning("ADMIN_TELEGRAM_IDS list is empty in config. Cannot send error notifications.")



class TelegramBot:
    """Encapsulates the Telegram Bot Application and its execution."""

    def __init__(self, token: str):
        """Initializes the bot with the Telegram token."""
        if not token or token == "YOUR_BOT_TOKEN_HERE":
            raise ValueError("Invalid Telegram Bot Token provided.")
        logger.info("Initializing Telegram Bot Class...")
        self.token = token
        builder = Application.builder().token(self.token)

        # Persistence setup
        if config.BOT_PERSISTENCE_FILEPATH:  # Check if path is configured
            try:
                persistence = PicklePersistence(filepath=config.BOT_PERSISTENCE_FILEPATH)
                builder.persistence(persistence)
                logger.info(f"Persistence enabled at: {config.BOT_PERSISTENCE_FILEPATH}")
            except Exception as e:
                logger.error(f"Failed to initialize persistence: {e}. Continuing without persistence.")
        else:
            logger.info("BOT_PERSISTENCE_FILEPATH not set. Running without persistence.")

        self.application = builder.build()
        self.application.add_error_handler(ptb_error_handler)   # Register the global error handler
        logger.info("Custom global error handler registered.")
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Registers all command, message, and callback query handlers."""
        try:
            logger.debug("Registering handlers...")

            # Verification Conversation Handler (Group 0)
            verification_conv_handler = ConversationHandler(
                entry_points=[CommandHandler("start", handlers.start)],  # Start command triggers it
                states={
                    # handlers.ASK_EDU_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_education_number)],
                    # handlers.ASK_ID_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_identity_number)],
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

            # Add Meal Conversation Handler
            self.application.add_handler(handlers.add_meal_conv_handler, group=0)

            # Other Command Handlers (Group 1)
            self.application.add_handler(CommandHandler("help", handlers.help_command), group=1)

            # These handlers react to the main menu button texts if NOT captured by a conversation entry point.
            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_BUY_FOOD)}$') & (~filters.COMMAND),
                               handlers.handle_buy_food), group=1)

            # "My Listing" button
            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_MY_LISTINGS)}$') & (~filters.COMMAND),
                               handlers.handle_my_listings), group=1)

            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_SETTINGS)}$') & (~filters.COMMAND),
                               handlers.handle_settings), group=1)  # This shows the settings menu with inline buttons

            self.application.add_handler(
                MessageHandler(filters.Regex(f'^{re.escape(handlers.BTN_HISTORY)}$') & (~filters.COMMAND),
                               handlers.handle_history), group=1)

            # Callback Query Handler (for potential Inline Keyboards)
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_buy_refresh, pattern=f'^{handlers.CALLBACK_BUY_REFRESH}$'
            ), group=1)

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
            self.application.add_handler(CallbackQueryHandler(  # Buyer cancels AFTER confirming and seeing seller details
                    handlers.handle_buyer_cancel_pending, pattern=fr'^{handlers.CALLBACK_BUYER_CANCEL_PENDING}_\d+$'
            ), group=1)


            # Seller Confirmation
            self.application.add_handler(CallbackQueryHandler(
                handlers.handle_seller_confirmation, pattern=r'^seller_confirm_\d+$'
            ), group=1)

            # Seller Rejection
            self.application.add_handler(CallbackQueryHandler(  # Seller rejects/cancels pending purchase
                handlers.handle_seller_reject_pending, pattern=fr'^{handlers.CALLBACK_SELLER_REJECT_PENDING}_\d+$'
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

            admin_handler_group = 10  # Using a new group for admin commands
            self.application.add_handler(CommandHandler("setadmin", handlers.set_admin_status),
                                         group=admin_handler_group)
            self.application.add_handler(CommandHandler("setactive", handlers.set_active_status),
                                         group=admin_handler_group)
            self.application.add_handler(CommandHandler("getuser", handlers.get_user_info), group=admin_handler_group)
            self.application.add_handler(CommandHandler("listusers", handlers.list_users_command),
                                         group=admin_handler_group)
            self.application.add_handler(CallbackQueryHandler(handlers.list_users_callback,
                                                              pattern=f"^{handlers.CALLBACK_ADMIN_LIST_USERS_PAGE}\\d+$"),
                                         group=admin_handler_group)
            self.application.add_handler(CallbackQueryHandler(handlers.admin_noop_callback, pattern=r'^admin_noop$'),
                                         group=admin_handler_group)

            self.application.add_handler(CommandHandler("delmeal", handlers.delete_meal_command),
                                         group=admin_handler_group)
            self.application.add_handler(CommandHandler("dellisting", handlers.delete_listing_command),
                                         group=admin_handler_group)

            # Generic Text Handler (Group 2)
            # self.application.add_handler(MessageHandler(
            #     filters.TEXT & ~filters.COMMAND, handlers.echo
            # ), group=2)

            logger.debug("Handlers registered successfully.")

        except Exception as e:
            logger.error(f"Handler registration failed: {e}", exc_info=True)
            # Depending on severity, you might want to raise this
            raise RuntimeError(f"Failed to register handlers: {e}")

    async def set_bot_webhook(self, webhook_url: str, secret_token: str | None = None):
        """Sets the webhook with Telegram. Called after app initialization."""
        logger.info(f"Attempting to set webhook with Telegram: {webhook_url}")
        await self.application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            secret_token=secret_token,
            drop_pending_updates=True
        )
        logger.info(f"Webhook set successfully with Telegram at {webhook_url}")

    async def run_ptb_webhook_server(
            self,
            listen_ip: str = "0.0.0.0",
            listen_port: int = 8000,
            secret_token: str | None = None,
            webhook_url_for_ptb: str | None = None  # The full URL PTB needs to match path
    ):
        """Runs the PTB webhook server. Assumes app is initialized and webhook is set."""
        logger.info(f"Starting PTB internal webhook server on {listen_ip}:{listen_port}")
        await self.application.run_webhook(
            listen=listen_ip,
            port=listen_port,
            secret_token=secret_token,
            webhook_url=webhook_url_for_ptb
        )
        logger.info("PTB webhook server has stopped.")