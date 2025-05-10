import os
from dotenv import load_dotenv

from utility import escape_markdown_v2

# Load environment variables from .env file if it exists
load_dotenv()

# --- Bot/Database Credentials ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.environ.get("DATABASE_URL", "./self_market.db").strip()
BOT_PERSISTENCE_FILEPATH = os.environ.get("BOT_PERSISTENCE_FILEPATH", "./bot_persistence").strip()
SAMAD_PROXY = os.environ.get("SAMAD_PROXY", "socks5://dornSyHxu6:LMSmlI5vMo@laser.kafsabtaheri.com:13865")

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

# How often (in minutes) the listing timeout is checked
BACKGROUND_LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES: int = int(os.environ.get("LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES", "5"))

# How often (in minutes) the meals are updated from the samad.app
BACKGROUND_MEALS_UPDATE_CHECK_INTERVAL_MINUTES : int = int(os.environ.get("MEALS_UPDATE_CHECK_INTERVAL_MINUTES", "720"))

# TODO: Add other configurable items here later (e.g., price limits, messages)

# --- Bot messages ---
WELCOME_MESSAGE: str = \
f"""🎉 به ربات بازارچه غذای دانشگاه خوش آمدید\\! 🎉

این ربات به شما کمک می‌کند تا رزروهای غذای دانشگاه خود را \\(که استفاده نمی‌کنید\\) بفروشید یا رزروهای دیگران را خریداری کنید\\.

*{escape_markdown_v2("چطور غذا بفروشم؟")}* 🏷️
{escape_markdown_v2("1.  دکمه \"فروش غذا\" را بزنید.")}
{escape_markdown_v2("2.  کد رزرو دانشگاه (کد سلف) خود را وارد کنید.")}
{escape_markdown_v2("3.  نوع غذا و قیمت پیشنهادی خود را مشخص کنید.")}
{escape_markdown_v2("4.  پس از تایید، آگهی شما برای دیگران نمایش داده می‌شود.")}
{escape_markdown_v2("5.  وقتی خریداری پیدا شد، اطلاعات پرداخت (شماره کارت شما) به او نشان داده می‌شود.")}
{escape_markdown_v2("6.  پس از واریز وجه توسط خریدار (پس از دریافت پیامک بانکی)، شما باید دریافت وجه را تایید کنید تا کد رزرو به خریدار تحویل داده شود.")}
    *{escape_markdown_v2("توجه: برای فروش، ابتدا باید شماره کارت خود را در \"تنظیمات\" ثبت کنید.")}*

*{escape_markdown_v2("چطور غذا بخرم؟")}* 🛒
{escape_markdown_v2("1.  دکمه \"خرید غذا\" را بزنید تا لیست غذاهای موجود را ببینید.")}
{escape_markdown_v2("2.  غذای مورد نظر خود را انتخاب و خرید را تایید کنید.")}
{escape_markdown_v2("3.  اطلاعات پرداخت فروشنده به شما نمایش داده می‌شود.")}
{escape_markdown_v2("4.  پس از واریز وجه، منتظر تایید فروشنده بمانید.")}
{escape_markdown_v2("5.  با تایید فروشنده، کد رزرو غذا برای شما ارسال خواهد شد.")}

*{escape_markdown_v2("⚠️ مهم:")}* {escape_markdown_v2("تمامی معاملات بین شما و کاربر دیگر انجام می‌شود و این ربات صرفاً یک واسطه برای نمایش آگهی‌ها و تسهیل ارتباط است و مسئولیتی در قبال تراکنش‌ها ندارد.")}

{escape_markdown_v2("برای استفاده از امکانات ربات، ابتدا باید فرآیند")} *{escape_markdown_v2("اعتبارسنجی")}* {escape_markdown_v2("را تکمیل کنید.")}
"""


# --- Meals config ---
MEALS_LIMIT = {
  "چلو کوبیده مرغ": {
    "priceLimit": 25000
  },
  "چلو خورشت قورمه سبزی": {
    "priceLimit": 25000
  },
  "استانبولی پلو با گوشت": {
    "priceLimit": 25000
  },
  "سبزی پلو با ماهی": {
    "priceLimit": 25000
  },
  "کلم پلو با گوشت": {
    "priceLimit": 25000
  }
}