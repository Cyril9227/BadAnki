# Anki Clone Testing Plan

This document outlines the testing strategy for the Anki Clone application. The goal is to ensure the application is robust, reliable, and free of regressions. We will use `pytest` as the testing framework and `httpx` for testing the FastAPI endpoints.

# IMPORTANT 

MAKE SURE TO NEVER, EVER INTERACT WITH PRODUCTION DATABASE. EVERYTHING MUST BE HANDLED WITH `from testcontainers.postgres import PostgresContainer`

The production database and the code interacting with it seems out of sync. Need to adapt the code and tests to reflect the state of production database : 


badiankidb=> \dt
               List of relations
 Schema |    Name     | Type  |      Owner
--------+-------------+-------+-----------------
 public | cards       | table | badiankidb_user
 public | course_tags | table | badiankidb_user
 public | courses     | table | badiankidb_user
 public | tags        | table | badiankidb_user
 public | users       | table | badiankidb_user



 badiankidb=> \d courses
                                        Table "public.courses"
   Column   |            Type             | Collation | Nullable |               Default
------------+-----------------------------+-----------+----------+-------------------------------------
 id         | integer                     |           | not null | nextval('courses_id_seq'::regclass)
 user_id    | integer                     |           | not null |
 path       | text                        |           | not null |
 content    | text                        |           |          |
 updated_at | timestamp without time zone |           |          | CURRENT_TIMESTAMP
Indexes:
    "courses_pkey" PRIMARY KEY, btree (id)
    "courses_user_id_path_key" UNIQUE CONSTRAINT, btree (user_id, path)
Foreign-key constraints:
    "courses_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id)




## 1. API Endpoint Tests (Integration Tests)

These tests will cover the main user flows and API interactions. We will use a separate test database to avoid interfering with development data.

-   **Authentication:**
    -   [ ] `POST /login`: Test successful login with correct credentials.
    -   [ ] `POST /login`: Test failed login with incorrect credentials.
    -   [ ] `POST /register`: Test successful user registration.
    -   [ ] `POST /register`: Test registration with a username that already exists.
    -   [ ] `POST /register`: Test registration with an invalid password (e.g., too short).
    -   [ ] `GET /logout`: Test successful logout.
-   **Course Management:**
    -   [ ] `GET /courses`: Test that an authenticated user can access the courses page.
    -   [ ] `GET /api/courses-tree`: Test fetching the course tree for a user.
    -   [ ] `POST /api/course-item`: Test creating a new file.
    -   [ ] `POST /api/course-item`: Test creating a new folder.
    -   [ ] `DELETE /api/course-item`: Test deleting a file.
    -   [ ] `DELETE /api/course-item`: Test deleting a folder.
    -   [ ] `POST /api/course-content`: Test saving course content.
    -   [ ] `GET /api/course-content/{path}`: Test retrieving course content.
-   **Card Management:**
    -   [ ] `GET /manage`: Test that an authenticated user can access the card management page.
    -   [ ] `POST /new`: Test creating a new card.
    -   [ ] `POST /edit-card/{card_id}`: Test updating an existing card.
    -   [ ] `POST /delete/{card_id}`: Test deleting a card.
-   **Review:**
    -   [ ] `GET /review`: Test fetching a card for review.
    -   [ ] `POST /review/{card_id}`: Test updating a card's review status.
-   **AI Card Generation:**
    -   [ ] `POST /api/generate-cards`: Test card generation with valid content (mocking the AI service).
    -   [ ] `POST /api/generate-cards`: Test card generation with empty content.
    -   [ ] `POST /api/save-cards`: Test saving generated cards.
-   **Secrets & API Keys:**
    -   [ ] `POST /api/save-api-keys`: Test saving user API keys.
    -   [ ] `POST /secrets`: Test saving user secrets (e.g., Telegram Chat ID).

## 2. CRUD Function Tests (Unit Tests)

These tests will focus on the functions in `crud.py`. We will mock the database connection to test the logic in isolation.

