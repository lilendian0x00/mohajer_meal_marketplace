import io
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from . import PERSIAN_DAYS_MAP
from .common import (
    CALLBACK_BUY_REFRESH, CALLBACK_BUYER_CANCEL_PENDING,
    CALLBACK_SELLER_REJECT_PENDING, get_main_menu_keyboard, CALLBACK_BUYER_PAYMENT_SENT
)
import utility
from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models

logger = logging.getLogger(__name__)


# Helper function moved here as it's only used by buying handlers
async def _generate_buy_food_response(db_session: crud.AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    """
    Fetches available listings and generates the message text and inline keyboard.
    Includes the "Refresh" button.

    Returns:
        tuple[str, InlineKeyboardMarkup | None]: The message text and the keyboard markup.
                                               Returns None for markup if no listings.
    """
    available_listings = await crud.get_available_listings(db_session) # Should load seller+meal

    title = utility.escape_markdown_v2("🛒 لیست غذاهای موجود برای خرید:\n\n")
    refresh_button = InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data=CALLBACK_BUY_REFRESH)

    if not available_listings:
        message_text = title + utility.escape_markdown_v2("در حال حاضر هیچ غذایی برای فروش ثبت نشده است.")
        # Still include Refresh button even if no listings
        reply_markup = InlineKeyboardMarkup([[refresh_button]])
        return message_text, reply_markup

    response_parts = [title]
    inline_buttons = [] # List to hold button rows

    for listing in available_listings:
        meal_desc_raw = "غذای نامشخص"
        shamsi_date_str_raw = "تاریخ نامشخص"
        persian_day_name_raw = "روز نامشخص"
        meal_type_raw = "نوع نامشخص"

        if listing.meal:
            meal = listing.meal
            meal_desc_raw = meal.description or meal_desc_raw
            meal_type_raw = meal.meal_type or meal_type_raw
            if meal.date:
                meal_date_obj = meal.date
                shamsi_date_str_raw = utility.format_gregorian_date_to_shamsi(meal_date_obj)
                day_of_week_int = meal_date_obj.weekday()
                persian_day_name_raw = PERSIAN_DAYS_MAP.get(day_of_week_int, "روز نامشخص")

        # Escape user-generated content
        meal_desc = utility.escape_markdown_v2(meal_desc_raw)
        meal_type = utility.escape_markdown_v2(meal_type_raw)
        shamsi_date_str = utility.escape_markdown_v2(shamsi_date_str_raw)
        persian_day_name = utility.escape_markdown_v2(persian_day_name_raw)

        # Escape seller name for Markdown V2 compatibility if needed, or use regular Markdown
        seller_name_raw_display = "ناشناس"
        if listing.seller and listing.seller.first_name:
            seller_name_raw_display = listing.seller.first_name

        # Prepare the display part of the link, escaping it
        escaped_seller_display_name = utility.escape_markdown_v2(seller_name_raw_display)

        seller_name_md = utility.escape_markdown_v2("ناشناس")  # Default if no seller info
        if listing.seller:
            seller_telegram_id = listing.seller.telegram_id
            if listing.seller.username:
                username_display_text = f"@{listing.seller.username}"
                escaped_link_text = utility.escape_markdown_v2(username_display_text)
                seller_name_md = f"[{escaped_link_text}](https://t.me/{listing.seller.username})"
            else:
                first_name_raw = listing.seller.first_name if listing.seller.first_name else "ناشناس"
                link_text_raw = f"{first_name_raw} (ID: {seller_telegram_id})"  # Keep (ID: ...) unescaped inside link text for now
                escaped_link_text = utility.escape_markdown_v2(link_text_raw)
                seller_name_md = f"[{escaped_link_text}](tg://user?id={seller_telegram_id})"


        price_str_raw = f"{listing.price:,.0f}" if listing.price is not None else "نامشخص"
        price_str = utility.escape_markdown_v2(price_str_raw)

        part = (
            f"🍽️ *{meal_desc}* \\({meal_type} \\- {persian_day_name}، {shamsi_date_str}\\)\n"
            f"👤 فروشنده: {seller_name_md}\n"
            f"💰 قیمت: {price_str} تومان\n"
            f"🆔 شماره آگهی: `{listing.id}`\n"
        )
        response_parts.append(part)

        inline_buttons.append([
            InlineKeyboardButton(
                f"خرید آگهی {listing.id} ({price_str_raw} تومان)",
                callback_data=f'buy_listing_{listing.id}'
            )
        ])
        # Add a separator after each listing's details
        response_parts.append(utility.escape_markdown_v2("--------------------") + "\n")

    # Add the refresh button as the last row
    inline_buttons.append([refresh_button])
    full_message = "".join(response_parts)
    reply_markup = InlineKeyboardMarkup(inline_buttons)

    # Handle potential length issues (optional refinement)
    if len(full_message) > 4096:
        logger.warning("Generated buy food list message exceeds 4096 chars, might be truncated by Telegram.")
        # Smart truncation
        truncated_message = full_message[:4000]  # Leave some space for ellipsis and note
        # Find last complete line
        last_newline = truncated_message.rfind('\n')
        if last_newline != -1:
            truncated_message = truncated_message[:last_newline]
        full_message = truncated_message + "\n" + utility.escape_markdown_v2("...\n(لیست برای نمایش خلاصه شد)")

    return full_message, reply_markup


