import os
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid

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
            # Create the 'auth' schema and a dummy 'users' table for FK dependencies
            cur.execute("CREATE SCHEMA auth;")
            cur.execute("""
                CREATE TABLE auth.users (
                    id UUID PRIMARY KEY,
                    email VARCHAR(255) UNIQUE
                );
            """)
            conn.commit()
            # Now, run the application's schema creation script
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
            cur.execute("TRUNCATE TABLE cards, courses, profiles RESTART IDENTITY CASCADE;")
            db_conn.commit()
        except Exception as e:
            # If truncate fails (e.g., due to permissions in some environments),
            # fall back to deleting rows.
            print(f"[WARN] TRUNCATE failed: {e}. Falling back to DELETE.")
            db_conn.rollback() # Rollback the failed transaction
            cur.execute("DELETE FROM cards;")
            cur.execute("DELETE FROM courses;")
            cur.execute("DELETE FROM profiles;")
            db_conn.commit()
    yield

# --- Tests ---
@patch("main.supabase.auth.sign_up")
@patch("main.supabase.auth.sign_in_with_password")
def test_register_user_successfully(mock_sign_in, mock_sign_up, client, db_conn):
    # Mock Supabase responses
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.email = "testuser123@example.com"

    # The user needs to exist in auth.users for the profile creation to succeed
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", (str(mock_user.id), mock_user.email))
        db_conn.commit()
    
    mock_session = MagicMock()
    mock_session.access_token = "fake-token"
    
    mock_sign_up.return_value = MagicMock(user=mock_user)
    mock_sign_in.return_value = MagicMock(user=mock_user, session=mock_session)

    response = client.post(
        "/register",
        data={"email": "testuser123@example.com", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    
    assert response.status_code == 303
    assert response.headers["location"] == "/courses"
    mock_sign_up.assert_called_once()
    mock_sign_in.assert_called_once()

@patch("main.supabase.auth.sign_up")
def test_register_user_duplicate_username(mock_sign_up, client):
    # Simulate Supabase returning no user on sign_up, which indicates a duplicate
    mock_sign_up.return_value = MagicMock(user=None)
    
    response = client.post(
        "/register",
        data={"email": "testuser2@example.com", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "Email already registered or invalid." in response.text

def test_register_user_short_password(client):
    response = client.post(
        "/register",
        data={"email": "testuser3@example.com", "password": "pw"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "Password must be at least 8 characters long" in response.text

@patch("main.supabase.auth.sign_in_with_password")
def test_login_successfully(mock_sign_in, client, db_conn):
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.email = "loginuser@example.com"

    # The user needs to exist in auth.users for the profile creation to succeed
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", (str(mock_user.id), mock_user.email))
        db_conn.commit()
    
    mock_session = MagicMock()
    mock_session.access_token = "fake-token"
    
    mock_sign_in.return_value = MagicMock(user=mock_user, session=mock_session)

    response = client.post(
        "/login",
        data={"email": "loginuser@example.com", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/courses"
    assert "access_token" in response.cookies

@patch("main.supabase.auth.sign_in_with_password")
def test_login_failed(mock_sign_in, client):
    # Simulate Supabase raising an exception on failed login
    mock_sign_in.side_effect = Exception("Invalid login credentials")
    
    response = client.post(
        "/login",
        data={"email": "wronguser@example.com", "password": "wrongpassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "Invalid email or password" in response.text

def test_password_validation_missing_number(client):
    """Test that passwords without numbers are rejected."""
    response = client.post(
        "/register",
        data={"email": "testuser4@example.com", "password": "passwordonly"},
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
def create_test_user(db_conn, email="testuser@example.com"):
    """Creates a user in the mock Supabase auth table and a corresponding profile."""
    auth_user_id = uuid.uuid4()
    with db_conn.cursor() as cur:
        # Cast UUID to string for psycopg2
        cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", (str(auth_user_id), email))
        cur.execute(
            "INSERT INTO profiles (auth_user_id, username) VALUES (%s, %s)",
            (str(auth_user_id), email)
        )
        db_conn.commit()
    return auth_user_id

def authenticate_client(mock_get_user, client, db_conn, email="testuser@example.com"):
    """Sets up a mock authenticated user and configures the client."""
    auth_user_id = create_test_user(db_conn, email=email)
    
    mock_user = MagicMock()
    mock_user.id = auth_user_id
    mock_user.email = email
    mock_get_user.return_value = MagicMock(user=mock_user)
    
    # Set a dummy access token cookie for the client
    client.cookies.set("access_token", "fake-test-token")
    return client, auth_user_id



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

@patch("main.supabase.auth.sign_out")
@patch("main.supabase.auth.get_user")
def test_logout(mock_get_user, mock_sign_out, client, db_conn):
    # Mock authenticated user
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="logoutuser@example.com")
    assert "access_token" in auth_client.cookies

    # Logout
    response = auth_client.get("/logout", follow_redirects=False)
    
    # Check redirect to login page
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    
    # Check that the 'set-cookie' header is correctly formatted to delete the cookie
    set_cookie_header = response.headers.get("set-cookie")
    assert set_cookie_header is not None
    assert "access_token=;" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header
    
    mock_sign_out.assert_called_once()

# --- Course Management Tests ---
@patch("main.supabase.auth.get_user")
def test_get_courses_page_authenticated(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn)
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

@patch("main.supabase.auth.get_user")
def test_get_courses_tree_empty(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="coursetest@example.com")
    response = auth_client.get("/api/courses-tree")
    assert response.status_code == 200
    assert response.json() == []

@patch("main.supabase.auth.get_user")
def test_create_and_list_course_file(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="coursetest2@example.com")
    
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

@patch("main.supabase.auth.get_user")
def test_create_and_list_course_folder(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="coursetest3@example.com")
    
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

@patch("main.supabase.auth.get_user")
def test_delete_course_file(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="coursetest4@example.com")
    auth_client.post("/api/course-item", json={"path": "test_to_delete.md", "type": "file"})

    # Delete the file
    response_delete = auth_client.request("DELETE", "/api/course-item", json={"path": "test_to_delete.md", "type": "file"})
    assert response_delete.status_code == 200
    assert response_delete.json() == {"success": True}

    # Check the tree is empty
    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    assert response_tree.json() == []

@patch("main.supabase.auth.get_user")
def test_delete_course_folder(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="coursetest5@example.com")
    auth_client.post("/api/course-item", json={"path": "folder_to_delete", "type": "directory"})

    # Delete the folder
    response_delete = auth_client.request("DELETE", "/api/course-item", json={"path": "folder_to_delete", "type": "directory"})
    assert response_delete.status_code == 200
    assert response_delete.json() == {"success": True}

    # Check the tree is empty
    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    assert response_tree.json() == []

@patch("main.supabase.auth.get_user")
def test_save_and_get_course_content(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="contentuser@example.com")
    
    # Create a file first
    file_path = "my_course.md"
    auth_client.post("/api/course-item", json={"path": file_path, "type": "file"})

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
@patch("main.supabase.auth.get_user")
def test_get_manage_cards_page_authenticated(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="carduser@example.com")
    response = auth_client.get("/manage")
    assert response.status_code == 200
    assert "Manage Cards" in response.text

@patch("main.supabase.auth.get_user")
def test_create_card(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="cardcreator@example.com")
    
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

@patch("main.supabase.auth.get_user")
def test_update_card(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="cardupdater@example.com")
    
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
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cur.fetchone()
    cur.close()
    assert card['question'] == "Updated Q1"
    assert card['answer'] == "Updated A1"

@patch("main.supabase.auth.get_user")
def test_delete_card(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="carddeleter@example.com")
    
    # Create a card
    card_id = create_test_card(db_conn, user_id, "ToDelete", "ToDelete")
    
    # Delete the card
    response = auth_client.post(f"/delete/{card_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/manage"

    # Verify it's deleted
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cur.fetchone()
    cur.close()
    assert card is None

# --- Review Tests ---
@patch("main.supabase.auth.get_user")
def test_get_review_page_with_due_card(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="reviewuser@example.com")
    
    # Create a due card
    create_test_card(db_conn, user_id, "Review Q", "Review A")
    
    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "Review Q" in response.text

@patch("main.supabase.auth.get_user")
def test_get_review_page_no_due_cards(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="reviewuser2@example.com")
    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "All Done!" in response.text

@patch("main.supabase.auth.get_user")
def test_update_review_status(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="reviewuser3@example.com")
    
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
    cur = db_conn.cursor()
    cur.execute("SELECT due_date FROM cards WHERE id = %s", (card_id,))
    new_due_date = cur.fetchone()['due_date']
    cur.close()
    # Verify the due date has been updated to the future
    # We check against now() - 1 second to avoid race conditions in the test runner
    assert new_due_date > datetime.now() - timedelta(seconds=1)

# --- AI Card Generation Tests ---
@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_api_success(mock_generate_cards, mock_get_user, client, db_conn):
    mock_generate_cards.return_value = [{"question": "Q", "answer": "A"}]
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="ai_user@example.com")
    response = auth_client.post("/api/generate-cards", json={"content": "Some text"})
    assert response.status_code == 200
    assert response.json() == {"cards": [{"question": "Q", "answer": "A"}]}
    mock_generate_cards.assert_called_once()

@patch("main.supabase.auth.get_user")
def test_generate_cards_api_empty_content(mock_get_user, client, db_conn):
    auth_client, _ = authenticate_client(mock_get_user, client, db_conn, email="ai_user_empty@example.com")
    response = auth_client.post("/api/generate-cards", json={"content": " "})
    assert response.status_code == 400

@patch("main.supabase.auth.get_user")
def test_save_generated_cards(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="ai_saver@example.com")
    cards_to_save = {"cards": [{"question": "GenQ1", "answer": "GenA1"}]}
    response = auth_client.post("/api/save-cards", json=cards_to_save)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify in DB
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE question = 'GenQ1' AND user_id = %s", (user_id,))
    card = cur.fetchone()
    cur.close()
    assert card is not None
    assert card['answer'] == "GenA1"

# --- Secrets & API Keys Tests ---
@patch("main.supabase.auth.get_user")
def test_save_api_keys(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="api_key_user@example.com")
    keys = {"gemini_api_key": "gemini_key", "anthropic_api_key": "anthropic_key"}
    response = auth_client.post("/api/save-api-keys", json=keys)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify in DB
    cur = db_conn.cursor()
    cur.execute("SELECT gemini_api_key, anthropic_api_key FROM profiles WHERE auth_user_id = %s", (user_id,))
    user_keys = cur.fetchone()
    cur.close()
    assert user_keys['gemini_api_key'] == "gemini_key"
    assert user_keys['anthropic_api_key'] == "anthropic_key"

@patch("main.supabase.auth.get_user")
def test_save_secrets(mock_get_user, client, db_conn):
    auth_client, user_id = authenticate_client(mock_get_user, client, db_conn, email="secrets_user@example.com")
    
    # CSRF token is required for this endpoint
    # We can generate one using the helper function from main
    from main import generate_csrf_token
    csrf_token = generate_csrf_token("secrets_user@example.com") # Session ID can be username for tests
    
    secrets_data = {"telegram_chat_id": "12345"}
    
    response = auth_client.post(
        "/secrets", 
        data=secrets_data, # Use data for form submission
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify in DB
    cur = db_conn.cursor()
    cur.execute("SELECT telegram_chat_id FROM profiles WHERE auth_user_id = %s", (user_id,))
    user_secrets = cur.fetchone()
    cur.close()
    assert user_secrets['telegram_chat_id'] == "12345"

# --- Scheduler Tests ---
@patch("main._ensure_webhook")
@patch("main.run_scheduler")
def test_trigger_scheduler_success(mock_run_scheduler, mock_ensure_webhook, client):
    """Test the scheduler endpoint triggers successfully."""
    mock_ensure_webhook.return_value = {"status": "already correct", "url": "https://example.com"}
    mock_run_scheduler.return_value = {"users_notified": 1}
    
    response = client.get(f"/api/trigger-scheduler?secret={os.environ.get('SCHEDULER_SECRET')}")
    
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "completed"
    assert json_response["result"] == {"users_notified": 1}
    assert json_response["webhook_status"]["status"] == "already correct"
    
    mock_ensure_webhook.assert_called_once()
    mock_run_scheduler.assert_called_once()

def test_trigger_scheduler_invalid_secret(client):
    """Test the scheduler endpoint with an invalid secret."""
    response = client.get("/api/trigger-scheduler?secret=wrongsecret")
    assert response.status_code == 403