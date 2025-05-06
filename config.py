import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# --- Bot/Database Credentials ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./self_market.db")


# --- Admin Configuration ---
# Comma-separated list of Telegram User IDs for admins
ADMIN_TELEGRAM_IDS_STR = os.environ.get("ADMIN_TELEGRAM_IDS", "")
ADMIN_TELEGRAM_IDS: list[int] = []
if ADMIN_TELEGRAM_IDS_STR:
    try:
        ADMIN_TELEGRAM_IDS = [int(uid.strip()) for uid in ADMIN_TELEGRAM_IDS_STR.split(',') if uid.strip()]
    except ValueError:
        print("ERROR: Invalid ADMIN_TELEGRAM_IDS in .env file. Should be comma-separated integers.")
        ADMIN_TELEGRAM_IDS = []

# --- Logging ---
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# --- Application Logic Constants ---
# How many items to show per page in history view
HISTORY_PAGE_SIZE: int = 5

# How long (in minutes) a listing can stay in AWAITING_CONFIRMATION before timeout
PENDING_TIMEOUT_MINUTES: int = int(os.environ.get("PENDING_TIMEOUT_MINUTES", "5"))

# How often (in minutes) the background task checks for timed-out listings
BACKGROUND_CHECK_INTERVAL_MINUTES: int = int(os.environ.get("BACKGROUND_CHECK_INTERVAL_MINUTES", "5"))

# TODO: Add other configurable items here later (e.g., price limits, messages)