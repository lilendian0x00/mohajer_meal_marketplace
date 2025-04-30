# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# --- Telegram Bot ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")

# --- Database ---
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./self_market.db")

# --- Logging ---
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = "INFO"