import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from utility import format_gregorian_date_to_shamsi
from .common import CALLBACK_SETTINGS_BACK_MAIN # For back button
from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models

logger = logging.getLogger(__name__)

async def handle_my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'My Listings' button press."""
    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    logger.info(f"'My Listings' button pressed by user {user.id}")

    # --- Prerequisite Checks (Verification, potentially CC for selling context) ---
    try:
        async with get_db_session() as db_session:
            db_user = await crud.get_user_by_telegram_id(db_session, user.id)
            if not db_user or not db_user.is_verified:
                await message.reply_text("برای مشاهده یا مدیریت آگهی‌ها، ابتدا باید اعتبارسنجی شوید (/start).")
                return
            # Optional: Check if credit card is needed even just to view? Usually not.
            # if not db_user.credit_card_number:
            #    await message.reply_text("برای مدیریت آگهی‌ها، شماره کارت بانکی باید ثبت شده باشد (از طریق تنظیمات).")
            #    return

            # --- Fetch Listings ---
            user_listings = await crud.get_user_active_listings(db_session, user.id)

    except Exception as e:
        logger.error(f"DB error fetching user/listings for {user.id} in handle_my_listings: {e}", exc_info=True)
        await message.reply_text("خطا در دریافت لیست آگهی‌ها. لطفا دوباره تلاش کنید.")
        return

    # --- Display Listings ---
    if not user_listings:
        await message.reply_text("شما هیچ آگهی فعالی (موجود یا در انتظار تایید) ندارید.")
        return

    response_parts = ["📄 **لیست آگهی‌های فعال شما:**\n\n"]
    inline_keyboard = []

    status_map = {
        models.ListingStatus.AVAILABLE: "✅ موجود",
        models.ListingStatus.AWAITING_CONFIRMATION: "⏳ در انتظار تایید شما", # From seller's perspective
    }

    for listing in user_listings:
        meal_desc = "نامشخص"
        meal_date_str = "نامشخص"
        if listing.meal:
            meal_desc = listing.meal.description or meal_desc
            if listing.meal.date:
                try:
                    # meal_date_str = listing.meal.date.strftime('%Y-%m-%d')
                    meal_date_str = format_gregorian_date_to_shamsi(listing.meal.date)
                except AttributeError:
                    meal_date_str = str(listing.meal.date)

        price_str = f"{listing.price:,.0f}" if listing.price is not None else "نامشخص"
        status_text = status_map.get(listing.status, listing.status.value) # Get friendly status text

        part = (
            f"🔢 **کد آگهی:** `{listing.id}`\n"
            f"🍽️ **غذا:** {meal_desc}\n"
            f"📅 **تاریخ:** {meal_date_str}\n"
            f"💰 **قیمت:** {price_str} تومان\n"
            f"🚦 **وضعیت:** {status_text}\n"
        )

        buttons_row = []
        # Add cancel button ONLY for AVAILABLE listings
        if listing.status == models.ListingStatus.AVAILABLE:
            buttons_row.append(
                InlineKeyboardButton(
                    f"❌ لغو آگهی {listing.id}",
                    callback_data=f'cancel_listing_{listing.id}'
                )
            )
        # Optional: Add button to view pending buyer info?
        # if listing.status == models.ListingStatus.AWAITING_CONFIRMATION:
            # buttons_row.append(InlineKeyboardButton("ℹ️ اطلاعات خریدار", callback_data=f'view_pending_{listing.id}'))

        response_parts.append(part)
        if buttons_row: # Only add button row if buttons exist
             response_parts.append("----\n") # Add separator only if buttons follow
             inline_keyboard.append(buttons_row)
        else:
            # Add a separator even if no buttons for this item, for consistency
            response_parts.append("--------------------\n")

    # Add a Back button at the end
    inline_keyboard.append([
        InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='settings_back_main') # Re-use existing back handler
    ])

    full_message = "".join(response_parts)
    # Remove the last separator if it exists right before the end
    if full_message.endswith("--------------------\n"):
         full_message = full_message[:-len("--------------------\n")]
    elif full_message.endswith("----\n"):
         full_message = full_message[:-len("----\n")]


    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    # Handle potential message length issues (less likely than full buy list)
    if len(full_message) > 4096:
        logger.warning(f"My Listings message for user {user.id} possibly truncated.")
        # Truncate smartly if needed, or consider pagination
        await message.reply_text(full_message[:4090] + "\n...", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)



# Callback Handler for Cancel Button
async def handle_cancel_available_listing_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Cancel Listing' button press from the My Listings view."""
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not query.data: return

    await query.answer("در حال پردازش لغو...")

    try:
        listing_id = int(query.data.split('_')[-1]) # Extract from 'cancel_listing_ID'
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data for cancel listing button: {query.data}")
        await query.edit_message_text("خطا: دکمه نامعتبر.")
        return

    logger.info(f"User {user.id} trying to cancel available listing {listing_id}")

    async with get_db_session() as db_session:
        success = await crud.cancel_available_listing_by_seller(
            db=db_session,
            listing_id=listing_id,
            seller_telegram_id=user.id
        )

    if success:
        await query.edit_message_text(f"✅ آگهی با شماره `{listing_id}` با موفقیت لغو شد.")
        # Optionally: Could try to refresh the original "My Listings" message here,
        # but editing might be complex. Simply confirming is usually enough.
        # Consider removing the buttons from the edited message if not refreshing view.
        # await query.edit_message_reply_markup(reply_markup=None) # Example
    else:
        await query.answer(
            "❌ امکان لغو این آگهی وجود ندارد.\n(ممکن است فروخته شده یا قبلاً لغو شده باشد)",
            show_alert=True # Show as a pop-up alert
        )
        # You might want to edit the original message slightly or just leave it
        # await query.edit_message_text(query.message.text + "\n\n(خطا در لغو آگهی بالا)", parse_mode=ParseMode.MARKDOWN)

