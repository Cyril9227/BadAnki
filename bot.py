# bot.py
# This file contains the Telegram bot application.

import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Bot Configuration ---

# Enable logging to see errors
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# The URL of your FastAPI application
# Change this to your public URL when you deploy
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")


# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Welcome to the Anki Clone bot! Use /review to get a link to your next review session."
    )

async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a link to the review page."""
    review_link = f"{APP_URL}/review"
    await update.message.reply_text(
        f"Click here to start your review session: {review_link}"
    )

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the user their chat ID."""
    chat_id = update.message.chat_id
    await update.message.reply_text(f"Your Telegram Chat ID is: `{chat_id}`")

def main():
    """Runs the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register the command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("review", review))
    application.add_handler(CommandHandler("myid", my_id))

    # Start the Bot
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
