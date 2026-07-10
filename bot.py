# bot.py
# This file contains the Telegram bot application.

from dotenv import load_dotenv

load_dotenv()

import hashlib
import os
import logging
import time

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from database import get_db_connection, release_db_connection
from crud import (
    cache_photo_file_id,
    get_cached_photo_file_id,
    get_card_for_user,
    get_random_card_for_user,
    get_user_by_telegram_chat_id,
    link_telegram_chat,
)
from render_auth import sign_render_request, verify_telegram_link_token
from telegram_format import (
    cloze_plain_markdown_v2,
    is_cloze,
    needs_screenshot,
    render_cloze_markdown_v2,
    render_markdown_v2,
    spoiler_safe,
)

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
TELEGRAM_CAPTION_LIMIT = 1024
RENDER_TIMEOUT_SECONDS = 15.0
RENDER_TOKEN_TTL_SECONDS = 300
# Bump to invalidate all cached renders (e.g. after changing the render page
# styling or screenshot parameters).
RENDER_CACHE_VERSION = "v1"


def _web_button(card_id) -> InlineKeyboardButton:
    return InlineKeyboardButton("View on Web", url=f"{APP_URL}/card/{card_id}")


def build_card_message(card, reveal: bool = False):
    """Builds the rich MarkdownV2 text and keyboard for a card.

    Math and code render as code/pre entities, which Telegram cannot nest
    inside a ||spoiler||; answers containing them are hidden behind a
    "Show answer" button instead.
    """
    keyboard = [[_web_button(card['id'])]]

    # Cloze cards are self-contained: each {{cN::...}} blank becomes an
    # in-place spoiler, so there is no separate answer to attach.
    if is_cloze(card['question']):
        text = f"📝 *Cloze*\n{render_cloze_markdown_v2(card['question'], reveal=reveal)}"
        return text, InlineKeyboardMarkup(keyboard)

    question = render_markdown_v2(card['question'])
    answer = render_markdown_v2(card['answer'])

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
    if is_cloze(card['question']):
        text = f"*Cloze:* {cloze_plain_markdown_v2(card['question'], reveal=reveal)}"
        return text, InlineKeyboardMarkup([[_web_button(card['id'])]])

    question = escape_markdown(card['question'], version=2)
    answer = escape_markdown(card['answer'], version=2)
    if reveal:
        text = f"*Question:* {question}\n\n*Answer:* {answer}"
    else:
        text = f"*Question:* {question}\n\n*Answer:* ||{answer}||"
    return text, InlineKeyboardMarkup([[_web_button(card['id'])]])


