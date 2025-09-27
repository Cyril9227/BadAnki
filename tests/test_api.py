import os
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from unittest.mock import patch

# --- Set test environment variables BEFORE importing main ---
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "testsecret"
os.environ["SCHEDULER_SECRET"] = "testsecret"
os.environ["BOT_RESTART_SECRET"] = "testsecret"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "testsecret"

# Import FastAPI app after setting env
from main import app

# --- Ephemeral Postgres Fixture ---
@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:15") as postgres:
        # Get connection URL and strip driver prefix for psycopg2
        url = postgres.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        os.environ["DATABASE_URL"] = url

        # Connect and initialize schema
        conn = psycopg2.connect(url)
        with conn.cursor() as cur:
            # Drop and recreate the public schema to ensure a clean slate
            cur.execute("DROP SCHEMA public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            conn.commit()
            # Now, run the schema creation script
            with open("database.sql") as f:
                cur.execute(f.read())
            conn.commit()
        conn.close()

        yield postgres

# --- FastAPI TestClient Fixture ---
@pytest.fixture
def client(pg_container):
    return TestClient(app)

# --- DB Connection Fixture ---
@pytest.fixture
def db_conn(pg_container):
    conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)
    yield conn
    conn.close()

# --- Test Isolation Fixture ---
@pytest.fixture(autouse=True)
def truncate_tables(db_conn):
    """Ensures all tables are empty before each test."""
    with db_conn.cursor() as cur:
        try:
            # Using TRUNCATE ... RESTART IDENTITY CASCADE is the most efficient way
            # to clean the database and reset primary key sequences.
            cur.execute("TRUNCATE TABLE cards, courses, users RESTART IDENTITY CASCADE;")
            db_conn.commit()
        except Exception as e:
            # If truncate fails (e.g., due to permissions in some environments),
            # fall back to deleting rows.
            print(f"[WARN] TRUNCATE failed: {e}. Falling back to DELETE.")
            db_conn.rollback() # Rollback the failed transaction
            cur.execute("DELETE FROM cards;")
            cur.execute("DELETE FROM courses;")
            cur.execute("DELETE FROM users;")
            db_conn.commit()
    yield

