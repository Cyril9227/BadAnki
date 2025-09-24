# scheduler.py
# This script checks for due cards for all users and sends notifications via Telegram.

from dotenv import load_dotenv
load_dotenv()

# --- Imports ---
import asyncio
import logging
import os
from datetime import datetime

import psycopg2
from psycopg2 import extras
from telegram import Bot

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_users_with_due_cards():
    """
    Queries the database to find users who have cards due for review.
    Returns a list of tuples: (telegram_chat_id, due_card_count).
    Includes users with 0 due cards.
    """
    if not DATABASE_URL:
        logger.error("Error: DATABASE_URL environment variable is not set.")
        return []

    conn = None
    users_with_due_cards = []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor(cursor_factory=extras.DictCursor)

        # SQL query: return all users with telegram_chat_id, count due cards (can be zero)
        query = """
            SELECT
                u.telegram_chat_id,
                COUNT(c.id) FILTER (WHERE c.due_date <= %s) AS due_cards_count
            FROM
                users u
            LEFT JOIN
                cards c ON u.id = c.user_id
            WHERE
                u.telegram_chat_id IS NOT NULL
            GROUP BY
                u.telegram_chat_id;
        """

        cursor.execute(query, (datetime.now(),))
        records = cursor.fetchall()

        for record in records:
            users_with_due_cards.append(
                (record["telegram_chat_id"], record["due_cards_count"])
            )

    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        if conn:
            conn.close()

    return users_with_due_cards


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

    for chat_id, due_count in users_to_notify:
        if due_count > 0:
            logger.info(
                f"Found {due_count} card(s) due for user with chat_id {chat_id}. Sending notification..."
            )
            review_link = f"{APP_URL}/review"
            message = (
                f"👋 You have {due_count} card(s) due for review today!\n\n"
                f"Click here to start your session: {review_link}"
            )
        else:
            logger.info(
                f"No cards due for user with chat_id {chat_id}. Sending encouragement message..."
            )
            message = (
                "🎉 No cards for review today, good job!\n\n\n"
                "Feel free to jog your memory with /random."
            )

        try:
            await bot.send_message(chat_id=chat_id, text=message)
            successful_notifications += 1
        except Exception as e:
            logger.error(f"Failed to send Telegram message to chat_id {chat_id}: {e}")
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