# Buy Food Handlers
# Handlers for main menu buttons
async def handle_buy_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Buy Food' button press: Fetches and displays available listings."""
    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    logger.info(f"'Buy Food' button pressed by user {user.id}")

    # Check Verification Status
    try:
        async with get_db_session() as db_session:
            db_user = await crud.get_or_create_user_and_update_info(db_session, user)

            # if not db_user:
            #      logger.error(f"User {user.id} not found in DB during buy food.")
            #      await message.reply_text("خطا: اطلاعات کاربری شما یافت نشد. لطفا /start بزنید.")
            #      return
            if not db_user.is_verified:
                logger.warning(f"Unverified user {user.id} attempted action: buy food")
                await message.reply_text("برای خرید غذا، ابتدا باید فرآیند اعتبارسنجی را با دستور /start کامل کنید.")
                return
    except Exception as e:
        logger.error(f"DB error checking user verification for {user.id} in handle_buy_food: {e}", exc_info=True)
        await message.reply_text("خطا در بررسی وضعیت اعتبارسنجی. لطفا دوباره تلاش کنید.")
        return

    try:
        message_text, reply_markup = await _generate_buy_food_response(db_session)

        # Send the response
        await message.reply_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup,
            disable_web_page_preview=True  # Good practice for lists
        )

    except Exception as e:
        logger.error(f"Failed to get or format available listings for user {user.id}: {e}", exc_info=True)
        await message.reply_text(
            "خطا در دریافت لیست غذاها. لطفا دوباره تلاش کنید."
        )

