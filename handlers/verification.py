import logging
import re

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Contact
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from config import WELCOME_MESSAGE
from .common import (
    ASK_EDU_NUM, ASK_ID_NUM, ASK_PHONE,
    get_main_menu_keyboard
)
import utility
from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models

logger = logging.getLogger(__name__)

# --- Start Command Handler (Entry point for verification) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Handles the /start command.
    Checks if user exists/is verified. Shows main menu or starts verification conversation.
    Returns the next state for the ConversationHandler.
    """
    telegram_user = update.effective_user
    message = update.message
    if not telegram_user or not message:
        logger.warning("Could not get user or message from update in /start command.")
        return ConversationHandler.END

    logger.info(f"/start command received from user_id: {telegram_user.id}")

    db_user: models.User | None = None
    try:
        async with get_db_session() as db_session:
            db_user = await crud.get_or_create_user(db_session, telegram_user)
            logger.info(f"User {db_user.username} (TG_ID: {db_user.telegram_id}) processed. Verified: {db_user.is_verified}")
    except Exception as e:
        logger.error(f"Error processing /start user DB interaction for {telegram_user.id}: {e}", exc_info=True)
        await message.reply_text("ببخشید، مشکلی در پردازش پروفایل شما پیش آمد. لطفا دوباره امتحان کنید.")
        return ConversationHandler.END

    if not db_user:
         logger.error(f"DB user object is None after get_or_create for TG ID {telegram_user.id}, ending.")
         await message.reply_text("خطای داخلی رخ داد، لطفا بعدا تلاش کنید.")
         return ConversationHandler.END

    # Escape user's name for MarkdownV2
    user_display_name_escaped = utility.escape_markdown_v2(
        telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
    )

    if db_user.is_verified:
        logger.info(f"User {telegram_user.id} is already verified. Showing main menu.")
        welcome_back_greeting = f"سلام مجدد {user_display_name_escaped} عزیز\\! 👋\n\n"

        replacement_text_escaped = utility.escape_markdown_v2(
            "شما اعتبارسنجی شده‌اید و می‌توانید از تمامی امکانات ربات استفاده کنید!"
        )

        # Construct the part to be replaced carefully based on how it's built in config.py
        part1 = utility.escape_markdown_v2("برای استفاده از امکانات ربات، ابتدا باید فرآیند")
        part2_bold = f"*{utility.escape_markdown_v2('اعتبارسنجی')}*"  # Correct bold for V2
        part3 = utility.escape_markdown_v2("را تکمیل کنید.")
        string_to_replace = f"{part1} {part2_bold} {part3}"

        full_welcome_message_for_verified = welcome_back_greeting + WELCOME_MESSAGE.replace(
            string_to_replace,
            replacement_text_escaped
        )

        await message.reply_text(
            full_welcome_message_for_verified,
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )
        return ConversationHandler.END
    else:
        logger.info(f"User {telegram_user.id} is not verified. Starting verification process.")

        new_user_greeting = f"سلام {user_display_name_escaped} عزیز\\! 👋\n"
        full_welcome_message_for_new = new_user_greeting + WELCOME_MESSAGE

        await message.reply_text(
            full_welcome_message_for_new,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )
        await message.reply_text(
            utility.escape_markdown_v2("1. لطفا شماره دانشجویی خود را وارد کنید:"),  # Also escape this prompt
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return ASK_EDU_NUM

# --- Verification Conversation Handlers ---
# async def receive_education_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     """Receives educational number, saves it, asks for ID number."""
#     message = update.message
#     if not message or not message.text:
#         return ASK_EDU_NUM
#
#     edu_num = message.text.strip()
#     logger.info(f"User {update.effective_user.id} entered educational number: {edu_num}")
#
#     if not edu_num.isdigit():
#         await message.reply_text("شماره دانشجویی نامعتبر است. لطفا فقط عدد وارد کنید:")
#         return ASK_EDU_NUM
#
#     context.user_data['edu_num'] = edu_num
#     await message.reply_text(
#         utility.escape_markdown_v2("2. لطفا شماره ملی خود را وارد کنید:"),
#         parse_mode=ParseMode.MARKDOWN_V2
#     )
#     return ASK_ID_NUM

# async def receive_identity_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     """Receives identity number, saves it, asks for phone number."""
#     message = update.message
#     if not message or not message.text: return ASK_ID_NUM
#
#     id_num = message.text.strip()
#     logger.info(f"User {update.effective_user.id} entered identity number: ***") # Masked log
#
#     if not id_num.isdigit() or not utility.is_valid_iranian_national_id(id_num):
#         await message.reply_text("شماره ملی نامعتبر است.")
#         return ASK_ID_NUM
#
#     context.user_data['id_num'] = id_num
#
#     await message.reply_text(
#         utility.escape_markdown_v2(
#             "3. برای تایید نهایی، لطفا شماره تلفن خود را با استفاده از دکمه زیر به اشتراک بگذارید."),
#         reply_markup=ReplyKeyboardMarkup(
#             [[KeyboardButton("ارسال شماره تلفن من", request_contact=True)], [KeyboardButton("/cancel")]],
#             resize_keyboard=True, one_time_keyboard=True),
#         parse_mode=ParseMode.MARKDOWN_V2
#     )
#     return ASK_PHONE

async def receive_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Copy the full function implementation from the original handlers.py) ...
    # Ensure imports for Contact, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton are present
    # Ensure imports for get_db_session, crud, models, logger are present
    # Ensure call to get_main_menu_keyboard() works
    message = update.message
    user = update.effective_user
    contact: Contact | None = message.contact

    if not contact:
        logger.warning(f"User {user.id} sent non-contact message in ASK_PHONE state.")
        await message.reply_text("لطفا از دکمه 'ارسال شماره تلفن من' استفاده کنید یا /cancel را بزنید.")
        return ASK_PHONE

    if contact.user_id != user.id:
        logger.warning(f"User {user.id} shared contact belonging to user {contact.user_id}.")
        await message.reply_text("خطا: شماره تلفن ارسال شده متعلق به شما نیست. لطفا دوباره تلاش کنید یا /cancel بزنید.")
        phone_button = KeyboardButton("ارسال شماره تلفن من", request_contact=True)
        cancel_button = KeyboardButton("/cancel")
        reply_markup = ReplyKeyboardMarkup([[phone_button], [cancel_button]], resize_keyboard=True, one_time_keyboard=True)
        await message.reply_text(
            "لطفا شماره تلفن *خودتان* را با استفاده از دکمه زیر به اشتراک بگذارید.",
            reply_markup=reply_markup
        )
        return ASK_PHONE

    phone_num_raw = contact.phone_number
    phone_num_normalized = phone_num_raw.replace("+", "").replace(" ", "")
    if not phone_num_normalized.startswith("98"):
        logger.warning(f"User {user.id} shared non-Iranian phone number: {phone_num_raw}")
        await message.reply_text(
            "خطا: به نظر می‌رسد شماره تلفن ارسال شده متعلق به ایران نیست. لطفا شماره تلفن معتبر ایرانی خود را ارسال کنید یا /cancel بزنید."
        )
        phone_button = KeyboardButton("ارسال شماره تلفن من", request_contact=True)
        cancel_button = KeyboardButton("/cancel")
        reply_markup = ReplyKeyboardMarkup([[phone_button], [cancel_button]], resize_keyboard=True,
                                           one_time_keyboard=True)
        await message.reply_text(
            "لطفا شماره تلفن *ایرانی* خودتان را با استفاده از دکمه زیر به اشتراک بگذارید.",
            reply_markup=reply_markup
        )
        return ASK_PHONE

    phone_num_to_save = phone_num_normalized
    logger.info(f"User {user.id} shared valid Iranian phone number: ...{phone_num_to_save[-4:]}")

    edu_num = context.user_data.get('edu_num')
    id_num = context.user_data.get('id_num')

    if not edu_num or not id_num:
        logger.error(f"Missing edu_num or id_num in user_data for user {user.id} during phone step.")
        await message.reply_text(
            "خطای داخلی رخ داد. لطفا فرآیند را با /start مجددا شروع کنید.",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        async with get_db_session() as db_session:
            updated_user = await crud.update_user_verification(
                db=db_session,
                telegram_id=user.id,
                # edu_num=edu_num,
                # id_num=id_num,
                phone_num=phone_num_to_save
            )
            if not updated_user:
                 raise Exception("User not found during verification update")

            logger.info(f"User {user.id} successfully verified and details updated.")
            await message.reply_text(
                "✅ اعتبارسنجی شما با موفقیت انجام شد! از الان می‌توانید از امکانات ربات استفاده کنید.",
                reply_markup=get_main_menu_keyboard()
            )
            context.user_data.clear()
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Failed to update verification details for user {user.id} in DB: {e}", exc_info=True)
        await message.reply_text(
            "خطا در ذخیره اطلاعات اعتبارسنجی. لطفا دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return ConversationHandler.END

async def cancel_verification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the verification process."""
    user = update.effective_user
    message = update.message
    logger.info(f"User {user.id} canceled the verification conversation.")
    context.user_data.clear()
    await message.reply_text(
        "فرآیند اعتبارسنجی لغو شد. برای شروع مجدد /start را بزنید.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# Help Command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays help message."""
    telegram_user = update.effective_user
    user_display_name_escaped = utility.escape_markdown_v2(
        telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
    )

    if context.user_data and (
            'edu_num' in context.user_data or 'id_num' in context.user_data or 'phone_num' in context.user_data):
        await update.message.reply_text(
            utility.escape_markdown_v2("شما در حال حاضر در فرآیند اعتبارسنجی هستید. برای لغو /cancel را بزنید."),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        is_verified = False
        async with get_db_session() as db_session:
            db_user = await crud.get_user_by_telegram_id(db_session, telegram_user.id)
            if db_user and db_user.is_verified:
                is_verified = True

        if is_verified:
            welcome_back_greeting = f"سلام {user_display_name_escaped} عزیز\\! 👋\n\n"

            # Construct the part to be replaced carefully based on how it's built in config.py
            part1 = utility.escape_markdown_v2("برای استفاده از امکانات ربات، ابتدا باید فرآیند")
            part2_bold = f"*{utility.escape_markdown_v2('اعتبارسنجی')}*"
            part3 = utility.escape_markdown_v2("را تکمیل کنید.")
            string_to_replace_in_help = f"{part1} {part2_bold} {part3}"

            replacement_for_help_escaped = utility.escape_markdown_v2(
                "در ادامه راهنمای استفاده از ربات آمده است. از دکمه‌های منوی اصلی برای دسترسی به امکانات استفاده کنید."
            )

            help_text = welcome_back_greeting + WELCOME_MESSAGE.replace(
                string_to_replace_in_help,
                replacement_for_help_escaped
            )
            await update.message.reply_text(
                help_text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True
            )
        else:
            simple_help_escaped = utility.escape_markdown_v2(
                "برای شروع کار با ربات از دستور /start استفاده کنید.\n"
                "پس از اعتبارسنجی، راهنمای کامل نمایش داده خواهد شد.\n"
                "در طول فرآیندهای مختلف، می‌توانید با دستور /cancel آن را لغو کنید."
            )
            await update.message.reply_text(
                simple_help_escaped,
                parse_mode=ParseMode.MARKDOWN_V2
            )