# handlers.py
import logging
import re # For basic validation
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Contact
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters, CommandHandler # Import conversation components

import utility
# Assuming your models and crud are in self_market package
from self_market.db.session import get_db_session
from self_market.db import crud
# Assuming models.py is in self_market package
from self_market import models

logger = logging.getLogger(__name__)

# --- Define Conversation States ---
(ASK_EDU_NUM, ASK_ID_NUM, ASK_PHONE, VERIFICATION_COMPLETE) = range(4)
# Using range is convenient for simple linear flows

# --- Helper Function for Main Menu Keyboard ---
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Returns the main ReplyKeyboardMarkup."""
    keyboard = [
        [KeyboardButton("🛒 خرید غذا"), KeyboardButton("🏷️ فروش غذا")],
        [KeyboardButton("⚙️ تنظیمات")]
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="گزینه مورد نظر را انتخاب کنید..."
    )

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Handles the /start command.
    Checks if user exists/is verified. Shows main menu or starts verification conversation.
    Returns the next state for the ConversationHandler.
    """
    telegram_user = update.effective_user
    message = update.message # Use message directly if available
    if not telegram_user or not message:
        logger.warning("Could not get user or message from update in /start command.")
        return ConversationHandler.END # End conversation if basic info missing

    logger.info(f"/start command received from user_id: {telegram_user.id}")

    db_user: models.User | None = None
    # --- Get or Create User ---
    try:
        async with get_db_session() as db_session:
            # Use the existing function to ensure user record exists
            db_user = await crud.get_or_create_user(db_session, telegram_user)
            logger.info(f"User {db_user.username} (TG_ID: {db_user.telegram_id}) processed. Verified: {db_user.is_verified}")
    except Exception as e:
        logger.error(f"Error processing /start user DB interaction for {telegram_user.id}: {e}", exc_info=True)
        await message.reply_text(
            "ببخشید، مشکلی در پردازش پروفایل شما پیش آمد. لطفا دوباره امتحان کنید."
        )
        return ConversationHandler.END # End conversation on DB error

    # Should always have a db_user object here
    if not db_user:
         logger.error(f"DB user object is None after get_or_create for TG ID {telegram_user.id}, ending.")
         await message.reply_text("خطای داخلی رخ داد، لطفا بعدا تلاش کنید.") # Internal error occurred
         return ConversationHandler.END

    # --- Check Verification Status ---
    if db_user.is_verified:
        logger.info(f"User {telegram_user.id} is already verified. Showing main menu.")
        user_display_name = telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
        welcome_message = (
            f"سلام مجدد {user_display_name} عزیز! 👋\n" # Welcome back
            "از دکمه‌های زیر برای ادامه استفاده کنید:"
        )
        await message.reply_text(welcome_message, reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END # End conversation, user is verified
    else:
        # --- Start Verification Process ---
        logger.info(f"User {telegram_user.id} is not verified. Starting verification process.")
        user_display_name = telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
        welcome_message = (
            f"سلام {user_display_name} عزیز! 👋\n"
            "به ربات خرید و فروش غذای مهاجر خوش آمدید.\n\n"
            "برای استفاده از ربات، لطفا ابتدا فرآیند اعتبارسنجی را کامل کنید." # To use the bot, please first complete the verification process.
        )
        await message.reply_text(welcome_message) # Send initial welcome

        # Ask first question
        await message.reply_text(
            "۱. لطفا شماره دانشجویی خود را وارد کنید:", # 1. Please enter your educational number:
            reply_markup=ReplyKeyboardRemove() # Remove previous keyboard if any
            )
        return ASK_EDU_NUM # Return the next state

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays help message."""
    # Check if user is potentially in a conversation
    if context.user_data and 'current_state' in context.user_data: # Check if in conversation
         await update.message.reply_text("شما در حال حاضر در فرآیند اعتبارسنجی هستید. برای لغو /cancel را بزنید.")
    else:
        await update.message.reply_text(
            "برای شروع کار با ربات از دستور /start استفاده کنید.\n"
            "برای راهنمایی بیشتر از دستور /help استفاده کنید.\n"
            "در طول فرآیند اعتبارسنجی، می‌توانید با دستور /cancel آن را لغو کنید."
        )

# --- Verification Conversation Handlers ---

async def receive_education_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives educational number, saves it, asks for ID number."""
    message = update.message
    if not message or not message.text:
        return ASK_EDU_NUM # Stay in current state if no text

    edu_num = message.text.strip()
    logger.info(f"User {update.effective_user.id} entered educational number: {edu_num}")

    # --- Basic Validation (Example: Check if numeric) ---
    if not edu_num.isdigit():
        await message.reply_text("شماره دانشجویی نامعتبر است. لطفا فقط عدد وارد کنید:")
        return ASK_EDU_NUM # Ask again

    # TODO: Maybe add a check?

    context.user_data['edu_num'] = edu_num # Store in context temporarily

    await message.reply_text("۲. لطفا شماره ملی خود را وارد کنید:") # 2. Please enter your identity number:
    return ASK_ID_NUM # Move to next state

async def receive_identity_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives identity number, saves it, asks for phone number."""
    message = update.message
    if not message or not message.text:
        return ASK_ID_NUM

    id_num = message.text.strip()
    logger.info(f"User {update.effective_user.id} entered identity number: {'*' * len(id_num)}") # Log obfuscated

    # Validation
    if not id_num.isdigit() or not utility.is_valid_iranian_national_id(id_num): # Example for Iranian National ID
        await message.reply_text("شماره ملی نامعتبر است.")
        return ASK_ID_NUM # Ask again

    context.user_data['id_num'] = id_num

    # Ask for phone number using Telegram's contact sharing button
    phone_button = KeyboardButton("ارسال شماره تلفن من", request_contact=True) # Share my phone number
    cancel_button = KeyboardButton("/cancel") # Allow cancellation
    reply_markup = ReplyKeyboardMarkup([[phone_button], [cancel_button]], resize_keyboard=True, one_time_keyboard=True) # One time use for contact

    await message.reply_text(
        "۳. برای تایید نهایی، لطفا شماره تلفن خود را با استفاده از دکمه زیر به اشتراک بگذارید.", # 3. For final confirmation, please share your phone number using the button below.
        reply_markup=reply_markup
        )
    return ASK_PHONE # Move to next state

async def receive_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives shared contact, validates, updates DB, completes verification."""
    message = update.message
    user = update.effective_user
    contact: Contact | None = message.contact

    if not contact:
        logger.warning(f"User {user.id} sent non-contact message in ASK_PHONE state.")
        await message.reply_text("لطفا از دکمه 'ارسال شماره تلفن من' استفاده کنید یا /cancel را بزنید.")
        return ASK_PHONE # Stay in current state

    # --- Security Check: Ensure the contact shared belongs to the user sending it ---
    if contact.user_id != user.id:
        logger.warning(f"User {user.id} shared contact belonging to user {contact.user_id}.")
        await message.reply_text("خطا: شماره تلفن ارسال شده متعلق به شما نیست. لطفا دوباره تلاش کنید یا /cancel بزنید.")
        # Re-ask for phone
        phone_button = KeyboardButton("ارسال شماره تلفن من", request_contact=True)
        cancel_button = KeyboardButton("/cancel")
        reply_markup = ReplyKeyboardMarkup([[phone_button], [cancel_button]], resize_keyboard=True, one_time_keyboard=True)
        await message.reply_text(
            "لطفا شماره تلفن *خودتان* را با استفاده از دکمه زیر به اشتراک بگذارید.",
            reply_markup=reply_markup
        )
        return ASK_PHONE

    phone_num = contact.phone_number
    # Remove '+' if present for consistency, or keep it based on preference
    phone_num = phone_num.lstrip('+')
    logger.info(f"User {user.id} shared phone number: ...{phone_num[-4:]}") # Log partial

    # Retrieve data stored in context
    edu_num = context.user_data.get('edu_num')
    id_num = context.user_data.get('id_num')

    if not edu_num or not id_num:
        logger.error(f"Missing edu_num or id_num in user_data for user {user.id} during phone step.")
        await message.reply_text(
            "خطای داخلی رخ داد. لطفا فرآیند را با /start مجددا شروع کنید.",
            reply_markup=ReplyKeyboardRemove() # Remove keyboard
            )
        context.user_data.clear() # Clear potentially corrupt data
        return ConversationHandler.END

    # Update Database
    try:
        async with get_db_session() as db_session:
            updated_user = await crud.update_user_verification(
                db=db_session,
                telegram_id=user.id,
                edu_num=edu_num,
                id_num=id_num,
                phone_num=phone_num
            )
            if not updated_user:
                 # This case should ideally be handled inside update_user_verification or earlier
                 raise Exception("User not found during verification update")

            logger.info(f"User {user.id} successfully verified and details updated.")
            await message.reply_text(
                "✅ اعتبارسنجی شما با موفقیت انجام شد! از الان می‌توانید از امکانات ربات استفاده کنید.", # Your verification was successful! You can now use the bot features.
                reply_markup=get_main_menu_keyboard() # Show main menu
                )
            context.user_data.clear() # Clean up user_data
            return ConversationHandler.END # End the conversation

    except Exception as e:
        logger.error(f"Failed to update verification details for user {user.id} in DB: {e}", exc_info=True)
        await message.reply_text(
            "خطا در ذخیره اطلاعات اعتبارسنجی. لطفا دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.", # Error saving verification info. Please try again or contact support.
            reply_markup=ReplyKeyboardRemove()
            )
        context.user_data.clear()
        return ConversationHandler.END # End on DB error


async def cancel_verification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the verification process."""
    user = update.effective_user
    message = update.message
    logger.info(f"User {user.id} canceled the verification conversation.")
    context.user_data.clear() # Clear any stored data
    await message.reply_text(
        "فرآیند اعتبارسنجی لغو شد. برای شروع مجدد /start را بزنید.", # Verification process canceled. Press /start to begin again.
        reply_markup=ReplyKeyboardRemove() # Remove any special keyboard
        )
    return ConversationHandler.END


async def unexpected_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages that are not expected in the current conversation state."""
    message = update.message
    if message and message.text:
         logger.warning(f"User {update.effective_user.id} sent unexpected text '{message.text}' during verification.")
         await message.reply_text("ورودی نامعتبر است. لطفا طبق دستورالعمل پیش بروید یا /cancel را بزنید.")
    # Decide if state should change or remain the same depending on current state
    # Returning None keeps the state the same implicitly if used directly in ConversationHandler states dict
    # Or you can retrieve current state from context if needed to return it explicitly


# --- Handlers for main menu buttons (remain the same) ---

async def handle_buy_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Buy Food' button press."""
    user_id = update.effective_user.id
    # Optional: Check verification again, though they shouldn't see button if not verified
    logger.info(f"'Buy Food' button pressed by user {user_id}")
    await update.message.reply_text("لیست غذاهای موجود برای خرید به زودی نمایش داده می‌شود...")

async def handle_sell_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Sell Food' button press."""
    user_id = update.effective_user.id
    logger.info(f"'Sell Food' button pressed by user {user_id}")
    await update.message.reply_text("برای فروش غذا، لطفا کد رزرو دانشگاه خود را وارد کنید:")

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Settings' button press."""
    user_id = update.effective_user.id
    logger.info(f"'Settings' button pressed by user {user_id}")
    await update.message.reply_text("بخش تنظیمات به زودی فعال خواهد شد.")


# Generic echo handler
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        logger.info(f"Received unhandled text message from {update.effective_user.username}: {update.message.text}")
        await update.message.reply_text(
             f"پیام '{update.message.text}' دریافت شد. برای نمایش منوی اصلی /start را بزنید."
        )
    else:
        logger.info("Received non-text message, ignoring.")