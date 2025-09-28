# Anki Clone Testing Plan

This document outlines the testing strategy for the Anki Clone application. The goal is to ensure the application is robust, reliable, and free of regressions. We will use `pytest` as the testing framework and `httpx` for testing the FastAPI endpoints.

# IMPORTANT 

MAKE SURE TO NEVER, EVER INTERACT WITH PRODUCTION DATABASE. EVERYTHING MUST BE HANDLED WITH `from testcontainers.postgres import PostgresContainer`


## 1. API Endpoint Tests (Integration Tests)

These tests will cover the main user flows and API interactions. We will use a separate test database to avoid interfering with development data.

-   **Authentication:**
    -   [x] `POST /login`: Test successful login with correct credentials.
    -   [x] `POST /login`: Test failed login with incorrect credentials.
    -   [x] `POST /register`: Test successful user registration.
    -   [x] `POST /register`: Test registration with a username that already exists.
    -   [x] `POST /register`: Test registration with an invalid password (e.g., too short).
    -   [x] `GET /logout`: Test successful logout.
-   **Course Management:**
    -   [x] `GET /courses`: Test that an authenticated user can access the courses page.
    -   [x] `GET /api/courses-tree`: Test fetching the course tree for a user.
    -   [x] `POST /api/course-item`: Test creating a new file.
    -   [x] `POST /api/course-item`: Test creating a new folder.
    -   [x] `DELETE /api/course-item`: Test deleting a file.
    -   [x] `DELETE /api/course-item`: Test deleting a folder.
    -   [x] `POST /api/course-content`: Test saving course content.
    -   [x] `GET /api/course-content/{path}`: Test retrieving course content.
-   **Card Management:**
    -   [x] `GET /manage`: Test that an authenticated user can access the card management page.
    -   [x] `POST /new`: Test creating a new card.
    -   [x] `POST /edit-card/{card_id}`: Test updating an existing card.
    -   [x] `POST /delete/{card_id}`: Test deleting a card.
-   **Review:**
    -   [x] `GET /review`: Test fetching a card for review.
    -   [x] `POST /review/{card_id}`: Test updating a card's review status.
-   **AI Card Generation:**
    -   [x] `POST /api/generate-cards`: Test card generation with valid content (mocking the AI service).
    -   [x] `POST /api/generate-cards`: Test card generation with empty content.
    -   [x] `POST /api/save-cards`: Test saving generated cards.
-   **Secrets & API Keys:**
    -   [x] `POST /api/save-api-keys`: Test saving user API keys.
    -   [x] `POST /secrets`: Test saving user secrets (e.g., Telegram Chat ID).

## 2. CRUD Function Tests (Unit Tests)

These tests will focus on the functions in `crud.py`. We will mock the database connection to test the logic in isolation.

-   **User Functions:**
    -   [x] `create_user`: Test that a user is created with a properly hashed password.
    -   [x] `get_user_by_username`: Test retrieving a user.
    -   [x] `verify_password`: Test password verification logic.
-   **Course Functions:**
    -   [x] `get_courses_tree_for_user`: Test the logic for building the hierarchical course tree.
    -   [x] `get_all_tags_for_user`: Test tag extraction from course content.
-   **Card Functions:**
    -   [x] `update_card_for_user`: Test the spaced repetition algorithm logic.
        -   [x] Test with `remembered=True`.
        -   [x] Test with `remembered=False`.
    -   [x] `get_review_cards_for_user`: Test that only due cards are returned.

## 3. Authentication & Authorization

-   [x] Test that unauthenticated users are redirected to the login page from protected routes.
-   [x] Test that a user cannot access or modify data belonging to another user.
-   [x] Test JWT creation and decoding.

## 4. Telegram Bot

-   [x] Test the `/start` command handler.
-   [x] Test the `/review` command handler.
-   [x] Test the `/random` command handler for a registered user.
-   [x] Test the `/random` command handler for an unregistered user.

## 5. Scheduler

-   [x] `get_users_with_due_cards`: Test that the function correctly identifies users with due cards.
-   [x] `run_scheduler`: Test the main scheduler logic (mocking the Telegram Bot).

# Next Steps :
- Implement CI/CD via github actions 