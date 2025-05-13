import logging
from decimal import Decimal, InvalidOperation

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from utility import escape_markdown_v2, format_gregorian_date_to_shamsi
from .common import (
    SELL_ASK_CODE, SELL_ASK_MEAL, SELL_ASK_PRICE, SELL_CONFIRM,
    CALLBACK_CANCEL_SELL_FLOW, get_main_menu_keyboard,
    CALLBACK_LISTING_CANCEL_CONFIRM_YES, CALLBACK_LISTING_CANCEL_CONFIRM_NO
)

from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models

logger = logging.getLogger(__name__)


PERSIAN_DAYS_MAP = {
    5: "شنبه",   # Saturday (datetime.weekday() == 5)
    6: "یکشنبه", # Sunday (datetime.weekday() == 6)
    0: "دوشنبه",  # Monday (datetime.weekday() == 0)
    1: "سه‌شنبه", # Tuesday (datetime.weekday() == 1)
    2: "چهارشنبه",# Wednesday (datetime.weekday() == 2)
    3: "پنجشنبه", # Thursday (datetime.weekday() == 3)
    4: "جمعه"     # Friday (datetime.weekday() == 4)
}

# Sell Food Conversation Handlers
async def handle_sell_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    user = update.effective_user
    message = update.message
    if not user or not message: return ConversationHandler.END

    logger.info(f"'Sell Food' button pressed by user {user.id}. Starting conversation.")

    next_state = ConversationHandler.END # Default to END
    reply_text = "خطا در پردازش درخواست شما." # Default error message
    reply_markup = get_main_menu_keyboard() # Default markup (main menu)

    try:
        async with get_db_session() as db_session: # Acquire session
            # Ensure user exists and info is updated
            db_user = await crud.get_or_create_user_and_update_info(db_session, user)

            if not db_user:  # Should be handled by crud function raising error
                raise Exception("User could not be fetched or created.")

            # Now proceed with selling logic using db_user
            if not db_user.is_verified:
                logger.warning(f"Unverified user {db_user.telegram_id} attempted action: sell food")
                reply_text = "برای فروش غذا، ابتدا اعتبارسنجی کنید (/start)."
                # next_state remains END
            # Check Credit Card ONLY if verified
            elif not db_user.credit_card_number:
                logger.info(f"User {db_user.telegram_id} attempting to sell, but CC number is missing.")
                reply_text = (
                    "⚠️ برای فروش غذا و دریافت وجه، باید شماره کارت بانکی خود را ثبت کنید.\n"
                    "لطفا این کار را از طریق منوی '⚙️ تنظیمات' انجام دهید."
                )
                # next_state remains END
            else:
                logger.info(f"User {db_user.telegram_id} is verified and has CC number. Proceeding with sell flow.")
                context.user_data['seller_db_id'] = db_user.id # Store DB ID early

                cancel_button = InlineKeyboardButton("❌ لغو", callback_data=CALLBACK_CANCEL_SELL_FLOW)
                reply_markup = InlineKeyboardMarkup([[cancel_button]]) # Specific markup for next step
                reply_text = "لطفا کد رزرو دانشگاه (کد سلف) که می‌خواهید بفروشید را وارد کنید:"
                next_state = SELL_ASK_CODE # Set next state only on success

    except Exception as e:
        logger.error(f"DB error checking user prerequisites for {user.id} in handle_sell_food: {e}", exc_info=True)
        reply_text = "خطا در بررسی وضعیت اعتبارسنجی. لطفا دوباره تلاش کنید."
        # next_state remains END
        # Ensure context is cleared on DB error during prerequisite check
        context.user_data.pop('seller_db_id', None)

    # Send the reply *after* the session is closed
    try:
        await message.reply_text(reply_text, reply_markup=reply_markup)
    except Exception as send_err:
        logger.error(f"Failed to send reply in handle_sell_food: {send_err}")

    return next_state


