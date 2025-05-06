# handlers/settings.py
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from .common import (
    SETTINGS_ASK_CARD, CALLBACK_SETTINGS_UPDATE_CARD,
    CALLBACK_SETTINGS_BACK_MAIN, get_main_menu_keyboard
)
# Assuming utility.py location allows direct import
import utility
# Adjust DB import path
from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models

logger = logging.getLogger(__name__)

# Settings Handlers
async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Settings' button press. Shows user info and options."""
    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    logger.info(f"'Settings' button pressed by user {user.id}")

    async with get_db_session() as db_session:
        try:
            db_user = await crud.get_user_by_telegram_id(db_session, user.id)

            if not db_user:
                logger.error(f"User {user.id} not found in DB during settings.")
                await message.reply_text("خطا: اطلاعات کاربری شما یافت نشد. لطفا /start بزنید.")
                return

            # Prepare display information
            username_display = utility.escape_markdown_v2(db_user.username) if db_user.username else 'ندارد'
            verification_status = "✅ تایید شده" if db_user.is_verified else "❌ تایید نشده"

            # Escape potentially problematic user-provided fields
            edu_num_display = utility.escape_markdown_v2(db_user.education_number or "ثبت نشده")
            id_num_display = utility.escape_markdown_v2(db_user.identity_number or "ثبت نشده")
            phone_num_display = utility.escape_markdown_v2(db_user.phone_number or "ثبت نشده")

            # Mask card number (utility function already returns `code`, which is fine for V2)
            card_num_display = utility.mask_card_number(db_user.credit_card_number)

            # Construct the message (Use V2 formatting: *bold*, `code`)
            settings_text = (
                # Use * for bold in V2
                f"⚙️ *تنظیمات حساب کاربری*\n\n"
                f"👤 نام کاربری تلگرام: @{username_display}\n"  # Escaped username
                f"📞 شماره تماس: {phone_num_display}\n"  # Escaped phone
                f"🎓 شماره دانشجویی: {edu_num_display}\n"  # Escaped edu num
                f"💳 شماره ملی: {id_num_display}\n"  # Escaped ID
                f"✔️ وضعیت اعتبارسنجی: {verification_status}\n"
                # Backticks for code are correct for V2
                f"🏦 شماره کارت بانکی:{card_num_display}\n\n"
                "چه کاری می‌خواهید انجام دهید؟"
            )

            # Create Inline Keyboard
            keyboard = [
                [InlineKeyboardButton("➕/✏️ افزودن/ویرایش شماره کارت", callback_data='settings_update_card')],
                [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='settings_back_main')]
                # TODO: Add other settings buttons here later if needed

            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send the message using MarkdownV2
            try:
                await message.reply_text(
                    settings_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as send_err:
                # Fallback to plain text if V2 sending fails unexpectedly
                logger.error(f"Error sending settings message with V2 markdown: {send_err}", exc_info=True)
                # Simple removal of V2 chars for fallback text
                plain_text = re.sub(r'([*_`\\])', '', settings_text)
                await message.reply_text(plain_text, reply_markup=reply_markup)


        except Exception as e:
            # Log the original DB error before handling send errors
            logger.error(f"DB error fetching user info for {user.id} in handle_settings: {e}", exc_info=True)
            await message.reply_text("خطا در دریافت اطلاعات تنظیمات. لطفا دوباره تلاش کنید.")


async def handle_settings_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Back to Main Menu' button press from the settings message."""
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return # Should not happen

    await query.answer() # Acknowledge the button press

    logger.info(f"User {user.id} pressed 'Back to Main Menu' from settings.")

    try:
        # Edit the original message (e.g., remove buttons, confirm action)
        await query.edit_message_text(
            text="بازگشت به منوی اصلی...", # "Returning to main menu..."
            reply_markup=None # Remove the inline keyboard
        )

        # Send a new message with the main menu keyboard
        #    (You cannot add ReplyKeyboardMarkup via edit_message_text)
        await query.message.reply_text(
            "گزینه مورد نظر را انتخاب کنید:", # "Select the desired option:"
            reply_markup=get_main_menu_keyboard() # Show the main reply keyboard
        )
    except Exception as e:
        logger.error(f"Error handling settings_back_main for user {user.id}: {e}", exc_info=True)
        # Try sending a fallback message if editing failed
        try:
            await query.message.reply_text(
                "خطا در بازگشت. منوی اصلی:", # "Error returning. Main Menu:"
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e2:
             logger.error(f"Error sending fallback main menu for user {user.id}: {e2}", exc_info=True)



# Settings Card Update Conversation
async def handle_settings_update_card_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the 'Add/Update Card Number' button press from settings."""
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    # Check if user is verified (optional, but good practice)
    async with get_db_session() as db_session:
        db_user = await crud.get_user_by_telegram_id(db_session, user.id)
        if not db_user or not db_user.is_verified:
             await query.edit_message_text("برای تغییر شماره کارت، ابتدا باید اعتبارسنجی شوید (/start).")
             return ConversationHandler.END # Or keep state if needed

    logger.info(f"User {user.id} initiated card update via settings.")

    # Ask for the new card number
    await query.edit_message_text(
        "لطفا شماره کارت بانکی جدید خود را وارد کنید (فقط اعداد):"
        # Remove the inline keyboard from the previous message
        #reply_markup=None # edit_message_text removes markup by default if not provided
    )
    return SETTINGS_ASK_CARD # Start the card update conversation


async def receive_settings_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and saves the new card number entered via settings."""
    user = update.effective_user
    message = update.message
    if not user or not message or not message.text:
        await message.reply_text("ورودی نامعتبر است. لطفا شماره کارت را ارسال کنید یا /cancel بزنید.")
        return SETTINGS_ASK_CARD # Stay in the same state

    new_card_number_raw = message.text.strip()

    # *** Basic Validation (Crucial!) ***
    # Remove spaces and check if all characters are digits
    if not new_card_number_raw.isdigit():
         await message.reply_text("شماره کارت نامعتبر است. لطفا فقط عدد وارد کنید:")
         return SETTINGS_ASK_CARD # Ask again

    # Add more checks if needed (length, Luhn algorithm)
    # Example length check (common Iranian cards are 16 digits)
    if len(new_card_number_raw) != 16:
         await message.reply_text("شماره کارت باید ۱۶ رقم باشد. لطفا مجددا وارد کنید:")
         return SETTINGS_ASK_CARD # Ask again

    # Add Luhn check here if desired using utility.is_valid_iranian_card_number or similar

    new_card_number = new_card_number_raw # Use the validated number

    logger.info(f"User {user.id} entered new card number via settings: ...{new_card_number[-4:]}")

    # --- Update Database ---
    try:
        async with get_db_session() as db_session:
            # OPTION 1: Use a dedicated CRUD function (Recommended)
            success = await crud.update_user_credit_card(db_session, user.id, new_card_number)

            # OPTION 2: Fetch user and update manually (Less clean)
            # db_user = await crud.get_user_by_telegram_id(db_session, user.id)
            # if db_user:
            #     db_user.credit_card_number = new_card_number
            #     await db_session.commit()
            #     success = True
            # else:
            #     success = False

        if success:
            logger.info(f"Successfully updated credit card for user {user.id}")
            await message.reply_text(
                f"✅ شماره کارت شما با موفقیت به {utility.mask_card_number(new_card_number)} تغییر یافت.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_menu_keyboard() # Show main menu again
            )
        else:
            logger.error(f"Failed to update credit card for user {user.id} in DB (user not found or DB error).")
            await message.reply_text(
                "خطا در به‌روزرسانی شماره کارت. لطفا دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.",
                reply_markup=get_main_menu_keyboard()
            )
        return ConversationHandler.END # End the settings card update conversation

    except Exception as e:
        logger.error(f"DB error updating card number for user {user.id}: {e}", exc_info=True)
        await message.reply_text("خطا در ذخیره شماره کارت. لطفا دوباره تلاش کنید.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

async def cancel_settings_card_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the process of updating card number via settings."""
    user = update.effective_user
    message = update.message # Or query if triggered by a cancel button
    logger.info(f"User {user.id} canceled the settings card update.")

    await message.reply_text( # Or update.callback_query.edit_message_text if using button cancel
        "به‌روزرسانی شماره کارت لغو شد.",
        reply_markup=get_main_menu_keyboard() # Show main menu
    )
    return ConversationHandler.END