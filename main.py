import logging
import os
from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# --- Configuration ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7977851702:AAEs8NFQh3su7Po9HtFxDNQjwzDBy_TEWKU")

# Enable logging to see errors and bot activity
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# --- Command Handlers ---

# Define the handler for the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    # Use HTML formatting for the reply
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! I'm a simple echo bot. Send me a message, and I'll echo it back.",
        # reply_markup=ForceReply(selective=True), # Optional: Force user to reply
    )


# --- Message Handlers ---

# Define the handler to echo text messages
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echoes the user's text message."""
    logger.info(f"Received message from {update.effective_user.username}: {update.message.text}")
    await update.message.reply_text(f"You said: {update.message.text}")


# --- Main Bot Logic ---
def main() -> None:
    """Start the bot."""
    # 1. Create the Application instance and pass it your bot's token.
    if TOKEN == "YOUR_BOT_TOKEN":
        logger.error("Please replace 'YOUR_BOT_TOKEN' with your actual bot token!")
        return

    application = Application.builder().token(TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))

    # on non command i.e message - echo the message on Telegram
    # filters.TEXT checks if the message contains text
    # ~filters.COMMAND ensures it's not a command
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # 3. Start the Bot using polling
    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()