async def receive_reservation_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives reservation code, checks if already listed, asks user to select Meal."""
    user = update.effective_user
    message = update.message
    if not message or not message.text:
        await message.reply_text("لطفا کد رزرو را وارد کنید.")
        return SELL_ASK_CODE

    reservation_code = message.text.strip()
    # Basic validation (e.g., non-empty)
    if not reservation_code:
        await message.reply_text("کد رزرو نمی‌تواند خالی باشد.")
        return SELL_ASK_CODE

    logger.info(f"User {user.id} entered reservation code: {reservation_code}")

    next_state = SELL_ASK_CODE
    reply_text = "خطا در پردازش کد رزرو."
    reply_markup = None
    current_parse_mode = ParseMode.MARKDOWN_V2

    # Check if code already listed
    try:
        async with get_db_session() as db_session:
            code_exists = await crud.check_listing_exists_by_code(db_session, reservation_code)
            if code_exists:
                logger.warning(f"User {user.id} tried to list code '{reservation_code}' which already exists.")
                reply_text = escape_markdown_v2(
                    "این کد رزرو قبلا برای فروش ثبت شده است یا در حال حاضر در وضعیت فروش قرار دارد."
                )
                next_state = ConversationHandler.END
            else:
                # Fetch available Meals for selection
                available_meals = await crud.get_meals_for_selling(db_session)  # TODO: Maybe filter by date?
                if not available_meals:
                    reply_text = escape_markdown_v2(
                        "متاسفانه در حال حاضر هیچ نوع غذایی در سیستم تعریف نشده است. لطفا با ادمین تماس بگیرید."
                    )
                    next_state = ConversationHandler.END
                else:
                    context.user_data['university_reservation_code'] = reservation_code

                    # Main instruction text, escaped
                    instruction_text = escape_markdown_v2(
                        "لطفا نوع غذای مربوط به این کد را از لیست زیر انتخاب کنید:")
                    message_parts = [instruction_text, "\n"]  # Add a newline after instruction
                    meal_details_for_text_md = []

                    for index, meal in enumerate(available_meals):
                        meal_date_obj = meal.date  # This should be a datetime.date object
                        shamsi_date_str = format_gregorian_date_to_shamsi(meal_date_obj)
                        persian_day_name = "روز نامشخص"  # Default
                        if meal_date_obj:
                            day_of_week_int = meal_date_obj.weekday()  # Monday is 0 and Sunday is 6
                            persian_day_name = PERSIAN_DAYS_MAP.get(day_of_week_int, "روز نامشخص")

                        meal_type_display = meal.meal_type

                        # Escape dynamic content from the meal object
                        escaped_description = escape_markdown_v2(meal.description or 'غذای نامشخص')
                        escaped_meal_type = escape_markdown_v2(meal_type_display)
                        escaped_shamsi_date = escape_markdown_v2(shamsi_date_str)
                        escaped_persian_day_name = escape_markdown_v2(persian_day_name)

                        # Format: "1\. Escaped Description \(Escaped Type \- Escaped Date\)"
                        meal_info = (
                            f"{index + 1}\\. {escaped_description} "
                            f"\\({escaped_meal_type} \\- {escaped_persian_day_name}، {escaped_shamsi_date}\\)"
                        )
                        meal_details_for_text_md.append(meal_info)

                    message_parts.append("\n".join(meal_details_for_text_md))  # Each meal on a new line
                    reply_text = "\n".join(message_parts)

                    # Build the inline keyboard
                    meal_buttons_rows = []
                    current_row = []
                    max_buttons_per_row = 3
                    for index, meal in enumerate(available_meals):
                        # Shorter, referential button text in Persian
                        button_text = f"انتخاب گزینه {index + 1}"  # "Select option X"
                        callback_data = f"sell_select_meal_{meal.id}"  # Callback still uses meal_id
                        current_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
                        if len(current_row) == max_buttons_per_row:
                            meal_buttons_rows.append(current_row)
                            current_row = []

                    if current_row:  # Add any remaining buttons in the last row
                        meal_buttons_rows.append(current_row)
                    meal_buttons_rows.append(
                        [InlineKeyboardButton("❌ لغو مراحل فروش", callback_data=CALLBACK_CANCEL_SELL_FLOW)])
                    reply_markup = InlineKeyboardMarkup(meal_buttons_rows)

                    next_state = SELL_ASK_MEAL

    except Exception as e:
        logger.error(f"Error processing reservation code '{reservation_code}' for user {user.id}: {e}", exc_info=True)
        reply_text = escape_markdown_v2("خطا در بررسی کد رزرو. لطفا دوباره تلاش کنید یا /cancel را بزنید.")
        next_state = SELL_ASK_CODE
        context.user_data.pop('university_reservation_code', None)

    try:
        await message.reply_text(
            reply_text,
            reply_markup=reply_markup,
            parse_mode=current_parse_mode
        )
    except Exception as send_err:
        logger.error(f"Failed to send reply in receive_reservation_code: {send_err}")

    if next_state == ConversationHandler.END:
        context.user_data.clear()

    return next_state



async def receive_meal_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user = update.effective_user
    await query.answer() # Answer callback

    callback_data = query.data
    next_state = ConversationHandler.END # Default to END on error
    edit_text = "خطای داخلی: دکمه نامعتبر." # Default error message
    edit_markup = None

    try:
        meal_id = int(callback_data.split('_')[-1]) # Extract ID from sell_select_meal_ID
        logger.info(f"User {user.id} selected meal_id {meal_id} for listing.")

        async with get_db_session() as db_session: # Acquire session
             meal = await db_session.get(models.Meal, meal_id) # Use session.get for PK lookup
             if not meal:
                 logger.error(f"Meal ID {meal_id} selected by user {user.id} not found in DB.")
                 edit_text = "خطا: غذای انتخاب شده یافت نشد."
                 # next_state remains ConversationHandler.END
             else:
                 # Successfully fetched meal, prepare the next step message
                 context.user_data['meal_id'] = meal.id
                 context.user_data['price_limit'] = meal.price_limit # Store limit (can be None)
                 context.user_data['meal_description'] = meal.description or "غذای نامشخص"

                 price_prompt = "لطفا قیمتی که می‌خواهید برای فروش این غذا تعیین کنید را به تومان وارد کنید:"
                 if meal.price_limit is not None:
                      # Format limit for display
                      try:
                           limit_decimal = Decimal(meal.price_limit)
                           price_prompt += f"\n(توجه: حداکثر قیمت مجاز برای این غذا {limit_decimal:,.0f} تومان است)"
                      except (InvalidOperation, ValueError, TypeError): # Handle potential conversion issues
                           logger.warning(f"Could not format price_limit '{meal.price_limit}' for meal {meal_id}.")
                           # Show raw value if formatting fails
                           price_prompt += f"\n(توجه: حداکثر قیمت مجاز: {meal.price_limit})"

                 cancel_button = InlineKeyboardButton("❌ لغو", callback_data=CALLBACK_CANCEL_SELL_FLOW)
                 edit_markup = InlineKeyboardMarkup([[cancel_button]])
                 edit_text = price_prompt
                 next_state = SELL_ASK_PRICE # Set next state only on success

    except (ValueError, IndexError):
        logger.error(f"Invalid callback data format for meal selection: {callback_data}")
        # edit_text already set to default error
        # next_state remains ConversationHandler.END
    except Exception as e:
        logger.error(f"Error processing meal selection for ID {meal_id}: {e}", exc_info=True)
        edit_text = "خطا در دریافت اطلاعات غذا. لطفا با /start دوباره شروع کنید."
        # next_state remains ConversationHandler.END

    # Perform the message edit *after* the session is closed
    try:
        await query.edit_message_text(edit_text, reply_markup=edit_markup)
    except Exception as edit_err:
         logger.error(f"Failed to edit message after meal selection processing: {edit_err}")
         # TODO: Might want to send a new message as fallback if edit fails

    # Clear context
    if next_state == ConversationHandler.END:
        context.user_data.clear()

    return next_state

async def receive_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the price, validates it against limit, asks for confirmation."""
    user = update.effective_user
    message = update.message
    if not message or not message.text or not context.user_data:
        # Should not happen if flow is correct, but handle defensively
        await message.reply_text("خطای داخلی. لطفا با /start شروع کنید.")
        context.user_data.clear()
        return ConversationHandler.END

    price_text = message.text.strip()
    logger.info(f"User {user.id} entered price: {price_text}")

    # --- Validate Price ---
    try:
        # Use Decimal for precise currency handling
        price = Decimal(price_text)
        if price <= 0:
            raise ValueError("Price must be positive")
    except (InvalidOperation, ValueError):
        logger.warning(f"Invalid price format '{price_text}' from user {user.id}")
        await message.reply_text("قیمت وارد شده نامعتبر است. لطفا فقط عدد مثبت (به تومان) وارد کنید:")
        return SELL_ASK_PRICE # Ask again

    # Check against price limit stored in context
    price_limit_decimal: Decimal | None = None
    price_limit_raw = context.user_data.get('price_limit')
    if price_limit_raw is not None:
        try:
             price_limit_decimal = Decimal(price_limit_raw)
        except InvalidOperation:
             logger.error(f"Invalid price_limit '{price_limit_raw}' retrieved from context for user {user.id}")
             price_limit_decimal = None # Ignore invalid limit

    if price_limit_decimal is not None and price > price_limit_decimal:
        await message.reply_text(f"قیمت ({price:,.0f}) بیشتر از حد مجاز ({price_limit_decimal:,.0f}) است.");
        return SELL_ASK_PRICE  # Ask again

    # Store price and ask for confirmation
    context.user_data['price'] = price # Store as Decimal
    meal_desc = context.user_data.get('meal_description', 'غذا')
    code = context.user_data.get('university_reservation_code', 'کد نامشخص')

    confirmation_text = (
        f"تایید اطلاعات:\n\nغذا: {meal_desc}\nکد رزرو: `{code}`\nقیمت فروش: {price:,.0f} تومان\n\nآیا ثبت شود؟")
    confirm_buttons = [[InlineKeyboardButton("✅ بله", callback_data='confirm_listing_yes'),
                        InlineKeyboardButton("❌ لغو", callback_data='confirm_listing_no')]]
    reply_markup = InlineKeyboardMarkup(confirm_buttons)

    await message.reply_text(confirmation_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    return SELL_CONFIRM # Move to confirmation state


async def confirm_listing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles final confirmation, calls CRUD create_listing."""
    query = update.callback_query; user = update.effective_user; await query.answer()
    required_keys = ['seller_db_id', 'university_reservation_code', 'meal_id', 'price']
    if not context.user_data or not all(key in context.user_data for key in required_keys):
        logger.error(f"Missing data confirming listing for user {user.id}: {context.user_data.keys()}")
        await query.edit_message_text("خطای داخلی. با /start شروع کنید."); context.user_data.clear(); return ConversationHandler.END

    # Retrieve data
    seller_db_id = context.user_data['seller_db_id']
    code = context.user_data['university_reservation_code']
    meal_id = context.user_data['meal_id']
    price = context.user_data['price'] # This is a Decimal

    logger.info(f"User {user.id} confirmed listing: code={code}, meal={meal_id}, price={price}")

    edit_text = "خطا در ثبت آگهی." # Default error message
    success = False

    # Create Listing in DB
    try:
        async with get_db_session() as db_session: # Acquire session
            new_listing = await crud.create_listing(
                db=db_session,
                seller_db_id=seller_db_id,
                university_reservation_code=code,
                meal_id=meal_id,
                price=price
            )
        if new_listing:
            edit_text = f"✅ آگهی شما با شماره `{new_listing.id}` ثبت شد\\."
            success = True
        else:
            edit_text = escape_markdown_v2("خطا: امکان ثبت آگهی نیست (ممکن است کد تکراری باشد).")

    except Exception as e:
        logger.error(f"Error creating listing: {e}", exc_info=True)
        # edit_text remains default error message

    # Edit the original confirmation message
    try:
        await query.edit_message_text(edit_text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as edit_err:
        logger.error(f"Failed to edit message after listing confirmation: {edit_err}", exc_info=True)

    # If successful, also send the main menu keyboard
    if success and query.message:
        try:
            await query.message.reply_text("منوی اصلی:", reply_markup=get_main_menu_keyboard())
        except Exception as send_err:
            logger.error(f"Failed to send main menu after successful listing: {send_err}")


    context.user_data.clear()
    return ConversationHandler.END

async def handle_inline_cancel_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the inline 'Cancel' button press during the sell conversation."""
    query = update.callback_query
    user = update.effective_user
    await query.answer() # Answer callback first

    logger.info(f"User {user.id} canceled the sell conversation via inline button.")
    context.user_data.clear() # Clear any stored data

    # Edit the original message to confirm cancellation
    await query.edit_message_text(
        text="فرآیند فروش غذا لغو شد.",
        reply_markup=None # Remove the inline keyboard
    )
    # Send a new message with the main menu
    # Check if query.message exists before replying
    if query.message:
        await query.message.reply_text(
            "منوی اصلی:",
            reply_markup=get_main_menu_keyboard() # Show main menu again
        )
    else: # Fallback if message context is lost somehow
        await context.bot.send_message(
            chat_id=user.id,
            text="فرآیند فروش لغو شد. منوی اصلی:",
             reply_markup=get_main_menu_keyboard()
        )

    return ConversationHandler.END

async def cancel_listing_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the cancel button during listing confirmation."""
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    logger.info(f"User {user.id} canceled listing creation.")

    await query.edit_message_text("ثبت آگهی لغو شد.")

    # Send message with main menu keyboard AFTER editing the inline message
    await query.message.reply_text("منوی اصلی:", reply_markup=get_main_menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_sell_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Generic cancel handler for the sell conversation."""
    user = update.effective_user
    message = update.message

    logger.info(f"User {user.id} canceled the sell conversation.")

    context.user_data.clear()
    await message.reply_text(
        "فرآیند فروش غذا لغو شد.",
        reply_markup=get_main_menu_keyboard() # Show main menu again
        )
    return ConversationHandler.END