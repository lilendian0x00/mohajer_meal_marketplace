import logging
from functools import wraps
from decimal import Decimal, InvalidOperation
from datetime import date as GregorianDate, timezone  # Alias to avoid conflict with datetime.date
from datetime import datetime
import jdatetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode
from config import ADMIN_TELEGRAM_IDS, USERS_LIST_PAGE_SIZE, HISTORY_PAGE_SIZE
from handlers import CALLBACK_ADMIN_REFRESH_STATS
from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models
from utility import escape_markdown_v2, format_gregorian_date_to_shamsi

logger = logging.getLogger(__name__)

# Admin Check Decorator
def admin_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ADMIN_TELEGRAM_IDS:
            logger.warning(f"Unauthorized admin command attempt by {user.id if user else 'Unknown User'}.")
            if update.callback_query:
                await update.callback_query.answer("شما مجاز به استفاده از این دستور نیستید.", show_alert=True)
                return ConversationHandler.END # Also end conversations if unauthorized
            elif update.message:
                await update.message.reply_text("شما مجاز به استفاده از این دستور نیستید.")
            return ConversationHandler.END # Ensure conversation ends if in one
        return await func(update, context, *args, **kwargs)
    return wrapper

# Conversation States for /addmeal
(
    ADDMEAL_ASK_DESCRIPTION,
    ADDMEAL_ASK_TYPE,
    ADDMEAL_ASK_DATE,
    ADDMEAL_ASK_PRICE,
    ADDMEAL_ASK_PRICELIMIT,
    ADDMEAL_CONFIRM,
) = range(100, 106) # Use a distinct range for admin conv states

# Callback Data Prefixes
CALLBACK_ADMIN_LIST_USERS_PAGE = "admin_users_page_"
CALLBACK_ADMIN_MEAL_CONFIRM_YES = "admin_meal_conf_yes"
CALLBACK_ADMIN_MEAL_CONFIRM_NO = "admin_meal_conf_no"
# Callback data for meal type selection
CALLBACK_ADDMEAL_TYPE_PREFIX = "addmeal_type_"
CALLBACK_ADDMEAL_TYPE_NAHAR = f"{CALLBACK_ADDMEAL_TYPE_PREFIX}ناهار" # Lunch
CALLBACK_ADDMEAL_TYPE_SHAM = f"{CALLBACK_ADDMEAL_TYPE_PREFIX}شام"   # Dinner
CALLBACK_ADMIN_ALL_SOLD_PAGE = "admin_allsold_page_"
CALLBACK_ADMIN_USER_SOLD_PAGE_PREFIX = "admin_usersold_"
CALLBACK_ADMIN_SOLD_NOOP = "admin_sold_noop" # For page number button


