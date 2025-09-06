import psycopg2
from psycopg2 import extras
import os
from datetime import datetime, timedelta

# --- Database Configuration ---
# The application will connect to the PostgreSQL database using the DATABASE_URL environment variable.
# For local development, you can set this to a local PostgreSQL instance.
# For production on Render, this will be provided by the PostgreSQL service.
DATABASE_URL = os.environ.get("DATABASE_URL")

# This file handles all database operations

def get_db_connection():
    """Creates a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set.")
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def create_database():
    """Creates the 'cards' table in the PostgreSQL database if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create table if it doesn't exist
    # - id: Auto-incrementing integer for PostgreSQL is SERIAL
    # - due_date: Use TIMESTAMP for date and time
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id SERIAL PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            due_date TIMESTAMP NOT NULL,
            ease_factor REAL NOT NULL DEFAULT 2.5,
            interval INTEGER NOT NULL DEFAULT 1
        )
    ''')

    # Check if the table is empty before inserting sample data
    cursor.execute("SELECT COUNT(*) FROM cards")
    if cursor.fetchone()[0] == 0:
        # Add some sample cards with LaTeX
        sample_cards = [
            (
                'What is the Pythagorean theorem?',
                'For a right-angled triangle, the square of the hypotenuse is equal to the sum of the squares of the other two sides: $a^2 + b^2 = c^2
,
                datetime.now()
            ),
            (
                'What is the formula for the area of a circle?',
                'The area of a circle with radius `r` is given by the formula: $A = \pi r^2
,
                datetime.now()
            ),
            (
                'What is the integral of $ \frac{1}{x} $?',
                'The integral of $ \frac{1}{x} $ with respect to `x` is $ \ln|x| + C 
,
                datetime.now()
            )
        ]
        # Use execute_values for efficient batch inserting with psycopg2
        extras.execute_values(
            cursor,
            "INSERT INTO cards (question, answer, due_date) VALUES %s",
            [(q, a, d) for q, a, d in sample_cards]
        )

    conn.commit()
    cursor.close()
    conn.close()

if __name__ == '__main__':
    # This allows running the script directly to initialize the database
    # Make sure to set the DATABASE_URL environment variable before running.
    create_database()
    print("Database check/initialization complete.")
