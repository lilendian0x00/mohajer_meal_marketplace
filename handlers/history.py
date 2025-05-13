import logging
import math

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from utility import format_gregorian_date_to_shamsi, escape_markdown_v2
from .common import (
    MAIN_MENU_BUTTON_TEXTS
)
from config import HISTORY_PAGE_SIZE
from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models

logger = logging.getLogger(__name__)

# History Handlers
async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Transaction History' button, prompts for type."""
    user = update.effective_user
    message = update.message
    if not user or not message: return

    logger.info(f"'Transaction History' button pressed by user {user.id}")

    # Check verification status if history is restricted
    async with get_db_session() as db_session:
       db_user = await crud.get_user_by_telegram_id(db_session, user.id)
       if not db_user or not db_user.is_verified:
           await message.reply_text("برای مشاهده تاریخچه، ابتدا باید اعتبارسنجی شوید (/start).")
           return

    keyboard = [
        [
            InlineKeyboardButton("🛒 خرید‌های من", callback_data='history_purchases_0'),
            InlineKeyboardButton("🏷️ فروش‌های من", callback_data='history_sales_0')
        ],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='settings_back_main')] # Re-use back handler
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(
        "📜 کدام تاریخچه را می‌خواهید مشاهده کنید؟",
        reply_markup=reply_markup
    )