@admin_required
async def help_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of available admin commands."""
    message = update.message
    if not message:
        return

    logger.info(f"Admin {update.effective_user.id} requested admin help.")

    admin_help_text_parts = [
        "⚙️ *راهنمای دستورات ادمین*\n",
        "دستورات زیر فقط برای ادمین‌ها قابل استفاده هستند:\n",
        "─" * 20 + "\n",

        "👤 *مدیریت کاربران:*\n",
        f"`/setadmin <user_id> <true|false>` {escape_markdown_v2('- تنظیم/لغو دسترسی ادمین برای کاربر')}\n",
        f"`/setactive <user_id> <true|false>` {escape_markdown_v2('- فعال/غیرفعال کردن کاربر')}\n",
        f"`/getuser <user_id>` {escape_markdown_v2('- نمایش اطلاعات کامل کاربر')}\n",
        f"`/listusers [page]` {escape_markdown_v2('- نمایش لیست کاربران (صفحه‌بندی شده)')}\n",
        "\n",

        "🍲 *مدیریت غذاها:*\n",
        f"`/addmeal` {escape_markdown_v2('- شروع فرآیند افزودن غذای جدید به سیستم')}\n",
        f"`/delmeal <meal_id>` {escape_markdown_v2('- حذف یک نوع غذا از سیستم (اگر توسط آگهی استفاده نشده باشد)')}\n",
        "\n",

        "🏷️ *مدیریت آگهی‌ها:*\n",
        f"`/dellisting <listing_id>` {escape_markdown_v2('- حذف یک آگهی خاص از سیستم')}\n",
        f"`/allsold [page]` {escape_markdown_v2('- نمایش تمام آگهی‌های فروخته شده (صفحه‌بندی شده)')}\n",
        f"`/usersold <user_id> [page]` {escape_markdown_v2('- نمایش آگهی‌های فروخته شده توسط یک کاربر خاص (صفحه‌بندی شده)')}\n",
        "\n",

        "📊 *آمار و راهنما:*\n",
        f"`/stats` {escape_markdown_v2('- نمایش آمار کلی ربات (با دکمه بروزرسانی)')}\n",
        f"`/help_admin` {escape_markdown_v2('- نمایش همین پیام راهنما')}\n",
        "\n",
        escape_markdown_v2("نکته: پارامترهای داخل [] اختیاری هستند.")
    ]

    full_help_message = "".join(admin_help_text_parts)

    await message.reply_text(
        text=full_help_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )


# --- Helper function to format and send sold listings ---
async def _send_sold_listings_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
    listings: list[models.Listing],
    total_count: int,
    page_size: int,
    title_prefix: str,
    callback_data_prefix: str
):
    """
    Helper function to format and send a paginated list of sold listings.
    """
    query = update.callback_query
    message_to_edit_or_reply = update.message or (query.message if query else None)
    if not message_to_edit_or_reply: return

    user_id = update.effective_user.id

    if not listings and page == 0:
        text = f"{title_prefix}\n\n{escape_markdown_v2('هیچ آیتم فروخته شده‌ای یافت نشد.')}"
        reply_markup = None # No pagination if no items
    else:
        text_parts = [f"{title_prefix} \\(صفحه {page + 1}\\)\n"]
        for l in listings:
            meal_desc = escape_markdown_v2(l.meal.description if l.meal else "غذای نامشخص")
            meal_date_shamsi = format_gregorian_date_to_shamsi(l.meal.date if l.meal else None)
            sold_at_shamsi_time = "تاریخ نامشخص"
            if l.sold_at:
                sold_at_shamsi_time = format_gregorian_date_to_shamsi(l.sold_at) + " " + l.sold_at.strftime('%H:%M')

            seller_info_parts = []
            if l.seller:
                seller_info_parts.append(f"🧑‍🍳 فروشنده: ")
                if l.seller.username:
                    seller_info_parts.append(f"@{escape_markdown_v2(l.seller.username)}")
                else:
                    seller_info_parts.append(escape_markdown_v2(l.seller.first_name or "ناشناس"))
                seller_info_parts.append(f" \\(ID: `{l.seller.telegram_id}`\\)")
            seller_info = "".join(seller_info_parts)


            buyer_info_parts = []
            if l.buyer:
                buyer_info_parts.append(f"🛍️ خریدار: ")
                if l.buyer.username:
                    buyer_info_parts.append(f"@{escape_markdown_v2(l.buyer.username)}")
                else:
                    buyer_info_parts.append(escape_markdown_v2(l.buyer.first_name or "ناشناس"))
                buyer_info_parts.append(f" \\(ID: `{l.buyer.telegram_id}`\\)")
            buyer_info = "".join(buyer_info_parts)

            price_formatted = f"{l.price:,.0f}" if l.price is not None else "نامشخص"

            text_parts.append(
                f"🆔 آگهی: `{l.id}`\n"
                f"🍲 غذا: *{meal_desc}* \\(تاریخ غذا: {meal_date_shamsi}\\)\n"
                f"{seller_info}\n"
                f"{buyer_info}\n"
                f"💰 قیمت: {escape_markdown_v2(price_formatted)} تومان\n"
                f"📅 تاریخ فروش: {escape_markdown_v2(sold_at_shamsi_time)}\n"
                f"─" * 15 # Short separator
            )
        text = "\n".join(text_parts)

        total_pages = (total_count + page_size - 1) // page_size
        keyboard_buttons_row = []
        if page > 0:
            keyboard_buttons_row.append(InlineKeyboardButton("« قبلی", callback_data=f"{callback_data_prefix}{page - 1}"))
        if total_pages > 1:
            keyboard_buttons_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data=CALLBACK_ADMIN_SOLD_NOOP))
        if page < total_pages - 1:
            keyboard_buttons_row.append(InlineKeyboardButton("بعدی »", callback_data=f"{callback_data_prefix}{page + 1}"))

        reply_markup = InlineKeyboardMarkup([keyboard_buttons_row]) if keyboard_buttons_row else None

    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info(f"Sold listings page for admin {user_id} not modified.")
                await query.answer("صفحه تغییری نکرده است.")
            else:
                logger.error(f"Error editing sold listings message for admin {user_id}: {e}", exc_info=True)
                await query.answer("خطا در بروزرسانی لیست.")
        except Exception as e_edit:
            logger.error(f"Unexpected error editing sold listings for admin {user_id}: {e_edit}", exc_info=True)
            await query.answer("خطای ناشناخته در بروزرسانی.")
    else:
        await message_to_edit_or_reply.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)


# 1. Handler for showing ALL sold meals
@admin_required
async def show_all_sold_meals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command handler to show all sold meals, paginated."""
    page = 0
    if context.args and context.args[0].isdigit():
        page = int(context.args[0]) - 1  # User inputs 1-based page
        if page < 0: page = 0

    await update.message.reply_text("در حال دریافت لیست تمام غذاهای فروخته شده...")
    async with get_db_session() as db_session:
        listings, total_count = await crud.get_all_sold_listings(db_session, page=page, page_size=HISTORY_PAGE_SIZE)

    await _send_sold_listings_page(
        update, context, page, listings, total_count, HISTORY_PAGE_SIZE,
        title_prefix="📦 *لیست تمام غذاهای فروخته شده*",
        callback_data_prefix=CALLBACK_ADMIN_ALL_SOLD_PAGE
    )

