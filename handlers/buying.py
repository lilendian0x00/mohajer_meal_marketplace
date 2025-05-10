import io
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from .common import (
    CALLBACK_BUY_REFRESH, CALLBACK_BUYER_CANCEL_PENDING,
    CALLBACK_SELLER_REJECT_PENDING, get_main_menu_keyboard
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

    title = "🛒 **لیست غذاهای موجود برای خرید:**\n\n"
    refresh_button = InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data=CALLBACK_BUY_REFRESH)

    if not available_listings:
        message_text = title + "در حال حاضر هیچ غذایی برای فروش ثبت نشده است\\."
        # Still include Refresh button even if no listings
        reply_markup = InlineKeyboardMarkup([[refresh_button]])
        return message_text, reply_markup

    response_parts = [title]
    inline_buttons = [] # List to hold button rows

    for listing in available_listings:
        meal_desc_raw = "غذای نامشخص"
        meal_date_str_raw = "نامشخص"
        meal_type_raw = "نامشخص"

        if listing.meal:
            meal = listing.meal
            meal_desc_raw = meal.description or meal_desc_raw
            meal_type_raw = meal.meal_type or meal_type_raw
            if meal.date:
                try:
                    #meal_date_str_raw = meal.date.strftime('%Y-%m-%d')
                    meal_date_str_raw = utility.format_gregorian_date_to_shamsi(meal.date)
                except AttributeError:
                    meal_date_str_raw = str(meal.date)  # Fallback if strftime fails or date is already string

        # Escape user-generated content
        meal_desc = escape_markdown(meal_desc_raw, version=2)
        meal_type = escape_markdown(meal_type_raw, version=2)
        meal_date_str = escape_markdown(meal_date_str_raw, version=2)

        # Escape seller name for Markdown V2 compatibility if needed, or use regular Markdown
        seller_name_raw_display = "ناشناس"
        if listing.seller and listing.seller.first_name:
            seller_name_raw_display = listing.seller.first_name

        # Prepare the display part of the link, escaping it
        escaped_seller_display_name = escape_markdown(seller_name_raw_display, version=2)

        seller_name = "ناشناس"

        if listing.seller:
            seller_telegram_id = listing.seller.telegram_id

            if listing.seller.username:
                username_display_text = f"@{listing.seller.username}"
                escaped_link_text = escape_markdown(username_display_text, version=2)
                # The username in the URL itself does not need Markdown escaping
                seller_name = f"[{escaped_link_text}](https://t.me/{listing.seller.username})"
            else:
                # Fallback for first_name if it's None or empty
                first_name_raw = listing.seller.first_name if listing.seller.first_name else "ناشناس"

                # Construct the full display text for the link
                link_text_raw = f"{first_name_raw} (ID: {seller_telegram_id})"
                escaped_link_text = escape_markdown(link_text_raw, version=2)
                seller_name = f"[{escaped_link_text}](tg://user?id={seller_telegram_id})"


        price_str_raw = f"{listing.price:,.0f}" if listing.price is not None else "نامشخص"
        price_str = escape_markdown(price_str_raw, version=2)

        part = (
            f"🍽️ *{meal_desc}* \\({meal_type} \\- {meal_date_str}\\)\n"
            f"👤 فروشنده: {seller_name}\n"
            f"💰 قیمت: {price_str} تومان\n"
            f"🆔 شماره آگهی: `{listing.id}`\n"  # listing.id is an int, doesn't need escaping inside backticks
        )
        response_parts.append(part)

        # Create the buy button for this listing
        inline_buttons.append([
            InlineKeyboardButton(
                f"خرید آگهی {listing.id} ({price_str} تومان)",
                callback_data=f'buy_listing_{listing.id}'
            )
        ])
        # Add a separator after each listing's details
        response_parts.append(escape_markdown("--------------------", version=2) + "\n")

    # Add the refresh button as the last row
    inline_buttons.append([refresh_button])

    full_message = "".join(response_parts)
    reply_markup = InlineKeyboardMarkup(inline_buttons)

    # Handle potential length issues (optional refinement)
    if len(full_message) > 4096:
        logger.warning("Generated buy food list message exceeds 4096 chars, might be truncated by Telegram.")
        # Simple truncation:
        full_message = full_message[:4090] + "\n... (لیست خلاصه شد)"

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
            db_user = await crud.get_user_by_telegram_id(db_session, user.id)
            if not db_user:
                 logger.error(f"User {user.id} not found in DB during buy food.")
                 await message.reply_text("خطا: اطلاعات کاربری شما یافت نشد. لطفا /start بزنید.")
                 return
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

    await query.answer("🔄 در حال بروزرسانی...") # Acknowledge button press

    logger.info(f"User {user.id} pressed 'Refresh List' for buy food.")

    try:
        async with get_db_session() as db_session:
            message_text, reply_markup = await _generate_buy_food_response(db_session)

            await query.edit_message_text(
                text=message_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            logger.debug(f"Successfully refreshed buy list for user {user.id}")

    except Forbidden:
        logger.warning(f"Bot blocked by user {user.id}, cannot refresh buy list.")
        await query.answer("خطਾ: امکان ویرایش پیام نیست. ربات مسدود شده؟", show_alert=True)
    except BadRequest as e:
        # Handle specific case where message hasn't changed
        if "Message is not modified" in str(e):
            logger.info(f"Buy list refresh for user {user.id} resulted in no changes.")
            await query.answer("لیست بروز است.") # Inform user message hasn't changed
        else:
            logger.error(f"BadRequest refreshing buy list for user {user.id}: {e}", exc_info=True)
            await query.answer("خطا در بروزرسانی لیست.", show_alert=True)
    except Exception as e:
        logger.error(f"Error refreshing buy list for user {user.id}: {e}", exc_info=True)
        # Try to edit the message to show error, otherwise just answer callback
        try:
            await query.edit_message_text("خطا در بروزرسانی لیست. لطفا دوباره تلاش کنید.")
        except Exception:
            await query.answer("خطا در بروزرسانی لیست.", show_alert=True)


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
                # CRUD function returned None, meaning pre-check failed (logged in CRUD)
                # Re-fetch listing to determine specific reason for user message
                listing_check = await crud.get_listing_by_id(db_session, listing_id)  # Use same session

                # Set specific user-facing error message based on re-check
                if listing_check and listing_check.seller_id == user.id:
                    error_message = "شما نمی‌توانید آگهی خودتان را بخرید."  # Specific message
                elif listing_check and listing_check.status != models.ListingStatus.AVAILABLE:
                    error_message = f"متاسفانه این آگهی دیگر برای خرید موجود نیست (وضعیت: {listing_check.status.value})."  # Specific message
                elif not listing_check:
                    error_message = "متاسفانه این آگهی یافت نشد."  # Specific message
                else:
                    # Default if reason isn't clear from re-check
                    error_message = "خطا در بروزرسانی وضعیت آگهی."

            elif updated_listing:
                if updated_listing.seller:
                    seller_card_number = updated_listing.seller.credit_card_number
                    seller_telegram_id = updated_listing.seller.telegram_id
                else:
                    logger.error(f"Listing {listing_id} seller info could not be loaded after update.")
                    error_message = "خطا: اطلاعات فروشنده یافت نشد."
                    updated_listing = None  # Mark as failed for subsequent logic

    except Exception as e:
        logger.error(f"Error setting listing {listing_id} to awaiting confirmation: {e}", exc_info=True)
        error_message = "خطای جدی در پردازش درخواست رخ داد."
        updated_listing = None

    # Notify Buyer and Seller
    if updated_listing and seller_card_number and seller_telegram_id:
        price_str = f"{updated_listing.price:,.0f}" if updated_listing.price is not None else "مبلغ"
        # Escape meal_desc for V2 *before* using it in the f-string for buyer
        meal_desc_escaped = utility.escape_markdown_v2(
            updated_listing.meal.description if updated_listing.meal else "غذا")

        buyer_message = (
            f"درخواست خرید شما برای آگهی `{listing_id}` ({meal_desc_escaped}) ثبت شد\\.\n"  # Escape dot for V2
            f"⏳ لطفا مبلغ **{price_str} تومان** را به شماره کارت زیر واریز نمایید:\n\n"
            f"💳 `{utility.escape_markdown_v2(seller_card_number)}`\n\n"  # Escape potential special chars in card num
            f"پس از واریز، فروشنده باید دریافت وجه را تایید کند\\.\n"  # Escape dot
            f"🚨 *هشدار:* ربات مسئولیتی در قبال تراکنش ندارد\\.\n\n"  # Escape dot
            f"در صورت انصراف از خرید، دکمه زیر را بزنید:"
        )
        buyer_cancel_button = InlineKeyboardButton(
            "❌ لغو درخواست خرید",
            callback_data=f'{CALLBACK_BUYER_CANCEL_PENDING}_{listing_id}'
        )
        buyer_markup = InlineKeyboardMarkup([[buyer_cancel_button]])

        # Edit buyer's message first
        await query.edit_message_text(buyer_message, parse_mode=ParseMode.MARKDOWN, reply_markup=buyer_markup)

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
                f"آگهی: `{listing_id}` \\({meal_desc_escaped}\\)\n"
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
        # ... (code to edit seller's message) ...

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

    else:
        await query.edit_message_text(error_message, parse_mode=ParseMode.MARKDOWN)  # Ensure parse_mode if error_message contains markdown
