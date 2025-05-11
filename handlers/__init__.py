# Import constants and shared functions first
from .common import *

# Import handlers from each module
from .verification import *
from .selling import *
from .buying import *
from .listings import *
from .settings import *
from .history import *
from .admin import *

# Explicitly define what gets imported with "from handlers import *"
# This is good practice and helps tools understand the package structure.
__all__ = [
    # Common Constants & Functions
    # 'ASK_EDU_NUM',
    # 'ASK_ID_NUM',
    'ASK_PHONE',
    'SELL_ASK_CODE', 'SELL_ASK_MEAL', 'SELL_ASK_PRICE', 'SELL_CONFIRM',
    'SETTINGS_ASK_CARD',
    'CALLBACK_CANCEL_SELL_FLOW', 'CALLBACK_BUYER_CANCEL_PENDING',
    'CALLBACK_SELLER_REJECT_PENDING', 'CALLBACK_BUY_REFRESH',
    'CALLBACK_SETTINGS_UPDATE_CARD', 'CALLBACK_SETTINGS_BACK_MAIN',
    'CALLBACK_HISTORY_PURCHASES', 'CALLBACK_HISTORY_SALES',
    'CALLBACK_HISTORY_BACK_SELECT', 'CALLBACK_HISTORY_NOOP',
    'CALLBACK_LISTING_CANCEL_CONFIRM_YES', 'CALLBACK_LISTING_CANCEL_CONFIRM_NO',
    'BTN_BUY_FOOD', 'BTN_SELL_FOOD', 'BTN_MY_LISTINGS',
    'BTN_HISTORY', 'BTN_SETTINGS', 'MAIN_MENU_BUTTON_TEXTS',
    'get_main_menu_keyboard',

    # Verification Handlers
    'start',
    # 'receive_education_number',
    # 'receive_identity_number',
    'receive_phone_number',
    'cancel_verification', 'help_command',

    # Selling Handlers
    'handle_sell_food', 'receive_reservation_code', 'receive_meal_selection',
    'receive_price', 'confirm_listing', 'handle_inline_cancel_sell',
    'cancel_listing_creation', 'cancel_sell_conversation',

    # Buying Handlers (includes confirmations/cancellations related to buying)
    'handle_buy_food', 'handle_buy_refresh', 'handle_purchase_button',
    'handle_confirm_purchase', 'handle_cancel_purchase',
    'handle_buyer_cancel_pending', 'handle_seller_reject_pending',
    'handle_seller_confirmation',

    # Listings Management Handlers
    'handle_my_listings', 'handle_cancel_available_listing_button',

    # Settings Handlers
    'handle_settings', 'handle_settings_back_main',
    'handle_settings_update_card_button', 'receive_settings_card_number',
    'cancel_settings_card_update',

    # History Handlers
    'handle_history', 'handle_history_view', 'handle_history_back_select',

    # Admin Handlers
    'set_admin_status', 'set_active_status', 'get_user_info',
    'list_users_command', 'list_users_callback', 'admin_noop_callback', # Added admin_noop_callback
    'add_meal_conv_handler', # Add the conversation handler itself
    'delete_meal_command', 'delete_listing_command',
    # Add conversation states for admin if they need to be globally accessible for some reason, usually not.
    # 'ADDMEAL_ASK_DESCRIPTION', 'ADDMEAL_ASK_TYPE', etc.
    # Add callback data constants for admin if needed globally
    'CALLBACK_ADMIN_LIST_USERS_PAGE',
    # 'CALLBACK_ADMIN_MEAL_CONFIRM_YES', 'CALLBACK_ADMIN_MEAL_CONFIRM_NO', # These are used within admin.py


    # Optional Fallback Handlers
    'echo', 'unexpected_message_handler',
]

print("Handlers package initialized and modules imported.")