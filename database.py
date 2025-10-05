import os
import psycopg2.pool
from psycopg2.extensions import connection
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# --- Database Connection Pool ---
# We use a connection pool to manage database connections efficiently.
# The pool is initialized lazily to avoid connection issues during app startup
# or in test environments where the DATABASE_URL might not be immediately available.

db_pool = None

def get_db_pool():
    """Initializes and returns the database connection pool."""
    global db_pool
    if db_pool is None:
        DATABASE_URL = os.environ.get("DATABASE_URL")
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is not set.")
        
        # In a test environment, we might need a smaller pool
        min_conn = 1 if os.environ.get("ENVIRONMENT") == "test" else 5
        max_conn = 2 if os.environ.get("ENVIRONMENT") == "test" else 20
        
        db_pool = psycopg2.pool.SimpleConnectionPool(
            min_conn, 
            max_conn, 
            dsn=DATABASE_URL
        )
    return db_pool

def get_db_connection() -> connection:
    """Gets a connection from the pool."""
    return get_db_pool().getconn()

def release_db_connection(conn: connection):
    """Releases a connection back to the pool."""
    get_db_pool().putconn(conn)

def close_db_pool():
    """Closes all connections in the pool."""
    global db_pool
    if db_pool:
        db_pool.closeall()
        db_pool = None
        print("Database connection pool closed.")

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