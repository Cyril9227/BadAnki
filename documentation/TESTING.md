# BadAnki Testing Documentation

This document describes the testing strategy, infrastructure, and test coverage for the BadAnki application.

## Testing Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Framework** | pytest | Test runner and assertions |
| **HTTP Client** | FastAPI TestClient | API endpoint testing |
| **Database** | testcontainers (PostgreSQL 15) | Ephemeral test database |
| **Mocking** | unittest.mock | Supabase auth, LLM APIs |

## Test Infrastructure

### Ephemeral Database with Testcontainers

Tests run against a real PostgreSQL database spun up in Docker. This ensures:
- Tests use the actual database schema (`database.sql`)
- No mock database behavior differences
- Complete isolation from development/production data

```python
@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:15") as postgres:
        url = postgres.get_connection_url()
        os.environ["DATABASE_URL"] = url

        # Initialize schema
        conn = psycopg2.connect(url)
        with conn.cursor() as cur:
            # Create mock Supabase auth schema
            cur.execute("CREATE SCHEMA auth;")
            cur.execute("CREATE TABLE auth.users (id UUID PRIMARY KEY, email VARCHAR(255));")

            # Run application schema
            with open("database.sql") as f:
                cur.execute(f.read())

        yield postgres
```

### Test Isolation

Each test starts with clean tables via automatic truncation:

```python
@pytest.fixture(autouse=True)
def truncate_tables(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE cards, courses, profiles RESTART IDENTITY CASCADE;")
        db_conn.commit()
```

### Authentication Mocking

Since Supabase handles authentication, we mock the auth layer:

```python
def authenticate_client(mock_get_user, client, db_conn, email="testuser@example.com"):
    # Create user in test database
    auth_user_id = create_test_user(db_conn, email=email)

    # Mock Supabase auth response
    mock_user = MagicMock()
    mock_user.id = str(auth_user_id)
    mock_user.email = email
    mock_get_user.return_value = MagicMock(user=mock_user)

    # Set auth cookie
    client.cookies.set("access_token", "fake-test-token")
    csrf_token = get_csrf_token(client)

    return client, str(auth_user_id), csrf_token
```

## Test Coverage

### Authentication Tests (`test_api.py`)

| Test | Description | Status |
|------|-------------|--------|
| `test_auth_login_successfully` | Login with correct credentials redirects to /review | :white_check_mark: |
| `test_auth_login_incorrect_password` | Wrong password shows error message | :white_check_mark: |
| `test_auth_login_user_not_found_prompts_register` | Non-existent user prompted to register | :white_check_mark: |
| `test_auth_register_successfully` | New user registration creates profile | :white_check_mark: |
| `test_get_auth_page` | Auth page loads with OAuth buttons | :white_check_mark: |
| `test_logout` | Logout clears cookies and redirects | :white_check_mark: |
| `test_health_check` | Health endpoint returns ok status | :white_check_mark: |

### Course Management Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_get_courses_page_authenticated` | Authenticated user can access courses | :white_check_mark: |
| `test_get_courses_page_unauthenticated` | Unauthenticated user redirected to /auth | :white_check_mark: |
| `test_get_courses_tree_empty` | Empty course tree returns [] | :white_check_mark: |
| `test_create_and_list_course_file` | Create file and verify in tree | :white_check_mark: |
| `test_delete_course_file` | Delete file removes from tree | :white_check_mark: |
| `test_save_and_get_course_content` | Save and retrieve course content | :white_check_mark: |

### Card Management Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_get_manage_cards_page_authenticated` | Card management page accessible | :white_check_mark: |
| `test_create_card` | Create new card via form | :white_check_mark: |
| `test_update_card` | Update existing card content | :white_check_mark: |
| `test_delete_card` | Delete card removes from database | :white_check_mark: |

### Review Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_get_review_page_with_due_card` | Shows due card for review | :white_check_mark: |
| `test_get_review_page_no_due_cards` | Shows "All Done!" when no cards due | :white_check_mark: |
| `test_update_review_status` | Review updates due_date | :white_check_mark: |

### AI Card Generation Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_generate_cards_api_success` | Card generation with mocked LLM | :white_check_mark: |
| `test_generate_cards_api_empty_content` | Empty content returns 400 | :white_check_mark: |
| `test_save_generated_cards` | Batch save generated cards | :white_check_mark: |

### Secrets & API Keys Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_save_api_keys` | Save Gemini/Anthropic API keys | :white_check_mark: |
| `test_save_secrets` | Save Telegram chat ID | :white_check_mark: |

### Scheduler Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_trigger_scheduler_success` | Scheduler endpoint triggers correctly | :white_check_mark: |
| `test_trigger_scheduler_invalid_secret` | Invalid secret returns 403 | :white_check_mark: |

### Smoke Tests (`test_main.py`)

| Test | Description | Status |
|------|-------------|--------|
| `test_read_main` | Home page accessible without auth | :white_check_mark: |

## CI/CD Pipeline

### GitHub Actions Workflow (`.github/workflows/ci.yml`)

Tests run automatically on pull requests to `main`:

```yaml
name: Python CI

on:
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Set up Python 3.10
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: Install Dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Run Tests
      run: pytest
      env:
        ENVIRONMENT: "test"
        SECRET_KEY: ${{ secrets.SECRET_KEY }}
        SCHEDULER_SECRET: ${{ secrets.SCHEDULER_SECRET }}
        TELEGRAM_WEBHOOK_SECRET: ${{ secrets.TELEGRAM_WEBHOOK_SECRET }}
        SUPABASE_URL: "http://localhost:8000"
        SUPABASE_KEY: "dummy-key"
```

### Required GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `SECRET_KEY` | Application secret for JWT/sessions |
| `SCHEDULER_SECRET` | Auth for scheduler endpoint |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook URL validation |

### Running Tests Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_api.py

# Run specific test
pytest tests/test_api.py::test_auth_login_successfully

# Run with coverage
pytest --cov=. --cov-report=html
```

### Docker Requirement

Tests require Docker to be running for testcontainers:

```bash
# Verify Docker is running
docker ps

# If using Docker Desktop, ensure it's started
```

## Test Design Principles

### 1. Real Database Testing
Use testcontainers instead of mocking database calls. This catches SQL errors, constraint violations, and schema issues.

### 2. Minimal Mocking
Only mock external services (Supabase auth, LLM APIs). Database operations use real PostgreSQL.

### 3. Test Isolation
Each test runs with truncated tables. No test depends on another test's state.

### 4. CSRF Token Handling
All POST requests include CSRF tokens obtained via GET request:

```python
csrf_token = get_csrf_token(client)  # Makes GET request, extracts cookie
response = client.post("/endpoint", headers={"X-CSRF-Token": csrf_token}, ...)
```

### 5. Authentication Pattern
Tests requiring auth use the `authenticate_client` helper which:
- Creates user in test database
- Mocks Supabase auth response
- Sets access_token cookie
- Returns CSRF token

## Future Test Improvements

- [ ] Add tests for Telegram bot command handlers
- [ ] Add tests for spaced repetition algorithm edge cases
- [ ] Add integration tests for OAuth callback flow
- [ ] Add performance tests for large card decks
- [ ] Add tests for course tree hierarchy with nested folders
- [ ] Add tests for tag extraction and filtering
