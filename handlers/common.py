import logging
from telegram import ReplyKeyboardMarkup, KeyboardButton

logger = logging.getLogger(__name__)

# --- Conversation States ---
(ASK_EDU_NUM, ASK_ID_NUM, ASK_PHONE) = range(3) # Verification States
(SELL_ASK_CODE, SELL_ASK_MEAL, SELL_ASK_PRICE, SELL_CONFIRM) = range(10, 14) # Selling States
(SETTINGS_ASK_CARD,) = range(20, 21) # Settings States

# --- Callback Data Constants ---
CALLBACK_CANCEL_SELL_FLOW = "cancel_sell_flow"
CALLBACK_BUYER_CANCEL_PENDING = "buyer_cancel_pending"
CALLBACK_SELLER_REJECT_PENDING = "seller_reject_pending"
CALLBACK_BUY_REFRESH = "buy_refresh_list"
# Add other specific callbacks here if needed by multiple modules or for registration central point
CALLBACK_SETTINGS_UPDATE_CARD = "settings_update_card"
CALLBACK_SETTINGS_BACK_MAIN = "settings_back_main"
CALLBACK_HISTORY_PURCHASES = "history_purchases_0"
CALLBACK_HISTORY_SALES = "history_sales_0"
CALLBACK_HISTORY_BACK_SELECT = "history_back_select"
CALLBACK_HISTORY_NOOP = "history_noop"
CALLBACK_LISTING_CANCEL_CONFIRM_YES = 'confirm_listing_yes'
CALLBACK_LISTING_CANCEL_CONFIRM_NO = 'confirm_listing_no'
CALLBACK_BUYER_PAYMENT_SENT = "buyer_payment_sent"
CALLBACK_ADMIN_REFRESH_STATS = "admin_refresh_stats"

# --- Main Menu Button Texts ---
BTN_BUY_FOOD = "🛒 خرید غذا"
BTN_SELL_FOOD = "🏷️ فروش غذا"
BTN_MY_LISTINGS = "📄 لیست آگهی‌های من"
BTN_HISTORY = "📜 تاریخچه معاملات"
BTN_SETTINGS = "⚙️ تنظیمات"
MAIN_MENU_BUTTON_TEXTS = {BTN_BUY_FOOD, BTN_SELL_FOOD, BTN_MY_LISTINGS, BTN_SETTINGS, BTN_HISTORY}


# Helper Function for Main Menu Keyboard
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Returns the main ReplyKeyboardMarkup."""
    keyboard = [
        [KeyboardButton(BTN_BUY_FOOD), KeyboardButton(BTN_SELL_FOOD)],
        [KeyboardButton(BTN_MY_LISTINGS), KeyboardButton(BTN_SETTINGS)],
        [KeyboardButton(BTN_HISTORY)]
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="گزینه مورد نظر را انتخاب کنید..."
    )

# logger.debug("Common handlers definitions loaded.")