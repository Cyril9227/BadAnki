import sqlite3
import os
from datetime import datetime, timedelta

# --- Database Configuration ---
# On Render, the database is stored on a persistent disk.
# We check for an environment variable to determine the path.
DB_PATH = os.path.join(os.environ.get("RENDER_DISK_MOUNT_PATH", "."), "anki.db")

# This file handles all database operations

def get_db_connection():
    """Creates a connection to the SQLite database."""
    # Ensure the directory for the database exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    return conn

def create_database():
    """Creates the 'cards' table if it doesn't exist and inserts sample data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create table if it doesn't exist
    # - question: The front of the card (can contain LaTeX)
    # - answer: The back of the card (can contain LaTeX)
    # - due_date: The next time the card should be reviewed
    # - ease_factor: A multiplier for the next review interval
    # - interval: The time in days until the next review
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT- NULL,
            due_date DATETIME NOT NULL,
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
                'For a right-angled triangle, the square of the hypotenuse is equal to the sum of the squares of the other two sides: $a^2 + b^2 = c^2$',
                datetime.now()
            ),
            (
                'What is the formula for the area of a circle?',
                'The area of a circle with radius `r` is given by the formula: $A = \pi r^2$',
                datetime.now()
            ),
            (
                'What is the integral of $ \frac{1}{x} $?',
                'The integral of $ \frac{1}{x} $ with respect to `x` is $ \ln|x| + C $',
                datetime.now()
            )
        ]
        cursor.executemany(
            "INSERT INTO cards (question, answer, due_date) VALUES (?, ?, ?)",
            sample_cards
        )
        print("Database created and sample cards inserted.")
    else:
        print("Database already exists.")


    conn.commit()
    conn.close()

if __name__ == '__main__':
    # This allows running the script directly to initialize the database
    create_database()
