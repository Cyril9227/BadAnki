# restore_db.py
# This script restores cards from a local 'backup.csv' file into the remote
# PostgreSQL database. It assumes the 'cards' table already exists.

import os
import csv
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# --- Configuration ---
load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL")
BACKUP_FILE_PATH = "backup.csv"

def restore_data():
    """Connects to the remote database and inserts data from the CSV."""
    pg_conn = None

    if not DATABASE_URL:
        print("Error: DATABASE_URL is not set. Please check your .env file.")
        return

    if not os.path.exists(BACKUP_FILE_PATH):
        print(f"Error: The backup file '{BACKUP_FILE_PATH}' was not found.")
        return

    print("Starting database restore...")

    try:
        # --- Prepare the PostgreSQL connection URL with SSL ---
        parsed_url = urlparse(DATABASE_URL)
        query_params = parse_qs(parsed_url.query)
        if 'sslmode' not in query_params:
            query_params['sslmode'] = ['require']
            new_query = urlencode(query_params, doseq=True)
            final_db_url = urlunparse(parsed_url._replace(query=new_query))
        else:
            final_db_url = DATABASE_URL

        # --- Connect to the PostgreSQL database ---
        print("Connecting to remote PostgreSQL database...")
        pg_conn = psycopg2.connect(final_db_url)
        pg_cursor = pg_conn.cursor()
        print("Connection successful.")

        # --- Ask user before deleting existing data ---
        pg_cursor.execute("SELECT COUNT(*) FROM cards")
        if pg_cursor.fetchone()[0] > 0:
            print("Warning: The 'cards' table already contains data.")
            user_input = input("Do you want to wipe it before restoring? (yes/no): ").lower()
            if user_input == 'yes':
                print("Deleting all existing cards...")
                pg_cursor.execute("TRUNCATE TABLE cards RESTART IDENTITY")
            else:
                print("Restore cancelled by user.")
                return

        # --- Read cards from the CSV file ---
        with open(BACKUP_FILE_PATH, 'r', encoding='utf-8') as csvfile:
            csv_reader = csv.reader(csvfile)
            header = next(csv_reader)  # Skip header row
            
            cards_to_insert = [tuple(row) for row in csv_reader]

        if not cards_to_insert:
            print("No cards found in the backup file. Nothing to restore.")
            return
            
        print(f"Found {len(cards_to_insert)} cards to restore from '{BACKUP_FILE_PATH}'.")

        # --- Insert cards into PostgreSQL ---
        # Note: We are inserting into all columns including 'id'.
        # This requires setting the sequence value later.
        insert_query = f"INSERT INTO cards ({', '.join(header)}) VALUES %s"
        psycopg2.extras.execute_values(pg_cursor, insert_query, cards_to_insert)

        # --- Sync the primary key sequence ---
        # After inserting explicit IDs, we must update the sequence
        # so that new cards don't have conflicting IDs.
        pg_cursor.execute("SELECT setval('cards_id_seq', (SELECT MAX(id) FROM cards))")

        # --- Commit changes ---
        pg_conn.commit()
        print(f"Successfully restored {len(cards_to_insert)} cards!")

    except (psycopg2.Error, FileNotFoundError) as e:
        print(f"An error occurred: {e}")
        if pg_conn:
            pg_conn.rollback()
    finally:
        if pg_conn:
            pg_conn.close()
        print("Restore process finished.")

if __name__ == "__main__":
    restore_data()
