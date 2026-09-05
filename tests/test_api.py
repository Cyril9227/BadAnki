import asyncio
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
import bot
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

@patch("main.supabase.auth.get_user")
def test_courses_page_is_server_rendered(mock_get_user, client, db_conn):
    """Courses and tags arrive in the HTML itself — no client fetch needed."""
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="ssr_courses@example.com")
    auth_client.post(
        "/api/course-content",
        json={"path": "maths/integrals.md", "content": "---\ntitle: Integration Tricks\ntags: [calculus]\n---\n# Body"},
        headers={"X-CSRF-Token": csrf_token},
    )
    response = auth_client.get("/courses")
    assert response.status_code == 200
    assert "Integration Tricks" in response.text   # frontmatter title
    assert "maths/integrals.md" in response.text   # path subtitle
    assert "calculus" in response.text             # tag chip

@patch("main.supabase.auth.get_user")
def test_courses_page_has_search_sort_and_recency(mock_get_user, client, db_conn):
    """The list was a bare alphabetical dump. It now carries a search box, a
    sort control, a count, and the last-edited time that `courses.updated_at`
    had been recording without ever surfacing."""
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="coursefind@example.com")
    for path, title in (("maths/integrals.md", "Integration Tricks"), ("physics/qm.md", "Quantum")):
        auth_client.post(
            "/api/course-content",
            json={"path": path, "content": f"---\ntitle: {title}\n---\n# Body"},
            headers={"X-CSRF-Token": csrf_token},
        )

    response = auth_client.get("/courses")
    assert response.status_code == 200
    assert 'id="course-search"' in response.text
    assert 'id="course-sort"' in response.text
    assert "2 courses" in response.text
    # Sort/filter keys ride on the rows so the JS never reads rendered text.
    assert 'data-title="integration tricks"' in response.text
    assert 'data-search="integration tricks maths/integrals.md"' in response.text
    # Freshly saved, so the relative label is the sub-minute case.
    assert "just now" in response.text

@patch("main.supabase.auth.get_user")
def test_courses_overview_carries_updated_at(mock_get_user, client, db_conn):
    """A file created but never saved has no updated_at — the row must still
    render (no timestamp) rather than blowing up the page."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="courseblank@example.com")
    auth_client.post(
        "/api/course-item",
        json={"path": "untouched.md", "type": "file"},
        headers={"X-CSRF-Token": csrf_token},
    )

    courses, _ = crud.get_courses_overview_for_user(db_conn, user_id)
    assert len(courses) == 1
    assert courses[0]["updated_at"] is None

    response = auth_client.get("/courses")
    assert response.status_code == 200
    assert 'data-updated=""' in response.text

def test_relative_time_filter():
    from main import relative_time
    now = datetime.now()
    assert relative_time(None) == ""
    assert relative_time(now) == "just now"
    assert relative_time(now + timedelta(hours=1)) == "just now"  # clock skew
    assert relative_time(now - timedelta(seconds=90)) == "1 minute ago"
    assert relative_time(now - timedelta(hours=5)) == "5 hours ago"
    assert relative_time(now - timedelta(days=1)) == "1 day ago"
    assert relative_time(now - timedelta(days=10)) == "1 week ago"
    assert relative_time(now - timedelta(days=400)) == "1 year ago"

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
def test_generation_modal_has_bulk_approval(mock_get_user, client, db_conn):
    """Trimming a ten-card batch meant clicking ten checkboxes. Pages that
    include the shared generation modal now ship the approve-all bar."""
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn, email="bulkapprove@example.com")

    response = auth_client.get("/new")
    assert response.status_code == 200
    assert 'id="approve-all"' in response.text
    assert 'id="approve-count"' in response.text
    assert "function refreshApproval()" in response.text

@patch("main.supabase.auth.get_user")
def test_manage_page_ships_each_question_once(mock_get_user, client, db_conn):
    """The question used to ride on the row as data-question AND in the cell as
    data-content — double the question bytes on every row of the page."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="onceonly@example.com")
    create_test_card(db_conn, user_id, "A distinctive question string", "An answer")

    body = auth_client.get("/manage").text
    assert body.count("A distinctive question string") == 1
    assert "data-question=" not in body
    assert "data-card-row" in body

def test_pinned_cdn_assets_are_versioned():
    """An unpinned jsdelivr path gets a 7-day cache instead of a year, and
    silently changes version — /npm/marked/ resolves by fallback, not to the
    real latest."""
    layout = open("templates/layout.html", encoding="utf-8").read()
    render_card = open("templates/render_card.html", encoding="utf-8").read()
    for body in (layout, render_card):
        assert "npm/marked@" in body
        assert "npm/marked/marked.min.js" not in body

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
    # Creation returns to a fresh form (card creation is repetitive).
    assert response.headers["location"] == "/new?card_type=basic"

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
def test_sweetalert_is_not_shipped_to_pages_that_never_open_a_dialog(mock_get_user, client, db_conn):
    """~26 KB of JS+CSS used to load on every page for the five that use it.
    /review is the hot path and opens no dialogs."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="noswal@example.com")
    create_test_card(db_conn, user_id, "Q", "A")

    for path in ("/review", "/"):
        body = auth_client.get(path).text
        assert '<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>' not in body
        assert "sweetalert2.min.css\" rel=\"stylesheet\"" not in body
        assert '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/sweetalert2@11' not in body
        # ...but the lazy entry point is there for anything that does need it.
        assert "function loadSweetAlert()" in body
        assert "window.swalClasses" in body

@patch("main.supabase.auth.get_user")
def test_review_page_is_screen_reader_navigable(mock_get_user, client, db_conn):
    """Card swaps rewrite text in place, so the loop needs a labelled region,
    a polite status region to narrate navigation, and shortcut hints that
    aren't hidden behind the touch-only kbd styling."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="a11yreview@example.com")
    create_test_card(db_conn, user_id, "Review Q", "Review A")

    response = auth_client.get("/review")
    assert response.status_code == 200
    assert 'aria-label="Review card"' in response.text
    assert 'id="review-status"' in response.text and 'role="status"' in response.text
    assert 'aria-keyshortcuts="1"' in response.text
    assert 'aria-label="Skip this card for now"' in response.text
    assert 'aria-label="Back to the previous card"' in response.text
    # The answer is focused on reveal rather than announced by a live region.
    assert 'id="answer-section"' in response.text
    assert 'tabindex="-1"' in response.text

