# Anki Clone Testing Plan

This document outlines the testing strategy for the Anki Clone application. The goal is to ensure the application is robust, reliable, and free of regressions. We will use `pytest` as the testing framework and `httpx` for testing the FastAPI endpoints.

# IMPORTANT 

MAKE SURE TO NEVER, EVER INTERACT WITH PRODUCTION DATABASE. EVERYTHING MUST BE HANDLED WITH `from testcontainers.postgres import PostgresContainer`

Database Schema Inconsistencies
Your database schema in database.sql has different field names than what your CRUD functions expect. For example:

CRUD expects ease_factor but schema has easiness_factor
CRUD expects interval but schema has repetition_level
Missing fields like telegram_chat_id in users table, updated_at in courses table

Remove every mention of sqlite for testing in database.py


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