# --- Tests ---
def test_register_user_successfully(client):
    response = client.post(
        "/register",
        data={"username": "testuser123", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    # To fully test the user experience, we can manually follow the redirect
    redirect_response = client.get(response.headers["location"])
    assert redirect_response.status_code == 200
    assert "Login" in redirect_response.text

def test_register_user_duplicate_username(client):
    # First registration
    client.post(
        "/register",
        data={"username": "testuser2", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # Second registration with same username
    response = client.post(
        "/register",
        data={"username": "testuser2", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "Username already registered" in response.text

def test_register_user_short_password(client):
    response = client.post(
        "/register",
        data={"username": "testuser3", "password": "pw"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "Password must be at least 8 characters long" in response.text

def test_login_successfully(client):
    # First register a user
    client.post(
        "/register",
        data={"username": "loginuser", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # Then try to login
    response = client.post(
        "/login",
        data={"username": "loginuser", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "All Courses" in response.text
    assert len(response.history) == 1
    redirect_response = response.history[0]
    assert redirect_response.status_code == 303
    assert "access_token" in redirect_response.cookies
    assert "access_token" in client.cookies

def test_login_failed(client):
    response = client.post(
        "/login",
        data={"username": "wronguser", "password": "wrongpassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "Incorrect username or password" in response.text

def test_password_validation_missing_number(client):
    """Test that passwords without numbers are rejected."""
    response = client.post(
        "/register",
        data={"username": "testuser4", "password": "passwordonly"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "Password must contain at least one number" in response.text

def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# --- Helper Functions ---
def authenticate_client(client, username="testuser", password="password123"):
    """Registers and logs in a user, returning the authenticated client."""
    # Register the user
    client.post(
        "/register",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # Login the user
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # Assert that the login was successful and the cookie is set
    assert "access_token" in client.cookies
    return client

def get_authenticated_client(client, db_conn, username="testuser", password="password123"):
    """Helper to register and login a user, returning an authenticated client and user_id."""
    authenticate_client(client, username, password)
    cur = db_conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    user_id = user['id'] if user else None
    cur.close()
    return client, user_id

def create_test_card(db_conn, user_id, question, answer, due_date=None):
    """Helper to insert a card directly into the database."""
    if due_date is None:
        due_date = datetime.now() - timedelta(days=1) # Due yesterday
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO cards (user_id, question, answer, due_date) VALUES (%s, %s, %s, %s) RETURNING id",
        (user_id, question, answer, due_date)
    )
    card_id = cur.fetchone()['id']
    db_conn.commit()
    cur.close()
    return card_id

# --- Authentication Tests ---
def test_logout(client):
    # Register and login
    authenticate_client(client, "logoutuser", "password123")
    assert "access_token" in client.cookies

    # Logout
    logout_response = client.get("/logout")
    
    # Check redirect to home page
    assert logout_response.status_code == 200
    assert "Personal Learning App" in logout_response.text
    assert len(logout_response.history) == 1
    redirect_response = logout_response.history[0]
    assert redirect_response.status_code == 303
    assert redirect_response.headers["location"] == "/"
    
    # Check cookie is gone
    assert "access_token" not in client.cookies

# --- Course Management Tests ---
def test_get_courses_page_authenticated(client):
    auth_client = authenticate_client(client)
    response = auth_client.get("/courses")
    assert response.status_code == 200
    assert "All Courses" in response.text

def test_get_courses_page_unauthenticated(client):
    response = client.get("/courses")
    # Should redirect to /login
    assert response.status_code == 200
    assert "Login" in response.text
    assert len(response.history) == 1
    assert response.history[0].status_code == 303
    assert response.history[0].headers["location"] == "/login"

def test_get_courses_tree_empty(client):
    auth_client = authenticate_client(client, "coursetest", "password123")
    response = auth_client.get("/api/courses-tree")
    assert response.status_code == 200
    assert response.json() == []

def test_create_and_list_course_file(client):
    auth_client = authenticate_client(client, "coursetest2", "password123")
    
    # Create a file
    response_create = auth_client.post("/api/course-item", json={"path": "test.md", "type": "file"})
    assert response_create.status_code == 200
    assert response_create.json() == {"success": True}

    # Check the tree
    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    tree = response_tree.json()
    assert len(tree) == 1
    assert tree[0]["name"] == "test.md"
    assert tree[0]["path"] == "test.md"
    assert tree[0]["type"] == "file"

def test_create_and_list_course_folder(client):
    auth_client = authenticate_client(client, "coursetest3", "password123")
    
    # Create a folder
    response_create = auth_client.post("/api/course-item", json={"path": "my_folder", "type": "directory"})
    assert response_create.status_code == 200
    assert response_create.json() == {"success": True}

    # Check the tree
    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    tree = response_tree.json()
    assert len(tree) == 1
    assert tree[0]["name"] == "my_folder"
    assert tree[0]["path"] == "my_folder"
    assert tree[0]["type"] == "directory"

def test_delete_course_file(client):
    auth_client = authenticate_client(client, "coursetest4", "password123")
    auth_client.post("/api/course-item", json={"path": "test_to_delete.md", "type": "file"})

    # Delete the file
    response_delete = auth_client.request("DELETE", "/api/course-item", json={"path": "test_to_delete.md", "type": "file"})
    assert response_delete.status_code == 200
    assert response_delete.json() == {"success": True}

    # Check the tree is empty
    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    assert response_tree.json() == []

def test_delete_course_folder(client):
    auth_client = authenticate_client(client, "coursetest5", "password123")
    auth_client.post("/api/course-item", json={"path": "folder_to_delete", "type": "directory"})

    # Delete the folder
    response_delete = auth_client.request("DELETE", "/api/course-item", json={"path": "folder_to_delete", "type": "directory"})
    assert response_delete.status_code == 200
    assert response_delete.json() == {"success": True}

    # Check the tree is empty
    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    assert response_tree.json() == []

def test_save_and_get_course_content(client):
    auth_client = authenticate_client(client, "contentuser", "password123")
    
    # Create a file first
    file_path = "my_course.md"
    auth_client.post("/api/course-item", json={"path": file_path})

    # Save content to the file
    content_to_save = "This is the course content."
    response_save = auth_client.post("/api/course-content", json={"path": file_path, "content": content_to_save})
    assert response_save.status_code == 200
    assert response_save.json() == {"success": True}

    # Retrieve the content
    response_get = auth_client.get(f"/api/course-content/{file_path}")
    assert response_get.status_code == 200
    assert response_get.json() == content_to_save

# --- Card Management Tests ---
def test_get_manage_cards_page_authenticated(client):
    auth_client = authenticate_client(client, "carduser", "password123")
    response = auth_client.get("/manage")
    assert response.status_code == 200
    assert "Manage Cards" in response.text

def test_create_card(client, db_conn):
    auth_client, user_id = get_authenticated_client(client, db_conn, "cardcreator", "password123")
    response = auth_client.post(
        "/new",
        data={"question": "What is FastAPI?", "answer": "A web framework."},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    # Verify the card was created in the database
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE question = 'What is FastAPI?'")
    card = cur.fetchone()
    cur.close()
    assert card is not None
    assert card['answer'] == "A web framework."

def test_update_card(client, db_conn):
    auth_client = authenticate_client(client, "cardupdater", "password123")
    
    # Get user ID
    cur = db_conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = 'cardupdater'")
    user_id = cur.fetchone()['id']
    
    # Create a card directly
    card_id = create_test_card(db_conn, user_id, "Q1", "A1")
    
    # Update the card
    response = auth_client.post(
        f"/edit-card/{card_id}",
        data={"question": "Updated Q1", "answer": "Updated A1"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/manage"

    # Verify the update in the database
    cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cur.fetchone()
    cur.close()
    assert card['question'] == "Updated Q1"
    assert card['answer'] == "Updated A1"

def test_delete_card(client, db_conn):
    auth_client = authenticate_client(client, "carddeleter", "password123")
    
    # Get user ID
    cur = db_conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = 'carddeleter'")
    user_id = cur.fetchone()['id']
    
    # Create a card
    card_id = create_test_card(db_conn, user_id, "ToDelete", "ToDelete")
    
    # Delete the card
    response = auth_client.post(f"/delete/{card_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/manage"

    # Verify it's deleted
    cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cur.fetchone()
    cur.close()
    assert card is None

# --- Review Tests ---
def test_get_review_page_with_due_card(client, db_conn):
    auth_client = authenticate_client(client, "reviewuser", "password123")
    
    # Get user ID
    cur = db_conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = 'reviewuser'")
    user_id = cur.fetchone()['id']
    cur.close()
    
    # Create a due card
    create_test_card(db_conn, user_id, "Review Q", "Review A")
    
    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "Review Q" in response.text

def test_get_review_page_no_due_cards(client):
    auth_client = authenticate_client(client, "reviewuser2", "password123")
    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "All Done!" in response.text

def test_update_review_status(client, db_conn):
    auth_client = authenticate_client(client, "reviewuser3", "password123")
    
    # Get user ID
    cur = db_conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = 'reviewuser3'")
    user_id = cur.fetchone()['id']
    
    # Create a due card
    card_id = create_test_card(db_conn, user_id, "Q", "A")
    
    # Mark as remembered
    response = auth_client.post(
        f"/review/{card_id}",
        data={"status": "remembered"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/review"

    # Verify the due date has been updated
    cur.execute("SELECT due_date FROM cards WHERE id = %s", (card_id,))
    new_due_date = cur.fetchone()['due_date']
    cur.close()
    # Verify the due date has been updated to the future
    # We check against now() - 1 second to avoid race conditions in the test runner
    assert new_due_date > datetime.now() - timedelta(seconds=1)

# --- AI Card Generation Tests ---
@patch("main.generate_cards")
def test_generate_cards_api_success(mock_generate_cards, client):
    mock_generate_cards.return_value = [{"question": "Q", "answer": "A"}]
    auth_client = authenticate_client(client, "ai_user", "password123")
    response = auth_client.post("/api/generate-cards", json={"content": "Some text"})
    assert response.status_code == 200
    assert response.json() == {"cards": [{"question": "Q", "answer": "A"}]}
    mock_generate_cards.assert_called_once()

def test_generate_cards_api_empty_content(client):
    auth_client = authenticate_client(client, "ai_user_empty", "password123")
    response = auth_client.post("/api/generate-cards", json={"content": " "})
    assert response.status_code == 400

def test_save_generated_cards(client, db_conn):
    auth_client = authenticate_client(client, "ai_saver", "password123")
    cards_to_save = {"cards": [{"question": "GenQ1", "answer": "GenA1"}]}
    response = auth_client.post("/api/save-cards", json=cards_to_save)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify in DB
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE question = 'GenQ1'")
    card = cur.fetchone()
    cur.close()
    assert card is not None
    assert card['answer'] == "GenA1"

# --- Secrets & API Keys Tests ---
def test_save_api_keys(client, db_conn):
    auth_client = authenticate_client(client, "api_key_user", "password123")
    keys = {"gemini_api_key": "gemini_key", "anthropic_api_key": "anthropic_key"}
    response = auth_client.post("/api/save-api-keys", json=keys)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify in DB
    cur = db_conn.cursor()
    cur.execute("SELECT gemini_api_key, anthropic_api_key FROM users WHERE username = 'api_key_user'")
    user_keys = cur.fetchone()
    cur.close()
    assert user_keys['gemini_api_key'] == "gemini_key"
    assert user_keys['anthropic_api_key'] == "anthropic_key"

def test_save_secrets(client, db_conn):
    auth_client = authenticate_client(client, "secrets_user", "password123")
    
    # Need to get a CSRF token first
    response = auth_client.get("/secrets")
    assert response.status_code == 200
    
    # A bit of a hack to get the token from the HTML for the test
    csrf_token = response.text.split('name="csrf_token" value="')[1].split('"')[0]
    
    secrets_data = {"telegram_chat_id": "12345"}
    headers = {"X-CSRF-Token": csrf_token}
    
    response = auth_client.post("/secrets", data=secrets_data, headers=headers)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify in DB
    cur = db_conn.cursor()
    cur.execute("SELECT telegram_chat_id FROM users WHERE username = 'secrets_user'")
    user_secrets = cur.fetchone()
    cur.close()
    assert user_secrets['telegram_chat_id'] == "12345"