async def handle_buy_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the refresh button press on the buy food list."""
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    # await query.answer("🔄 در حال بروزرسانی...") # Acknowledge button press

    logger.info(f"User {user.id} pressed 'Refresh List' for buy food.")

    message_text = "خطا در بروزرسانی لیست."  # Default error
    reply_markup = None  # Default markup

    try:
        async with get_db_session() as db_session:  # Session acquired
            # Acknowledge button press *after* getting session, before long operation
            # This is generally safer than acknowledging right at the start.
            # If DB connection fails, the user doesn't get a potentially misleading "updating" message.
            await query.answer("🔄 در حال بروزرسانی...")
            message_text, reply_markup = await _generate_buy_food_response(db_session)

        # Edit the message *after* the session is closed
        try:
            await query.edit_message_text(
                text=message_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            logger.debug(f"Successfully refreshed buy list for user {user.id}")
        except BadRequest as e:
            # Explicitly check for "Message is not modified"
            if "Message is not modified" in str(e):
                logger.info(f"Buy list refresh for user {user.id} resulted in no changes.")
                # Answer the callback quietly if the message didn't change
                await query.answer("لیست بروز است.")
            else:
                # Log and report other BadRequest errors
                logger.error(f"Unhandled BadRequest refreshing buy list for user {user.id}: {e}", exc_info=True)
                # Use answer for non-critical errors after initial edit attempt
                await query.answer("خطای تلگرام در بروزرسانی.", show_alert=True)
        except Forbidden:
            logger.warning(f"Bot blocked by user {user.id}, cannot refresh buy list.")
            await query.answer("خطا: امکان ویرایش پیام نیست. ربات مسدود شده؟", show_alert=True)
        except Exception as e_edit:
            # Catch other potential errors during edit_message_text
            logger.error(f"Error editing message after refresh for user {user.id}: {e_edit}", exc_info=True)
            await query.answer("خطا در نمایش لیست بروز شده.", show_alert=True)

    except Exception as e_db:
        # This catches errors during DB interaction (within async with)
        logger.error(f"Error fetching data for buy list refresh for user {user.id}: {e_db}", exc_info=True)
        # If DB fails, we might not have even answered the callback yet
        try:
            # Try to answer the original callback with an error
            await query.answer("خطا در دریافت اطلاعات بروز شده.", show_alert=True)
        except Exception as e_answer:
            logger.error(f"Failed to even answer callback query after DB error: {e_answer}")
        # Also try to edit the message if possible (might fail if query already answered)
        try:
            await query.edit_message_text("خطا در دریافت اطلاعات بروز شده.")
        except Exception:
            pass  # Ignore error if editing fails after answering


async def handle_purchase_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the initial 'Buy Listing X' button press. Shows confirmation."""
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    callback_data = query.data
    try:
        listing_id = int(callback_data.split('_')[-1]) # Extracts ID from 'buy_listing_ID'
        logger.info(f"User {user.id} initiated purchase for listing {listing_id}")
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data format for buy button: {callback_data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return

    # Check user verification status
    try:
        async with get_db_session() as db_session:
             buyer_db_user = await crud.get_user_by_telegram_id(db_session, user.id)
             if not buyer_db_user or not buyer_db_user.is_verified:
                 logger.warning(f"Unverified user {user.id} clicked buy button for listing {listing_id}.")
                 await query.answer("برای خرید باید ابتدا اعتبارسنجی شوید (/start).", show_alert=True)
                 return
    except Exception as e:
        logger.error(f"DB Error checking buyer {user.id} verification: {e}")
        await query.edit_message_text("خطا در بررسی اعتبارسنجی.")
        return

    # Fetch listing details for confirmation
    try:
        async with get_db_session() as db_session:
            # get_listing_by_id should load seller and meal
            listing = await crud.get_listing_by_id(db_session, listing_id)

        if not listing:
            await query.edit_message_text("متاسفانه این آگهی دیگر موجود نیست.")
            return
        if listing.status != models.ListingStatus.AVAILABLE:
             await query.edit_message_text(f"این آگهی در حال حاضر برای خرید در دسترس نیست (وضعیت: {listing.status.value}).")
             return
        if listing.seller_id == user.id: # Check against DB user ID
             await query.edit_message_text("شما نمی‌توانید آگهی خودتان را بخرید.")
             return

        meal_desc_raw = "نامشخص"
        meal_date_str_raw = "نامشخص"
        meal_type_raw = "نامشخص"

        # Access meal directly from listing
        if listing.meal:
            meal = listing.meal
            meal_desc_raw = meal.description or meal_desc_raw
            meal_type_raw = meal.meal_type or meal_type_raw
            if meal.date:
                try:
                    # meal_date_str_raw = meal.date.strftime('%Y-%m-%d')
                    meal_date_str_raw = utility.format_gregorian_date_to_shamsi(meal.date)
                except AttributeError:
                    meal_date_str_raw = str(meal.date)

        # Escape all dynamic parts for MarkdownV2
        meal_desc = escape_markdown(meal_desc_raw, version=2)
        meal_type = escape_markdown(meal_type_raw, version=2)
        meal_date_str = escape_markdown(meal_date_str_raw, version=2)

        seller_telegram_id = listing.seller.telegram_id
        seller_name = "ناشناس"

        if listing.seller.username:
            # Link text will be @username
            # Link URL will be https://t.me/username
            # The username part of the link text needs to be escaped for MarkdownV2
            username_display_text = f"@{listing.seller.username}"
            escaped_link_text = escape_markdown(username_display_text, version=2)
            # The username in the URL itself does not need Markdown escaping
            seller_name = f"[{escaped_link_text}](https://t.me/{listing.seller.username})"
        else:
            # 2. No username, use First Name (ID: TELEGRAM_ID)
            # Link text will be "FirstName (ID: 1234567)"
            # Link URL will be tg://user?id=1234567

            # Fallback for first_name if it's None or empty
            first_name_raw = listing.seller.first_name if listing.seller.first_name else "ناشناس"

            # Construct the full display text for the link
            link_text_raw = f"{first_name_raw} (ID: {seller_telegram_id})"
            escaped_link_text = escape_markdown(link_text_raw, version=2)
            seller_name = f"[{escaped_link_text}](tg://user?id={seller_telegram_id})"



        price_raw = listing.price
        price_str = escape_markdown(f"{price_raw:,.0f}" if price_raw is not None else "نامشخص", version=2)
        listing_id_str = escape_markdown(str(listing.id), version=2)

        # Use the corrected variables here
        confirmation_text = (
            "⚠️ *تایید خرید* ⚠️\n\n"
            f"شما در حال خرید:\n"
            # Escaped literal parentheses here:
            f"🍽️ *{meal_desc}* \\({meal_type} \\- {meal_date_str}\\)\n"
            f"👤 از فروشنده: {seller_name}\n"
            f"💰 به قیمت: {price_str} تومان\n"
            f"🆔 شماره آگهی: `{listing_id_str}`\n\n"
            "آیا خرید را تایید می‌کنید؟\n"
            # Escaped literal parentheses here:
            "_\\(با تایید، اطلاعات پرداخت فروشنده به شما نمایش داده می‌شود و آگهی برای دیگران غیرفعال خواهد شد تا فروشنده پرداخت شما را تایید کند\\.\\)_"
        )
        confirm_buttons = [[
            InlineKeyboardButton("✅ بله، خرید را تایید می‌کنم", callback_data=f'confirm_buy_{listing_id}'),
            InlineKeyboardButton("❌ لغو", callback_data='cancel_buy')
        ]]
        reply_markup = InlineKeyboardMarkup(confirm_buttons)
        await query.edit_message_text(confirmation_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error preparing purchase confirmation for listing {listing_id}: {e}", exc_info=True)
        await query.edit_message_text("خطا در نمایش اطلاعات خرید.")



async def handle_confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Confirm Buy' button. Sets listing to AWAITING_CONFIRMATION, notifies users."""
    query = update.callback_query
    user = update.effective_user # This is the BUYER
    await query.answer("در حال ثبت درخواست خرید...")

    callback_data = query.data
    try:
        listing_id = int(callback_data.split('_')[-1]) # Extract ID from confirm_buy_ID
        logger.info(f"User {user.id} confirmed purchase intent for listing {listing_id}")
    except (ValueError, IndexError):
        logger.error(f"Invalid confirm callback data format: {callback_data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return

    # --- Update Listing Status and Get Seller Info ---
    updated_listing: models.Listing | None = None
    seller_card_number: str | None = None
    seller_telegram_id: int | None = None
    seller_username: str | None = None
    error_message = "خطا در پردازش درخواست خرید. لطفا دوباره تلاش کنید." # Default error

    try:
        async with get_db_session() as db_session:
            # Set listing status and pending buyer
            updated_listing = await crud.set_listing_awaiting_confirmation(
                db=db_session,
                listing_id=listing_id,
                buyer_telegram_id=user.id
            )

            # Check Failure Reason IF update failed
            if not updated_listing:
                listing_check = await crud.get_listing_by_id(db_session, listing_id)
                buyer_user_check = await crud.get_user_by_telegram_id(db_session, user.id)
                if listing_check and buyer_user_check and listing_check.seller_id == buyer_user_check.id:
                    error_message = "شما نمی‌توانید آگهی خودتان را بخرید."
                elif listing_check and listing_check.status != models.ListingStatus.AVAILABLE:
                    error_message = f"متاسفانه این آگهی دیگر برای خرید موجود نیست (وضعیت: {listing_check.status.value})."
                elif not listing_check:
                    error_message = "متاسفانه این آگهی یافت نشد."
                else:
                    error_message = "خطا در بروزرسانی وضعیت آگهی."
            elif updated_listing:
                if updated_listing.seller:
                    seller_card_number = updated_listing.seller.credit_card_number
                    seller_telegram_id = updated_listing.seller.telegram_id
                    seller_username = updated_listing.seller.username  # Get username
                else:
                    logger.error(f"Listing {listing_id} seller info could not be loaded after update.")
                    error_message = "خطا: اطلاعات فروشنده یافت نشد."
                    updated_listing = None

    except Exception as e:
        logger.error(f"Error setting listing {listing_id} to awaiting confirmation: {e}", exc_info=True)
        error_message = "خطای جدی در پردازش درخواست رخ داد."
        updated_listing = None

    # Notify Buyer and Seller
    if updated_listing and seller_card_number and seller_telegram_id:
        price_str = f"{updated_listing.price:,.0f}" if updated_listing.price is not None else "مبلغ"
        raw_meal_description = updated_listing.meal.description if updated_listing.meal else "غذا"

        part1 = f"درخواست خرید شما برای آگهی "
        part2_listing_id = f"`{listing_id}`"
        part3_meal_intro = f" ("
        part4_meal_desc = utility.escape_markdown_v2(raw_meal_description)
        part5_meal_outro_and_status = f") ثبت شد.\n"
        part6_payment_instruction1 = f"⏳ لطفا مبلغ "
        part7_price = f"*{utility.escape_markdown_v2(price_str)} تومان*"
        part8_payment_instruction2 = f" را به فروشنده واریز نمایید:\n\n"  # Changed "شماره کارت زیر" to "فروشنده"

        # Seller contact information part
        seller_contact_info_parts = [utility.escape_markdown_v2("👤 فروشنده: ")]
        if seller_username:
            seller_contact_info_parts.append(f"@{utility.escape_markdown_v2(seller_username)}")
            seller_contact_info_parts.append(utility.escape_markdown_v2(f" (ID: "))
            seller_contact_info_parts.append(f"`{seller_telegram_id}`")
            seller_contact_info_parts.append(utility.escape_markdown_v2(")\n"))
        else:
            seller_contact_info_parts.append(utility.escape_markdown_v2(f"ID: "))
            seller_contact_info_parts.append(f"`{seller_telegram_id}`")
            seller_contact_info_parts.append(utility.escape_markdown_v2("\n"))
        part_seller_contact_line = "".join(seller_contact_info_parts)

        part9_card_intro = f"💳 شماره کارت: "  # Added "شماره کارت: "
        part10_card_number = f"`{utility.escape_markdown_v2(seller_card_number)}`"
        part11_card_outro = f"\n\n"
        part12_seller_confirmation_notice = f"پس از واریز، *ابتدا دکمه «وجه را واریز کردم» را بزنید* تا به فروشنده اطلاع داده شود، سپس منتظر تایید فروشنده برای دریافت کد بمانید.\n"
        part13_warning_intro = f"🚨 "
        # part14_warning_text remains the same
        part15_cancellation_option = f"در صورت انصراف از خرید (قبل از واریز یا تایید فروشنده)، دکمه لغو را بزنید:"

        buyer_message = (
            f"{utility.escape_markdown_v2(part1)}"
            f"{part2_listing_id}"
            f"{utility.escape_markdown_v2(part3_meal_intro)}"
            f"{part4_meal_desc}"
            f"{utility.escape_markdown_v2(part5_meal_outro_and_status)}"
            f"{utility.escape_markdown_v2(part6_payment_instruction1)}"
            f"{part7_price}"
            f"{utility.escape_markdown_v2(part8_payment_instruction2)}"
            f"{part_seller_contact_line}"  # <-- ADDED SELLER CONTACT LINE
            f"{utility.escape_markdown_v2(part9_card_intro)}"
            f"{part10_card_number}"
            f"{utility.escape_markdown_v2(part11_card_outro)}"
            f"{utility.escape_markdown_v2(part12_seller_confirmation_notice)}"
            f"{utility.escape_markdown_v2(part13_warning_intro)}"
            f"*{utility.escape_markdown_v2('هشدار:')}* {utility.escape_markdown_v2(' ربات مسئولیتی در قبال تراکنش ندارد.')}\n\n"
            f"{utility.escape_markdown_v2(part15_cancellation_option)}"
        )

        buyer_payment_sent_button = InlineKeyboardButton(
            "💳 وجه را واریز کردم (اطلاع به فروشنده)",
            callback_data=f'{CALLBACK_BUYER_PAYMENT_SENT}_{listing_id}'
        )
        buyer_cancel_button = InlineKeyboardButton(
            "❌ لغو درخواست خرید",
            callback_data=f'{CALLBACK_BUYER_CANCEL_PENDING}_{listing_id}'
        )
        buyer_markup = InlineKeyboardMarkup([
            [buyer_payment_sent_button],
            [buyer_cancel_button]
        ])

        logger.debug(f"BUYER MESSAGE (handle_confirm_purchase) constructed: {buyer_message}")
        await query.edit_message_text(
            text=buyer_message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=buyer_markup
        )

        # Notify Seller
        try:
            # Escape buyer name for V2
            buyer_name_escaped = utility.escape_markdown_v2(f"@{user.username}" or user.first_name)
            # Escape price string just in case it contains '.' or other chars (though unlikely for price_str)
            price_str_escaped = utility.escape_markdown_v2(price_str)

            seller_confirm_button = InlineKeyboardButton(
                "✅ تایید دریافت وجه",
                callback_data=f'seller_confirm_{listing_id}'
            )
            seller_reject_button = InlineKeyboardButton(
                "❌ رد کردن / لغو",
                callback_data=f'{CALLBACK_SELLER_REJECT_PENDING}_{listing_id}'
            )
            seller_markup = InlineKeyboardMarkup([[seller_confirm_button, seller_reject_button]])

            seller_message = (
                f"🔔 درخواست خرید جدید برای آگهی شما\\!\n\n"
                # Escape the parentheses around meal_desc_escaped -> \\( ... \\)
                f"آگهی: `{listing_id}` \\({utility.escape_markdown_v2(raw_meal_description)}\\)\n"
                f"خریدار: {buyer_name_escaped} \\(ID: `{user.id}`\\)\n"
                f"مبلغ: {price_str_escaped} تومان\n\n"
                f"خریدار اطلاعات کارت شما را دریافت کرد\\. لطفا *پس از دریافت وجه*، دکمه 'تایید دریافت وجه' را بزنید\\.\n"
                f"در صورت عدم تمایل به فروش به این کاربر یا مشکل دیگر، دکمه 'رد کردن / لغو' را بزنید\\."
            )

            # Send notification to seller
            await context.bot.send_message(
                chat_id=seller_telegram_id,
                text=seller_message,
                reply_markup=seller_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(f"Notified seller {seller_telegram_id} about pending sale {listing_id}")
        except BadRequest as e:
            # Log the V2 specific error
            logger.error(f"Failed to notify seller {seller_telegram_id} for pending sale {listing_id} using V2: {e}", exc_info=True)
            # Try sending a fallback simple message (without markdown)
            try:
                fallback_text = f"درخواست خرید جدید برای آگهی {listing_id} از کاربر {user.first_name or user.id}. لطفا برای تایید یا رد به ربات مراجعه کنید."
                await context.bot.send_message(chat_id=seller_telegram_id, text=fallback_text)
            except Exception as fallback_err:
                logger.error(f"Failed to send even fallback notification to seller {seller_telegram_id}: {fallback_err}")
        except Exception as notify_err:
            logger.error(
                f"Unexpected error notifying seller {seller_telegram_id} for pending sale {listing_id}: {notify_err}",
                exc_info=True)
            # Inform buyer about the notification failure
            await context.bot.send_message(user.id, "خطا در ارسال پیام به فروشنده. لطفا با پشتیبانی تماس بگیرید.")
    else:
        # Handle failure: edit buyer's original message if possible
        try:
            await query.edit_message_text(error_message)
        except Exception as edit_err:
            logger.error(f"Failed to edit buyer message after purchase confirmation failure: {edit_err}")


async def handle_buyer_payment_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles when the buyer clicks 'I've Transferred the Money'.
    Records the event, notifies the seller, and updates the buyer's message.
    """
    query = update.callback_query
    user = update.effective_user

    if not query or not user or not query.data:
        logger.warning("handle_buyer_payment_sent: Missing query, user, or data.")
        if query: await query.answer("خطای داخلی در پردازش درخواست شما.", show_alert=True)
        return

    await query.answer("در حال پردازش و اطلاع‌رسانی...")

    try:
        listing_id_str = query.data.split(f"{CALLBACK_BUYER_PAYMENT_SENT}_")[-1]
        listing_id = int(listing_id_str)
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for buyer_payment_sent: {query.data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر است.", reply_markup=None)
        return

    logger.info(
        f"Buyer {user.id} (TG: @{user.username or user.first_name}) "
        f"claims to have sent payment for listing ID: {listing_id}."
    )

    seller_tg_id: int | None = None
    listing_meal_desc_raw: str = "غذا"  # Store raw description

    listing_id_md = f"`{listing_id}`"
    updated_buyer_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            "❌ لغو درخواست خرید",
            callback_data=f'{CALLBACK_BUYER_CANCEL_PENDING}_{listing_id}'
        )]]
    )

    try:
        async with get_db_session() as db_session:
            stmt = select(models.Listing).where(models.Listing.id == listing_id).options(
                joinedload(models.Listing.seller).load_only(models.User.telegram_id, models.User.username,
                                                            models.User.first_name),
                joinedload(models.Listing.meal).load_only(models.Meal.description)
            )
            listing_result = await db_session.execute(stmt)
            listing = listing_result.scalar_one_or_none()
            current_db_user = await crud.get_user_by_telegram_id(db_session, user.id)

            if not listing:
                logger.warning(f"Listing {listing_id} not found when buyer {user.id} claimed payment sent.")
                await query.edit_message_text("خطا: آگهی مورد نظر یافت نشد.", reply_markup=None)
                return
            if listing.status != models.ListingStatus.AWAITING_CONFIRMATION:
                logger.warning(
                    f"Listing {listing_id} status is '{listing.status.value}' (not AWAITING_CONFIRMATION) "
                    f"when buyer {user.id} claimed payment."
                )
                await query.edit_message_text("خطا: این آگهی دیگر در انتظار پرداخت نیست.", reply_markup=None)
                return
            if not current_db_user or listing.pending_buyer_id != current_db_user.id:
                logger.warning(
                    f"User {user.id} (DB ID: {current_db_user.id if current_db_user else 'N/A'}) "
                    f"is not the pending buyer for listing {listing_id} "
                    f"(Pending Buyer DB ID: {listing.pending_buyer_id})."
                )
                await query.edit_message_text("خطا: شما خریدار این آگهی نیستید.", reply_markup=None)
                return
            if listing.seller:
                seller_tg_id = listing.seller.telegram_id
            else:
                logger.error(f"Critical: Seller not found for listing {listing_id} in AWAITING_CONFIRMATION state.")
                await query.edit_message_text("خطای سیستمی: اطلاعات فروشنده یافت نشد.", reply_markup=None)
                return
            if listing.meal and listing.meal.description:
                listing_meal_desc_raw = listing.meal.description  # Store raw

            if not hasattr(listing, 'buyer_notified_payment_at') or listing.buyer_notified_payment_at is None:
                listing.buyer_notified_payment_at = datetime.now(timezone.utc)
                db_session.add(listing)
                await db_session.commit()
                logger.info(f"Recorded timestamp: Buyer {user.id} notified payment for listing {listing_id}.")
            else:
                logger.info(
                    f"Buyer {user.id} re-clicked payment notification for listing {listing_id}. Timestamp already exists.")
    except Exception as e_db:
        logger.error(f"Database error during buyer_payment_sent for listing {listing_id} by buyer {user.id}: {e_db}",
                     exc_info=True)
        await query.edit_message_text(
            "خطا در پردازش اطلاعات شما. لطفا به فروشنده اطلاع دهید یا با پشتیبانی تماس بگیرید.",
            reply_markup=updated_buyer_markup
        )
        return

    if not seller_tg_id:
        logger.error(f"Seller TG ID is still None after DB checks for listing {listing_id}. Cannot notify.")
        await query.edit_message_text(
            "خطای سیستمی: امکان اطلاع‌رسانی به فروشنده وجود ندارد. لطفا با پشتیبانی تماس بگیرید.",
            reply_markup=updated_buyer_markup
        )
        return

    # Prepare dynamic parts (escape them individually)
    buyer_display_name_escaped = utility.escape_markdown_v2(
        user.username or user.first_name or f"ID: {user.id}")
    listing_meal_desc_escaped = utility.escape_markdown_v2(listing_meal_desc_raw)

    # Construct seller notification text carefully for MarkdownV2
    seller_notification_text = (
        f"📢 خریدار \\({buyer_display_name_escaped}\\) اعلام کرد که وجه را برای آگهی {listing_id_md} "
        f"\\({listing_meal_desc_escaped}\\) واریز کرده است\\.\n\n"
        f"لطفا موجودی حساب خود را بررسی کرده و در صورت دریافت وجه، از طریق دکمه‌های قبلی در ربات، فروش را تایید کنید\\."
    )

    # Construct buyer's updated message texts
    # These are the pieces that will be joined. Dynamic parts are already escaped.
    # Static parts that need escaping are escaped here directly.
    buyer_msg_part1 = utility.escape_markdown_v2(f"شما اعلام کردید که وجه را برای آگهی ")
    buyer_msg_part2_listing_info = f"{listing_id_md} \\({listing_meal_desc_escaped}\\) "  # Note escaped parens
    buyer_msg_part3 = utility.escape_markdown_v2(f"واریز کرده‌اید.\n\n")
    buyer_msg_part4 = utility.escape_markdown_v2("لطفا منتظر تایید فروشنده بمانید.\n")
    buyer_msg_part5 = utility.escape_markdown_v2(
        "در صورت عدم تایید توسط فروشنده پس از مدت معقول، می‌توانید با ایشان یا پشتیبانی تماس بگیرید.\n\n")
    buyer_msg_part6 = utility.escape_markdown_v2(
        "همچنان می‌توانید درخواست خرید خود را از طریق دکمه زیر لغو کنید (تا پیش از تایید نهایی فروشنده):")

    common_buyer_message_suffix = (
        f"{buyer_msg_part1}{buyer_msg_part2_listing_info}{buyer_msg_part3}"
        f"{buyer_msg_part4}{buyer_msg_part5}{buyer_msg_part6}"
    )

    buyer_message_on_seller_notify_success = utility.escape_markdown_v2(
        "✅ به فروشنده اطلاع داده شد.\n") + common_buyer_message_suffix

    buyer_message_on_seller_notify_fail = (
            utility.escape_markdown_v2(
                "اقدام شما مبنی بر پرداخت وجه در سیستم ثبت شد.\n"
                "⚠️ اما مشکلی در اطلاع‌رسانی مستقیم به فروشنده پیش آمد. "
                "لطفا خودتان نیز به ایشان اطلاع دهید یا منتظر بمانید.\n\n"
            ) + common_buyer_message_suffix
    )

    try:
        await context.bot.send_message(
            chat_id=seller_tg_id,
            text=seller_notification_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(
            f"Successfully notified seller {seller_tg_id} that buyer {user.id} claims to have paid for listing {listing_id}.")

        await query.edit_message_text(
            text=buyer_message_on_seller_notify_success,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=updated_buyer_markup
        )

    except (Forbidden, BadRequest) as e_tg:
        logger.warning(
            f"Telegram error notifying seller {seller_tg_id} for listing {listing_id} payment: {e_tg}. "
            f"Error message: {e_tg.message}"  # Log the actual Telegram error message
        )
        await query.edit_message_text(
            text=buyer_message_on_seller_notify_fail,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=updated_buyer_markup
        )
    except Exception as e_unexpected:
        logger.error(
            f"Unexpected error during seller notification or buyer message update for listing {listing_id}: {e_unexpected}",
            exc_info=True)

        fallback_buyer_text = utility.escape_markdown_v2(
            "خطای ناشناخته‌ای هنگام اطلاع‌رسانی به فروشنده رخ داد. "
            "اقدام شما ثبت شده است. لطفا با فروشنده نیز تماس بگیرید."
        )
        await query.edit_message_text(
            text=fallback_buyer_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=updated_buyer_markup
        )

async def handle_cancel_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Cancel' button press during purchase confirmation."""
    query = update.callback_query
    user = update.effective_user
    await query.answer() # Answer callback

    logger.info(f"User {user.id} canceled purchase process.")
    # Edit message back or simply confirm cancellation
    await query.edit_message_text(
        "خرید لغو شد. برای مشاهده مجدد لیست غذاها، دکمه 'خرید غذا' را بزنید.", # Purchase canceled. To see list again, press 'Buy Food'.
        reply_markup=None # Remove confirmation buttons
        )


async def handle_buyer_cancel_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the buyer cancelling a purchase in AWAITING_CONFIRMATION state."""
    query = update.callback_query
    user = update.effective_user # Buyer
    await query.answer("در حال لغو درخواست...")

    if not query.data: return

    try:
        listing_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for buyer cancel pending: {query.data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return

    logger.info(f"Buyer {user.id} initiated cancellation for pending listing {listing_id}")

    updated_listing: models.Listing | None = None
    seller_tg_id: int | None = None
    error_message = "خطا در لغو درخواست." # Default error

    try:
        async with get_db_session() as db_session:
            updated_listing, seller_tg_id = await crud.cancel_pending_purchase_by_buyer(
                db=db_session,
                listing_id=listing_id,
                buyer_telegram_id=user.id
            )
            if not updated_listing:
                # Check specific reasons if needed, e.g., listing not found or not pending
                listing_check = await crud.get_listing_by_id(db_session, listing_id)
                if not listing_check: error_message = "آگهی یافت نشد."
                elif listing_check.status != models.ListingStatus.AWAITING_CONFIRMATION: error_message="این درخواست دیگر در انتظار تایید نیست."
                elif listing_check.pending_buyer_id != user.id: error_message="شما درخواست‌دهنده این خرید نیستید."

    except Exception as e:
        logger.error(f"Error handling buyer cancellation for listing {listing_id}: {e}", exc_info=True)
        error_message = "خطای جدی هنگام لغو رخ داد."

    if updated_listing:
        # Edit buyer's message
        meal_desc = updated_listing.meal.description if updated_listing.meal else "غذا"
        await query.edit_message_text(
            f"✅ درخواست خرید شما برای آگهی `{listing_id}` ({meal_desc}) لغو شد.\n"
            f"این آگهی مجددا در دسترس قرار گرفت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None # Remove buttons
        )
        # Notify Seller
        if seller_tg_id:
            try:
                seller_message = (
                    f"❌ خریدار درخواست خرید برای آگهی `{listing_id}` ({meal_desc}) را لغو کرد.\n"
                    f"این آگهی مجدداً در وضعیت **موجود** قرار گرفت."
                )
                await context.bot.send_message(
                    chat_id=seller_tg_id,
                    text=seller_message,
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Notified seller {seller_tg_id} about buyer cancellation for listing {listing_id}")
            except (Forbidden, BadRequest) as e:
                logger.warning(f"Failed to notify seller {seller_tg_id} about buyer cancellation for {listing_id}: {e}")
            except Exception as notify_err:
                logger.error(f"Unexpected error notifying seller {seller_tg_id} about buyer cancellation for {listing_id}: {notify_err}", exc_info=True)
        else:
            logger.warning(f"Seller TG ID not found for notification on buyer cancellation of listing {listing_id}")

    else:
        # Failed to cancel, inform buyer via editing their message
        await query.edit_message_text(f"⚠️ {error_message}\nلطفا وضعیت را بررسی کنید یا با پشتیبانی تماس بگیرید.", reply_markup=None)


async def handle_seller_reject_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the seller rejecting/cancelling a purchase in AWAITING_CONFIRMATION state."""
    query = update.callback_query
    user = update.effective_user # Seller
    await query.answer("در حال رد کردن درخواست...")

    if not query.data: return

    try:
        listing_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for seller reject pending: {query.data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return

    logger.info(f"Seller {user.id} initiated rejection for pending listing {listing_id}")

    updated_listing: models.Listing | None = None
    buyer_tg_id: int | None = None
    error_message = "خطا در رد کردن درخواست." # Default error

    try:
        async with get_db_session() as db_session:
            updated_listing, buyer_tg_id = await crud.reject_pending_purchase_by_seller(
                db=db_session,
                listing_id=listing_id,
                seller_telegram_id=user.id
            )
            if not updated_listing:
                # Check specific reasons if needed
                listing_check = await crud.get_listing_by_id(db_session, listing_id)
                if not listing_check: error_message = "آگهی یافت نشد."
                elif listing_check.status != models.ListingStatus.AWAITING_CONFIRMATION: error_message="این درخواست دیگر در انتظار تایید نیست."
                elif listing_check.seller_id != user.id: error_message="شما فروشنده این آگهی نیستید."

    except Exception as e:
        logger.error(f"Error handling seller rejection for listing {listing_id}: {e}", exc_info=True)
        error_message = "خطای جدی هنگام رد کردن رخ داد."

    if updated_listing:
        # Edit seller's message
        meal_desc = updated_listing.meal.description if updated_listing.meal else "غذا"
        await query.edit_message_text(
            f"✅ درخواست خرید برای آگهی `{listing_id}` ({meal_desc}) توسط شما رد/لغو شد.\n"
            f"این آگهی مجددا در دسترس قرار گرفت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None # Remove buttons
        )
        # Notify Buyer
        if buyer_tg_id:
            try:
                buyer_message = (
                    f"❌ متاسفانه فروشنده درخواست خرید شما برای آگهی `{listing_id}` ({meal_desc}) را رد/لغو کرد.\n"
                    f"این آگهی مجدداً در وضعیت **موجود** قرار گرفته است. در صورت تمایل می‌توانید دوباره تلاش کنید یا آگهی دیگری را بررسی کنید."
                )
                await context.bot.send_message(
                    chat_id=buyer_tg_id,
                    text=buyer_message,
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Notified buyer {buyer_tg_id} about seller rejection for listing {listing_id}")
            except (Forbidden, BadRequest) as e:
                logger.warning(f"Failed to notify buyer {buyer_tg_id} about seller rejection for {listing_id}: {e}")
            except Exception as notify_err:
                logger.error(f"Unexpected error notifying buyer {buyer_tg_id} about seller rejection for {listing_id}: {notify_err}", exc_info=True)
        else:
            logger.warning(f"Buyer TG ID not found for notification on seller rejection of listing {listing_id}")
    else:
        # Failed to reject, inform seller via editing their message
        await query.edit_message_text(f"⚠️ {error_message}\nلطفا وضعیت را بررسی کنید یا با پشتیبانی تماس بگیرید.", reply_markup=None)


async def handle_seller_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles seller confirmation, calls finalize, sends code to buyer."""
    query = update.callback_query
    user = update.effective_user
    await query.answer("در حال تایید...")

    try:
        listing_id = int(query.data.split('_')[-1])
    except:
        logger.error(f"Invalid callback data for seller confirmation: {query.data}")
        await query.edit_message_text("خطا: دکمه نامعتبر.");
        return

    logger.info(f"Seller {user.id} confirmed payment for listing {listing_id}")

    # Finalize Sale Logic
    finalized_listing: models.Listing | None = None
    error_message = "خطا در نهایی کردن فروش."  # Default error
    buyer_telegram_id: int | None = None
    reservation_code: str | None = None

    try:  # INNER TRY BLOCK
        async with get_db_session() as db_session:
            # Call finalize_listing_sale
            finalized_listing, reservation_code = await crud.finalize_listing_sale(
                db=db_session, listing_id=listing_id, confirming_seller_telegram_id=user.id
            )

            if finalized_listing and finalized_listing.buyer:  # Ensure buyer is loaded
                buyer_telegram_id = finalized_listing.buyer.telegram_id
            elif not finalized_listing:
                listing_check = await crud.get_listing_by_id(db_session, listing_id)
                if not listing_check:
                    error_message = "آگهی یافت نشد."
                elif not listing_check.seller or listing_check.seller.telegram_id != user.id:
                    error_message = "شما فروشنده این آگهی نیستید."
                elif listing_check.status == models.ListingStatus.SOLD:
                    error_message = "فروش قبلا نهایی شده."
                elif listing_check.status != models.ListingStatus.AWAITING_CONFIRMATION:
                    error_message = f"وضعیت آگهی ({listing_check.status.value}) قابل تایید نیست."
                else:
                    error_message = "خطا در بروزرسانی وضعیت."


    except Exception as e:
        logger.error(
            f"Caught exception during finalize process for listing {listing_id}. Type: {type(e)}, Error: {str(e)}",
            exc_info=True
        )
        error_message = "خطای جدی در سرور رخ داد."
        finalized_listing = None
    if finalized_listing and buyer_telegram_id and reservation_code:
        text_part_seller_1 = f"✅ دریافت وجه برای آگهی "
        text_part_seller_2_id = f"`{listing_id}`"  # listing_id is int, safe in backticks
        text_part_seller_3 = f" تایید شد.\nکد و بارکد برای خریدار ارسال می‌شود."

        escaped_success_edit_text = (
            f"{utility.escape_markdown_v2(text_part_seller_1)}"
            f"{text_part_seller_2_id}"  # listing_id is an int, safe in backticks
            f"{utility.escape_markdown_v2(text_part_seller_3)}"  # This will escape the periods
        )

        logger.info(
            f"SELLER MSG EDIT (SUCCESS): Attempting to edit seller's message to: {escaped_success_edit_text}")  # YOUR ADDED LOG
        try:
            await query.edit_message_text(
                text=escaped_success_edit_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info("SELLER MSG EDIT (SUCCESS): Successfully edited seller's message.")
        except Exception as e_edit_seller_success:
            logger.error(f"SELLER MSG EDIT (SUCCESS): FAILED to edit seller's message: {e_edit_seller_success}",
                         exc_info=True)

        barcode_image_bytes = utility.generate_qr_code_image(data=reservation_code)

        # Construct the caption, escaping static parts
        # Part 1
        text_part1 = f"✅ پرداخت شما برای آگهی "
        # Part 2 (dynamic listing_id, already safe in backticks)
        text_part2_listing_id = f"`{listing_id}`"
        # Part 3
        text_part3 = f" تایید شد!\n\nکد رزرو شما: "
        # Part 4 (dynamic reservation_code, ensure it's escaped if it can contain special chars)
        # The backticks around it are Markdown syntax.
        text_part4_code = f"`{utility.escape_markdown_v2(str(reservation_code))}`"
        # Part 5
        text_part5 = f"\n\nمی‌توانید از بارکد بالا یا کد برای دریافت غذا استفاده کنید."

        buyer_message_caption = (
            f"{utility.escape_markdown_v2(text_part1)}"
            f"{text_part2_listing_id}"  # listing_id is int, safe in backticks
            f"{utility.escape_markdown_v2(text_part3)}"
            f"{text_part4_code}"  # Code is already escaped and in backticks
            f"{utility.escape_markdown_v2(text_part5)}"
        )

        try:
            if barcode_image_bytes:
                await context.bot.send_photo(
                    chat_id=buyer_telegram_id,
                    photo=io.BytesIO(barcode_image_bytes),
                    caption=buyer_message_caption,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=get_main_menu_keyboard()
                )
                logger.info(f"Sent QR code and text for listing {listing_id} to buyer {buyer_telegram_id}")
            else:
                # Fallback
                logger.error(f"Barcode generation failed for listing {listing_id}. Sending text code only.")
                # If sending text only, and the text is the same caption, it also needs to be escaped for V2
                await context.bot.send_message(
                    chat_id=buyer_telegram_id,
                    text=buyer_message_caption,  # Use the same fully escaped caption
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=get_main_menu_keyboard()
                )
        except Exception as notify_err:
            logger.error(
                f"Failed to send code/photo to buyer {buyer_telegram_id} for listing {listing_id}: {notify_err}",
                exc_info=True)
            # Inform seller about the failure
            await context.bot.send_message(user.id,
                                           f"پرداخت تایید شد، اما در ارسال کد به خریدار آگهی {listing_id} مشکلی پیش آمد. لطفا کد `{reservation_code}` را دستی برای او ارسال کنید.")

    else:  # finalization failed or data missing
        error_edit_text = utility.escape_markdown_v2(error_message)
        logger.info(
            f"SELLER MSG EDIT (FAILURE): Attempting to edit seller's message to: {error_edit_text}")  # YOUR ADDED LOG
        try:
            await query.edit_message_text(
                error_edit_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info("SELLER MSG EDIT (FAILURE): Successfully edited seller's message with error.")
        except Exception as e_edit_seller_failure:
            logger.error(
                f"SELLER MSG EDIT (FAILURE): FAILED to edit seller's message with error: {e_edit_seller_failure}",
                exc_info=True)
