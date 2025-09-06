# scheduler.py
# This script checks for due cards and sends a notification to a specified Telegram chat.

import os
import psycopg2
import asyncio
from datetime import datetime
from telegram import Bot

# --- Configuration ---
# Load environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_due_cards_count():
    """Queries the database and returns the number of cards due for review."""
    if not DATABASE_URL:
        print("Error: DATABASE_URL environment variable is not set.")
        return 0
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        # Query for cards where the due_date is in the past or today
        cursor.execute("SELECT COUNT(*) FROM cards WHERE due_date <= %s", (datetime.now(),))
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return count
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return 0

async def main():
    """The main function to check cards and send a notification."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables must be set.")
        return

    due_count = get_due_cards_count()

    if due_count > 0:
        print(f"Found {due_count} card(s) due for review. Sending notification...")
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        review_link = f"{APP_URL}/review"
        message = (
            f"👋 You have {due_count} card(s) due for review today!\n\n"
            f"Click here to start your session: {review_link}"
        )
        
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
            print("Notification sent successfully.")
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")
    else:
        print("No cards due for review today.")

if __name__ == "__main__":
    # The python-telegram-bot library is asynchronous.
    # We use asyncio.run() to execute our async main function.
    asyncio.run(main())
