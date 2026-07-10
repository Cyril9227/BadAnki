import os
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid
from supabase_auth.errors import AuthApiError

# --- Set test environment variables BEFORE importing main ---
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "testsecret"
os.environ["SCHEDULER_SECRET"] = "testsecret"
os.environ["BOT_RESTART_SECRET"] = "testsecret"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "testsecret"

# Import FastAPI app after setting env
from main import app
import crud

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
            cur.execute("TRUNCATE TABLE cards, courses, profiles, folders, review_activity RESTART IDENTITY CASCADE;")
            db_conn.commit()
        except Exception as e:
            # If truncate fails (e.g., due to permissions in some environments),
            # fall back to deleting rows.
            print(f"[WARN] TRUNCATE failed: {e}. Falling back to DELETE.")
            db_conn.rollback() # Rollback the failed transaction
            cur.execute("DELETE FROM cards;")
            cur.execute("DELETE FROM courses;")
            cur.execute("DELETE FROM profiles;")
            cur.execute("DELETE FROM folders;")
            cur.execute("DELETE FROM review_activity;")
            db_conn.commit()
    yield

# --- Helper Functions ---
def get_csrf_token(client):
    """Make a GET request to a page that sets the CSRF token and return the token."""
    client.get("/")  # Any GET request will set the cookie
    return client.cookies.get("csrf_token")

def create_test_user(db_conn, email="testuser@example.com"):
    """Creates a user in the mock Supabase auth table and a corresponding profile."""
    auth_user_id = uuid.uuid4()
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", (str(auth_user_id), email))
        cur.execute(
            "INSERT INTO profiles (auth_user_id, username) VALUES (%s, %s)",
            (str(auth_user_id), email)
        )
        db_conn.commit()
    return auth_user_id

def authenticate_client(mock_get_user, client, db_conn, email="testuser@example.com"):
    """Sets up a mock authenticated user and configures the client.

    Note: The mock_get_user parameter should be provided by the test function's
    @patch("main.supabase.auth.get_user") decorator.
    """
    auth_user_id = create_test_user(db_conn, email=email)

    mock_user = MagicMock()
    mock_user.id = str(auth_user_id)  # Ensure it's a string for consistency
    mock_user.email = email
    mock_get_user.return_value = MagicMock(user=mock_user)

    client.cookies.set("access_token", "fake-test-token")

    # Also fetch a CSRF token for the authenticated session
    csrf_token = get_csrf_token(client)

    return client, str(auth_user_id), csrf_token

