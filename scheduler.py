# scheduler.py
# This script checks for due cards for all users and sends notifications via Telegram.

from dotenv import load_dotenv
load_dotenv()

# --- Imports ---
import asyncio
import logging
import os
from datetime import datetime

from psycopg2 import extras
from telegram import Bot

import crud
from database import get_db_connection, release_db_connection

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")


def _redact_identifier(value) -> str:
    text = str(value)
    if len(text) <= 4:
        return "***"
    return f"***{text[-4:]}"


def get_users_with_due_cards():
    """
    Queries the database to find users who have cards due for review.
    Returns a list of tuples: (telegram_chat_id, due_card_count, streak).
    Includes users with 0 due cards. `streak` is the crud streak dict, or
    None when activity tracking is unavailable.
    """
    query = """
        SELECT
            p.auth_user_id,
            p.telegram_chat_id,
            COUNT(c.id) FILTER (WHERE c.due_date <= %s) AS due_cards_count
        FROM
            profiles p
        LEFT JOIN
            cards c ON p.auth_user_id = c.user_id
        WHERE
            p.telegram_chat_id IS NOT NULL
        GROUP BY
            p.auth_user_id, p.telegram_chat_id;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            cursor.execute(query, (datetime.now(),))
            rows = cursor.fetchall()
            return [
                (
                    r["telegram_chat_id"],
                    r["due_cards_count"],
                    crud.get_review_streak_for_user(conn, r["auth_user_id"]),
                )
                for r in rows
            ]
    except Exception as e:
        logger.error(f"Database error: {e}")
        return []
    finally:
        if conn:
            release_db_connection(conn)


async def run_scheduler():
    """
    Checks for users with due cards and sends them a notification.
    """
    logger.info("Scheduler started: Checking for due cards for all users...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Error: TELEGRAM_BOT_TOKEN environment variable must be set.")
        return "Missing TELEGRAM_BOT_TOKEN environment variable."

    users_to_notify = get_users_with_due_cards()

    if not users_to_notify:
        result = "No users found with telegram_chat_id."
        logger.info(result)
        return result

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    successful_notifications = 0
    failed_notifications = 0

    for chat_id, due_count, streak in users_to_notify:
        redacted_chat_id = _redact_identifier(chat_id)
        if due_count > 0:
            logger.info(
                f"Found {due_count} card(s) due for chat_id {redacted_chat_id}. Sending notification..."
            )
            review_link = f"{APP_URL}/review"
            # A streak at stake is the strongest nudge there is.
            streak_line = ""
            if streak and streak["current"] and not streak["reviewed_today"]:
                streak_line = (
                    f"🔥 Your {streak['current']}-day streak is on the line — "
                    "review today to keep it alive!\n\n"
                )
            message = (
                f"{streak_line}"
                f"👋 You have {due_count} card(s) due for review today!\n\n"
                f"Click here to start your session: {review_link}"
            )
        else:
            logger.info(
                f"No cards due for chat_id {redacted_chat_id}. Sending encouragement message..."
            )
            message = (
                "🎉 No cards for review today, good job!\n\n\n"
                "Feel free to jog your memory with /random."
            )

        try:
            await bot.send_message(chat_id=chat_id, text=message)
            successful_notifications += 1
        except Exception as e:
            logger.error(f"Failed to send Telegram message to chat_id {redacted_chat_id}: {e}")
            failed_notifications += 1

    result = (
        f"Scheduler finished. Sent {successful_notifications} notifications. "
        f"Failed for {failed_notifications} users."
    )
    logger.info(result)
    return result


async def main():
    """Runs the scheduler directly."""
    await run_scheduler()


if __name__ == "__main__":
    asyncio.run(main())