async def handle_history_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not query.data:
        return

    await query.answer()

    try:
        parts = query.data.split('_')
        history_type = parts[1]
        page = int(parts[2])
    except (IndexError, ValueError):
        logger.error(f"Invalid callback data for history view: {query.data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return

    logger.info(f"User {user.id} viewing history: type={history_type}, page={page}")

    listings = []
    total_count = 0
    title = ""  # Initialize title
    no_items_message = ""  # Initialize
    try:
        async with get_db_session() as db_session:
            if history_type == 'purchases':
                listings, total_count = await crud.get_user_purchase_history(
                    db=db_session, user_telegram_id=user.id, page=page, page_size=HISTORY_PAGE_SIZE
                )
                title = "*🛒 تاریخچه خرید‌های شما*"  # Changed to V2 bold
                no_items_message = escape_markdown_v2("سابقه خریدی برای شما ثبت نشده است.")
            elif history_type == 'sales':
                listings, total_count = await crud.get_user_sale_history(
                    db=db_session, user_telegram_id=user.id, page=page, page_size=HISTORY_PAGE_SIZE
                )
                title = "*🏷️ تاریخچه فروش‌های شما*"  # Changed to V2 bold
                no_items_message = escape_markdown_v2("سابقه فروشی برای شما ثبت نشده است.")
            else:
                raise ValueError("Invalid history type")

    except Exception as e:
        logger.error(f"DB error fetching history for user {user.id} (type={history_type}, page={page}): {e}",
                     exc_info=True)
        await query.edit_message_text("خطا در دریافت تاریخچه. لطفا دوباره تلاش کنید.")
        return

    if total_count == 0:
        no_history_text = f"{title}\n\n{no_items_message}"
        inline_keyboard = [[
            InlineKeyboardButton("🔙 بازگشت به انتخاب نوع", callback_data='history_back_select')
        ]]
        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        await query.edit_message_text(
            no_history_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    response_parts = [f"{title}\n\n"]
    for listing in listings:
        meal_desc_raw = listing.meal.description if listing.meal else "غذای نامشخص"
        meal_date_raw = listing.meal.date if listing.meal else None

        meal_desc = escape_markdown_v2(meal_desc_raw)
        meal_date_shamsi = format_gregorian_date_to_shamsi(meal_date_raw)  # Already returns escaped or safe string

        price_str_raw = f"{listing.price:,.0f}" if listing.price is not None else "نامشخص"
        price_str = escape_markdown_v2(price_str_raw)  # Escape the formatted price

        sold_at_raw = listing.sold_at
        event_date_str_display = "نامشخص"
        if sold_at_raw:
            event_date_shamsi = format_gregorian_date_to_shamsi(sold_at_raw)
            event_time_str = sold_at_raw.strftime('%H:%M')
            event_date_str_display = escape_markdown_v2(f"{event_date_shamsi} {event_time_str}".strip())

        part = ""
        if history_type == 'purchases':
            seller_info_raw = "ناشناس"
            if listing.seller:
                seller_info_raw = f"@{listing.seller.username}" if listing.seller.username else listing.seller.first_name
            seller_info = escape_markdown_v2(seller_info_raw or "ناشناس")
            part = (
                f"🗓️ تاریخ خرید: {event_date_str_display}\n"
                f"🍽️ غذا: *{meal_desc}* \\({meal_date_shamsi}\\)\n"
                f"💰 قیمت: {price_str} تومان\n"
                f"👤 فروشنده: {seller_info}\n"
                f"🔢 کد آگهی: `{listing.id}`\n" 
                f"{escape_markdown_v2('--------------------')}\n"
            )
        elif history_type == 'sales':
            buyer_info_raw = "ناشناس"
            if listing.buyer:
                buyer_info_raw = f"@{listing.buyer.username}" if listing.buyer.username else listing.buyer.first_name
            buyer_info = escape_markdown_v2(buyer_info_raw or "ناشناس")
            part = (
                f"🗓️ تاریخ فروش: {event_date_str_display}\n"
                f"🍽️ غذا: *{meal_desc}* \\({meal_date_shamsi}\\)\n"
                f"💰 قیمت: {price_str} تومان\n"
                f"👤 خریدار: {buyer_info}\n"
                f"🔢 کد آگهی: `{listing.id}`\n"
                f"{escape_markdown_v2('--------------------')}\n"
            )
        response_parts.append(part)

    total_pages = math.ceil(total_count / HISTORY_PAGE_SIZE)
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(
            InlineKeyboardButton("« صفحه قبل", callback_data=f'history_{history_type}_{page - 1}')
        )
    if total_pages > 1:
        pagination_buttons.append(
            InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data='history_noop')
        )
    if page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton("صفحه بعد »", callback_data=f'history_{history_type}_{page + 1}')
        )

    inline_keyboard = []
    if pagination_buttons:
        inline_keyboard.append(pagination_buttons)
    inline_keyboard.append([
        InlineKeyboardButton("🔙 بازگشت به انتخاب نوع", callback_data='history_back_select')
    ])
    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    full_message = "".join(response_parts)
    if len(full_message) > 4096:
        logger.warning(f"History message for user {user.id} possibly truncated.")
        full_message = full_message[:4090] + escape_markdown_v2("\n...")

    try:
        await query.edit_message_text(
            full_message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info(f"History view for user {user.id} not modified.")
            await query.answer("صفحه تغییری نکرده است.")  # Or don't answer again if initial answer was enough
        else:
            # Log the full error if it's not "Message is not modified"
            logger.error(
                f"BadRequest editing history message for user {user.id} (V2): {e}\nMessage content: {full_message[:500]}",
                exc_info=True)
            await query.answer("خطا در بروزرسانی لیست.")
    except Exception as e_edit:
        logger.error(
            f"Unexpected error editing history message for user {user.id} (V2): {e_edit}\nMessage content: {full_message[:500]}",
            exc_info=True)
        await query.answer("خطای ناشناخته در بروزرسانی.")



async def handle_history_back_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Back to selection' button press from history view."""
    query = update.callback_query
    user = update.effective_user
    if not query or not user: return
    await query.answer()
    logger.info(f"User {user.id} going back to history type selection.")
    # Re-display the initial history type selection message and buttons
    keyboard = [
        [
            InlineKeyboardButton("🛒 خرید‌های من", callback_data='history_purchases_0'),
            InlineKeyboardButton("🏷️ فروش‌های من", callback_data='history_sales_0')
        ],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='settings_back_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📜 کدام تاریخچه را می‌خواهید مشاهده کنید؟",
        reply_markup=reply_markup
    )


# Generic Echo Handler - Optional
# Maybe move to common.py or keep commented out if not actively used
# Generic echo handler
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text messages that are not commands or known buttons, ignoring if inside a known conversation OR if it's a known button."""

    # Get message text safely
    message_text = update.message.text if update.message else None

    # Check 1: Inside a known conversation? ---
    # (Keep the check from the previous step)
    if context.user_data and ('edu_num' in context.user_data or 'reservation_id' in context.user_data):
        logger.debug(f"Echo handler ignoring message from user {update.effective_user.id}, likely in conversation.")
        return # Do nothing

    # Check 2: Is it a known main menu button text? ---
    if message_text and message_text in MAIN_MENU_BUTTON_TEXTS:
         logger.debug(f"Echo handler ignoring known button text: {message_text}")
         return # Do nothing, it was handled by a specific MessageHandler

    # Original echo logic for truly unhandled messages
    if message_text:
        logger.info(f"Received unhandled text message from {update.effective_user.username}: {message_text}")
        await update.message.reply_text(
             f"پیام '{message_text}' دریافت شد. برای نمایش منوی اصلی /start را بزنید."
        )
    else:
        # Handle other types of unhandled messages if necessary
        logger.info("Received non-text/non-command/non-button message, ignoring.")


# Unexpected Message Handler - Optional
# Belongs more with verification flow? Or general fallback?
async def unexpected_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages that are not expected in the current conversation state."""
    message = update.message
    if message and message.text:
         logger.warning(f"User {update.effective_user.id} sent unexpected text '{message.text}' during verification.")
         await message.reply_text("ورودی نامعتبر است. لطفا طبق دستورالعمل پیش بروید یا /cancel را بزنید.")
    # Decide if state should change or remain the same depending on current state
    # Returning None keeps the state the same implicitly if used directly in ConversationHandler states dict
    # Or you can retrieve current state from context if needed to return it explicitly
