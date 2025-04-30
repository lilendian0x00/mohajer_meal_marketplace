import logging
from typing import Optional
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from self_market.db.session import get_db_session
from self_market.db import crud

logger = logging.getLogger(__name__)

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends welcome message, registers/updates user, and shows the main Reply Keyboard."""
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Could not get user from update in /start command.")
        return

    logger.info(f"/start command received from user_id: {telegram_user.id}")

    db_user = None

    # --- Database Interaction  ---
    try:
        async with get_db_session() as db_session:
            db_user = await crud.get_or_create_user(db_session, telegram_user)
            logger.info(f"User {db_user.username} (ID: {db_user.id}, TG_ID: {db_user.telegram_id}) processed.")
    except Exception as e:
        logger.error(f"Error processing /start user DB interaction for {telegram_user.id}: {e}", exc_info=True)
        await update.message.reply_text(
            "ببخشید، مشکلی در پردازش پروفایل شما پیش آمد. لطفا دوباره امتحان کنید."
        )
        return

    # Create Personalized Welcome Message
    user_display_name = telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
    welcome_message = (
        f"سلام {user_display_name} عزیز! 👋\n"
        "به ربات خرید و فروش غذای مهاجر خوش آمدید.\n\n"
        "از دکمه‌های زیر برای ادامه استفاده کنید:"  # Use the buttons below to continue:
    )

    # Check if the user has verified
    if not db_user.is_verified:
        keyboard = [
            [KeyboardButton("✅ اعتبارسنجی")],
        ]

        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,  # Recommended: Adjusts button height
            one_time_keyboard=False,  # Keyboard stays visible until removed/replaced
            input_field_placeholder="گزینه مورد نظر را انتخاب کنید..."  # Optional: Placeholder text
            # persistent=True # Default is False, True keeps it across restarts for the user
        )

        if update.message:
            await update.message.reply_text(welcome_message, reply_markup=reply_markup)

        return


    # --- Create Reply Keyboard Buttons ---
    # Using the exact text the user will send when clicking
    keyboard = [
        # Row 1: Buy and Sell buttons
        [KeyboardButton("🛒 خرید غذا"), KeyboardButton("🏷️ فروش غذا")],
        # Row 2: Settings button (centered if possible, but default layout works)
        [KeyboardButton("⚙️ تنظیمات")]
    ]
    # Create the ReplyKeyboardMarkup object
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,         # Recommended: Adjusts button height
        one_time_keyboard=False,      # Keyboard stays visible until removed/replaced
        input_field_placeholder="گزینه مورد نظر را انتخاب کنید..." # Optional: Placeholder text
        # persistent=True # Default is False, True keeps it across restarts for the user
    )

    # Send Message with Reply Keyboard
    if update.message:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    # Note: Sending/updating ReplyKeyboard via callback_query is not standard practice.
    # If /start is triggered via callback, you might need to send a new message.


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays help message."""
    await update.message.reply_text(
        "برای شروع کار با ربات از دستور /start استفاده کنید.\n"
        "برای راهنمایی بیشتر از دستور /help استفاده کنید."
    )


# --- Message Handlers ---

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text messages that are not commands or known keyboard buttons."""
    # This handler might need to be removed or adjusted once you add handlers
    # for the keyboard button texts below.
    if update.message and update.message.text:
        logger.info(f"Received unhandled text message from {update.effective_user.username}: {update.message.text}")
        await update.message.reply_text(
             f"پیام '{update.message.text}' دریافت شد. برای نمایش منوی اصلی /start را بزنید."
        )
    else:
        logger.info("Received non-text message, ignoring.")


async def handle_buy_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Buy Food' button press."""
    user_id = update.effective_user.id
    logger.info(f"'Buy Food' button pressed by user {user_id}")
    # TODO: Add logic to show available listings...
    await update.message.reply_text("لیست غذاهای موجود برای خرید به زودی نمایش داده می‌شود...") # Food listings coming soon...

async def handle_sell_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Sell Food' button press."""
    user_id = update.effective_user.id
    logger.info(f"'Sell Food' button pressed by user {user_id}")
    # TODO: Add logic to start the selling process (e.g., ask for reservation code)...
    await update.message.reply_text("برای فروش غذا، لطفا کد رزرو دانشگاه خود را وارد کنید:") # To sell food, enter your uni reservation code:

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Settings' button press."""
    user_id = update.effective_user.id
    logger.info(f"'Settings' button pressed by user {user_id}")
    # Add logic to show user settings...
    # TODO: Maybe show inline buttons for specific settings?
    await update.message.reply_text("بخش تنظیمات به زودی فعال خواهد شد.") # Settings section coming soon.