@patch("main.supabase.auth.get_user")
def test_review_streak_badge_keeps_the_flame_out_of_the_name(mock_get_user, client, db_conn):
    """"Day Streak, fire, 5" is what a screen reader read before the emoji was
    split into its own aria-hidden span."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="flame@example.com")
    card_id = create_test_card(db_conn, user_id, "Q", "A")
    create_test_card(db_conn, user_id, "Q2", "A2")
    auth_client.post(
        f"/review/{card_id}",
        data={"status": "remembered"},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )

    response = auth_client.get("/review")
    assert response.status_code == 200
    assert '<span aria-hidden="true">\U0001F525</span>' in response.text
    assert '<span id="streak-badge">1</span>' in response.text

@patch("main.supabase.auth.get_user")
def test_card_viewer_offers_edit(mock_get_user, client, db_conn):
    """/card/{id} is where Telegram's /list and /card links land — Edit is the
    action people arrive wanting, and it was a dead end before."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="cardview@example.com")
    card_id = create_test_card(db_conn, user_id, "Q", "A")

    response = auth_client.get(f"/card/{card_id}")
    assert response.status_code == 200
    assert f'href="/edit-card/{card_id}"' in response.text

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
def test_next_card_respects_exclude(mock_get_user, client, db_conn):
    """Swipe-to-skip: /api/review/next serves the next due card minus the
    session's skipped ids."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="skipuser@example.com")
    first = create_test_card(db_conn, user_id, "Q1", "A1", due_date=datetime.now() - timedelta(days=2))
    second = create_test_card(db_conn, user_id, "Q2", "A2", due_date=datetime.now() - timedelta(days=1))

    response = auth_client.get(f"/api/review/next?exclude={first}")
    assert response.status_code == 200
    assert response.json()["next_card"]["id"] == second

    response = auth_client.get(f"/api/review/next?exclude={first},{second}")
    assert response.status_code == 200
    assert response.json()["next_card"] is None


def _seed_review_state(db_conn, email):
    """A deck with one due card, one scheduled ahead, and two days of activity
    ending yesterday — enough to exercise every branch of the combined query."""
    user_id = create_test_user(db_conn, email=email)
    due = create_test_card(db_conn, user_id, "Due now", "A")
    later = create_test_card(db_conn, user_id, "Later", "A",
                             due_date=datetime.now() + timedelta(days=40))
    with db_conn.cursor() as cur:
        cur.execute("UPDATE cards SET interval = 30 WHERE id = %s", (later,))
        cur.execute(
            "INSERT INTO review_activity (user_id, day, reviews, remembered) VALUES"
            " (%s, CURRENT_DATE - 1, 4, 3), (%s, CURRENT_DATE - 2, 2, 2)",
            (str(user_id), str(user_id)),
        )
        db_conn.commit()
    return user_id, due

def test_review_state_one_query_matches_the_three_helpers(pg_container, db_conn):
    """The combined query has to be a drop-in for the three reads it replaced,
    so assert it against them rather than against hand-written expectations."""
    user_id, due = _seed_review_state(db_conn, "combined@example.com")

    card, counters, streak_current = crud.get_review_state_for_user(db_conn, user_id)
    want_card = crud.get_review_cards_for_user(db_conn, user_id)
    want_counters = crud.get_review_stats_for_user(db_conn, user_id)
    want_streak = crud.get_review_streak_for_user(db_conn, user_id)

    assert card["id"] == want_card["id"] == due
    assert card["question"] == want_card["question"]
    assert card["answer"] == want_card["answer"]
    assert card["card_type"] == want_card["card_type"]
    for key in ("total_cards", "due_today", "due_week", "new_cards", "young", "mature"):
        assert counters[key] == want_counters[key], key
    # Activity ends yesterday, so the streak is alive but at risk: 2 days.
    assert streak_current == want_streak["current"] == 2

def test_review_state_excludes_skipped_cards(pg_container, db_conn):
    user_id, due = _seed_review_state(db_conn, "combinedskip@example.com")

    card, counters, _ = crud.get_review_state_for_user(db_conn, user_id, exclude_ids=[due])
    assert card is None                 # the only due card was set aside
    assert counters["due_today"] == 1   # ...but it is still counted as due
    # An empty exclude list must not filter anything out.
    card, _, _ = crud.get_review_state_for_user(db_conn, user_id, exclude_ids=[])
    assert card["id"] == due

def test_review_state_falls_back_when_the_combined_query_fails(pg_container, db_conn, monkeypatch):
    """review_activity is best-effort, so folding it into the same statement
    must not be able to take the card and counters down with it."""
    user_id, due = _seed_review_state(db_conn, "combinedfallback@example.com")
    # No placeholders, so .format(tag_clause=...) leaves it alone and the
    # execute raises — which is the point.
    monkeypatch.setattr(crud, "_REVIEW_STATE_QUERY_TEMPLATE", "SELECT * FROM table_that_is_not_here")

    card, counters, streak_current = crud.get_review_state_for_user(db_conn, user_id)
    assert card["id"] == due
    assert counters["total_cards"] == 2
    assert streak_current == 2

def test_review_state_on_an_empty_deck(pg_container, db_conn):
    user_id = create_test_user(db_conn, email="combinedempty@example.com")
    card, counters, streak_current = crud.get_review_state_for_user(db_conn, user_id)
    assert card is None
    assert counters["total_cards"] == 0
    assert streak_current == 0  # no activity rows at all -> array_agg is NULL

@patch("main.supabase.auth.get_user")
def test_all_done_page_shows_streak(mock_get_user, client, db_conn):
    """Once the deck is cleared, the done page shows the streak (the
    leaderboard moved to the home page)."""
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
    assert "Top Reviewers" not in response.text

@patch("main.supabase.auth.get_user")
def test_home_leaderboard_members_only_local_part(mock_get_user, client, db_conn):
    """The home page shows the leaderboard to logged-in users only. The
    caller's own row shows their email local part (never the full address);
    every other reviewer is reduced to an initial."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="boarduser2@example.com")
    card_id = create_test_card(db_conn, user_id, "Q", "A")
    auth_client.post(
        f"/review/{card_id}",
        data={"status": "remembered"},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )
    other_id = create_test_user(db_conn, email="otherperson@example.com")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO review_activity (user_id, day, reviews, remembered) VALUES (%s, CURRENT_DATE, 5, 5)", (str(other_id),))
        db_conn.commit()

    response = auth_client.get("/")
    assert response.status_code == 200
    assert "Top Reviewers" in response.text
    assert "boarduser2" in response.text
    assert "boarduser2@example.com" not in response.text
    assert "otherperson" not in response.text
    assert "o…" in response.text

    # Anonymous visitors get the public page without the leaderboard.
    auth_client.cookies.delete("access_token")
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "Top Reviewers" not in response.text