-   **User Functions:**
    -   [ ] `create_user`: Test that a user is created with a properly hashed password.
    -   [ ] `get_user_by_username`: Test retrieving a user.
    -   [ ] `verify_password`: Test password verification logic.
-   **Course Functions:**
    -   [ ] `get_courses_tree_for_user`: Test the logic for building the hierarchical course tree.
    -   [ ] `get_all_tags_for_user`: Test tag extraction from course content.
-   **Card Functions:**
    -   [ ] `update_card_for_user`: Test the spaced repetition algorithm logic.
        -   [ ] Test with `remembered=True`.
        -   [ ] Test with `remembered=False`.
    -   [ ] `get_review_cards_for_user`: Test that only due cards are returned.

## 3. Authentication & Authorization

-   [ ] Test that unauthenticated users are redirected to the login page from protected routes.
-   [ ] Test that a user cannot access or modify data belonging to another user.
-   [ ] Test JWT creation and decoding.

## 4. Telegram Bot

-   [ ] Test the `/start` command handler.
-   [ ] Test the `/review` command handler.
-   [ ] Test the `/random` command handler for a registered user.
-   [ ] Test the `/random` command handler for an unregistered user.

## 5. Scheduler

-   [ ] `get_users_with_due_cards`: Test that the function correctly identifies users with due cards.
-   [ ] `run_scheduler`: Test the main scheduler logic (mocking the Telegram Bot).

## 6. Debugging Session (2025-09-26)

### Progress
1.  **Initial `KeyError: 0` Failures:** The initial test run showed a large number of failures with `KeyError: 0`. This was diagnosed as a mismatch between the database cursor configuration in the test environment and the application code. The tests were using `RealDictCursor` (returning dictionary-like rows) while the application code in `crud.py` sometimes expected tuples.
2.  **Cursor Correction:** The issue was resolved by removing the global `cursor_factory` from the `db_conn` fixture in `tests/test_api.py` and instead explicitly using `cursor_factory=DictCursor` within the specific test functions and helpers that required dictionary-style access to database rows.
3.  **Spaced Repetition Logic:** Corrected a bug in the `update_card_for_user` function in `crud.py` where the `due_date` was not being correctly calculated, causing the `test_update_review_status` to fail.
4.  **Deprecation Warnings:** Fixed several `DeprecationWarning`s in `main.py` related to the `TemplateResponse` signature, ensuring the `request` object is passed as the first parameter.

### Remaining Challenges
After fixing the initial issues, a new set of failures appeared:

1.  **`psycopg2.errors.ForeignKeyViolation`:** Multiple tests related to creating courses and cards are failing because the `user_id` is not being correctly passed to the `INSERT` statements. This points to an underlying issue where the `user` object, retrieved from the request state, is likely a tuple instead of a dictionary-like object, causing `user['id']` to fail.
    -   **Next Step:** The highest priority is to ensure that all `crud.py` functions that fetch user data return dictionary-like rows. This involves adding `cursor_factory=extras.DictCursor` to every `conn.cursor()` call in `crud.py` where data is being read.

2.  **`TypeError: tuple indices must be integers or slices, not str`:** This occurs in `test_save_api_keys` and `test_save_secrets`. It's a direct symptom of the same problem causing the foreign key violations. The code is attempting to access `user['id']` on a tuple.
    -   **Next Step:** This will be resolved by the same fix mentioned above.

3.  **`AssertionError` in `test_update_card` and `test_delete_card`:** These tests are failing because the database state after the update/delete operation is not what the test expects. This is likely a side effect of the inconsistent `user` object and cursor issues.
    -   **Next Step:** After fixing the primary cursor issue in `crud.py`, these tests should be re-run and re-evaluated. The fix might resolve them automatically.

4.  **`AssertionError` in `test_get_review_page_with_due_card`:** The test fails because the expected question text ("Review Q") is not found in the HTML response. This could be due to the card not being created correctly (due to the foreign key issue) or a problem with how the review page template is rendering the data.
    -   **Next Step:** Investigate after the foreign key violation is fixed.