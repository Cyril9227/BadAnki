from dotenv import load_dotenv

load_dotenv()

import psycopg2
from psycopg2 import extras
import os
from datetime import datetime, timedelta

# --- Database Configuration ---
# This file handles all database operations

def get_db_connection():
    """Creates a connection to the PostgreSQL database."""
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set.")
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def create_database():
    """Creates and updates the database schema by executing the database.sql file."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Read and execute the SQL file to create/update the schema
    with open('database.sql', 'r') as f:
        cursor.execute(f.read())

    # Check if the cards table is empty before inserting sample data
    cursor.execute("SELECT COUNT(*) FROM cards")
    if cursor.fetchone()[0] == 0:
        # Add some sample cards with LaTeX
        sample_cards = [
            (
                'What is the Pythagorean theorem?',
                'For a right-angled triangle, the square of the hypotenuse is equal to the sum of the squares of the other two sides: $a^2 + b^2 = c^2'
,
                datetime.now()
            ),
            (
                'What is the formula for the area of a circle?',
                'The area of a circle with radius `r` is given by the formula: $A = \pi r^2'
,
                datetime.now()
            ),
            (
                'What is the integral of $ \frac{1}{x} $?',
                'The integral of $ \frac{1}{x} $ with respect to `x` is $ \ln|x| + C'
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
