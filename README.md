# (Bad) Anki: A Smart Flashcard App

(Bad) Anki is a web-based, simplified clone of the popular Anki flashcard application, designed to help you study and remember information efficiently. It leverages a spaced repetition system (SRS) inspired by the SM-2 algorithm to optimize your learning process. The application is built with a modern Python backend, a simple and effective frontend, and includes powerful features like AI-powered card generation and Telegram integration for daily review reminders.

The workflow is simple and powerful:

> Learn something cool → write or upload a Markdown file (with LaTeX support) → use an AI provider (Gemini, Anthropic) or a local Ollama instance to generate relevant Anki cards → review, edit, and approve the AI-generated cards → the cards are added to your deck, and the spaced repetition algorithm schedules them for review → receive a daily reminder on Telegram with a link to the cards that are due.

## Key Features

*   **Course & Card Management:** Easily create, edit, delete, and download courses and flashcards through an intuitive and mobile-responsive web interface.
*   **Markdown & LaTeX Support:** Write your course content and flashcards using Markdown for formatting and LaTeX for mathematical and scientific notation.
*   **AI-Powered Card Generation:**
    *   **Multi-Provider Support:** Automatically generate flashcards from your course notes using multiple AI providers, including Google's Gemini, Anthropic's Claude, and local models via Ollama.
    *   **Approval Workflow:** Review, edit, and approve each AI-generated card before it's added to your deck, ensuring the quality of your study material.
*   **Spaced Repetition System (SRS):** Utilizes an algorithm inspired by SM-2 to schedule card reviews at optimal intervals, maximizing memory retention.
*   **Secure, Multi-User Core:** Built on a secure, token-based (JWT) authentication system, ensuring that your data is private and isolated.
*   **Telegram Integration:** Receive daily review reminders via a dedicated Telegram bot. You can also interact with your cards using commands like `/random` to get a random card.

## Core Technologies

*   **Backend:** Python 3.10+ with [FastAPI](https://fastapi.tiangolo.com/)
*   **Frontend:** [Jinja2](https://jinja.palletsprojects.com/) Templates with [Bootstrap 5](https://getbootstrap.com/)
*   **Database:** PostgreSQL (Production) / SQLite (Local)
*   **Deployment:** [Render.com](https://render.com/) (Free Tier)
*   **LLM Integration:** `google-generativeai`, `anthropic`, `ollama`
*   **Telegram Bot:** `python-telegram-bot`

## Project Structure

```
/
├── main.py             # The main FastAPI application file.
├── bot.py              # Contains the logic for the Telegram bot.
├── crud.py             # Contains database create, read, update, and delete operations.
├── database.py         # Script to initialize the database schema.
├── scheduler.py        # Logic for sending daily review notifications.
├── requirements.txt    # Python dependencies.
└── templates/          # Directory for all Jinja2 HTML templates.
    └── ...
```

## Local Development

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/BadAnki.git
    cd BadAnki
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    Create a `.env` file in the project root. You will need to provide your own `SECRET_KEY`, `DATABASE_URL`, and other keys for external services.

4.  **Initialize the database:**
    ```bash
    python database.py
    ```

5.  **Run the web server:**
    ```bash
    uvicorn main:app --reload
    ```
    The application will be available at `http://1227.0.0.1:8000`.

6.  **Run the Telegram Bot (for local testing):**
    The bot can be tested independently by running:
    ```bash
    python bot.py
    ```

## Deployment on Render (Free Tier)

The application is designed to be deployed as a single web service on Render's free tier.

*   **Start Command:** To ensure the Telegram bot's webhook initializes correctly, you must use a single Gunicorn worker. Set your start command on the Render dashboard to:
    ```
    gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
    ```

*   **Scheduler:** The daily scheduler is triggered by an API endpoint. You can use a free external cron job service (like [cron-job.org](https://cron-job.org/)) to send a daily GET request to the following endpoint:
    ```
    https://<your-app-url>/api/trigger-scheduler?secret=<your-secret>
    ```
    You must set a `SCHEDULER_SECRET` environment variable for this to work.

## Database Management

The project includes scripts for backing up and restoring the PostgreSQL database.

*   **Backup:** To create a full backup of the database, run the following command:
    ```bash
    python utils/full_backup.py
    ```
    This will create a timestamped backup file in the project's root directory.

*   **Restore:** To restore the database from a backup file, run:
    ```bash
    python utils/full_restore.py <backup-file.sql>
    ```

## Next Steps

*   **Add Unit Tests & CI/CD:** Implement a testing framework (like `pytest`) to create unit and integration tests for the backend API. Set up a CI/CD pipeline (e.g., using GitHub Actions) to automatically run tests on each push.
*   **Code Quality & Security Audit:** Perform a thorough review of the codebase to identify areas for improvement, including refactoring, ensuring consistent coding style, and verifying that all external inputs are properly sanitized.
*   **CSRF Protection:** Implement CSRF protection across the application to prevent cross-site request forgery attacks.
*   **Modern Frontend with Next.js:** Plan and execute a complete rewrite of the frontend using Next.js and TypeScript for a more modern, fast, and maintainable UI.

## Caveats

*   Currently only handles Markdown files. Support for other formats like PDFs could be added in the future.
*   The project was developed without a strong test suite or CI/CD pipeline, so there may be some undiscovered bugs.
*   The link between courses is based on a rudimentary tagging system.
*   Local LLM calls for card generation can sometimes fail due to JSON parsing issues.