@admin_required
async def show_all_sold_meals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback handler for paginating all sold meals."""
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split(CALLBACK_ADMIN_ALL_SOLD_PAGE)[1])
    except (IndexError, ValueError):
        logger.error(f"Invalid callback data for all_sold_meals pagination: {query.data}")
        await query.edit_message_text("خطای دکمه.")
        return

    async with get_db_session() as db_session:
        listings, total_count = await crud.get_all_sold_listings(db_session, page=page, page_size=HISTORY_PAGE_SIZE)

    await _send_sold_listings_page(
        update, context, page, listings, total_count, HISTORY_PAGE_SIZE,
        title_prefix="📦 *لیست تمام غذاهای فروخته شده*",
        callback_data_prefix=CALLBACK_ADMIN_ALL_SOLD_PAGE
    )


# 2. Handler for showing sold meals of a SPECIFIC person
@admin_required
async def show_user_sold_meals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command handler to show sold meals for a specific user, paginated."""
    message = update.message
    if not context.args or len(context.args) == 0:
        await message.reply_text(f"استفاده: `{escape_markdown_v2('/usersold <user_telegram_id> [page_number]')}`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_seller_tg_id = int(context.args[0])
    except ValueError:
        await message.reply_text(f"{escape_markdown_v2('آیدی تلگرام کاربر باید عدد باشد.')}", parse_mode=ParseMode.MARKDOWN_V2)
        return

    page = 0
    if len(context.args) > 1 and context.args[1].isdigit():
        page = int(context.args[1]) - 1 # User inputs 1-based page
        if page < 0: page = 0

    await message.reply_text(f"در حال دریافت لیست غذاهای فروخته شده توسط کاربر `{target_seller_tg_id}`...")

    async with get_db_session() as db_session:
        listings, total_count, seller_user = await crud.get_sold_listings_by_seller(
            db_session, seller_telegram_id=target_seller_tg_id, page=page, page_size=HISTORY_PAGE_SIZE
        )

    if not seller_user:
        await message.reply_text(f"کاربر با آیدی تلگرام `{target_seller_tg_id}` یافت نشد.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    seller_display = f"@{escape_markdown_v2(seller_user.username)}" if seller_user.username else escape_markdown_v2(seller_user.first_name or f"ID: {seller_user.telegram_id}")
    title = f"📦 *لیست فروش‌های کاربر {seller_display}*"
    # Append seller_tg_id to the callback prefix for user-specific pagination
    callback_prefix_with_user = f"{CALLBACK_ADMIN_USER_SOLD_PAGE_PREFIX}{target_seller_tg_id}_"

    await _send_sold_listings_page(
        update, context, page, listings, total_count, HISTORY_PAGE_SIZE,
        title_prefix=title,
        callback_data_prefix=callback_prefix_with_user
    )


@admin_required
async def show_user_sold_meals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback handler for paginating a specific user's sold meals."""
    query = update.callback_query
    await query.answer()

    # Callback data format: CALLBACK_ADMIN_USER_SOLD_PAGE_PREFIX<seller_tg_id>_<page>
    # Example: "admin_usersold_1234567_1"
    try:
        # Remove the base prefix
        data_part = query.data.replace(CALLBACK_ADMIN_USER_SOLD_PAGE_PREFIX, "", 1)
        # Split the remaining <seller_tg_id>_<page>
        seller_tg_id_str, page_str = data_part.rsplit('_', 1)
        target_seller_tg_id = int(seller_tg_id_str)
        page = int(page_str)
    except (ValueError, IndexError) as e:
        logger.error(f"Invalid callback data for user_sold_meals pagination: {query.data}, Error: {e}")
        await query.edit_message_text("خطای دکمه.")
        return

    async with get_db_session() as db_session:
        listings, total_count, seller_user = await crud.get_sold_listings_by_seller(
            db_session, seller_telegram_id=target_seller_tg_id, page=page, page_size=HISTORY_PAGE_SIZE
        )

    if not seller_user: # Should ideally not happen if command initiated correctly
        await query.edit_message_text(f"کاربر فروشنده با آیدی `{target_seller_tg_id}` یافت نشد.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    seller_display = f"@{escape_markdown_v2(seller_user.username)}" if seller_user.username else escape_markdown_v2(seller_user.first_name or f"ID: {seller_user.telegram_id}")
    title = f"📦 *لیست فروش‌های کاربر {seller_display}*"
    callback_prefix_with_user = f"{CALLBACK_ADMIN_USER_SOLD_PAGE_PREFIX}{target_seller_tg_id}_"

    await _send_sold_listings_page(
        update, context, page, listings, total_count, HISTORY_PAGE_SIZE,
        title_prefix=title,
        callback_data_prefix=callback_prefix_with_user
    )

@admin_required
async def admin_sold_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles no-operation callbacks for sold listings pagination page numbers."""
    query = update.callback_query
    if query:
        await query.answer()



@admin_required
async def bot_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays comprehensive bot statistics for admins. Can be refreshed."""
    query = update.callback_query
    message = update.message
    effective_message = message or (query.message if query else None) # Get the message to reply to or edit

    if not effective_message:
        logger.warning("bot_statistics called without a message or query context.")
        return

    user_id = update.effective_user.id
    logger.info(f"Admin {user_id} requested bot statistics (via {'command' if message else 'button'}).")

    # If it's a button press, answer the callback query first
    if query:
        try:
            await query.answer("در حال بروزرسانی آمار...")
        except BadRequest as e:
            if "Query is too old" not in str(e) and "query id is invalid" not in str(e):
                logger.warning(f"Error answering stats refresh callback for admin {user_id}: {e}")
            # Continue even if answer fails for old query, try to edit
    else: # It's a command, send an initial "gathering" message
        await effective_message.reply_text("در حال جمع‌آوری آمار ربات...")

    try:
        async with get_db_session() as db_session:
            total_users = await crud.get_total_users_count(db_session)
            admin_users = await crud.get_admin_users_count(db_session)
            verified_users = await crud.get_verified_users_count(db_session)
            inactive_users = await crud.get_inactive_users_count(db_session)

            sold_listings_count = await crud.get_listings_count_by_status(db_session, models.ListingStatus.SOLD)
            sold_listings_value = await crud.get_total_value_of_listings_by_status(db_session, models.ListingStatus.SOLD)

            available_listings_count = await crud.get_listings_count_by_status(db_session, models.ListingStatus.AVAILABLE)
            available_listings_value = await crud.get_total_value_of_listings_by_status(db_session, models.ListingStatus.AVAILABLE)

            pending_listings_count = await crud.get_listings_count_by_status(db_session, models.ListingStatus.AWAITING_CONFIRMATION)
            pending_listings_value = await crud.get_total_value_of_listings_by_status(db_session, models.ListingStatus.AWAITING_CONFIRMATION)

            cancelled_listings_count = await crud.get_listings_count_by_status(db_session, models.ListingStatus.CANCELLED)

            total_meals = await crud.get_total_meals_count(db_session)
            active_meals = await crud.get_active_meals_count(db_session)

        # Prepare the message using MarkdownV2
        stats_message_parts = [
            f"📊 *آمار کلی ربات*\n",
            "─" * 20 + "\n",

            f"👤 *بخش کاربران:*\n"
            f"  ▫️ کل کاربران ثبت‌شده: `{total_users}` نفر\n"
            f"  ▫️ کاربران ادمین: `{admin_users}` نفر\n"
            f"  ▫️ کاربران تایید شده: `{verified_users}` نفر\n"
            f"  ▫️ کاربران غیرفعال: `{inactive_users}` نفر\n",

            f"🏷️ *بخش آگهی‌ها \\(لیستینگ‌ها\\):*\n"
            f"  ✅ فروخته شده:\n"
            f"    ▫️ تعداد: `{sold_listings_count}` عدد\n"
            f"    ▫️ ارزش کل: `{sold_listings_value:,.0f}` تومان\n"
            f"  🛒 موجود برای فروش:\n"
            f"    ▫️ تعداد: `{available_listings_count}` عدد\n"
            f"    ▫️ ارزش کل آگهی‌های موجود: `{available_listings_value:,.0f}` تومان\n"
            f"  ⏳ در انتظار تایید فروشنده:\n"
            f"    ▫️ تعداد: `{pending_listings_count}` عدد\n"
            f"    ▫️ ارزش کل آگهی‌های در انتظار: `{pending_listings_value:,.0f}` تومان\n"
            f"  ❌ لغو شده:\n"
            f"    ▫️ تعداد: `{cancelled_listings_count}` عدد\n",

            f"🍲 *بخش غذاها \\(تعریف شده در سیستم\\):*\n"
            f"  ▫️ کل غذاهای تعریف شده: `{total_meals}` نوع\n"
            f"  ▫️ غذاهای فعال \\(امروز و آینده\\): `{active_meals}` نوع\n",

            "─" * 20 + "\n",
            f"⏱️ آمار بروز شده در: `{escape_markdown_v2(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z'))}`"
        ]

        full_stats_message = "\n".join(stats_message_parts)

        if len(full_stats_message) > 4096:
            logger.warning("Statistics message is too long, might be truncated by Telegram.")
            full_stats_message = full_stats_message[:4090] + "\n\n\\.\\.\\.\\(پیام خلاصه شد\\)"

        # Create the inline keyboard with the refresh button
        keyboard = [[
            InlineKeyboardButton("🔄 به روز رسانی آمار", callback_data=CALLBACK_ADMIN_REFRESH_STATS)
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query: # If triggered by button, edit the existing message
            try:
                await query.edit_message_text(
                    text=full_stats_message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    logger.info(f"Stats refresh for admin {user_id} resulted in no changes to the message content.")
                    # answer the query to indicate no change if not already done by the initial answer.
                    await query.answer("آمار تغییری نکرده است.")
                elif "Query is too old" in str(e) or "query id is invalid" in str(e):
                     logger.warning(f"Failed to edit stats message due to old query for admin {user_id}: {e}")
                else:
                    logger.error(f"BadRequest editing stats message for admin {user_id}: {e}", exc_info=True)
            except Exception as e_edit:
                 logger.error(f"Error editing stats message for admin {user_id}: {e_edit}", exc_info=True)

        else: # If triggered by command, send a new message
            await effective_message.reply_text(
                text=full_stats_message,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Error generating bot statistics for admin {user_id}: {e}", exc_info=True)
        error_text = "متاسفانه در دریافت آمار خطایی رخ داد. لطفا دوباره تلاش کنید."
        if query:
            try:
                await query.edit_message_text(error_text) # Try to edit to show error
            except: # If edit fails, fall back to sending new message
                await context.bot.send_message(chat_id=user_id, text=error_text)
        elif effective_message:
            await effective_message.reply_text(error_text)

# User Management Handlers
@admin_required
async def set_admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not context.args or len(context.args) != 2:
        await message.reply_text("استفاده: `/setadmin <user_telegram_id> <true|false>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_user_tg_id = int(context.args[0])
        is_admin_str = context.args[1].lower()
        if is_admin_str not in ['true', 'false']:
            raise ValueError("مقدار دوم باید 'true' یا 'false' باشد.")
        is_admin = is_admin_str == 'true'
    except (ValueError, IndexError) as e:
        await message.reply_text(f"ورودی نامعتبر: {escape_markdown_v2(str(e))}\nاستفاده: `/setadmin <user_telegram_id> <true|false>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    async with get_db_session() as db_session:
        updated_user = await crud.set_user_admin_state(db_session, target_user_tg_id, is_admin)

    if updated_user:
        await message.reply_text(f"وضعیت ادمین برای کاربر {target_user_tg_id} به `{is_admin}` تغییر یافت\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await message.reply_text(f"کاربر با آیدی تلگرام {target_user_tg_id} یافت نشد یا تغییری اعمال نشد\\.", parse_mode=ParseMode.MARKDOWN_V2)

@admin_required
async def set_active_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not context.args or len(context.args) != 2:
        await message.reply_text("استفاده: `/setactive <user_telegram_id> <true|false>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_user_tg_id = int(context.args[0])
        is_active_str = context.args[1].lower()
        if is_active_str not in ['true', 'false']:
            raise ValueError("مقدار دوم باید 'true' یا 'false' باشد.")
        is_active = is_active_str == 'true'
    except (ValueError, IndexError) as e:
        await message.reply_text(f"ورودی نامعتبر: {escape_markdown_v2(str(e))}\nاستفاده: `/setactive <user_telegram_id> <true|false>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    async with get_db_session() as db_session:
        updated_user = await crud.set_user_active_status(db_session, target_user_tg_id, is_active)

    if updated_user:
        status_text = "فعال" if is_active else "غیرفعال"
        await message.reply_text(f"وضعیت کاربر {target_user_tg_id} به `{status_text}` تغییر یافت\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await message.reply_text(f"کاربر با آیدی تلگرام {target_user_tg_id} یافت نشد یا تغییری اعمال نشد\\.", parse_mode=ParseMode.MARKDOWN_V2)

@admin_required
async def get_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not context.args or len(context.args) != 1:
        await message.reply_text(
            f"استفاده: `{escape_markdown_v2('/getuser <user_telegram_id | @username>')}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    identifier = context.args[0]
    db_user: models.User | None = None

    async with get_db_session() as db_session:
        if identifier.isdigit(): # Assume it's a Telegram ID
            try:
                target_user_tg_id = int(identifier)
                db_user = await crud.get_user_details_for_admin(db_session, target_user_tg_id)
            except ValueError: # Should not happen if isdigit() is true, but defensive
                await message.reply_text(
                    escape_markdown_v2("آیدی تلگرام کاربر باید یک عدد باشد."),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                return
        elif identifier.startswith("@"): # Assume it's a username
            username_to_find = identifier[1:] # Remove the "@"
            db_user = await crud.get_user_by_username_for_admin(db_session, username_to_find) # New CRUD needed
        else: # Not a valid ID and not starting with @
            await message.reply_text(
                escape_markdown_v2("ورودی نامعتبر است. لطفا آیدی عددی تلگرام یا نام کاربری با @ (مانند @testuser) وارد کنید."),
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

    if db_user:
        credit_card_display = "ثبت نشده"
        if db_user.credit_card_number:
            credit_card_display = f"`{escape_markdown_v2(db_user.credit_card_number)}`"

        created_at_shamsi = format_gregorian_date_to_shamsi(db_user.created_at)
        time_str = db_user.created_at.strftime('%H:%M') if db_user.created_at else ""

        user_info_parts = [
            f"*اطلاعات کاربر: {db_user.telegram_id}*",
            f"نام کاربری: @{escape_markdown_v2(db_user.username)}" if db_user.username else "نام کاربری: ندارد",
            f"نام: {escape_markdown_v2(db_user.first_name)}",
            f"نام خانوادگی: {escape_markdown_v2(db_user.last_name)}" if db_user.last_name else "نام خانوادگی: ندارد",
            f"شماره دانشجویی: `{escape_markdown_v2(db_user.education_number)}`" if db_user.education_number else "شماره دانشجویی: ثبت نشده",
            f"شماره ملی: `{escape_markdown_v2(db_user.identity_number)}`" if db_user.identity_number else "شماره ملی: ثبت نشده",
            f"شماره تماس: `{escape_markdown_v2(db_user.phone_number)}`" if db_user.phone_number else "شماره تماس: ثبت نشده",
            f"شماره کارت: {credit_card_display}",
            f"تایید شده: {'✅' if db_user.is_verified else '❌'}",
            f"ادمین: {'✅' if db_user.is_admin else '❌'}",
            f"فعال: {'✅' if db_user.is_active else '❌'}",
            f"تاریخ عضویت: {created_at_shamsi} {escape_markdown_v2(time_str)}",
            f"تعداد آگهی‌های فروش: {len(db_user.listings) if db_user.listings else 0}", # Assumes listings are loaded
            f"تعداد خریدها: {len(db_user.purchases) if db_user.purchases else 0}", # Assumes purchases are loaded
        ]
        await message.reply_text("\n".join(user_info_parts), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await message.reply_text(
            f"کاربر با شناسه '{escape_markdown_v2(identifier)}' یافت نشد\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def _send_list_users_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    query = update.callback_query
    message = update.message or (query.message if query else None)
    if not message: return

    async with get_db_session() as db_session:
        users, total_count = await crud.admin_get_all_users(db_session, page=page, page_size=USERS_LIST_PAGE_SIZE)

    if not users and page == 0:
        text = "هیچ کاربری یافت نشد."
        reply_markup = None
    else:
        # Escape literal parentheses for MARKDOWN_V2
        text_parts = [f"*لیست کاربران \\(صفحه {page + 1}\\)*\n"]
        for u in users:
            status_icons = []
            if u.is_admin: status_icons.append("👑") # Admin
            if u.is_verified: status_icons.append("✅") # Verified
            if not u.is_active: status_icons.append("🚫") # Disabled icon

            status_str = " ".join(status_icons)
            # FIX: Escape literal parentheses for MARKDOWN_V2
            text_parts.append(
                f"`{u.telegram_id}`: @{escape_markdown_v2(u.username or 'N/A')} \\({escape_markdown_v2(u.first_name or 'N/A')}\\) {status_str}"
            )
        text = "\n".join(text_parts)

        total_pages = (total_count + USERS_LIST_PAGE_SIZE - 1) // USERS_LIST_PAGE_SIZE
        keyboard_buttons = []
        row = []
        if page > 0:
            row.append(InlineKeyboardButton("« قبلی", callback_data=f"{CALLBACK_ADMIN_LIST_USERS_PAGE}{page - 1}"))
        if total_pages > 1 : # Only show page number if more than one page
             row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="admin_noop")) # No operation
        if page < total_pages - 1:
            row.append(InlineKeyboardButton("بعدی »", callback_data=f"{CALLBACK_ADMIN_LIST_USERS_PAGE}{page + 1}"))
        if row:
            keyboard_buttons.append(row)
        reply_markup = InlineKeyboardMarkup(keyboard_buttons) if keyboard_buttons else None

    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e: # Handle cases where message content is unchanged
            if "Message is not modified" in str(e):
                await query.answer("صفحه تغییری نکرده است.")
            else:
                logger.error(f"Error editing message for list_users: {e}", exc_info=True)
                await query.answer("خطا در بروزرسانی لیست.")
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)


@admin_required
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    page = 0
    if context.args and context.args[0].isdigit():
        page = int(context.args[0]) -1 # User inputs 1-based page
        if page < 0: page = 0
    await _send_list_users_page(update, context, page=page)

@admin_required
async def list_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(CALLBACK_ADMIN_LIST_USERS_PAGE)[1])
    await _send_list_users_page(update, context, page=page)

@admin_required
async def admin_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles no-operation callbacks, like page numbers."""
    query = update.callback_query
    if query:
        await query.answer() # Acknowledge the callback


# Meal Management Handlers
@admin_required
async def add_meal_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("شروع فرآیند افزودن غذا جدید.\n۱. توضیحات غذا را وارد کنید (مثال: چلو خورشت قیمه):")
    return ADDMEAL_ASK_DESCRIPTION

async def add_meal_receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text("توضیحات نمی‌تواند خالی باشد. لطفا مجددا وارد کنید:")
        return ADDMEAL_ASK_DESCRIPTION
    context.user_data['addmeal_description'] = description

    # Create InlineKeyboard for meal type selection
    keyboard = [
        [
            InlineKeyboardButton("ناهار 🍚", callback_data=CALLBACK_ADDMEAL_TYPE_NAHAR),
            InlineKeyboardButton("شام 🌙", callback_data=CALLBACK_ADDMEAL_TYPE_SHAM),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("۲\\. نوع غذا را انتخاب کنید:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return ADDMEAL_ASK_TYPE


async def add_meal_receive_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Extract meal type from callback data
    # e.g., "addmeal_type_ناهار" -> "ناهار"
    meal_type = query.data.split(CALLBACK_ADDMEAL_TYPE_PREFIX)[1]

    if not meal_type:
        await query.edit_message_text("خطا در انتخاب نوع غذا. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END  # Or return to a previous state if appropriate

    context.user_data['addmeal_type'] = meal_type
    logger.info(f"Admin selected meal type: {meal_type} for meal {context.user_data.get('addmeal_description')}")

    # Edit the message to remove buttons and ask for the next step
    await query.edit_message_text(
        f"نوع غذا انتخاب شد: *{escape_markdown_v2(meal_type)}*\n\n"
        "۳\\. تاریخ شمسی غذا را وارد کنید \\(فرمت ۱۴۰۴/۰۲/۱۸\\):",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    return ADDMEAL_ASK_DATE

async def add_meal_receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    try:
        # Use jdatetime.datetime.strptime to handle potential time component then get date
        j_date = jdatetime.datetime.strptime(date_str, '%Y/%m/%d').date()

        # Basic validation: Check if date is in the past (using jdatetime)
        if j_date < jdatetime.date.today():
            await update.message.reply_text(
                "تاریخ غذا نمی‌تواند در گذشته باشد\\. لطفا تاریخ شمسی معتبری وارد کنید \\(YYYY/MM/DD\\):",
                parse_mode=ParseMode.MARKDOWN_V2)
            return ADDMEAL_ASK_DATE

        # Convert to Gregorian for storage
        gregorian_date = j_date.togregorian()
        context.user_data['addmeal_date'] = gregorian_date  # Store Gregorian date object
        logger.info(f"Received Shamsi date {date_str}, stored as Gregorian {gregorian_date}")

        await update.message.reply_text("۴\\. قیمت اصلی غذا \\(دانشگاه\\) به تومان را وارد کنید \\(عدد\\):",
                                        parse_mode=ParseMode.MARKDOWN_V2)
        return ADDMEAL_ASK_PRICE
    except ValueError:
        await update.message.reply_text("فرمت تاریخ شمسی نامعتبر است\\. لطفا مجددا وارد کنید \\(YYYY/MM/DD\\):", parse_mode=ParseMode.MARKDOWN_V2)
        return ADDMEAL_ASK_DATE


async def add_meal_receive_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_str = update.message.text.strip()
    try:
        price = Decimal(price_str)
        if price <= 0:
            raise ValueError("قیمت باید مثبت باشد.")
        context.user_data['addmeal_price'] = price
        await update.message.reply_text(
            "۵\\. حداکثر قیمت مجاز فروش \\(به تومان\\) را وارد کنید \\(عدد\\)\\. اگر محدودیت ندارد، '0' یا 'skip' را وارد کنید:",
            parse_mode=ParseMode.MARKDOWN_V2)
        return ADDMEAL_ASK_PRICELIMIT
    except (InvalidOperation, ValueError) as e:
        await update.message.reply_text(f"قیمت نامعتبر: {escape_markdown_v2(str(e))}\\. لطفا فقط عدد مثبت وارد کنید:")
        return ADDMEAL_ASK_PRICE

async def add_meal_receive_price_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_limit_str = update.message.text.strip().lower()
    price_limit = None
    if price_limit_str not in ['0', 'skip', '']:
        try:
            price_limit_decimal = Decimal(price_limit_str)
            if price_limit_decimal < 0: # Allow 0 for no limit, but not negative
                 raise ValueError("حداکثر قیمت نمی‌تواند منفی باشد.")
            if price_limit_decimal == 0 :
                price_limit = None # Treat 0 as no limit explicit None
            else:
                price_limit = price_limit_decimal
        except (InvalidOperation, ValueError) as e:
            await update.message.reply_text(f"حداکثر قیمت نامعتبر: {escape_markdown_v2(str(e))}\\. لطفا عدد مثبت، '0' یا 'skip' وارد کنید:")
            return ADDMEAL_ASK_PRICELIMIT
    elif price_limit_str == '0': # Explicitly handle '0' string as no limit
        price_limit = None


    context.user_data['addmeal_price_limit'] = price_limit

    # Confirmation
    desc = context.user_data['addmeal_description']
    mtype = context.user_data['addmeal_type']
    gregorian_date = context.user_data['addmeal_date']
    mdate_shamsi = format_gregorian_date_to_shamsi(gregorian_date)  # Convert for display
    mprice = context.user_data['addmeal_price']
    mplimit_val = context.user_data['addmeal_price_limit']

    mplimit_display = "ندارد"
    if isinstance(mplimit_val, Decimal):
        mplimit_display = f"`{mplimit_val:,.0f} تومان`"

    text = (
        f"*تایید اطلاعات غذا:*\n"
        f"توضیحات: {escape_markdown_v2(desc)}\n"
        f"نوع: {escape_markdown_v2(mtype)}\n"
        f"تاریخ: `{mdate_shamsi}`\n"
        f"قیمت اصلی: `{mprice:,.0f}` تومان\n"
        f"حداکثر قیمت فروش: {mplimit_display}\n"
        f"\nآیا این غذا به سیستم اضافه شود؟"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ بله، اضافه کن", callback_data=CALLBACK_ADMIN_MEAL_CONFIRM_YES),
            InlineKeyboardButton("❌ خیر، لغو کن", callback_data=CALLBACK_ADMIN_MEAL_CONFIRM_NO),
        ]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    return ADDMEAL_CONFIRM

async def add_meal_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == CALLBACK_ADMIN_MEAL_CONFIRM_NO:
        await query.edit_message_text("عملیات افزودن غذا لغو شد.")
        context.user_data.clear()
        return ConversationHandler.END

    description = context.user_data.get('addmeal_description')
    meal_type = context.user_data.get('addmeal_type')
    meal_date = context.user_data.get('addmeal_date')
    price = context.user_data.get('addmeal_price')
    price_limit = context.user_data.get('addmeal_price_limit')

    if not all([description, meal_type, meal_date, price is not None]):
        await query.edit_message_text("خطا: اطلاعات ناقص است\\. لطفا دوباره با /addmeal شروع کنید\\.")
        context.user_data.clear()
        return ConversationHandler.END

    async with get_db_session() as db_session:
        new_meal = await crud.create_meal(
            db_session,
            description=description,
            meal_type=meal_type,
            meal_date=meal_date,
            price=price,
            price_limit=price_limit
        )

    if new_meal:
        await query.edit_message_text(f"✅ غذای '{escape_markdown_v2(new_meal.description)}' با موفقیت به سیستم اضافه شد \\(ID: `{new_meal.id}`\\)\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped parentheses
    else:
        await query.edit_message_text("❌ خطا در افزودن غذا به پایگاه داده \\(ممکن است تکراری باشد یا خطای دیگری رخ داده باشد\\)\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped parentheses

    context.user_data.clear()
    return ConversationHandler.END

async def add_meal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("عملیات افزودن غذا لغو شد.")
    elif update.message:
        await update.message.reply_text("عملیات افزودن غذا لغو شد.")
    logger.info(f"Admin {update.effective_user.id} cancelled add_meal conversation.")
    context.user_data.clear()
    return ConversationHandler.END


@admin_required
async def delete_meal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not context.args or len(context.args) != 1:
        await message.reply_text("استفاده: `/delmeal <meal_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        meal_id = int(context.args[0])
    except ValueError:
        await message.reply_text("آیدی غذا باید یک عدد باشد\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    async with get_db_session() as db_session:
        meal_to_delete = await crud.get_meal_by_id(db_session, meal_id)
        if not meal_to_delete:
            await message.reply_text(f"غذا با آیدی {meal_id} یافت نشد\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return

        deleted = await crud.delete_meal(db_session, meal_id)

    if deleted:
        await message.reply_text(f"✅ غذای '{escape_markdown_v2(meal_to_delete.description)}' \\(ID: `{meal_id}`\\) با موفقیت حذف شد\\.", parse_mode=ParseMode.MARKDOWN_V2) # Escaped parentheses
    else:
        await message.reply_text(f"❌ خطا در حذف غذا با آیدی {meal_id}\\. \\(ممکن است توسط آگهی‌ها استفاده شده باشد یا وجود نداشته باشد\\)", parse_mode=ParseMode.MARKDOWN_V2) # Escaped parentheses


# Listing Management Handlers
@admin_required
async def delete_listing_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not context.args or len(context.args) != 1:
        await message.reply_text("استفاده: `/dellisting <listing_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        listing_id = int(context.args[0])
    except ValueError:
        await message.reply_text("آیدی آگهی باید یک عدد باشد\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    async with get_db_session() as db_session:
        deleted = await crud.admin_delete_listing(db_session, listing_id)

    if deleted:
        await message.reply_text(f"✅ آگهی با آیدی `{listing_id}` با موفقیت حذف شد\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await message.reply_text(f"❌ خطا در حذف آگهی با آیدی {listing_id}\\. \\(ممکن است وجود نداشته باشد\\)", parse_mode=ParseMode.MARKDOWN_V2) # Escaped parentheses


# Conversation Handler for /addmeal
add_meal_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("addmeal", add_meal_start)],
    states={
        ADDMEAL_ASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meal_receive_description)],
        ADDMEAL_ASK_TYPE: [CallbackQueryHandler(add_meal_receive_type_callback, pattern=f"^{CALLBACK_ADDMEAL_TYPE_PREFIX}(ناهار|شام)$")],
        ADDMEAL_ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meal_receive_date)],
        ADDMEAL_ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meal_receive_price)],
        ADDMEAL_ASK_PRICELIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meal_receive_price_limit)],
        ADDMEAL_CONFIRM: [CallbackQueryHandler(add_meal_confirm, pattern=f"^({CALLBACK_ADMIN_MEAL_CONFIRM_YES}|{CALLBACK_ADMIN_MEAL_CONFIRM_NO})$")],
    },
    fallbacks=[
        CommandHandler("cancel", add_meal_cancel),
    ],
    conversation_timeout=600,
)