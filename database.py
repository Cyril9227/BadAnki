from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2 import pool
import os
from datetime import datetime, timedelta


# --- Database Configuration ---
# This file handles all database operations

DATABASE_URL = os.environ.get("DATABASE_URL")


if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set.")


db_pool = psycopg2.pool.SimpleConnectionPool(1, 20, dsn=DATABASE_URL)

def get_db_connection():
    return db_pool.getconn()

def release_db_connection(conn):
    """Releases a connection back to the pool."""
    db_pool.putconn(conn)

def create_database():
    """Creates and updates the database schema by executing the database.sql file."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Read and execute the SQL file to create/update the schema
    with open('database.sql', 'r') as f:
        sql_script = f.read()
        cursor.execute(sql_script)

    # Do not insert sample data in production
    if os.environ.get("ENVIRONMENT") != "production":
        # Check if the cards table is empty before inserting sample data
        cursor.execute("SELECT COUNT(*) FROM cards WHERE user_id IS NULL")
        if cursor.fetchone()[0] == 0:
            # Add a sample card with LaTeX
            sample_cards = [
                (
                    'What is the Pythagorean theorem?',
                    'For a right-angled triangle, the square of the hypotenuse is equal to the sum of the squares of the other two sides: $a^2 + b^2 = c^2',
                    datetime.now()
                ),
            ]
            from psycopg2 import extras
            extras.execute_values(
                cursor,
                "INSERT INTO cards (question, answer, due_date) VALUES %s",
                [(q, a, d) for q, a, d in sample_cards]
            )

    conn.commit()
    cursor.close()
    release_db_connection(conn)

if __name__ == '__main__':
    # This allows running the script directly to initialize the database
    # Make sure to set the DATABASE_URL environment variable before running.
    create_database()
    print("Database check/initialization complete.")