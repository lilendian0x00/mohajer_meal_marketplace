import logging
import math

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
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
            InlineKeyboardButton("🛒 خرید‌های من", callback_data='history_purchases_0'), # Start on page 0
            InlineKeyboardButton("🏷️ فروش‌های من", callback_data='history_sales_0') # Start on page 0
        ],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='settings_back_main')] # Re-use back handler
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(
        "📜 کدام تاریخچه را می‌خواهید مشاهده کنید؟",
        reply_markup=reply_markup
    )

async def handle_history_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a paginated view of purchase or sale history."""
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not query.data:
        return

    await query.answer()

    # Parse Callback Data
    try:
        parts = query.data.split('_')
        history_type = parts[1] # 'purchases' or 'sales'
        page = int(parts[2])    # Current page number
    except (IndexError, ValueError):
        logger.error(f"Invalid callback data for history view: {query.data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return

    logger.info(f"User {user.id} viewing history: type={history_type}, page={page}")

    # Fetch Data
    listings = []
    total_count = 0
    try:
        async with get_db_session() as db_session:
            if history_type == 'purchases':
                listings, total_count = await crud.get_user_purchase_history(
                    db=db_session, user_telegram_id=user.id, page=page, page_size=HISTORY_PAGE_SIZE
                )
                title = "**🛒 تاریخچه خرید‌های شما**"
                no_items_message = "سابقه خریدی برای شما ثبت نشده است."
            elif history_type == 'sales':
                listings, total_count = await crud.get_user_sale_history(
                    db=db_session, user_telegram_id=user.id, page=page, page_size=HISTORY_PAGE_SIZE
                )
                title = "**🏷️ تاریخچه فروش‌های شما**"
                no_items_message = "سابقه فروشی برای شما ثبت نشده است."
            else:
                raise ValueError("Invalid history type")

    except Exception as e:
        logger.error(f"DB error fetching history for user {user.id} (type={history_type}, page={page}): {e}", exc_info=True)
        await query.edit_message_text("خطا در دریافت تاریخچه. لطفا دوباره تلاش کنید.")
        return

    # Format Message
    if total_count == 0:
        no_history_text = f"{title}\n\n{no_items_message}"  # Ensure newlines
        # Create the back button keyboard even when there's no history
        inline_keyboard = [[
            InlineKeyboardButton("🔙 بازگشت به انتخاب نوع", callback_data='history_back_select')
        ]]
        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        # Send the message WITH the keyboard
        await query.edit_message_text(
            no_history_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return

    response_parts = [f"{title}\n\n"]
    if not listings and page == 0: # Should be caught by total_count check, but defensive
         response_parts.append(no_items_message)
    else:
        for listing in listings:
            meal_desc = "نامشخص"
            meal_date_str = "نامشخص"
            if listing.meal:
                meal_desc = listing.meal.description or meal_desc
                if listing.meal.date:
                    try: meal_date_str = listing.meal.date.strftime('%Y-%m-%d')
                    except AttributeError: meal_date_str = str(listing.meal.date)

            price_str = f"{listing.price:,.0f}" if listing.price is not None else "نامشخص"
            event_date_str = "نامشخص"
            if listing.sold_at:
                try: event_date_str = listing.sold_at.strftime('%Y-%m-%d %H:%M')
                except AttributeError: event_date_str = str(listing.sold_at)

            part = ""
            if history_type == 'purchases':
                seller_info = f"@{listing.seller.username}" if listing.seller and listing.seller.username else (listing.seller.first_name if listing.seller else "ناشناس")
                part = (
                    f"🗓️ تاریخ خرید: {event_date_str}\n"
                    f"🍽️ غذا: {meal_desc} ({meal_date_str})\n"
                    f"💰 قیمت: {price_str} تومان\n"
                    f"👤 فروشنده: {seller_info}\n"
                    f"🔢 کد آگهی: `{listing.id}`\n"
                    f"--------------------\n"
                )
            elif history_type == 'sales':
                buyer_info = f"@{listing.buyer.username}" if listing.buyer and listing.buyer.username else (listing.buyer.first_name if listing.buyer else "ناشناس")
                part = (
                    f"🗓️ تاریخ فروش: {event_date_str}\n"
                    f"🍽️ غذا: {meal_desc} ({meal_date_str})\n"
                    f"💰 قیمت: {price_str} تومان\n"
                    f"👤 خریدار: {buyer_info}\n"
                    f"🔢 کد آگهی: `{listing.id}`\n"
                    f"--------------------\n"
                )
            response_parts.append(part)

    # Pagination Logic
    total_pages = math.ceil(total_count / HISTORY_PAGE_SIZE)
    pagination_buttons = []
    if page > 0: # Show Previous button if not on first page
        pagination_buttons.append(
            InlineKeyboardButton("« صفحه قبل", callback_data=f'history_{history_type}_{page-1}')
        )
    if total_pages > 1: # Show page number if more than one page
         pagination_buttons.append(
             InlineKeyboardButton(f"صفحه {page+1}/{total_pages}", callback_data='history_noop') # No operation button
         )
    if page < total_pages - 1: # Show Next button if not on last page
        pagination_buttons.append(
            InlineKeyboardButton("صفحه بعد »", callback_data=f'history_{history_type}_{page+1}')
        )

    # Keyboard Assembly
    inline_keyboard = []
    if pagination_buttons:
        # Add pagination row if there are any pagination buttons
        inline_keyboard.append(pagination_buttons)

    # Add Back button to go back to the selection menu (or main menu)
    inline_keyboard.append([
         InlineKeyboardButton("🔙 بازگشت به انتخاب نوع", callback_data='history_back_select')
    ])

    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    full_message = "".join(response_parts)
    # Handle message length just in case
    if len(full_message) > 4096:
        logger.warning(f"History message for user {user.id} possibly truncated.")
        full_message = full_message[:4090] + "\n..."

    # Edit the original message (from handle_history or previous page)
    await query.edit_message_text(full_message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)



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
