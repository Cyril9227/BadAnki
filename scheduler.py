# scheduler.py
# This script checks for due cards and sends a notification to a specified Telegram chat.

from dotenv import load_dotenv

load_dotenv()

import os
import psycopg2
import asyncio
from datetime import datetime
from telegram import Bot
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

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
    
    conn = None
    try:
        # --- Prepare the PostgreSQL connection URL with SSL for Render ---
        parsed_url = urlparse(DATABASE_URL)
        query_params = parse_qs(parsed_url.query)
        if 'sslmode' not in query_params:
            query_params['sslmode'] = ['require']
            new_query = urlencode(query_params, doseq=True)
            final_db_url = urlunparse(parsed_url._replace(query=new_query))
        else:
            final_db_url = DATABASE_URL

        conn = psycopg2.connect(final_db_url)
        cursor = conn.cursor()
        # Query for cards where the due_date is in the past or today
        cursor.execute("SELECT COUNT(*) FROM cards WHERE due_date <= %s", (datetime.now(),))
        count = cursor.fetchone()[0]
        return count
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return 0
    finally:
        if conn:
            conn.close()

async def run_scheduler():
    """The main function to check cards and send a notification."""
    print("Scheduler started: Checking for due cards...")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables must be set.")
        return "Missing environment variables."

    due_count = get_due_cards_count()
    message_to_return = ""

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
            result = "Notification sent successfully."
            print(result)
            message_to_return = result
        except Exception as e:
            result = f"Failed to send Telegram message: {e}"
            print(result)
            message_to_return = result
    else:
        result = "No cards due for review today."
        print(result)
        message_to_return = result
    
    print("Scheduler finished.")
    return message_to_return

async def main():
    """Runs the scheduler directly."""
    await run_scheduler()

if __name__ == "__main__":
    # The python-telegram-bot library is asynchronous.
    # We use asyncio.run() to execute our async main function.
    asyncio.run(main())
