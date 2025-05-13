import logging
from functools import wraps
from decimal import Decimal, InvalidOperation
from datetime import date as GregorianDate # Alias to avoid conflict with datetime.date
from datetime import datetime
import jdatetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode
from config import ADMIN_TELEGRAM_IDS, USERS_LIST_PAGE_SIZE
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
    # /getuser
    message = update.message
    if not message or not context.args or len(context.args) != 1:
        await message.reply_text("استفاده: `/getuser <user_telegram_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_user_tg_id = int(context.args[0])
    except ValueError:
        await message.reply_text("آیدی تلگرام کاربر باید یک عدد باشد\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    async with get_db_session() as db_session:
        user = await crud.get_user_details_for_admin(db_session, target_user_tg_id) # This loads listings/purchases

    if user:
        credit_card_display = "ثبت نشده"
        if user.credit_card_number:
            # raw_card = user.credit_card_number
            # if len(raw_card) > 4:
            #     credit_card_display = f"`**** **** **** {escape_markdown_v2(raw_card[-4:])}`"
            # else:
            #     credit_card_display = f"`{escape_markdown_v2(raw_card)}` \\(کوتاه\\)"
            credit_card_display = f"`{escape_markdown_v2(user.credit_card_number)}`"

        # Convert created_at to Shamsi for display
        created_at_shamsi = format_gregorian_date_to_shamsi(user.created_at)
        # Get time part separately if needed (Shamsi conversion only done for date part)
        time_str = user.created_at.strftime('%H:%M') if user.created_at else ""

        user_info_parts = [
            f"*اطلاعات کاربر: {user.telegram_id}*",
            f"نام کاربری: @{escape_markdown_v2(user.username)}" if user.username else "نام کاربری: ندارد",
            f"نام: {escape_markdown_v2(user.first_name)}",
            f"نام خانوادگی: {escape_markdown_v2(user.last_name)}" if user.last_name else "نام خانوادگی: ندارد",
            f"شماره دانشجویی: `{escape_markdown_v2(user.education_number)}`" if user.education_number else "شماره دانشجویی: ثبت نشده",
            f"شماره ملی: `{escape_markdown_v2(user.identity_number)}`" if user.identity_number else "شماره ملی: ثبت نشده",
            f"شماره تماس: `{escape_markdown_v2(user.phone_number)}`" if user.phone_number else "شماره تماس: ثبت نشده",
            f"شماره کارت: {credit_card_display}",
            f"تایید شده: {'✅' if user.is_verified else '❌'}",
            f"ادمین: {'✅' if user.is_admin else '❌'}",
            f"فعال: {'✅' if user.is_active else '❌'}",
            f"تاریخ عضویت: {created_at_shamsi} {escape_markdown_v2(time_str)}",
            f"تعداد آگهی‌های فروش: {len(user.listings) if user.listings else 0}",
            f"تعداد خریدها: {len(user.purchases) if user.purchases else 0}",
        ]
        await message.reply_text("\n".join(user_info_parts), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await message.reply_text(f"کاربر با آیدی تلگرام {target_user_tg_id} یافت نشد\\.", parse_mode=ParseMode.MARKDOWN_V2)

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