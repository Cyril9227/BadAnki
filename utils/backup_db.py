# backup_db.py
# This script connects to the remote PostgreSQL database and saves the contents
# of the 'cards' table to a local CSV file.

import os
import csv
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# --- Configuration ---
load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL")
BACKUP_FILE_PATH = "backup.csv"

def backup_data():
    """Connects to the remote database and dumps the 'cards' table to a CSV."""
    pg_conn = None

    if not DATABASE_URL:
        print("Error: DATABASE_URL is not set. Please check your .env file.")
        return

    print("Starting database backup...")

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

        # --- Fetch all cards from the database ---
        print("Fetching all cards from the 'cards' table...")
        pg_cursor.execute("SELECT id, question, answer, due_date, ease_factor, interval FROM cards ORDER BY id")
        cards = pg_cursor.fetchall()
        
        if not cards:
            print("No cards found in the database. Nothing to back up.")
            return

        print(f"Found {len(cards)} cards to back up.")

        # --- Write cards to a CSV file ---
        with open(BACKUP_FILE_PATH, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            
            # Write the header row
            column_names = [desc[0] for desc in pg_cursor.description]
            csv_writer.writerow(column_names)
            
            # Write the data rows
            csv_writer.writerows(cards)

        print(f"Successfully saved {len(cards)} cards to '{BACKUP_FILE_PATH}'")

    except psycopg2.Error as e:
        print(f"A database error occurred: {e}")
    finally:
        if pg_conn:
            pg_conn.close()
        print("Backup process finished.")

if __name__ == "__main__":
    backup_data()
