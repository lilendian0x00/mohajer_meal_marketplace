# handlers.py
import logging
import math
import re # For basic validation
from decimal import Decimal, InvalidOperation

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Contact, InlineKeyboardButton, \
    InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters, CommandHandler # Import conversation components
from config import HISTORY_PAGE_SIZE
import utility
from self_market.db.session import get_db_session
from self_market.db import crud
from self_market import models

logger = logging.getLogger(__name__)

# Define Conversation States
# Verification States
(ASK_EDU_NUM, ASK_ID_NUM, ASK_PHONE) = range(3)
# Selling States (start from a different range)
(SELL_ASK_CODE, SELL_ASK_MEAL, SELL_ASK_PRICE, SELL_CONFIRM) = range(10, 14) # Use different range to avoid clashes
# States for Settings
(SETTINGS_ASK_CARD,) = range(20, 21) # Example range


# Define Callback Data Constant
CALLBACK_CANCEL_SELL_FLOW = "cancel_sell_flow"

# Helper Function for Main Menu Keyboard
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Returns the main ReplyKeyboardMarkup."""
    keyboard = [
        [KeyboardButton(BTN_BUY_FOOD), KeyboardButton(BTN_SELL_FOOD)],
        [KeyboardButton(BTN_MY_LISTINGS), KeyboardButton(BTN_SETTINGS)],
        [KeyboardButton(BTN_HISTORY)]   # Added new button here
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="گزینه مورد نظر را انتخاب کنید..."
    )

# Command Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Handles the /start command.
    Checks if user exists/is verified. Shows main menu or starts verification conversation.
    Returns the next state for the ConversationHandler.
    """
    telegram_user = update.effective_user
    message = update.message # Use message directly if available
    if not telegram_user or not message:
        logger.warning("Could not get user or message from update in /start command.")
        return ConversationHandler.END # End conversation if basic info missing

    logger.info(f"/start command received from user_id: {telegram_user.id}")

    db_user: models.User | None = None
    # --- Get or Create User ---
    try:
        async with get_db_session() as db_session:
            # Use the existing function to ensure user record exists
            db_user = await crud.get_or_create_user(db_session, telegram_user)
            logger.info(f"User {db_user.username} (TG_ID: {db_user.telegram_id}) processed. Verified: {db_user.is_verified}")
    except Exception as e:
        logger.error(f"Error processing /start user DB interaction for {telegram_user.id}: {e}", exc_info=True)
        await message.reply_text(
            "ببخشید، مشکلی در پردازش پروفایل شما پیش آمد. لطفا دوباره امتحان کنید."
        )
        return ConversationHandler.END # End conversation on DB error

    # Should always have a db_user object here
    if not db_user:
         logger.error(f"DB user object is None after get_or_create for TG ID {telegram_user.id}, ending.")
         await message.reply_text("خطای داخلی رخ داد، لطفا بعدا تلاش کنید.") # Internal error occurred
         return ConversationHandler.END

    # --- Check Verification Status ---
    if db_user.is_verified:
        logger.info(f"User {telegram_user.id} is already verified. Showing main menu.")
        user_display_name = telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
        welcome_message = (
            f"سلام مجدد {user_display_name} عزیز! 👋\n" # Welcome back
            "از دکمه‌های زیر برای ادامه استفاده کنید:"
        )
        await message.reply_text(welcome_message, reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END # End conversation, user is verified
    else:
        # --- Start Verification Process ---
        logger.info(f"User {telegram_user.id} is not verified. Starting verification process.")
        user_display_name = telegram_user.first_name or telegram_user.username or f"کاربر {telegram_user.id}"
        welcome_message = (
            f"سلام {user_display_name} عزیز! 👋\n"
            "به ربات خرید و فروش غذای مهاجر خوش آمدید.\n\n"
            "برای استفاده از ربات، لطفا ابتدا فرآیند اعتبارسنجی را کامل کنید." # To use the bot, please first complete the verification process.
        )
        await message.reply_text(welcome_message) # Send initial welcome

        # Ask first question
        await message.reply_text(
            "1. لطفا شماره دانشجویی خود را وارد کنید:", # 1. Please enter your educational number:
            reply_markup=ReplyKeyboardRemove() # Remove previous keyboard if any
            )
        return ASK_EDU_NUM # Return the next state

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays help message."""
    # Check if user is potentially in a conversation
    if context.user_data and 'current_state' in context.user_data: # Check if in conversation
         await update.message.reply_text("شما در حال حاضر در فرآیند اعتبارسنجی هستید. برای لغو /cancel را بزنید.")
    else:
        await update.message.reply_text(
            "برای شروع کار با ربات از دستور /start استفاده کنید.\n"
            "برای راهنمایی بیشتر از دستور /help استفاده کنید.\n"
            "در طول فرآیند اعتبارسنجی، می‌توانید با دستور /cancel آن را لغو کنید."
        )

# --- Verification Conversation Handlers ---

async def receive_education_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives educational number, saves it, asks for ID number."""
    message = update.message
    if not message or not message.text:
        return ASK_EDU_NUM # Stay in current state if no text

    edu_num = message.text.strip()
    logger.info(f"User {update.effective_user.id} entered educational number: {edu_num}")

    # --- Basic Validation (Example: Check if numeric) ---
    if not edu_num.isdigit():
        await message.reply_text("شماره دانشجویی نامعتبر است. لطفا فقط عدد وارد کنید:")
        return ASK_EDU_NUM # Ask again

    # TODO: Maybe add a check?

    context.user_data['edu_num'] = edu_num # Store in context temporarily

    await message.reply_text("2. لطفا شماره ملی خود را وارد کنید:") # 2. Please enter your identity number:
    return ASK_ID_NUM # Move to next state

async def receive_identity_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives identity number, saves it, asks for phone number."""
    message = update.message
    if not message or not message.text:
        return ASK_ID_NUM

    id_num = message.text.strip()
    logger.info(f"User {update.effective_user.id} entered identity number: {'*' * len(id_num)}") # Log obfuscated

    # Validation
    if not id_num.isdigit() or not utility.is_valid_iranian_national_id(id_num): # Example for Iranian National ID
        await message.reply_text("شماره ملی نامعتبر است.")
        return ASK_ID_NUM # Ask again

    context.user_data['id_num'] = id_num

    # Ask for phone number using Telegram's contact sharing button
    phone_button = KeyboardButton("ارسال شماره تلفن من", request_contact=True) # Share my phone number
    cancel_button = KeyboardButton("/cancel") # Allow cancellation
    reply_markup = ReplyKeyboardMarkup([[phone_button], [cancel_button]], resize_keyboard=True, one_time_keyboard=True) # One time use for contact

    await message.reply_text(
        "3. برای تایید نهایی، لطفا شماره تلفن خود را با استفاده از دکمه زیر به اشتراک بگذارید.", # 3. For final confirmation, please share your phone number using the button below.
        reply_markup=reply_markup
        )
    return ASK_PHONE # Move to next state

async def receive_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives shared contact, validates, updates DB, completes verification."""
    message = update.message
    user = update.effective_user
    contact: Contact | None = message.contact

    if not contact:
        logger.warning(f"User {user.id} sent non-contact message in ASK_PHONE state.")
        await message.reply_text("لطفا از دکمه 'ارسال شماره تلفن من' استفاده کنید یا /cancel را بزنید.")
        return ASK_PHONE # Stay in current state

    # Security Check: Ensure the contact shared belongs to the user sending it
    if contact.user_id != user.id:
        logger.warning(f"User {user.id} shared contact belonging to user {contact.user_id}.")
        await message.reply_text("خطا: شماره تلفن ارسال شده متعلق به شما نیست. لطفا دوباره تلاش کنید یا /cancel بزنید.")
        # Re-ask for phone
        phone_button = KeyboardButton("ارسال شماره تلفن من", request_contact=True)
        cancel_button = KeyboardButton("/cancel")
        reply_markup = ReplyKeyboardMarkup([[phone_button], [cancel_button]], resize_keyboard=True, one_time_keyboard=True)
        await message.reply_text(
            "لطفا شماره تلفن *خودتان* را با استفاده از دکمه زیر به اشتراک بگذارید.",
            reply_markup=reply_markup
        )
        return ASK_PHONE

    phone_num = contact.phone_number
    # Remove '+' if present for consistency, or keep it based on preference
    phone_num = phone_num.lstrip('+')
    logger.info(f"User {user.id} shared phone number: ...{phone_num[-4:]}") # Log partial

    # Retrieve data stored in context
    edu_num = context.user_data.get('edu_num')
    id_num = context.user_data.get('id_num')

    if not edu_num or not id_num:
        logger.error(f"Missing edu_num or id_num in user_data for user {user.id} during phone step.")
        await message.reply_text(
            "خطای داخلی رخ داد. لطفا فرآیند را با /start مجددا شروع کنید.",
            reply_markup=ReplyKeyboardRemove() # Remove keyboard
            )
        context.user_data.clear() # Clear potentially corrupt data
        return ConversationHandler.END

    # Update Database
    try:
        async with get_db_session() as db_session:
            updated_user = await crud.update_user_verification(
                db=db_session,
                telegram_id=user.id,
                edu_num=edu_num,
                id_num=id_num,
                phone_num=phone_num
            )
            if not updated_user:
                 # This case should ideally be handled inside update_user_verification or earlier
                 raise Exception("User not found during verification update")

            logger.info(f"User {user.id} successfully verified and details updated.")
            await message.reply_text(
                "✅ اعتبارسنجی شما با موفقیت انجام شد! از الان می‌توانید از امکانات ربات استفاده کنید.", # Your verification was successful! You can now use the bot features.
                reply_markup=get_main_menu_keyboard() # Show main menu
                )
            context.user_data.clear() # Clean up user_data
            return ConversationHandler.END # End the conversation

    except Exception as e:
        logger.error(f"Failed to update verification details for user {user.id} in DB: {e}", exc_info=True)
        await message.reply_text(
            "خطا در ذخیره اطلاعات اعتبارسنجی. لطفا دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.", # Error saving verification info. Please try again or contact support.
            reply_markup=ReplyKeyboardRemove()
            )
        context.user_data.clear()
        return ConversationHandler.END # End on DB error


async def cancel_verification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the verification process."""
    user = update.effective_user
    message = update.message
    logger.info(f"User {user.id} canceled the verification conversation.")
    context.user_data.clear() # Clear any stored data
    await message.reply_text(
        "فرآیند اعتبارسنجی لغو شد. برای شروع مجدد /start را بزنید.", # Verification process canceled. Press /start to begin again.
        reply_markup=ReplyKeyboardRemove() # Remove any special keyboard
        )
    return ConversationHandler.END


async def unexpected_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages that are not expected in the current conversation state."""
    message = update.message
    if message and message.text:
         logger.warning(f"User {update.effective_user.id} sent unexpected text '{message.text}' during verification.")
         await message.reply_text("ورودی نامعتبر است. لطفا طبق دستورالعمل پیش بروید یا /cancel را بزنید.")
    # Decide if state should change or remain the same depending on current state
    # Returning None keeps the state the same implicitly if used directly in ConversationHandler states dict
    # Or you can retrieve current state from context if needed to return it explicitly


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

    # Fetch Available Listings
    try:
        async with get_db_session() as db_session:
            # crud.get_available_listings should now load Listing.meal directly
            available_listings = await crud.get_available_listings(db_session)

        if not available_listings:
            await message.reply_text("در حال حاضر هیچ غذایی برای فروش ثبت نشده است.")
            return

        response_parts = ["🛒 **لیست غذاهای موجود برای خرید:**\n\n"]
        purchase_buttons = []

        for listing in available_listings:
            meal_desc = "غذای نامشخص"
            meal_date_str = "نامشخص"
            meal_type = "نامشخص"
            # Access meal directly from the listing object
            if listing.meal: # Check if the relationship loaded correctly
                meal = listing.meal
                meal_desc = meal.description or meal_desc
                meal_type = meal.meal_type or meal_type
                if meal.date:
                    try:
                        meal_date_str = meal.date.strftime('%Y-%m-%d')
                    except AttributeError:
                        meal_date_str = str(meal.date)

            seller_name = "ناشناس"
            if listing.seller: # Use seller's username then telegram_id then ناشناس
                 seller_name = f"@{listing.seller.username}" or listing.seller.telegram_id or seller_name

            price_str = f"{listing.price:,.0f}" if listing.price is not None else "نامشخص"

            part = (
                f"🍽️ *{meal_desc}* ({meal_type} - {meal_date_str})\n"
                f"👤 فروشنده: {seller_name}\n"
                f"💰 قیمت: {price_str} تومان\n"
                f"🆔 شماره آگهی: `{listing.id}`\n"
                f"--------------------\n"
            )
            response_parts.append(part)

            purchase_buttons.append([
                InlineKeyboardButton(
                    f"خرید آگهی {listing.id} ({price_str} تومان)",
                    callback_data=f'buy_listing_{listing.id}'
                )
            ])

        full_message = "".join(response_parts)
        reply_markup = InlineKeyboardMarkup(purchase_buttons)

        if len(full_message) > 4096:
            full_message = full_message[:4090] + "\n..."
            logger.warning(f"Listing message for user {user.id} was truncated.")
            await message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN)
            await message.reply_text("لیست کامل طولانی است و خلاصه شد.")
        else:
             await message.reply_text(
                 full_message,
                 parse_mode=ParseMode.MARKDOWN,
                 reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Failed to get or format available listings for user {user.id}: {e}", exc_info=True)
        await message.reply_text(
            "خطا در دریافت لیست غذاها. لطفا دوباره تلاش کنید."
        )


async def handle_sell_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Starts the sell food conversation. Asks for reservation code."""
    user = update.effective_user
    message = update.message
    if not user or not message: return ConversationHandler.END

    logger.info(f"'Sell Food' button pressed by user {user.id}. Starting conversation.")

    # Check Verification Status
    try:
        async with get_db_session() as db_session:
            db_user = await crud.get_user_by_telegram_id(db_session, user.id)

            # Check Verification
            if not db_user or not db_user.is_verified:
                logger.warning(f"Unverified user {user.id} attempted action: sell food")
                await message.reply_text("برای فروش غذا، ابتدا اعتبارسنجی کنید (/start).")
                return ConversationHandler.END  # End if not verified

            # Check Credit Card ONLY if verified
            if not db_user.credit_card_number:
                logger.info(f"User {user.id} attempting to sell, but CC number is missing.")
                # Inform and stop (Guide to Settings)
                await message.reply_text(
                    "⚠️ برای فروش غذا و دریافت وجه، باید شماره کارت بانکی خود را ثبت کنید.\n"
                    "لطفا این کار را از طریق منوی '⚙️ تنظیمات' انجام دهید.",
                    reply_markup=get_main_menu_keyboard()  # Go back to main menu
                )

                return ConversationHandler.END  # Stop the selling process for now

            # If all checks pass, proceed
            logger.info(f"User {user.id} is verified and has CC number. Proceeding with sell flow.")
            context.user_data['seller_db_id'] = db_user.id

            cancel_button = InlineKeyboardButton("❌ لغو", callback_data=CALLBACK_CANCEL_SELL_FLOW)
            reply_markup = InlineKeyboardMarkup([[cancel_button]])

            await message.reply_text(
                "لطفا کد رزرو دانشگاه (کد سلف) که می‌خواهید بفروشید را وارد کنید:",
                reply_markup=reply_markup
            )
            return SELL_ASK_CODE

    except Exception as e:
        logger.error(f"DB error checking user prerequisites for {user.id} in handle_sell_food: {e}", exc_info=True)
        await message.reply_text("خطا در بررسی وضعیت اعتبارسنجی. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END



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

    # Check if code already listed
    try:
        async with get_db_session() as db_session:
            code_exists = await crud.check_listing_exists_by_code(db_session, reservation_code)
            if code_exists:
                logger.warning(f"User {user.id} tried to list code '{reservation_code}' which already exists.")
                await message.reply_text("این کد رزرو قبلا برای فروش ثبت شده است.")
                return ConversationHandler.END

            # Fetch available Meals for selection
            available_meals = await crud.get_meals_for_selling(db_session)  # TODO: Maybe filter by date?
            if not available_meals:
                await message.reply_text(
                    "متاسفانه در حال حاضر هیچ نوع غذایی در سیستم تعریف نشده است. لطفا با ادمین تماس بگیرید.")
                return ConversationHandler.END

            # Store code and prepare meal selection buttons
            context.user_data['university_reservation_code'] = reservation_code
            meal_buttons = []
            # Group buttons, e.g., 2 per row
            button_row = []
            for meal in available_meals:
                button_text = f"{meal.description} ({meal.meal_type} - {meal.date.strftime('%Y-%m-%d')})"
                callback_data = f"sell_select_meal_{meal.id}"
                button_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
                if len(button_row) == 2:  # Max 2 buttons per row
                    meal_buttons.append(button_row)
                    button_row = []
            if button_row:  # Add remaining button(s) if odd number
                meal_buttons.append(button_row)

            meal_buttons.append([InlineKeyboardButton("❌ لغو", callback_data=CALLBACK_CANCEL_SELL_FLOW)])

            if not available_meals: # Check if available_meals was empty before adding cancel
                await message.reply_text("خطا در ساخت دکمه‌های انتخاب غذا.")
                return ConversationHandler.END

            reply_markup = InlineKeyboardMarkup(meal_buttons)
            await message.reply_text("کد معتبر است. لطفا نوع غذای مربوط به این کد را انتخاب کنید:",
                                     reply_markup=reply_markup)
            return SELL_ASK_MEAL  # Move to state waiting for meal selection

    except Exception as e:
        logger.error(f"Error processing reservation code '{reservation_code}' for user {user.id}: {e}", exc_info=True)
        await message.reply_text("خطا در بررسی کد رزرو. لطفا دوباره تلاش کنید یا /cancel را بزنید.")
        return SELL_ASK_CODE  # Ask again

async def receive_meal_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the inline button press for selecting the meal being sold."""
    query = update.callback_query
    user = update.effective_user
    await query.answer() # Answer callback

    callback_data = query.data
    try:
        meal_id = int(callback_data.split('_')[-1]) # Extract ID from sell_select_meal_ID
        logger.info(f"User {user.id} selected meal_id {meal_id} for listing.")
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data format for meal selection: {callback_data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return ConversationHandler.END # End on error

    # Fetch meal details (esp. price limit)
    try:
         async with get_db_session() as db_session:
             meal = await db_session.get(models.Meal, meal_id) # Use session.get for PK lookup
             if not meal:
                 logger.error(f"Meal ID {meal_id} selected by user {user.id} not found in DB.")
                 await query.edit_message_text("خطا: غذای انتخاب شده یافت نشد.")
                 return ConversationHandler.END

             context.user_data['meal_id'] = meal.id
             context.user_data['price_limit'] = meal.price_limit # Store limit (can be None)
             context.user_data['meal_description'] = meal.description or "غذای نامشخص"

             price_prompt = "لطفا قیمتی که می‌خواهید برای فروش این غذا تعیین کنید را به تومان وارد کنید:"
             if meal.price_limit is not None:
                 # Format limit for display
                 try:
                      limit_decimal = Decimal(meal.price_limit)
                      price_prompt += f"\n(توجه: حداکثر قیمت مجاز برای این غذا {limit_decimal:,.0f} تومان است)"
                 except InvalidOperation:
                      price_prompt += f"\n(توجه: حداکثر قیمت مجاز: {meal.price_limit})"

             cancel_button = InlineKeyboardButton("❌ لغو", callback_data=CALLBACK_CANCEL_SELL_FLOW)
             reply_markup = InlineKeyboardMarkup([[cancel_button]])

             await query.edit_message_text(price_prompt, reply_markup=reply_markup) # Edit previous message
             return SELL_ASK_PRICE

    except Exception as e:
        logger.error(f"Error fetching meal details for ID {meal_id}: {e}", exc_info=True)
        await query.edit_message_text("خطا در دریافت اطلاعات غذا. لطفا با /start دوباره شروع کنید.")
        context.user_data.clear()
        return ConversationHandler.END


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
    # --- Create Listing in DB ---
    try:
        async with get_db_session() as db_session:
            new_listing = await crud.create_listing(
                db=db_session,
                seller_db_id=seller_db_id,
                university_reservation_code=code,
                meal_id=meal_id,
                price=price
            )
        if new_listing:
            await query.edit_message_text(f"✅ آگهی شما با شماره `{new_listing.id}` ثبت شد.", parse_mode=ParseMode.MARKDOWN)
            await query.message.reply_text("منوی اصلی:", reply_markup=get_main_menu_keyboard())
        else: await query.edit_message_text("خطا: امکان ثبت آگهی نیست (ممکن است کد تکراری باشد).")
    except Exception as e:
        logger.error(f"Error creating listing: {e}"); await query.edit_message_text("خطا در ثبت آگهی.")
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

# It's good practice to define these constants, maybe even in config.py or a dedicated constants file
BTN_BUY_FOOD = "🛒 خرید غذا"
BTN_SELL_FOOD = "🏷️ فروش غذا"
BTN_MY_LISTINGS = "📄 لیست آگهی‌های من"
BTN_HISTORY = "📜 تاریخچه معاملات"
BTN_SETTINGS = "⚙️ تنظیمات"
MAIN_MENU_BUTTON_TEXTS = {BTN_BUY_FOOD, BTN_SELL_FOOD, BTN_MY_LISTINGS, BTN_SETTINGS, BTN_HISTORY}

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

        meal_desc="نامشخص"; meal_date_str="نامشخص"; meal_type="نامشخص"
        # Access meal directly from listing
        if listing.meal:
            meal=listing.meal
            meal_desc=meal.description or meal_desc
            meal_type=meal.meal_type or meal_type
            if meal.date:
                 try: meal_date_str=meal.date.strftime('%Y-%m-%d')
                 except AttributeError: meal_date_str=str(meal.date)

        seller_name = listing.seller.first_name or listing.seller.username if listing.seller else "ناشناس"
        price_str = f"{listing.price:,.0f}" if listing.price is not None else "نامشخص"

        # Use the corrected variables here
        confirmation_text = (
            "⚠️ **تایید خرید** ⚠️\n\n"
            f"شما در حال خرید:\n"
            f"🍽️ *{meal_desc}* ({meal_type} - {meal_date_str})\n"
            f"👤 از فروشنده: {seller_name}\n"
            f"💰 به قیمت: {price_str} تومان\n"
            f"🆔 شماره آگهی: `{listing.id}`\n\n"
            "آیا خرید را تایید می‌کنید؟\n"
            "(با تایید، اطلاعات پرداخت فروشنده به شما نمایش داده می‌شود و آگهی برای دیگران غیرفعال خواهد شد تا فروشنده پرداخت شما را تایید کند.)"
        )
        confirm_buttons = [[
            InlineKeyboardButton("✅ بله، خرید را تایید می‌کنم", callback_data=f'confirm_buy_{listing_id}'),
            InlineKeyboardButton("❌ لغو", callback_data='cancel_buy')
        ]]
        reply_markup = InlineKeyboardMarkup(confirm_buttons)
        await query.edit_message_text(confirmation_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

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
        buyer_message = (  # Buyer message including card number - RISK!
            f"درخواست خرید شما برای آگهی `{listing_id}` ثبت شد.\n"
            f"⏳ لطفا مبلغ **{price_str} تومان** را به شماره کارت زیر واریز نمایید:\n\n"
            f"💳 **`{seller_card_number}`**\n\n"  # !!! SECURITY RISK !!!
            f"پس از واریز، فروشنده باید دریافت وجه را تایید کند تا کد رزرو برای شما ارسال شود.\n"
            f"🚨 **هشدار:** این ربات مسئولیتی در قبال تراکنش‌های مالی ندارد. با احتیاط اقدام کنید."
        )
        # Edit buyer's message first
        await query.edit_message_text(buyer_message, parse_mode=ParseMode.MARKDOWN)

        # Notify Seller
        try:
            buyer_name = user.first_name or user.username or f"کاربر {user.id}"

            meal_desc = updated_listing.meal.description if updated_listing.meal else "غذا"

            seller_confirm_button = InlineKeyboardButton(
                "✅ تایید دریافت وجه",
                callback_data=f'seller_confirm_{listing_id}'
            )
            seller_markup = InlineKeyboardMarkup([[seller_confirm_button]])
            seller_message = (
                f"🔔 درخواست خرید جدید برای آگهی شما!\n\n"
                f"آگهی: `{listing_id}` ({meal_desc})\n"  # Use corrected meal_desc
                f"خریدار: {buyer_name} (ID: `{user.id}`)\n"
                f"مبلغ: {price_str} تومان\n\n"
                f"خریدار اطلاعات کارت شما را دریافت کرد. لطفا پس از دریافت وجه، دکمه زیر را بزنید تا کد رزرو برای خریدار ارسال شود."
            )
            # Send notification to seller
            await context.bot.send_message(
                chat_id=seller_telegram_id,
                text=seller_message,
                reply_markup=seller_markup,
                parse_mode=ParseMode.MARKDOWN
                )
            logger.info(f"Notified seller {seller_telegram_id} about pending sale {listing_id}")
        except Exception as notify_err:
            logger.error(f"Failed to notify seller {seller_telegram_id} for pending sale {listing_id}: {notify_err}", exc_info=True)
            await context.bot.send_message(user.id, "خطا در ارسال پیام به فروشنده. لطفا با پشتیبانی تماس بگیرید.") # Inform buyer
    else:
        # Handle failure: edit buyer's original message if possible
        try:
            await query.edit_message_text(error_message)
        except Exception as edit_err:
            logger.error(f"Failed to edit buyer message after purchase confirmation failure: {edit_err}")


async def handle_seller_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles seller confirmation, calls finalize, sends code to buyer."""
    query = update.callback_query;
    user = update.effective_user;
    await query.answer("در حال تایید...")
    try:
        listing_id = int(query.data.split('_')[-1])
    except:
        await query.edit_message_text("خطا: دکمه نامعتبر."); return
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

            if finalized_listing:
                buyer_telegram_id = finalized_listing.buyer.telegram_id if finalized_listing.buyer else None
            else:  # Check failure reason if finalize returned None
                # Fetch listing again to provide specific feedback
                listing_check = await crud.get_listing_by_id(db_session, listing_id)  # Ensure await is here
                if not listing_check:
                    error_message = "آگهی یافت نشد."
                elif listing_check.seller_id != user.id:
                    error_message = "شما فروشنده نیستید."
                elif listing_check.status == models.ListingStatus.SOLD:
                    error_message = "فروش قبلا نهایی شده."
                elif listing_check.status != models.ListingStatus.AWAITING_CONFIRMATION:
                    error_message = f"وضعیت آگهی ({listing_check.status.value}) قابل تایید نیست."
                else:
                    error_message = "خطا در بروزرسانی وضعیت."  # Fallback if reason unclear

    except Exception as e:
        # Log the type of e and convert it to string for the message, include full traceback
        logger.error(
            f"Caught exception during finalize process for listing {listing_id}. Type: {type(e)}, Error: {str(e)}",
            exc_info=True  # This is important to get the full traceback
        )
        error_message = "خطای جدی."
        finalized_listing = None
    # --- Notify ---
    if finalized_listing and buyer_telegram_id and reservation_code:
        await query.edit_message_text(f"✅ دریافت وجه برای آگهی `{listing_id}` تایید شد.\nکد برای خریدار ارسال شد.")
        try:
            buyer_message = (f"✅ پرداخت شما برای آگهی `{listing_id}` تایید شد!\n\nکد رزرو شما: `{reservation_code}`\n\nاز این کد برای دریافت غذا استفاده کنید.")
            await context.bot.send_message(chat_id=buyer_telegram_id, text=buyer_message, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu_keyboard())
            logger.info(f"Sent code for listing {listing_id} to buyer {buyer_telegram_id}")
        except Exception as notify_err: logger.error(f"Failed send code to buyer {buyer_telegram_id}: {notify_err}"); await context.bot.send_message(user.id, f"خطا در ارسال کد به خریدار آگهی {listing_id}.")
    else: await query.edit_message_text(error_message)


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
                try: meal_date_str = listing.meal.date.strftime('%Y-%m-%d')
                except AttributeError: meal_date_str = str(listing.meal.date)

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
                InlineKeyboardButton("❌ لغو این آگهی", callback_data=f'cancel_listing_{listing.id}')
            )
        # Optional: Add button to view pending buyer info?
        # if listing.status == models.ListingStatus.AWAITING_CONFIRMATION:
            # buttons_row.append(InlineKeyboardButton("ℹ️ اطلاعات خریدار", callback_data=f'view_pending_{listing.id}'))

        response_parts.append(part)
        if buttons_row: # Only add button row if buttons exist
             response_parts.append("----\n") # Add separator only if buttons follow
             inline_keyboard.append(buttons_row)
        else:
            response_parts.append("--------------------\n") # Add separator

    # Add a Back button at the end
    inline_keyboard.append([
        InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='settings_back_main') # Re-use existing back handler
    ])

    full_message = "".join(response_parts)
    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    # Handle potential message length issues (less likely than full buy list)
    if len(full_message) > 4096:
        logger.warning(f"My Listings message for user {user.id} possibly truncated.")
        # Truncate smartly if needed, or consider pagination
        await message.reply_text(full_message[:4090] + "\n...", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# --- Callback Handler for Cancel Button ---
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


async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Transaction History' button, prompts for type."""
    user = update.effective_user
    message = update.message
    if not user or not message: return

    logger.info(f"'Transaction History' button pressed by user {user.id}")

    # Optional: Check verification status if history is restricted
    # async with get_db_session() as db_session:
    #    db_user = await crud.get_user_by_telegram_id(db_session, user.id)
    #    if not db_user or not db_user.is_verified:
    #        await message.reply_text("برای مشاهده تاریخچه، ابتدا باید اعتبارسنجی شوید (/start).")
    #        return

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
    if not query or not user or not query.data: return

    await query.answer()

    # --- Parse Callback Data ---
    try:
        parts = query.data.split('_')
        history_type = parts[1] # 'purchases' or 'sales'
        page = int(parts[2])    # Current page number
    except (IndexError, ValueError):
        logger.error(f"Invalid callback data for history view: {query.data}")
        await query.edit_message_text("خطای داخلی: دکمه نامعتبر.")
        return

    logger.info(f"User {user.id} viewing history: type={history_type}, page={page}")

    # --- Fetch Data ---
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

    # --- Format Message ---
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

    # --- Pagination Logic ---
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

    # --- Keyboard Assembly ---
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