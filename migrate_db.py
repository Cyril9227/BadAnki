# migrate_db.py
# This is a one-time script to migrate cards from the local SQLite database (anki.db)
# to the new remote PostgreSQL database on Render.

import os
import sqlite3
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# --- Configuration ---
# This script needs the DATABASE_URL for the remote PostgreSQL database.
# To avoid putting the URL in the code, we'll load it from a .env file.
load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL")
SQLITE_DB_PATH = "anki.db"

def migrate_data():
    """Connects to both databases and copies cards from SQLite to PostgreSQL."""
    pg_conn = None
    sqlite_conn = None

    if not DATABASE_URL:
        print("Error: DATABASE_URL is not set. Please create a .env file with the URL.")
        return

    if not os.path.exists(SQLITE_DB_PATH):
        print(f"Error: The local database file '{SQLITE_DB_PATH}' was not found.")
        return

    try:
        # --- Connect to the source SQLite database ---
        print(f"Connecting to local SQLite database: {SQLITE_DB_PATH}")
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        print("SQLite connection successful.")

        # --- Prepare the PostgreSQL connection URL ---
        # Render's external PostgreSQL URLs require SSL.
        # We'll ensure sslmode=require is part of the connection string.
        parsed_url = urlparse(DATABASE_URL)
        query_params = parse_qs(parsed_url.query)
        if 'sslmode' not in query_params:
            query_params['sslmode'] = ['require']
            # Rebuild the URL with the new query parameter
            new_query = urlencode(query_params, doseq=True)
            final_db_url = urlunparse(parsed_url._replace(query=new_query))
        else:
            final_db_url = DATABASE_URL

        # --- Connect to the target PostgreSQL database ---
        print("Connecting to remote PostgreSQL database...")
        pg_conn = psycopg2.connect(final_db_url)
        pg_cursor = pg_conn.cursor()
        print("PostgreSQL connection successful.")

        # --- Fetch all cards from SQLite ---
        sqlite_cursor.execute("SELECT question, answer, due_date, ease_factor, interval FROM cards")
        cards = sqlite_cursor.fetchall()
        print(f"Found {len(cards)} cards to migrate from SQLite.")

        if not cards:
            print("No cards found in the local database. Nothing to migrate.")
            return

        # --- Check if cards already exist in PostgreSQL to avoid duplicates ---
        pg_cursor.execute("SELECT COUNT(*) FROM cards")
        if pg_cursor.fetchone()[0] > 0:
            print("Warning: The PostgreSQL database already contains data.")
            user_input = input("Do you want to wipe it and continue? (yes/no): ").lower()
            if user_input == 'yes':
                print("Deleting all existing cards from PostgreSQL...")
                pg_cursor.execute("DELETE FROM cards")
            else:
                print("Migration cancelled by user.")
                return

        # --- Insert cards into PostgreSQL ---
        print("Migrating cards...")
        for card in cards:
            pg_cursor.execute(
                """
                INSERT INTO cards (question, answer, due_date, ease_factor, interval)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (card['question'], card['answer'], card['due_date'], card['ease_factor'], card['interval'])
            )

        # --- Commit changes ---
        pg_conn.commit()
        print(f"Successfully migrated {len(cards)} cards!")

    except psycopg2.OperationalError as e:
        print(f"PostgreSQL Connection Error: Could not connect to the database.")
        print(f"Details: {e}")
        print("Please check the following:")
        print("1. Is the DATABASE_URL in your .env file correct?")
        print("2. Is the database running and accessible from your network?")
        print("3. Does your database require SSL? This script attempts to add 'sslmode=require'.")
        if pg_conn:
            pg_conn.rollback()
    except (sqlite3.Error, psycopg2.Error) as e:
        print(f"A database error occurred: {e}")
        if pg_conn:
            pg_conn.rollback()
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if pg_conn:
            pg_conn.close()
        print("Migration process finished.")

if __name__ == "__main__":
    migrate_data()