@patch("main.supabase.auth.get_user")
def test_stats_page_authenticated(mock_get_user, client, db_conn):
    """/stats embeds the user's review activity, the due-load forecast (the
    rated card comes back due tomorrow) and the streak for the heatmap."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="statsuser@example.com")
    card_id = create_test_card(db_conn, user_id, "Q", "A")
    auth_client.post(
        f"/review/{card_id}",
        data={"status": "remembered"},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )

    response = auth_client.get("/stats")
    assert response.status_code == 200
    assert "Review Heatmap" in response.text
    assert 'id="stats-data"' in response.text
    assert '"reviews": 1' in response.text   # today's activity row
    assert '"due": 1' in response.text       # forecast row for the rescheduled card
    assert '"current": 1' in response.text   # streak from the rating above

@patch("main.supabase.auth.get_user")
def test_stats_page_empty_deck_still_renders(mock_get_user, client, db_conn):
    """A user with no activity and no cards gets the page, not an error."""
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn, email="statsempty@example.com")
    response = auth_client.get("/stats")
    assert response.status_code == 200
    assert "Review Heatmap" in response.text

def test_stats_page_unauthenticated(client):
    response = client.get("/stats", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth"

@patch("main.supabase.auth.get_user")
def test_stats_page_shows_recall_and_deck_composition(mock_get_user, client, db_conn):
    """The deck card counts new/learning/mature/due-this-week, and the recall
    tile is present for the client-side computation off the heatmap payload."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="deckstats@example.com")
    # One never-rated card (interval 0), one young (interval 5), one mature
    # (interval 30). Only the new one is due inside the week window.
    create_test_card(db_conn, user_id, "new", "A")
    young = create_test_card(db_conn, user_id, "young", "A", due_date=datetime.now() + timedelta(days=40))
    mature = create_test_card(db_conn, user_id, "mature", "A", due_date=datetime.now() + timedelta(days=40))
    with db_conn.cursor() as cur:
        cur.execute("UPDATE cards SET interval = 5 WHERE id = %s", (young,))
        cur.execute("UPDATE cards SET interval = 30 WHERE id = %s", (mature,))
        db_conn.commit()

    composition = crud.get_review_stats_for_user(db_conn, user_id)
    assert composition["total_cards"] == 3
    assert composition["new_cards"] == 1
    assert composition["young"] == 1
    assert composition["mature"] == 1
    assert composition["due_week"] == 1  # the two 40-days-out cards are outside it
    # new/young/mature partition the deck — the reason new_cards dropped its
    # redundant ease_factor conjunct when these counters were folded in.
    assert composition["new_cards"] + composition["young"] + composition["mature"] \
        == composition["total_cards"]

    response = auth_client.get("/stats")
    assert response.status_code == 200
    assert ">Deck</div>" in response.text  # the deck card's header
    assert 'id="stat-recall"' in response.text
    assert "due this week" in response.text

