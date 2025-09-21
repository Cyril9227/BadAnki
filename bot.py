# bot.py
# This file contains the Telegram bot application.

from dotenv import load_dotenv

load_dotenv()

import os
import logging
from telegram import Update
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
from database import get_db_connection, release_db_connection
from crud import get_random_card_for_user, get_user_by_username, verify_password, get_user_by_telegram_chat_id, update_telegram_chat_id

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
    try:
        await update.message.reply_text(
            "Welcome to the Anki Clone bot! Use /review to get a link to your next review session."
        )
    except Exception as e:
        logger.error(f"Error in /start command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, something went wrong.")

async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a link to the review page."""
    try:
        review_link = f"{APP_URL}/review"
        await update.message.reply_text(
            f"Click here to start your review session: {review_link}"
        )
    except Exception as e:
        logger.error(f"Error in /review command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, something went wrong.")

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the user their chat ID."""
    try:
        chat_id = update.message.chat_id
        await update.message.reply_text(f"Your Telegram Chat ID is: `{chat_id}`")
    except Exception as e:
        logger.error(f"Error in /my_id command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, something went wrong.")

async def random_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a random card to a registered user with better formatting and a web link."""
    logger.info(f"Received /random command from chat_id: {update.message.chat_id}")
    conn = None
    try:
        conn = get_db_connection()
        chat_id = update.message.chat_id
        user = get_user_by_telegram_chat_id(conn, chat_id)

        if user:
            logger.info(f"User found for chat_id {chat_id}: user_id {user['id']}")
            card = get_random_card_for_user(conn, user['id'])
            if card:
                # Prepare the message with MarkdownV2
                question_text = escape_markdown(card['question'], version=2)
                answer_text = escape_markdown(card['answer'], version=2)
                message = f"*Question:* {question_text} *Answer:* ||{answer_text}||"

                # Prepare the "View on Web" button
                card_url = f"{APP_URL}/card/{card['id']}"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("View on Web", url=card_url)]
                ])

                await update.message.reply_text(
                    message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=keyboard
                )
                logger.info(f"Sent random card {card['id']} to user {user['id']}.")
            else:
                await update.message.reply_text("You have no cards in your deck.")
                logger.info(f"No cards found for user {user['id']}.")
        else:
            await update.message.reply_text(
                "Your Telegram account is not linked. "
                "Please log in to the web application and link your account in the settings."
            )
            logger.warning(f"User not found for chat_id {chat_id}.")
    except Exception as e:
        logger.error(f"Error in /random command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, something went wrong while fetching a card.")
    finally:
        if conn:
            release_db_connection(conn)

def setup_bot():
    """Creates and configures the bot application."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return None

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register the command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("review", review))
    application.add_handler(CommandHandler("myid", my_id))
    application.add_handler(CommandHandler("random", random_card))

    return application

if __name__ == "__main__":
    logger.info("Starting bot in standalone polling mode...")
    bot_app = setup_bot()
    if bot_app:
        logger.info("Bot application created. Starting polling.")
        bot_app.run_polling()
    else:
        logger.error("Failed to create bot application. Check TELEGRAM_BOT_TOKEN.")