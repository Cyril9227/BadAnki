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
from database import get_db_connection
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
                message = f"*Question:*\n{question_text}\n\n*Answer:*\n||{answer_text}||"

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
            await update.message.reply_text("You are not registered. Please use `/register <username> <password>` to link your account.")
            logger.warning(f"User not found for chat_id {chat_id}.")
    except Exception as e:
        logger.error(f"Error in /random command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, something went wrong while fetching a card.")
    finally:
        if conn:
            conn.close()

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registers a user's Telegram chat ID with their account."""
    logger.info(f"Received /register command from chat_id: {update.message.chat_id}")
    conn = None
    try:
        chat_id = update.message.chat_id
        args = context.args
        if len(args) != 2:
            await update.message.reply_text("Usage: /register <username> <password>")
            return

        username, password = args
        conn = get_db_connection()
        
        user = get_user_by_telegram_chat_id(conn, chat_id)
        if user:
            await update.message.reply_text("This chat is already registered to a user.")
            logger.warning(f"Chat_id {chat_id} is already registered to user {user['id']}.")
            return

        user = get_user_by_username(conn, username)
        if user and verify_password(password, user['password_hash']):
            update_telegram_chat_id(conn, user['id'], chat_id)
            await update.message.reply_text("Successfully registered your Telegram account!")
            logger.info(f"Successfully registered chat_id {chat_id} to user {user['id']}.")
        else:
            await update.message.reply_text("Invalid username or password.")
            logger.warning(f"Failed registration attempt for username: {username}.")
    except Exception as e:
        logger.error(f"Error in /register command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, something went wrong during registration.")
    finally:
        if conn:
            conn.close()

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
    application.add_handler(CommandHandler("register", register))

    return application