@patch("main.supabase.auth.get_user")
def test_stats_deck_card_survives_missing_activity_table(mock_get_user, client, db_conn):
    """Deck make-up reads `cards`, so it still renders when activity tracking
    (and therefore the heatmap) is unavailable."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="deckonly@example.com")
    create_test_card(db_conn, user_id, "Q", "A")

    with patch("crud.get_review_heatmap_for_user", return_value=None):
        response = auth_client.get("/stats")
    assert response.status_code == 200
    assert "Review Heatmap" not in response.text
    assert "due this week" in response.text

@patch("main.supabase.auth.get_user")
def test_home_shows_deck_status_when_signed_in(mock_get_user, client, db_conn):
    """Signed-in visitors get the due count (hero copy + button badge), their
    streak and the deck size; anonymous visitors keep the generic pitch."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="deckhome@example.com")
    card_id = create_test_card(db_conn, user_id, "Q", "A")
    create_test_card(db_conn, user_id, "Q2", "A2", due_date=datetime.now() + timedelta(days=30))
    auth_client.post(
        f"/review/{card_id}",
        data={"status": "remembered"},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )

    # Both cards are now scheduled ahead, so the deck reads as caught up.
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "all caught up" in response.text
    assert "<strong>2</strong> cards in your deck" in response.text
    assert "1</strong>-day streak" in response.text
    assert "Welcome to your personal spaced repetition" not in response.text

    auth_client.cookies.delete("access_token")
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "Welcome to your personal spaced repetition" in response.text
    assert "in your deck" not in response.text

@patch("main.supabase.auth.get_user")
def test_home_counts_due_cards(mock_get_user, client, db_conn):
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="duehome@example.com")
    create_test_card(db_conn, user_id, "Q1", "A1")
    create_test_card(db_conn, user_id, "Q2", "A2")

    response = auth_client.get("/")
    assert response.status_code == 200
    assert "You have <strong>2</strong> cards due for review." in response.text

