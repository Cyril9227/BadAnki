# bot.py
# This file contains the Telegram bot application.

from dotenv import load_dotenv

load_dotenv()

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from database import get_db_connection, release_db_connection
from crud import get_card_for_user, get_random_card_for_user, get_user_by_telegram_chat_id
from telegram_format import render_markdown_v2, spoiler_safe

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- Configuration ---
# Note: We read APP_URL at module level since it's not sensitive and rarely changes.
# TELEGRAM_BOT_TOKEN is read at runtime in get_bot_application() to avoid
# serverless cold-start issues.
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")


def _redact_identifier(value) -> str:
    text = str(value)
    if len(text) <= 4:
        return "***"
    return f"***{text[-4:]}"


# --- Card Message Building ---

TELEGRAM_MESSAGE_LIMIT = 4096


def _web_button(card_id) -> InlineKeyboardButton:
    return InlineKeyboardButton("View on Web", url=f"{APP_URL}/card/{card_id}")


def build_card_message(card, reveal: bool = False):
    """Builds the rich MarkdownV2 text and keyboard for a card.

    Math and code render as code/pre entities, which Telegram cannot nest
    inside a ||spoiler||; answers containing them are hidden behind a
    "Show answer" button instead.
    """
    question = render_markdown_v2(card['question'])
    answer = render_markdown_v2(card['answer'])
    keyboard = [[_web_button(card['id'])]]

    if reveal:
        text = f"❓ *Question*\n{question}\n\n💡 *Answer*\n{answer}"
    elif spoiler_safe(answer):
        text = f"❓ *Question*\n{question}\n\n💡 *Answer*\n||{answer}||"
    else:
        text = f"❓ *Question*\n{question}"
        keyboard.insert(0, [InlineKeyboardButton("💡 Show answer", callback_data=f"ans:{card['id']}")])

    return text, InlineKeyboardMarkup(keyboard)


def build_plain_card_message(card, reveal: bool = False):
    """Escape-everything fallback (the original format) — always parseable."""
    question = escape_markdown(card['question'], version=2)
    answer = escape_markdown(card['answer'], version=2)
    if reveal:
        text = f"*Question:* {question}\n\n*Answer:* {answer}"
    else:
        text = f"*Question:* {question}\n\n*Answer:* ||{answer}||"
    return text, InlineKeyboardMarkup([[_web_button(card['id'])]])


async def _reply_card(send, card, reveal: bool):
    """Delivers a card via `send` (a reply_text or edit_message_text callable),
    degrading gracefully: rich rendering -> plain escaped text -> web link."""
    for build in (build_card_message, build_plain_card_message):
        text, keyboard = build(card, reveal)
        if len(text) > TELEGRAM_MESSAGE_LIMIT:
            continue
        try:
            await send(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
            return
        except BadRequest:
            logger.warning(
                "Telegram rejected %s for card %s; degrading.",
                build.__name__, card['id'], exc_info=True,
            )
    await send(
        "This card can't be displayed in Telegram. Use the button below to view it.",
        reply_markup=InlineKeyboardMarkup([[_web_button(card['id'])]]),
    )


# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    try:
        await update.message.reply_text(
            "Welcome to the Anki Clone bot! Use /review to get a link to your next review session or /random to get a random card."
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


async def random_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a random card to a registered user."""
    logger.info("Received /random command from chat_id: %s", _redact_identifier(update.message.chat_id))
    conn = None
    try:
        conn = get_db_connection()
        chat_id = update.message.chat_id
        redacted_chat_id = _redact_identifier(chat_id)
        user = get_user_by_telegram_chat_id(conn, chat_id)

        if user:
            logger.info("User found for chat_id %s.", redacted_chat_id)
            card = get_random_card_for_user(conn, user['auth_user_id'])
            if card:
                await _reply_card(update.message.reply_text, card, reveal=False)
                logger.info("Sent random card %s to chat_id %s.", card['id'], redacted_chat_id)
            else:
                await update.message.reply_text("You have no cards in your deck.")
                logger.info("No cards found for chat_id %s.", redacted_chat_id)
        else:
            await update.message.reply_text(
                "Your Telegram account is not linked. "
                "Please log in to the web application and link your account in the settings."
            )
            logger.warning("User not found for chat_id %s.", redacted_chat_id)
    except Exception as e:
        logger.error(f"Error in /random command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, something went wrong while fetching a card.")
    finally:
        if conn:
            release_db_connection(conn)

async def show_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reveals a card's answer when its "Show answer" button is tapped."""
    query = update.callback_query
    conn = None
    try:
        card_id = int(query.data.split(":", 1)[1])
        conn = get_db_connection()
        user = get_user_by_telegram_chat_id(conn, query.message.chat.id)
        card = get_card_for_user(conn, card_id, user['auth_user_id']) if user else None
        if not card:
            await query.answer("Card not found.")
            return

        await _reply_card(query.edit_message_text, card, reveal=True)
        await query.answer()
    except Exception as e:
        logger.error(f"Error in show answer callback: {e}", exc_info=True)
        try:
            await query.answer("Sorry, something went wrong.")
        except Exception:
            pass
    finally:
        if conn:
            release_db_connection(conn)


def get_bot_application():
    """Creates and configures a fresh bot application (serverless pattern).

    The token is read at runtime to avoid serverless cold-start timing issues.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return None

    application = Application.builder().token(token).build()

    # Register the command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("review", review))
    application.add_handler(CommandHandler("random", random_card))
    application.add_handler(CallbackQueryHandler(show_answer, pattern=r"^ans:\d+$"))

    return application

if __name__ == "__main__":
    logger.info("Starting bot in standalone polling mode...")
    bot_app = get_bot_application()
    if bot_app:
        logger.info("Bot application created. Starting polling.")
        bot_app.run_polling()