async def _fetch_answer_image(card_id) -> bytes | None:
    """Asks the api/render-card.js screenshot function for a PNG of the
    card's answer, authorized by a short-lived HMAC signature. Never raises:
    a failed render must degrade to the text flow, not break the card."""
    try:
        expires_at = int(time.time()) + RENDER_TOKEN_TTL_SECONDS
        params = {
            "card_id": card_id,
            "exp": expires_at,
            "sig": sign_render_request(card_id, expires_at),
        }
        async with httpx.AsyncClient(timeout=RENDER_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{APP_URL}/api/render-card", params=params)
        if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
            return response.content
        logger.warning("Screenshot service returned status %s for card %s.", response.status_code, card_id)
    except Exception as e:
        logger.warning(f"Screenshot service failed for card {card_id}: {e}")
    return None


def _answer_cache_key(answer: str) -> str:
    """Cache key for a rendered answer. Content-addressed: editing a card
    changes the key, so stale cache rows are simply never read again."""
    return hashlib.sha256(f"{RENDER_CACHE_VERSION}:{answer}".encode()).hexdigest()


def _rollback_quietly(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _get_cached_file_id(conn, cache_key):
    """Best-effort cache lookup. A failure (e.g. the cache table does not
    exist yet) must never break the photo flow, but it does require a
    rollback so the aborted transaction can't poison later queries."""
    try:
        return get_cached_photo_file_id(conn, cache_key)
    except Exception as e:
        logger.info(f"Photo cache lookup unavailable: {e}")
        _rollback_quietly(conn)
        return None


def _store_cached_file_id(conn, cache_key, file_id, card_id):
    try:
        cache_photo_file_id(conn, cache_key, file_id, card_id)
    except Exception as e:
        logger.info(f"Photo cache store unavailable: {e}")
        _rollback_quietly(conn)


def _is_photo_error(error: BadRequest) -> bool:
    """Whether a BadRequest is about the photo itself (e.g. a stale cached
    file_id) rather than the caption formatting."""
    message = str(error).lower()
    return "file" in message or "photo" in message or "image" in message


async def _try_send_photo(message, card, photo):
    """Sends the spoilered answer photo with the question attached, degrading
    the caption (rich -> plain -> separate text message). Returns the sent
    photo Message, or None when Telegram refuses the photo itself."""
    keyboard = InlineKeyboardMarkup([[_web_button(card['id'])]])
    rich_caption = f"❓ *Question*\n{render_markdown_v2(card['question'])}"
    plain_caption = f"*Question:* {escape_markdown(card['question'], version=2)}"

    for caption in (rich_caption, plain_caption):
        if len(caption) > TELEGRAM_CAPTION_LIMIT:
            continue
        try:
            return await message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN_V2,
                has_spoiler=True,
                reply_markup=keyboard,
            )
        except BadRequest as e:
            if _is_photo_error(e):
                logger.info("Telegram refused photo for card %s: %s", card['id'], e)
                return None
            logger.warning("Telegram rejected photo caption for card %s; degrading.", card['id'], exc_info=True)

    # Question too long for a caption (or rejected): bare photo first (same
    # photo-then-question order a caption renders in), then the question.
    try:
        sent = await message.reply_photo(photo=photo, has_spoiler=True, reply_markup=keyboard)
    except Exception as e:
        logger.warning(f"Failed to send answer photo for card {card['id']}: {e}")
        return None
    for question in (rich_caption, plain_caption):
        if len(question) > TELEGRAM_MESSAGE_LIMIT:
            continue
        try:
            await message.reply_text(question, parse_mode=ParseMode.MARKDOWN_V2)
            break
        except BadRequest:
            logger.warning("Telegram rejected question text for card %s; degrading.", card['id'], exc_info=True)
    return sent


async def _send_answer_photo(message, card, conn) -> bool:
    """Sends the card as question + spoilered screenshot of the answer,
    reusing Telegram's copy (file_id) when this answer was rendered before.
    Returns False when no image can be produced or sent, so the caller can
    fall back to the text flow."""
    cache_key = _answer_cache_key(card['answer'])

    cached_file_id = _get_cached_file_id(conn, cache_key)
    if cached_file_id:
        sent = await _try_send_photo(message, card, cached_file_id)
        if sent:
            return True
        logger.info("Cached file_id rejected for card %s; re-rendering.", card['id'])

    try:
        await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    except Exception:
        pass  # Cosmetic only; never block the card on it.

    image = await _fetch_answer_image(card['id'])
    if image is None:
        return False

    sent = await _try_send_photo(message, card, image)
    if sent is None:
        return False
    if sent.photo:
        # Largest PhotoSize is last; its file_id resends this exact photo
        # without uploading or rendering anything.
        _store_cached_file_id(conn, cache_key, sent.photo[-1].file_id, card['id'])
    return True


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
    """Welcomes the user; with a deep-link token from the settings page,
    links this chat to the web account that generated it. Receiving the
    token here proves the caller owns the chat, which self-reported chat
    IDs never did."""
    try:
        if context.args:
            auth_user_id = verify_telegram_link_token(context.args[0])
            if not auth_user_id:
                await update.message.reply_text(
                    "This link is invalid or has expired. Open Settings in the web app and tap Connect Telegram again."
                )
                return
            conn = get_db_connection()
            try:
                link_telegram_chat(conn, auth_user_id, update.message.chat_id)
            finally:
                release_db_connection(conn)
            logger.info("Linked chat_id %s via deep link.", _redact_identifier(update.message.chat_id))
            await update.message.reply_text(
                "✅ Telegram connected! Daily review reminders will arrive here. Try /random for a card."
            )
            return
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
                # Math-heavy answers are unreadable as Unicode text, so those
                # (and only those) go through the screenshot pipeline; any
                # failure there falls back to the regular text flow. Cloze
                # cards always stay text — their in-place spoiler blanks ARE
                # the interaction, and their answer field is just the hidden
                # word, so an answer screenshot would be meaningless.
                sent_as_photo = (
                    not is_cloze(card['question'])
                    and needs_screenshot(card['answer'])
                    and await _send_answer_photo(update.message, card, conn)
                )
                if not sent_as_photo:
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
