import logging
import re

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Contact
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

import config
from config import WELCOME_MESSAGE
from .common import (
    # ASK_EDU_NUM, ASK_ID_NUM,
    ASK_PHONE,
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
    db_user_obj: models.User | None = None  # Initialize

    try:
        async with get_db_session() as db_session:
            db_user_obj = await crud.get_or_create_user_and_update_info(db_session, telegram_user)
            logger.info(f"User {db_user_obj.username} (TG_ID: {db_user_obj.telegram_id}) processed. Verified: {db_user_obj.is_verified}")
    except Exception as e:
        logger.error(f"Error processing /start user DB interaction for {telegram_user.id}: {e}", exc_info=True)
        await message.reply_text("ببخشید، مشکلی در پردازش پروفایل شما پیش آمد. لطفا دوباره امتحان کنید.")
        return ConversationHandler.END

    if not db_user_obj:
         logger.error(f"DB user object is None after get_or_create for TG ID {telegram_user.id}, ending.")
         await message.reply_text("خطای داخلی رخ داد، لطفا بعدا تلاش کنید.")
         return ConversationHandler.END

    # Escape user's name for MarkdownV2
    user_display_name_escaped = utility.escape_markdown_v2(
        telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
    )

    if db_user_obj.is_verified:
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
        # await message.reply_text(
        #     utility.escape_markdown_v2("1. لطفا شماره دانشجویی خود را وارد کنید:"),  # Also escape this prompt
        #     reply_markup=ReplyKeyboardRemove(),
        #     parse_mode=ParseMode.MARKDOWN_V2
        # )

        # Directly ask for phone number
        await message.reply_text(
            utility.escape_markdown_v2(
                "برای تکمیل اعتبارسنجی، لطفا شماره تلفن خود را با استفاده از دکمه زیر به اشتراک بگذارید:"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("ارسال شماره تلفن من", request_contact=True)], [KeyboardButton("/cancel")]],
                resize_keyboard=True, one_time_keyboard=True),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        # return ASK_EDU_NUM
        return ASK_PHONE

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
            "لطفا شماره تلفن *خودتان* را با استفاده از دکمه زیر به اشتراک بگذارید.", # Keep self prompt
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2 # Ensure parse mode for *
        )
        return ASK_PHONE

    phone_num_raw = contact.phone_number
    phone_num_normalized = phone_num_raw.replace("+", "").replace(" ", "")

    # Don't verify phone number's country on DEV Mode
    if config.BOT_MODE == "production":
        if not phone_num_normalized.startswith("98"): # Assuming Iranian numbers
            logger.warning(f"User {user.id} shared non-Iranian phone number: {phone_num_raw}")
            await message.reply_text(
                "خطا: به نظر می‌رسد شماره تلفن ارسال شده متعلق به ایران نیست. لطفا شماره تلفن معتبر ایرانی خود را ارسال کنید یا /cancel بزنید."
            )
            phone_button = KeyboardButton("ارسال شماره تلفن من", request_contact=True)
            cancel_button = KeyboardButton("/cancel")
            reply_markup = ReplyKeyboardMarkup([[phone_button], [cancel_button]], resize_keyboard=True,
                                               one_time_keyboard=True)
            await message.reply_text(
                "لطفا شماره تلفن *ایرانی* خودتان را با استفاده از دکمه زیر به اشتراک بگذارید.", # Keep self prompt
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2 # Ensure parse mode for *
            )
            return ASK_PHONE

    phone_num_to_save = phone_num_normalized
    logger.info(f"User {user.id} shared valid Iranian phone number: ...{phone_num_to_save[-4:]}")

    # edu_num and id_num are no longer collected from context.user_data

    try:
        async with get_db_session() as db_session:
            updated_user = await crud.update_user_verification(
                db=db_session,
                telegram_id=user.id,
                phone_num=phone_num_to_save
            )
            if not updated_user:
                 raise Exception("User not found or update failed during verification update")

            logger.info(f"User {user.id} successfully verified (phone only) and details updated.")
            await message.reply_text(
                "✅ اعتبارسنجی شما (بر اساس شماره تلفن) با موفقیت انجام شد! از الان می‌توانید از امکانات ربات استفاده کنید.",
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
    # Check if user is in the middle of the (now very short) verification
    if context.user_data and any(key in context.user_data for key in []): # No specific keys expected anymore
        # if /help is called during ASK_PHONE, it's fine to show help.
        # The /cancel command is the primary way out.
        pass # Let help proceed normally

    is_verified = False
    async with get_db_session() as db_session:
        db_user = await crud.get_user_by_telegram_id(db_session, telegram_user.id)
        if db_user and db_user.is_verified:
            is_verified = True

    if is_verified:
        welcome_back_greeting = f"سلام {user_display_name_escaped} عزیز\\! 👋\n\n"
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
            "پس از اعتبارسنجی (ارسال شماره تماس)، راهنمای کامل نمایش داده خواهد شد.\n"
            "در طول فرآیند، می‌توانید با دستور /cancel آن را لغو کنید."
        )
        await update.message.reply_text(
            simple_help_escaped,
            parse_mode=ParseMode.MARKDOWN_V2
        )