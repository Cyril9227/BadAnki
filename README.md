# Bad Anki: A Smart Flashcard App

Bad Anki is a web-based, simplified clone of the Anki flashcard application, supercharged with AI and designed for efficient, long-term knowledge retention. It uses a spaced repetition system (SRS) to help you study and remember information, from complex math formulas to everyday facts.

The core workflow is simple: create courses from Markdown notes, let AI generate flashcards for you, and receive daily review reminders on Telegram.

## Key Features

*   **Spaced Repetition System (SRS):** Employs an SM-2 inspired algorithm to schedule card reviews at optimal intervals, maximizing memory retention.
*   **Secure, Multi-User Core:** Built on a secure, token-based (JWT) authentication system, ensuring each user's data is completely isolated and private.
*   **Collapsible Course UI:** A mobile-responsive, hierarchical navigation for your courses. This collapsible folder view keeps your content organized and easy to browse, whether you have one file or hundreds.
*   **Course & Card Management:** Easily create, edit, delete, and download courses through an intuitive web interface.
*   **Markdown & LaTeX Support:** Write or upload course content and flashcards using Markdown for formatting and LaTeX for complex mathematical notation.
*   **AI-Powered Card Generation:**
    *   **Multi-Provider Support:** Automatically generate flashcards from your notes using multiple AI providers (Gemini, Anthropic) or a local Ollama instance.
    *   **User-Managed API Keys:** A secure interface for users to add and manage their own API keys for different AI providers.
    *   **Approval Workflow:** Review, edit, or delete each AI-generated card before saving it to your collection, ensuring content quality.
*   **Telegram Integration:**
    *   Receive daily review reminders via a dedicated Telegram bot.
    *   Configure notifications by simply providing your Chat ID in the secure secrets manager.
    *   Interact with your cards using bot commands like `/random`.
*   **Admin Tools:** Includes secure, secret-protected API endpoints for administrators to trigger the scheduler or restart the bot without a full server reboot.

## Tech Stack

*   **Backend:** Python 3.10+ with [FastAPI](https://fastapi.tiangolo.com/)
*   **Frontend:** [Jinja2](https://jinja.palletsprojects.com/) Templates with [Bootstrap 5](https://getbootstrap.com/)
*   **Database:** PostgreSQL (Production) / SQLite (Local)
*   **Deployment:** [Render.com](https://render.com/) (Free Tier)
*   **LLM Integration:** `google-generativeai`, `anthropic`, `ollama`
*   **Telegram Bot:** `python-telegram-bot`

## Getting Started: Local Development

### 1. Prerequisites
- Python 3.10 or higher
- PostgreSQL (optional, for production-like setup) or SQLite
- An active Telegram account

### 2. Clone the Repository
```bash
git clone https://github.com/your-username/BadAnki.git
cd BadAnki
```

### 3. Create a Virtual Environment and Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows, use `.venv\Scripts\activate`
pip install -r requirements.txt
```

### 4. Set Up Environment Variables
Create a file named `.env` in the project root and add the following variables. You can generate a secure secret key using Python's `secrets` module.

```env
# A strong, randomly generated string for signing JWTs
SECRET_KEY="your_super_secret_key_here"

# The token for your Telegram bot from BotFather
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"

# A secret token to protect the webhook URL in production
TELEGRAM_WEBHOOK_SECRET="a_long_random_string_for_your_webhook"

# A secret to protect the scheduler's trigger endpoint
SCHEDULER_SECRET="another_strong_random_secret"

# A secret to protect the bot restart endpoint
BOT_RESTART_SECRET="a_final_strong_random_secret"

# For production deployment on Render, set this to your app's public URL
# Example: APP_URL="https://bad-anki.onrender.com"
APP_URL="http://127.0.0.1:8000"

# Set to "production" when deploying, otherwise it runs in development mode
ENVIRONMENT="development"
```

### 5. Initialize the Database
The application uses a PostgreSQL database in production but can use SQLite for local development if you do not have a PostgreSQL server. The `database.py` script will create the necessary tables.

```bash
python database.py
```

### 6. Run the Web Server
```bash
uvicorn main:app --reload
```
The application will be available at `http://127.0.0.1:8000`.

### 7. Run the Telegram Bot (for local testing)
In a separate terminal, activate the virtual environment and run the bot in polling mode. This allows you to test bot commands without setting up a webhook.
```bash
source .venv/bin/activate
python bot.py
```

## Deployment on Render

This application is designed for easy deployment on Render's free tier.

1.  **Create a new Web Service** on Render and connect it to your GitHub repository.
2.  **Set the Start Command:** To ensure stability with the Telegram bot's async operations, you must use a single Gunicorn worker.
    ```
    gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
    ```
3.  **Add Environment Variables:** Add all the variables from your `.env` file to the Render dashboard. Make sure to set `ENVIRONMENT` to `production` and update `APP_URL` to your Render service URL.
4.  **Set up the Scheduler:** The daily scheduler is triggered by an API endpoint. Use a free external cron job service (like [cron-job.org](https://cron-job.org/)) to send a daily GET request to the following endpoint:
    ```
    https://<your-app-url>/api/trigger-scheduler?secret=<your-scheduler-secret>
    ```

## Next Steps

*   **Update Database Schema File:** The `database.sql` file is currently out of sync with the actual database schema. It needs to be updated to serve as a reliable reference for setting up new environments.
*   **Code Quality & Security Audit:** Perform a thorough review of the codebase to refactor complex functions, ensure consistent style, and add robust error handling.
*   **Modern Frontend with Next.js:** Plan and execute a complete rewrite of the frontend using Next.js and TypeScript for a more modern, component-based, and maintainable UI.
