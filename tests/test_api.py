import os
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer
import psycopg2
from psycopg2.extras import RealDictCursor

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
        cur = conn.cursor()
        with open("database.sql") as f:
            cur.execute(f.read())
        conn.commit()
        cur.close()
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
    cur = db_conn.cursor()
    # Truncate all tables before each test in the correct order (due to foreign keys)
    try:
        cur.execute("""
            TRUNCATE TABLE cards, courses, user_api_keys, user_secrets, users RESTART IDENTITY CASCADE;
        """)
        db_conn.commit()
    except Exception as e:
        print(f"[WARN] Could not truncate tables: {e}")
        # Try individual table truncation as fallback
        try:
            tables = ['cards', 'courses', 'user_api_keys', 'user_secrets', 'users']
            for table in tables:
                cur.execute(f"DELETE FROM {table};")
            db_conn.commit()
        except Exception as e2:
            print(f"[WARN] Could not delete from tables: {e2}")
    cur.close()
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
def get_authenticated_client(client, username="testuser", password="password123"):
    """Helper to register and login a user, returning an authenticated client."""
    client.post(
        "/register",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    client.post(
        "/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return client

# --- Authentication Tests ---
def test_logout(client):
    # Register and login
    get_authenticated_client(client, "logoutuser", "password123")
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
    auth_client = get_authenticated_client(client)
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
    auth_client = get_authenticated_client(client, "coursetest", "password123")
    response = auth_client.get("/api/courses-tree")
    assert response.status_code == 200
    assert response.json() == []

def test_create_and_list_course_file(client):
    auth_client = get_authenticated_client(client, "coursetest2", "password123")
    
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
    auth_client = get_authenticated_client(client, "coursetest3", "password123")
    
    # Create a folder
    response_create = auth_client.post("/api/course-item", json={"path": "my_folder", "type": "folder"})
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
    auth_client = get_authenticated_client(client, "coursetest4", "password123")
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
    auth_client = get_authenticated_client(client, "coursetest5", "password123")
    auth_client.post("/api/course-item", json={"path": "folder_to_delete", "type": "folder"})

    # Delete the folder
    response_delete = auth_client.request("DELETE", "/api/course-item", json={"path": "folder_to_delete", "type": "folder"})
    assert response_delete.status_code == 200
    assert response_delete.json() == {"success": True}

    # Check the tree is empty
    response_tree = auth_client.get("/api/courses-tree")
    assert response_tree.status_code == 200
    assert response_tree.json() == []

def test_save_and_get_course_content(client):
    auth_client = get_authenticated_client(client, "contentuser", "password123")
    
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

