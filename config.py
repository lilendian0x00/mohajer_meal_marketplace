import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# --- Bot/Database Credentials ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./self_market.db")

# --- Logging ---
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# --- Application Logic Constants ---
# How many items to show per page in history view
HISTORY_PAGE_SIZE: int = 5

# How long (in minutes) a listing can stay in AWAITING_CONFIRMATION before timeout
PENDING_TIMEOUT_MINUTES: int = 5

# How often (in minutes) the background task checks for timed-out listings
BACKGROUND_CHECK_INTERVAL_MINUTES: int = 5

# TODO: Add other configurable items here later (e.g., price limits, messages)