# --- Tests ---
@patch("main.supabase.auth.sign_in_with_password")
def test_auth_login_successfully(mock_sign_in, client, db_conn):
    email = "loginuser@example.com"
    csrf_token = get_csrf_token(client)

    # Mock Supabase responses
    mock_auth_user = MagicMock()
    mock_auth_user.id = uuid.uuid4()
    mock_auth_user.email = email

    mock_session = MagicMock()
    mock_session.access_token = "fake-token"
    mock_sign_in.return_value = MagicMock(user=mock_auth_user, session=mock_session)

    response = client.post(
        "/auth",
        data={"email": email, "password": "password123", "action": "login"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["success"] is True
    assert json_response["redirect_url"] == "/"
    assert "access_token" in response.cookies

@patch("main.supabase.auth.sign_in_with_password")
def test_auth_login_incorrect_password(mock_sign_in, client):
    email = "loginuser@example.com"
    csrf_token = get_csrf_token(client)

    mock_sign_in.side_effect = AuthApiError("Invalid login credentials", 400, "invalid_credentials")

    response = client.post(
        "/auth",
        data={"email": email, "password": "wrongpassword", "action": "login"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["success"] is False
    assert "Invalid email or password" in json_response["error"]
    assert json_response["prompt_register"] is True

@patch("main.supabase.auth.sign_in_with_password")
def test_auth_login_user_not_found_prompts_register(mock_sign_in, client):
    csrf_token = get_csrf_token(client)
    # Supabase returns "Invalid login credentials" for non-existent users too
    mock_sign_in.side_effect = AuthApiError("Invalid login credentials", 400, "invalid_credentials")

    response = client.post(
        "/auth",
        data={"email": "nonexistent@example.com", "password": "password123", "action": "login"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["success"] is False
    assert json_response["prompt_register"] is True
    assert "Invalid email or password" in json_response["error"]

@patch("main.supabase.auth.sign_up")
@patch("main.supabase.auth.sign_in_with_password")
def test_auth_register_successfully(mock_sign_in, mock_sign_up, client, db_conn):
    email = "newuser@example.com"
    csrf_token = get_csrf_token(client)

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.email = email
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", (str(mock_user.id), email))
        db_conn.commit()

    mock_session = MagicMock()
    mock_session.access_token = "fake-token"
    mock_sign_up.return_value = MagicMock(user=mock_user)
    mock_sign_in.return_value = MagicMock(user=mock_user, session=mock_session)

    response = client.post(
        "/auth",
        data={"email": email, "password": "password123", "action": "register"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["success"] is True
    assert json_response["redirect_url"] == "/"
    assert "access_token" in response.cookies
    mock_sign_up.assert_called_once()
    mock_sign_in.assert_called_once()

@patch("main.supabase.auth.sign_up")
def test_auth_register_existing_email_flags_account_exists(mock_sign_up, client):
    """The page uses account_exists to drop its register intent and fall back
    to treating the next submit as a login attempt."""
    csrf_token = get_csrf_token(client)
    mock_sign_up.side_effect = AuthApiError("User already registered", 422, "user_already_exists")

    response = client.post(
        "/auth",
        data={"email": "existing@example.com", "password": "password123", "action": "register"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["success"] is False
    assert json_response["account_exists"] is True
    assert "already exists" in json_response["error"]

def test_get_auth_page(client):
    """Test that the new unified auth page loads correctly."""
    response = client.get("/auth")
    assert response.status_code == 200
    assert "Continue with Google" in response.text
    assert "csrf_token" in response.cookies

def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}



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

@patch("main._sign_out_sync")
@patch("main.supabase.auth.get_user")
def test_logout(mock_get_user, mock_sign_out, client, db_conn):
    # Mock authenticated user
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="logoutuser@example.com")
    assert "access_token" in auth_client.cookies

    # Logout
    response = auth_client.get("/logout", follow_redirects=False)
    
    # Check redirect to login page
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    
    # Check that the 'set-cookie' header is correctly formatted to delete the cookie
    set_cookie_header = response.headers.get("set-cookie")
    assert set_cookie_header is not None
    assert "access_token=\"\";" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header
    
    mock_sign_out.assert_called_once()

# --- Course Management Tests ---
@patch("main.supabase.auth.get_user")
def test_get_courses_page_authenticated(mock_get_user, client, db_conn):
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn)
    response = auth_client.get("/courses")
    assert response.status_code == 200
    assert "All Courses" in response.text

def test_get_courses_page_unauthenticated(client):
    response = client.get("/courses", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth"

@patch("main.supabase.auth.get_user")
def test_get_courses_tree_empty(mock_get_user, client, db_conn):
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn, email="coursetest@example.com")
    response = auth_client.get("/api/courses-tree")
    assert response.status_code == 200
    assert response.json() == []

@patch("main.supabase.auth.get_user")
def test_create_and_list_course_file(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="coursetest2@example.com")
    
    response_create = auth_client.post(
        "/api/course-item", 
        json={"path": "test.md", "type": "file"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response_create.status_code == 200
    assert response_create.json() == {"success": True}

    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    tree = response_tree.json()
    assert len(tree) == 1
    assert tree[0]["name"] == "test.md"

@patch("main.supabase.auth.get_user")
def test_delete_course_file(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="coursetest4@example.com")
    auth_client.post("/api/course-item", json={"path": "test_to_delete.md", "type": "file"}, headers={"X-CSRF-Token": csrf_token})

    response_delete = auth_client.request(
        "DELETE", 
        "/api/course-item", 
        json={"path": "test_to_delete.md", "type": "file"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response_delete.status_code == 200
    assert response_delete.json() == {"success": True}

    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    assert response_tree.json() == []

@patch("main.supabase.auth.get_user")
def test_save_and_get_course_content(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="contentuser@example.com")
    
    file_path = "my_course.md"
    auth_client.post("/api/course-item", json={"path": file_path, "type": "file"}, headers={"X-CSRF-Token": csrf_token})

    content_to_save = "This is the course content."
    response_save = auth_client.post(
        "/api/course-content", 
        json={"path": file_path, "content": content_to_save},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response_save.status_code == 200
    assert response_save.json() == {"success": True}

    response_get = auth_client.get(f"/api/course-content/{file_path}")
    assert response_get.status_code == 200
    assert response_get.json() == content_to_save

# --- Folder Tests ---
@patch("main.supabase.auth.get_user")
def test_empty_folder_lifecycle(mock_get_user, client, db_conn):
    """Creating an empty folder shows it in the tree; deleting removes it."""
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="folderuser@example.com")

    auth_client.post("/api/course-item", json={"path": "empty_folder", "type": "folder"}, headers={"X-CSRF-Token": csrf_token})
    tree = auth_client.get("/api/courses-tree").json()
    assert tree == [{"name": "empty_folder", "path": "empty_folder", "type": "directory", "depth": 0, "children": []}]

    auth_client.request("DELETE", "/api/course-item", json={"path": "empty_folder", "type": "folder"}, headers={"X-CSRF-Token": csrf_token})
    assert auth_client.get("/api/courses-tree").json() == []

@patch("main.supabase.auth.get_user")
def test_rename_course_file(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="renamefile@example.com")
    auth_client.post("/api/course-content", json={"path": "old.md", "content": "hello"}, headers={"X-CSRF-Token": csrf_token})

    response = auth_client.post(
        "/api/course-item/rename",
        json={"path": "old.md", "new_path": "sub/new.md", "type": "file"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    assert auth_client.get("/api/course-content/sub/new.md").json() == "hello"
    assert auth_client.get("/api/course-content/old.md").status_code == 404

@patch("main.supabase.auth.get_user")
def test_rename_folder_moves_contents(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="renamefolder@example.com")
    auth_client.post("/api/course-content", json={"path": "olddir/a.md", "content": "A"}, headers={"X-CSRF-Token": csrf_token})
    auth_client.post("/api/course-content", json={"path": "olddir/deep/b.md", "content": "B"}, headers={"X-CSRF-Token": csrf_token})

    response = auth_client.post(
        "/api/course-item/rename",
        json={"path": "olddir", "new_path": "newdir", "type": "folder"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    assert auth_client.get("/api/course-content/newdir/a.md").json() == "A"
    assert auth_client.get("/api/course-content/newdir/deep/b.md").json() == "B"
    assert auth_client.get("/api/course-content/olddir/a.md").status_code == 404

    # Guard rails: no moving a folder into itself, destination conflicts 409.
    assert auth_client.post(
        "/api/course-item/rename",
        json={"path": "newdir", "new_path": "newdir/inner", "type": "folder"},
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 400
    auth_client.post("/api/course-content", json={"path": "newdir/a2.md", "content": "A2"}, headers={"X-CSRF-Token": csrf_token})
    assert auth_client.post(
        "/api/course-item/rename",
        json={"path": "newdir/a2.md", "new_path": "newdir/a.md", "type": "file"},
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 409

# --- Card Management Tests ---
@patch("main.supabase.auth.get_user")
def test_get_manage_cards_page_authenticated(mock_get_user, client, db_conn):
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn, email="carduser@example.com")
    response = auth_client.get("/manage")
    assert response.status_code == 200
    assert "Manage Cards" in response.text

@patch("main.supabase.auth.get_user")
def test_create_card(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="cardcreator@example.com")

    response = auth_client.post(
        "/new",
        data={"question": "What is FastAPI?", "answer": "A web framework."},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE question = 'What is FastAPI?'")
    card = cur.fetchone()
    cur.close()
    assert card is not None
    assert card['answer'] == "A web framework."

@patch("main.supabase.auth.get_user")
def test_update_card(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="cardupdater@example.com")

    card_id = create_test_card(db_conn, user_id, "Q1", "A1")

    response = auth_client.post(
        f"/edit-card/{card_id}",
        data={"question": "Updated Q1", "answer": "Updated A1"},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/manage"

    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cur.fetchone()
    cur.close()
    assert card['question'] == "Updated Q1"
    assert card['answer'] == "Updated A1"

@patch("main.supabase.auth.get_user")
def test_delete_card(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="carddeleter@example.com")

    card_id = create_test_card(db_conn, user_id, "ToDelete", "ToDelete")

    response = auth_client.post(
        f"/delete/{card_id}",
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/manage"

    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cur.fetchone()
    cur.close()
    assert card is None

# --- Review Tests ---
@patch("main.supabase.auth.get_user")
def test_get_review_page_with_due_card(mock_get_user, client, db_conn):
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="reviewuser@example.com")
    
    create_test_card(db_conn, user_id, "Review Q", "Review A")
    
    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "Review Q" in response.text

@patch("main.supabase.auth.get_user")
def test_review_page_uses_markdown_code_block_styling(mock_get_user, client, db_conn):
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="reviewmarkdown@example.com")

    answer = "Example:\n```python\nprint('hello')\n```"
    create_test_card(db_conn, user_id, "Review Q", answer)

    response = auth_client.get("/review")
    assert response.status_code == 200
    assert 'id="question-content"' in response.text
    assert 'id="answer-content"' in response.text
    assert response.text.count("markdown-content review-card-content") == 2
    assert ".review-card-content pre" in response.text
    assert ".review-card-content code" in response.text

@patch("main.supabase.auth.get_user")
def test_review_page_submits_rating_via_ajax(mock_get_user, client, db_conn):
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="reviewstatus@example.com")

    create_test_card(db_conn, user_id, "Review Q", "Review A")

    response = auth_client.get("/review")
    assert response.status_code == 200
    # The review loop posts the rating to the JSON endpoint and swaps the next
    # card in without a full page reload...
    assert "/api/review/" in response.text
    assert "function rate(status)" in response.text
    assert "function renderCard(" in response.text
    # ...while the form keeps its action so it still works without JavaScript.
    assert 'action="/review/' in response.text

@patch("main.supabase.auth.get_user")
def test_get_review_page_no_due_cards(mock_get_user, client, db_conn):
    """A user with no cards at all gets the empty-deck state."""
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn, email="reviewuser2@example.com")
    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "Your deck is empty" in response.text


@patch("main.supabase.auth.get_user")
def test_get_review_page_all_done(mock_get_user, client, db_conn):
    """A user whose cards are all scheduled for later gets the done state."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="reviewuser4@example.com")
    create_test_card(db_conn, user_id, "Q", "A", due_date=datetime.now() + timedelta(days=3))
    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "All Done!" in response.text

@patch("main.supabase.auth.get_user")
def test_update_review_status(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="reviewuser3@example.com")

    card_id = create_test_card(db_conn, user_id, "Q", "A")

    response = auth_client.post(
        f"/review/{card_id}",
        data={"status": "remembered"},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/review"

    cur = db_conn.cursor()
    cur.execute("SELECT due_date FROM cards WHERE id = %s", (card_id,))
    new_due_date = cur.fetchone()['due_date']
    cur.close()
    assert new_due_date > datetime.now() - timedelta(seconds=1)

# --- Gamification Tests ---
@patch("main.supabase.auth.get_user")
def test_review_records_streak_activity(mock_get_user, client, db_conn):
    """Rating cards upserts today's review_activity row and the AJAX stats
    payload reports the resulting streak."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="streakuser@example.com")

    first = create_test_card(db_conn, user_id, "Q1", "A1")
    second = create_test_card(db_conn, user_id, "Q2", "A2")

    response = auth_client.post(
        f"/api/review/{first}",
        data={"status": "remembered"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["stats"]["streak"] == 1

    auth_client.post(
        f"/api/review/{second}",
        data={"status": "forgot"},
        headers={"X-CSRF-Token": csrf_token},
    )

    cur = db_conn.cursor()
    cur.execute("SELECT reviews, remembered FROM review_activity WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    assert row["reviews"] == 2
    assert row["remembered"] == 1


@patch("main.supabase.auth.get_user")
def test_all_done_page_shows_streak_and_leaderboard(mock_get_user, client, db_conn):
    """Once the deck is cleared, the done page shows the streak and the
    leaderboard with the email local part only (never the full address)."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="boarduser@example.com")
    card_id = create_test_card(db_conn, user_id, "Q", "A")

    auth_client.post(
        f"/review/{card_id}",
        data={"status": "remembered"},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )

    response = auth_client.get("/review")
    assert response.status_code == 200
    assert "All Done!" in response.text
    assert "day streak" in response.text
    assert "Top Reviewers" in response.text
    assert "boarduser" in response.text
    assert "boarduser@example.com" not in response.text

# --- AI Card Generation Tests ---
@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_api_success(mock_generate_cards, mock_get_user, client, db_conn):
    mock_generate_cards.return_value = [{"question": "Q", "answer": "A"}]
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="ai_user@example.com")
    response = auth_client.post(
        "/api/generate-cards", 
        json={"content": "Some text"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert response.json() == {"cards": [{"question": "Q", "answer": "A"}]}
    mock_generate_cards.assert_called_once()

@patch("main.supabase.auth.get_user")
def test_generate_cards_api_empty_content(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="ai_user_empty@example.com")
    response = auth_client.post(
        "/api/generate-cards", 
        json={"content": " "},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 400

@patch("main.supabase.auth.get_user")
def test_save_generated_cards(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="ai_saver@example.com")
    cards_to_save = {"cards": [{"question": "GenQ1", "answer": "GenA1"}]}
    response = auth_client.post(
        "/api/save-cards", 
        json=cards_to_save,
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    cur = db_conn.cursor()
    cur.execute("SELECT * FROM cards WHERE question = 'GenQ1' AND user_id = %s", (user_id,))
    card = cur.fetchone()
    cur.close()
    assert card is not None
    assert card['answer'] == "GenA1"

# --- Secrets & API Keys Tests ---
@patch("main.supabase.auth.get_user")
def test_save_api_keys(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="api_key_user@example.com")
    keys = {"gemini_api_key": "gemini_key", "anthropic_api_key": "anthropic_key"}
    response = auth_client.post(
        "/api/save-api-keys", 
        json=keys,
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    cur = db_conn.cursor()
    cur.execute("SELECT gemini_api_key, anthropic_api_key FROM profiles WHERE auth_user_id = %s", (user_id,))
    user_keys = cur.fetchone()
    cur.close()
    assert user_keys['gemini_api_key'] == "gemini_key"
    assert user_keys['anthropic_api_key'] == "anthropic_key"

@patch("main.supabase.auth.get_user")
def test_save_secrets(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="secrets_user@example.com")

    # Chat IDs are no longer accepted from the browser — linking goes through
    # the bot's signed /start deep link, which proves chat ownership.
    response = auth_client.post(
        "/secrets",
        data={"telegram_chat_id": "12345"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 400

    # An empty POST disconnects.
    cur = db_conn.cursor()
    cur.execute("UPDATE profiles SET telegram_chat_id = '12345' WHERE auth_user_id = %s", (user_id,))
    db_conn.commit()
    cur.close()

    response = auth_client.post("/secrets", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 200
    assert response.json()["success"] is True

    cur = db_conn.cursor()
    cur.execute("SELECT telegram_chat_id FROM profiles WHERE auth_user_id = %s", (user_id,))
    user_secrets = cur.fetchone()
    cur.close()
    assert user_secrets['telegram_chat_id'] is None

@patch("main.supabase.auth.get_user")
def test_settings_page_and_legacy_redirects(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="settings_user@example.com")

    response = auth_client.get("/settings")
    assert response.status_code == 200
    assert "AI Provider Keys" in response.text
    assert "Telegram Notifications" in response.text

    # The old pages were merged into /settings and now redirect there.
    for legacy in ("/api-keys", "/secrets"):
        response = auth_client.get(legacy, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/settings"

def test_create_profile_retries_on_username_collision(db_conn):
    """One email can belong to two auth users (e.g. Google sign-in next to an
    unconfirmed email signup); the second must still get a profile instead of
    a silent login loop."""
    email = "collision@example.com"
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    cur = db_conn.cursor()
    # The fixture's dummy auth.users enforces UNIQUE(email); real Supabase
    # doesn't for unverified accounts. Only the FK ids matter here — the
    # collision under test is on profiles.username.
    cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s), (%s, %s)",
                (first, email, second, f"other-{email}"))
    db_conn.commit()
    cur.close()

    assert crud.create_profile(db_conn, username=email, auth_user_id=first) is True
    assert crud.create_profile(db_conn, username=email, auth_user_id=second) is True

    cur = db_conn.cursor()
    cur.execute("SELECT username FROM profiles WHERE auth_user_id = %s", (second,))
    assert cur.fetchone()["username"] == f"{email}#{second[:8]}"
    cur.close()

# --- Scheduler Tests ---
@patch("main._ensure_webhook")
@patch("main.run_scheduler")
def test_trigger_scheduler_success(mock_run_scheduler, mock_ensure_webhook, client):
    """Test the scheduler endpoint triggers successfully."""
    mock_ensure_webhook.return_value = {"status": "already correct", "url": "https://example.com"}
    mock_run_scheduler.return_value = {"users_notified": 1}

    # The endpoint reads the secret from the X-Scheduler-Secret header (see
    # api/cron.py), not from a query parameter.
    response = client.get(
        "/api/trigger-scheduler",
        headers={"X-Scheduler-Secret": os.environ.get("SCHEDULER_SECRET")},
    )

    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "completed"
    assert json_response["result"] == {"users_notified": 1}
    assert json_response["webhook_status"]["status"] == "already correct"
    
    mock_ensure_webhook.assert_called_once()
    mock_run_scheduler.assert_called_once()

def test_trigger_scheduler_invalid_secret(client):
    """Test the scheduler endpoint with an invalid secret."""
    response = client.get("/api/trigger-scheduler", headers={"X-Scheduler-Secret": "wrongsecret"})
    assert response.status_code == 403

# --- Telegram Photo Cache ---
def test_photo_cache_roundtrip_and_upsert(db_conn):
    """The cache is standalone: keyed by content hash, no FK into cards."""
    import crud

    content_hash = f"test-{uuid.uuid4().hex}"
    assert crud.get_cached_photo_file_id(db_conn, content_hash) is None

    crud.cache_photo_file_id(db_conn, content_hash, "file-1", card_id=123)
    assert crud.get_cached_photo_file_id(db_conn, content_hash) == "file-1"

    # Re-rendering the same content upserts the newer file_id.
    crud.cache_photo_file_id(db_conn, content_hash, "file-2", card_id=123)
    assert crud.get_cached_photo_file_id(db_conn, content_hash) == "file-2"

# --- Password Reset & Change Tests ---
def _fake_httpx_response(status_code, json_body=None):
    """Stand-in for the GoTrue REST responses used by the password helpers."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    return response

def test_password_reset_request_is_enumeration_safe(client):
    """Known and unknown addresses must get the same generic answer."""
    csrf_token = get_csrf_token(client)
    with patch("main.httpx.post", return_value=_fake_httpx_response(200)) as mock_post:
        response = client.post(
            "/auth/reset",
            data={"email": "whoever@example.com", "csrf_token": csrf_token},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "if an account exists" in body["message"].lower()
    # The recovery link must land back on the reset page to be completed.
    assert mock_post.call_args.kwargs["params"]["redirect_to"].endswith("/auth/reset")

def test_password_reset_request_surfaces_rate_limit(client):
    csrf_token = get_csrf_token(client)
    with patch("main.httpx.post", return_value=_fake_httpx_response(429)):
        response = client.post(
            "/auth/reset",
            data={"email": "whoever@example.com", "csrf_token": csrf_token},
        )
    body = response.json()
    assert body["success"] is False
    assert "too many" in body["error"].lower()

def test_password_reset_confirm_enforces_password_policy(client):
    csrf_token = get_csrf_token(client)
    with patch("main.httpx.put") as mock_put:
        response = client.post(
            "/auth/reset/confirm",
            json={"access_token": "recovery-token", "password": "short"},
            headers={"X-CSRF-Token": csrf_token},
        )
    body = response.json()
    assert body["success"] is False
    assert "8 characters" in body["error"]
    mock_put.assert_not_called()

def test_password_reset_confirm_success_logs_user_in(client):
    csrf_token = get_csrf_token(client)
    with patch("main.httpx.put", return_value=_fake_httpx_response(200)):
        response = client.post(
            "/auth/reset/confirm",
            json={
                "access_token": "recovery-token",
                "refresh_token": "recovery-refresh",
                "password": "newpassword1",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
    body = response.json()
    assert body["success"] is True
    # The recovery session doubles as the login session.
    assert response.cookies.get("access_token") == "recovery-token"
    assert response.cookies.get("refresh_token") == "recovery-refresh"

def test_password_reset_confirm_rejects_dead_link(client):
    csrf_token = get_csrf_token(client)
    with patch("main.httpx.put", return_value=_fake_httpx_response(401)):
        response = client.post(
            "/auth/reset/confirm",
            json={"access_token": "stale-token", "password": "newpassword1"},
            headers={"X-CSRF-Token": csrf_token},
        )
    body = response.json()
    assert body["success"] is False
    assert "expired" in body["error"].lower()
    assert "access_token" not in response.cookies

@patch("main.supabase.auth.get_user")
def test_change_password_rejects_wrong_current_password(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="pw_user@example.com")
    with patch("main.httpx.post", return_value=_fake_httpx_response(400)), \
         patch("main.httpx.put") as mock_put:
        response = auth_client.post(
            "/auth/change-password",
            data={"current_password": "wrong", "new_password": "newpassword1"},
            headers={"X-CSRF-Token": csrf_token},
        )
    body = response.json()
    assert body["success"] is False
    assert "current password" in body["error"].lower()
    mock_put.assert_not_called()

@patch("main.supabase.auth.get_user")
def test_change_password_success(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="pw_user2@example.com")
    with patch("main.httpx.post", return_value=_fake_httpx_response(200)) as mock_grant, \
         patch("main.httpx.put", return_value=_fake_httpx_response(200)) as mock_put:
        response = auth_client.post(
            "/auth/change-password",
            data={"current_password": "oldpassword1", "new_password": "newpassword1"},
            headers={"X-CSRF-Token": csrf_token},
        )
    body = response.json()
    assert body["success"] is True
    # Verified against the account email, updated with the session's token.
    assert mock_grant.call_args.kwargs["json"]["email"] == "pw_user2@example.com"
    assert mock_put.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-test-token"