# --- AI Card Generation Tests ---
@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_releases_the_db_before_the_provider_call(mock_generate_cards, mock_get_user, client, db_conn):
    """The middleware would otherwise hold a pooled connection for the whole
    10-60s provider call. Production runs DB_POOL_MAX=2, so that starved
    everything else on the instance."""
    from database import get_db_pool

    observed = {}

    def record_pool_state(*args, **kwargs):
        # Runs inside run_in_threadpool, i.e. exactly while the request is
        # waiting on the provider. db_conn is a direct connect(), not pooled.
        observed["checked_out"] = len(get_db_pool()._used)
        return [{"question": "Q", "answer": "A"}]

    mock_generate_cards.side_effect = record_pool_state
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="poolrelease@example.com")

    response = auth_client.post(
        "/api/generate-cards/gemini",
        json={"content": "Some course text"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["cards"] == [{"question": "Q", "answer": "A"}]
    assert observed["checked_out"] == 0, "connection was still held during the provider call"

def test_release_request_db_is_idempotent():
    """The middleware releases in a finally block keyed on request.state.db, so
    releasing early must clear the slot or the connection goes back twice."""
    from main import release_request_db
    import types as _types

    released = []
    request = _types.SimpleNamespace(state=_types.SimpleNamespace(db="conn-sentinel"))
    with patch("main.release_db_connection", side_effect=released.append):
        release_request_db(request)
        release_request_db(request)  # second call must be a no-op
    assert released == ["conn-sentinel"]
    assert request.state.db is None

@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_api_success(mock_generate_cards, mock_get_user, client, db_conn):
    mock_generate_cards.return_value = [{"question": "Q", "answer": "A"}]
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="ai_user@example.com")
    response = auth_client.post(
        "/api/generate-cards/gemini",
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
        "/api/generate-cards/gemini",
        json={"content": " "},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 400

@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_api_surfaces_provider_errors(mock_generate_cards, mock_get_user, client, db_conn):
    """A rejected key must come back as a 400 carrying a message the user can
    act on, not as the generic 500 every failure used to collapse into."""
    from main import GenerationError
    mock_generate_cards.side_effect = GenerationError(400, "Gemini rejected the API key. Check it in Settings.")
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="ai_user_badkey@example.com")
    response = auth_client.post(
        "/api/generate-cards/gemini",
        json={"content": "Some text"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Gemini rejected the API key. Check it in Settings."

def test_generate_cards_without_a_key_is_a_client_error():
    from main import GenerationError, generate_cards
    with pytest.raises(GenerationError) as excinfo:
        generate_cards("Some text", mode="anthropic", api_key=None)
    assert excinfo.value.status_code == 400
    assert "Anthropic" in excinfo.value.detail

def test_provider_error_classification():
    from main import _provider_error

    class FakeStatusError(Exception):
        def __init__(self, status_code, message="boom"):
            super().__init__(message)
            self.status_code = status_code

    class FakeGeminiError(Exception):
        def __init__(self, code, message):
            super().__init__(message)
            self.code = code

    assert _provider_error("anthropic", FakeStatusError(401)).status_code == 400
    assert _provider_error("openai", FakeStatusError(429)).status_code == 429
    # Gemini reports a malformed key as 400, not 401.
    rejected = _provider_error("gemini", FakeGeminiError(400, "API key not valid. Please pass a valid API key."))
    assert rejected.status_code == 400 and "rejected" in rejected.detail
    assert _provider_error("gemini", FakeGeminiError(400, "invalid argument")).status_code == 502
    assert _provider_error("openai", TimeoutError("read timed out")).status_code == 502

@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_from_topic_api_success(mock_generate_cards, mock_get_user, client, db_conn):
    mock_generate_cards.return_value = [{"question": "Q", "answer": "A", "card_type": "basic"}]
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="topic_user@example.com")
    response = auth_client.post(
        "/api/generate-cards-from-topic/gemini",
        json={"content": "Integration tricks like +1/-1 and partial fraction decomposition"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert response.json() == {"cards": [{"question": "Q", "answer": "A", "card_type": "basic"}]}
    # The topic prompt (not the course-material prompt) must be used.
    assert mock_generate_cards.call_args.kwargs.get("source") == "topic"

@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_from_topic_caps_batch_size(mock_generate_cards, mock_get_user, client, db_conn):
    """The prompt asks the model for at most 10 cards; the endpoint enforces
    the cap even when the model ignores it."""
    mock_generate_cards.return_value = [
        {"question": f"Q{i}", "answer": "A", "card_type": "basic"} for i in range(15)
    ]
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="topic_cap@example.com")
    response = auth_client.post(
        "/api/generate-cards-from-topic/gemini",
        json={"content": "extensive integration tricks"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert len(response.json()["cards"]) == 10

@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_from_topic_accepts_any_card_type(mock_generate_cards, mock_get_user, client, db_conn):
    """card_type "any" (the topic bar's default) lets the model pick per card;
    course-material generation still rejects it."""
    mock_generate_cards.return_value = [{"question": "Q", "answer": "A", "card_type": "cloze"}]
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="topic_any@example.com")
    response = auth_client.post(
        "/api/generate-cards-from-topic/gemini",
        json={"content": "Ohm's law", "card_type": "any"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert mock_generate_cards.call_args.kwargs.get("card_type") == "any"

    response = auth_client.post(
        "/api/generate-cards/gemini",
        json={"content": "some course text", "card_type": "any"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 422

@patch("main.supabase.auth.get_user")
@patch("main.generate_cards")
def test_generate_cards_from_topic_openai(mock_generate_cards, mock_get_user, client, db_conn):
    """The OpenAI endpoints route to mode="openai" with the user's OpenAI key."""
    mock_generate_cards.return_value = [{"question": "Q", "answer": "A", "card_type": "basic"}]
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="topic_openai@example.com")
    cur = db_conn.cursor()
    cur.execute("UPDATE profiles SET openai_api_key = 'sk-test' WHERE auth_user_id = %s", (user_id,))
    db_conn.commit()
    cur.close()

    response = auth_client.post(
        "/api/generate-cards-from-topic/openai",
        json={"content": "Ohm's law"},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert mock_generate_cards.call_args.kwargs.get("mode") == "openai"
    assert mock_generate_cards.call_args.kwargs.get("api_key") == "sk-test"

@patch("main.supabase.auth.get_user")
def test_generate_cards_from_topic_rejects_blank_topic(mock_get_user, client, db_conn):
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="topic_blank@example.com")
    response = auth_client.post(
        "/api/generate-cards-from-topic/gemini",
        json={"content": "  "},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 400

@patch("main.supabase.auth.get_user")
def test_generate_cards_from_topic_rejects_oversized_topic(mock_get_user, client, db_conn):
    """Topic requests are capped far below course content — the field is a
    prompt, and an unbounded one is an abuse vector on shared API keys."""
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="topic_long@example.com")
    response = auth_client.post(
        "/api/generate-cards-from-topic/gemini",
        json={"content": "x" * 501},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 422

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

@patch("main.supabase.auth.get_user")
def test_bulk_delete_cards_scoped_to_owner(mock_get_user, client, db_conn):
    """One request deletes many owned cards; foreign and unknown ids are
    silently skipped and never touched."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="bulk_deleter@example.com")
    other_id = str(create_test_user(db_conn, email="bulk_victim@example.com"))
    own_a = create_test_card(db_conn, user_id, "Q1", "A1")
    own_b = create_test_card(db_conn, user_id, "Q2", "A2")
    keep = create_test_card(db_conn, user_id, "Q3", "A3")
    foreign = create_test_card(db_conn, other_id, "QF", "AF")

    response = auth_client.post(
        "/api/cards/delete",
        json={"ids": [own_a, own_b, foreign, 999999]},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 2

    cur = db_conn.cursor()
    cur.execute("SELECT id FROM cards WHERE id = ANY(%s)", ([own_a, own_b, keep, foreign],))
    remaining = {row["id"] for row in cur.fetchall()}
    cur.close()
    assert remaining == {keep, foreign}

# --- Deck Export Tests ---
@patch("main.supabase.auth.get_user")
def test_export_cards_round_trips_the_deck(mock_get_user, client, db_conn):
    """Export is a backup, so it carries scheduling as well as text, and has
    to survive content that would break a naive CSV writer."""
    import csv as _csv, io as _io

    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="exporter@example.com")
    tricky_q = 'Line one, with a comma\nand a "quoted" second line: $e^{i\\pi}$'
    card_id = create_test_card(db_conn, user_id, tricky_q, "The answer")
    with db_conn.cursor() as cur:
        cur.execute("UPDATE cards SET card_type = 'cloze', interval = 7 WHERE id = %s", (card_id,))
        db_conn.commit()

    response = auth_client.get("/api/export-cards")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=\"badanki-cards-" in response.headers["content-disposition"]

    rows = list(_csv.DictReader(_io.StringIO(response.text, newline="")))
    assert len(rows) == 1
    assert rows[0]["question"] == tricky_q      # commas, quotes, newlines, LaTeX
    assert rows[0]["answer"] == "The answer"
    assert rows[0]["card_type"] == "cloze"
    assert rows[0]["interval"] == "7"
    assert rows[0]["ease_factor"] == "2.5"
    assert rows[0]["due_date"]                  # scheduling rides along
    assert "user_id" not in rows[0]             # same on every row, meaningless outside this DB

@patch("main.supabase.auth.get_user")
def test_export_cards_only_returns_your_own(mock_get_user, client, db_conn):
    import csv as _csv, io as _io

    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="exportmine@example.com")
    other_id = create_test_user(db_conn, email="exportnotmine@example.com")
    create_test_card(db_conn, user_id, "Mine", "A")
    create_test_card(db_conn, other_id, "Theirs", "A")

    response = auth_client.get("/api/export-cards")
    questions = [row["question"] for row in _csv.DictReader(_io.StringIO(response.text, newline=""))]
    assert questions == ["Mine"]

@patch("main.supabase.auth.get_user")
def test_export_cards_on_an_empty_deck_is_a_header_only_file(mock_get_user, client, db_conn):
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn, email="exportempty@example.com")
    response = auth_client.get("/api/export-cards")
    assert response.status_code == 200
    assert response.text.strip() == "id,card_type,question,answer,due_date,interval,ease_factor"

def test_export_cards_requires_login(client):
    response = client.get("/api/export-cards", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth"

@patch("main.supabase.auth.get_user")
def test_settings_offers_the_export(mock_get_user, client, db_conn):
    auth_client, _, _ = authenticate_client(mock_get_user, client, db_conn, email="exportlink@example.com")
    response = auth_client.get("/settings")
    assert response.status_code == 200
    assert 'href="/api/export-cards"' in response.text

# --- Account Deletion Tests ---
@patch("main.supabase.auth.get_user")
def test_delete_account_requires_service_key(mock_get_user, client, db_conn, monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="deleter_unconf@example.com")
    response = auth_client.post("/api/delete-account", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 503

@patch("main.supabase.auth.get_user")
@patch("main.httpx.delete")
def test_delete_account_calls_supabase_admin(mock_delete, mock_get_user, client, db_conn, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    mock_delete.return_value = MagicMock(status_code=200)
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="deleter@example.com")
    # Rows in the standalone tables have no FK to cascade from; the endpoint
    # must clear them itself or the leaderboard keeps a ghost reviewer.
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO review_activity (user_id, day, reviews, remembered) VALUES (%s, CURRENT_DATE, 3, 2)", (user_id,))
        cur.execute("INSERT INTO folders (user_id, path) VALUES (%s, 'maths')", (user_id,))
        db_conn.commit()
    response = auth_client.post("/api/delete-account", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 200
    assert response.json()["success"] is True
    called_url = mock_delete.call_args.args[0]
    assert called_url.endswith(f"/auth/v1/admin/users/{user_id}")
    assert mock_delete.call_args.kwargs["headers"]["apikey"] == "service-key"
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM review_activity WHERE user_id = %s", (user_id,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT COUNT(*) AS n FROM folders WHERE user_id = %s", (user_id,))
        assert cur.fetchone()["n"] == 0

@patch("main.supabase.auth.get_user")
@patch("main.httpx.delete")
def test_delete_account_surfaces_admin_failure(mock_delete, mock_get_user, client, db_conn, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    mock_delete.return_value = MagicMock(status_code=403, text="nope")
    auth_client, _, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="deleter_fail@example.com")
    response = auth_client.post("/api/delete-account", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 500

# --- Secrets & API Keys Tests ---
@patch("main.supabase.auth.get_user")
def test_save_api_keys(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="api_key_user@example.com")
    keys = {"gemini_api_key": "gemini_key", "anthropic_api_key": "anthropic_key", "openai_api_key": "openai_key"}
    response = auth_client.post(
        "/api/save-api-keys",
        json=keys,
        headers={"X-CSRF-Token": csrf_token}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    cur = db_conn.cursor()
    cur.execute("SELECT gemini_api_key, anthropic_api_key, openai_api_key FROM profiles WHERE auth_user_id = %s", (user_id,))
    user_keys = cur.fetchone()
    cur.close()
    # Stored encrypted at rest; plaintext only ever exists on the User model.
    from key_encryption import decrypt_secret
    for column, plaintext in (("gemini_api_key", "gemini_key"),
                              ("anthropic_api_key", "anthropic_key"),
                              ("openai_api_key", "openai_key")):
        assert user_keys[column].startswith("enc:")
        assert plaintext not in user_keys[column]
        assert decrypt_secret(user_keys[column]) == plaintext

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

@patch("main._ensure_webhook")
@patch("main.run_scheduler")
def test_trigger_scheduler_runs_when_the_webhook_check_fails(mock_run_scheduler, mock_ensure_webhook, client):
    """A Telegram hiccup on getWebhookInfo must not cancel the day's reminders."""
    mock_ensure_webhook.side_effect = RuntimeError("telegram unreachable")
    mock_run_scheduler.return_value = "Scheduler finished."
    response = client.get(
        "/api/trigger-scheduler",
        headers={"X-Scheduler-Secret": os.environ.get("SCHEDULER_SECRET")},
    )
    assert response.status_code == 200
    assert response.json()["webhook_status"]["status"] == "check failed"
    mock_run_scheduler.assert_called_once()

def test_scheduler_db_failure_is_not_reported_as_success():
    """A database error while listing users used to be swallowed, so the run
    reported "No users found" and the cron logged a green day with no
    reminders sent. It must propagate."""
    import scheduler
    with patch("scheduler.get_db_connection", side_effect=RuntimeError("pool exhausted")):
        with pytest.raises(RuntimeError):
            scheduler.get_users_with_due_cards()

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

# --- Card Theme (tag) Tests ---
def test_sanitize_tags_drops_blanks():
    from parsing import sanitize_tags
    assert sanitize_tags("maths, , physics,") == ["maths", "physics"]
    assert sanitize_tags(["Maths", "MATHS", " physics "]) == ["maths", "physics"]
    assert sanitize_tags(",,") == []

@patch("main.supabase.auth.get_user")
def test_card_themes_round_trip(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="themes@example.com")

    auth_client.post("/new", data={"question": "2+2?", "answer": "4",
                                   "tags": "Maths, , ALGEBRA"},
                     headers={"X-CSRF-Token": csrf_token}, follow_redirects=False)
    with db_conn.cursor() as cur:
        cur.execute("SELECT id, tags FROM cards WHERE user_id = %s", (str(user_id),))
        row = cur.fetchone()
    # Lowercased, de-duped, blanks dropped.
    assert row["tags"] == ["algebra", "maths"]

    auth_client.post(f"/edit-card/{row['id']}", data={"question": "2+2?", "answer": "4", "tags": "maths"},
                     headers={"X-CSRF-Token": csrf_token}, follow_redirects=False)
    with db_conn.cursor() as cur:
        cur.execute("SELECT tags FROM cards WHERE id = %s", (row["id"],))
        assert cur.fetchone()["tags"] == ["maths"]

    # Manage shows the theme as a chip and feeds it to the search index.
    assert 'data-tags="maths"' in auth_client.get("/manage").text

@patch("main.supabase.auth.get_user")
def test_themed_review_narrows_the_same_due_queue(mock_get_user, client, db_conn):
    """A theme filters what is due — it never surfaces cards that aren't due,
    so the schedule is untouched."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="themedreview@example.com")
    maths = create_test_card(db_conn, user_id, "Maths due", "A")
    create_test_card(db_conn, user_id, "Physics due", "A")
    ahead = create_test_card(db_conn, user_id, "Maths not due", "A",
                             due_date=datetime.now() + timedelta(days=9))
    with db_conn.cursor() as cur:
        cur.execute("UPDATE cards SET tags = ARRAY['maths'] WHERE id IN (%s, %s)", (maths, ahead))
        db_conn.commit()

    card, counters, _ = crud.get_review_state_for_user(db_conn, user_id, tag="maths")
    assert card["id"] == maths                 # the due maths card
    assert counters["due_today"] == 1          # counters are scoped to the theme
    assert counters["total_cards"] == 2        # both maths cards, not the physics one

    # Unscoped, everything due is still there.
    _, all_counters, _ = crud.get_review_state_for_user(db_conn, user_id)
    assert all_counters["due_today"] == 2

    response = auth_client.get("/review?tag=maths")
    assert response.status_code == 200
    assert "Maths due" in response.text
    assert "Physics due" not in response.text

@patch("main.supabase.auth.get_user")
def test_themed_session_running_dry_does_not_claim_you_are_done(mock_get_user, client, db_conn):
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="themedone@example.com")
    create_test_card(db_conn, user_id, "Physics due", "A")  # due, untagged

    response = auth_client.get("/review?tag=maths")
    assert response.status_code == 200
    assert "No maths cards due" in response.text
    assert "still due elsewhere in your deck" in response.text
    assert "All Done!" not in response.text
    # Manage grows a Themes column only once some card carries a theme.
    assert 'class="tags-col"' not in auth_client.get("/manage").text

@patch("main.supabase.auth.get_user")
def test_focus_chips_only_offer_themes_with_work_waiting(mock_get_user, client, db_conn):
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="focuschips@example.com")
    due = create_test_card(db_conn, user_id, "Q", "A")
    later = create_test_card(db_conn, user_id, "Q2", "A2", due_date=datetime.now() + timedelta(days=9))
    with db_conn.cursor() as cur:
        cur.execute("UPDATE cards SET tags = ARRAY['maths'] WHERE id = %s", (due,))
        cur.execute("UPDATE cards SET tags = ARRAY['history'] WHERE id = %s", (later,))
        db_conn.commit()

    assert crud.get_due_tag_counts_for_user(db_conn, user_id) == [("maths", 1)]
    body = auth_client.get("/").text
    assert "/review?tag=maths" in body
    assert "/review?tag=history" not in body   # nothing due there, so it isn't offered

@patch("main.supabase.auth.get_user")
def test_generated_cards_inherit_the_courses_themes(mock_get_user, client, db_conn):
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="seedtags@example.com")
    auth_client.post(
        "/api/save-cards",
        json={"cards": [{"question": "Q", "answer": "A", "tags": ["Calculus", "maths"]}]},
        headers={"X-CSRF-Token": csrf_token},
    )
    with db_conn.cursor() as cur:
        cur.execute("SELECT tags FROM cards WHERE user_id = %s", (str(user_id),))
        assert cur.fetchone()["tags"] == ["calculus", "maths"]

@patch("main.supabase.auth.get_user")
def test_themes_hide_entirely_without_the_column(mock_get_user, client, db_conn, monkeypatch):
    """Same best-effort contract as folders and review_activity: the feature
    disappears rather than erroring when the migration hasn't run."""
    auth_client, user_id, _ = authenticate_client(mock_get_user, client, db_conn, email="notags@example.com")
    create_test_card(db_conn, user_id, "Only card here", "A")
    monkeypatch.setitem(crud._column_presence, ("cards", "tags"), False)

    assert crud.get_due_tag_counts_for_user(db_conn, user_id) == []
    assert 'name="tags"' not in auth_client.get("/new").text
    assert 'class="tags-col"' not in auth_client.get("/manage").text
    # A tag in the URL is ignored rather than yielding an empty session.
    response = auth_client.get("/review?tag=maths")
    assert response.status_code == 200
    assert "Only card here" in response.text

# --- Telegram Command Tests ---
# The handlers open their own pooled connection through linked_command, so
# every fixture write has to be committed before the handler is invoked.

def _fake_telegram_update(chat_id):
    """The pieces of telegram.Update the command handlers actually touch,
    plus a list that collects whatever they reply."""
    update = MagicMock()
    update.message.chat_id = chat_id
    sent = []

    async def reply_text(text, **kwargs):
        sent.append(text)

    update.message.reply_text = reply_text
    return update, sent

def _link_telegram(db_conn, auth_user_id, chat_id):
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE profiles SET telegram_chat_id = %s WHERE auth_user_id = %s",
            (str(chat_id), str(auth_user_id)),
        )
        db_conn.commit()

def test_telegram_due_reports_the_waiting_count(pg_container, db_conn):
    user_id = create_test_user(db_conn, email="tgdue@example.com")
    _link_telegram(db_conn, user_id, 4242)
    create_test_card(db_conn, user_id, "Q1", "A1")
    create_test_card(db_conn, user_id, "Q2", "A2")

    update, sent = _fake_telegram_update(4242)
    asyncio.run(bot.due_cards(update, MagicMock()))

    assert len(sent) == 1
    assert "2 cards due" in sent[0]
    assert "/review" in sent[0]

def test_telegram_due_when_nothing_is_waiting(pg_container, db_conn):
    user_id = create_test_user(db_conn, email="tgdueclear@example.com")
    _link_telegram(db_conn, user_id, 4243)
    create_test_card(db_conn, user_id, "Q", "A", due_date=datetime.now() + timedelta(days=3))

    update, sent = _fake_telegram_update(4243)
    asyncio.run(bot.due_cards(update, MagicMock()))

    assert "Nothing due" in sent[0]
    assert "/random" in sent[0]

def test_telegram_stats_reports_streak_and_counters(pg_container, db_conn):
    user_id = create_test_user(db_conn, email="tgstats@example.com")
    _link_telegram(db_conn, user_id, 4244)
    create_test_card(db_conn, user_id, "Q1", "A1")
    create_test_card(db_conn, user_id, "Q2", "A2", due_date=datetime.now() + timedelta(days=3))
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO review_activity (user_id, day, reviews, remembered) VALUES (%s, CURRENT_DATE, 3, 2)",
            (str(user_id),),
        )
        db_conn.commit()

    update, sent = _fake_telegram_update(4244)
    asyncio.run(bot.deck_stats(update, MagicMock()))

    message = sent[0]
    assert "Streak: 1 day" in message
    assert "Due today: 1" in message
    assert "Total: 2" in message
    # Today's activity row exists, so the at-risk warning must not fire.
    assert "on the line" not in message

def test_telegram_stats_warns_when_the_streak_is_at_risk(pg_container, db_conn):
    user_id = create_test_user(db_conn, email="tgrisk@example.com")
    _link_telegram(db_conn, user_id, 4245)
    create_test_card(db_conn, user_id, "Q", "A")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO review_activity (user_id, day, reviews, remembered)"
            " VALUES (%s, CURRENT_DATE - 1, 5, 4)",
            (str(user_id),),
        )
        db_conn.commit()

    update, sent = _fake_telegram_update(4245)
    asyncio.run(bot.deck_stats(update, MagicMock()))

    assert "Streak: 1 day" in sent[0]
    assert "on the line" in sent[0]

def test_telegram_stats_on_an_empty_deck(pg_container, db_conn):
    user_id = create_test_user(db_conn, email="tgempty@example.com")
    _link_telegram(db_conn, user_id, 4246)

    update, sent = _fake_telegram_update(4246)
    asyncio.run(bot.deck_stats(update, MagicMock()))

    assert "deck is empty" in sent[0]

def test_telegram_new_commands_require_a_linked_account(pg_container, db_conn):
    for handler in (bot.due_cards, bot.deck_stats):
        update, sent = _fake_telegram_update(999999)
        asyncio.run(handler(update, MagicMock()))
        assert sent == [bot.NOT_LINKED_MESSAGE]

def test_telegram_commands_are_registered(monkeypatch):
    # Canonical token shape; build() never talks to Telegram, only initialize() does.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    application = bot.get_bot_application()
    registered = {
        command
        for handlers in application.handlers.values()
        for handler in handlers
        for command in getattr(handler, "commands", ())
    }
    assert {"due", "stats"} <= registered

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

@patch("main.supabase.auth.get_user")
def test_change_password_verifies_the_email_for_deduplicated_usernames(mock_get_user, client, db_conn):
    """create_profile stores a colliding username as "email#authid8". The
    current-password check must still go to GoTrue with the bare email, or
    every attempt for such an account fails as "incorrect"."""
    auth_client, user_id, csrf_token = authenticate_client(mock_get_user, client, db_conn, email="pw_user3@example.com")
    with db_conn.cursor() as cur:
        cur.execute("UPDATE profiles SET username = %s WHERE auth_user_id = %s",
                    (f"pw_user3@example.com#{user_id[:8]}", user_id))
        db_conn.commit()
    with patch("main.httpx.post", return_value=_fake_httpx_response(200)) as mock_grant, \
         patch("main.httpx.put", return_value=_fake_httpx_response(200)):
        response = auth_client.post(
            "/auth/change-password",
            data={"current_password": "oldpassword1", "new_password": "newpassword1"},
            headers={"X-CSRF-Token": csrf_token},
        )
    assert response.json()["success"] is True
    assert mock_grant.call_args.kwargs["json"]["email"] == "pw_user3@example.com"
