# [(Bad) Anki](https://bad-anki.vercel.app/)

(Bad) Anki is a web-based adaptation of the popular Anki flashcard application, designed to help you study and remember information efficiently. It leverages a spaced repetition system (SRS) inspired by the SM-2 algorithm to optimize your learning process. The application is built with a modern Python backend, a simple and effective frontend, and includes powerful features like AI-powered card generation and Telegram integration for daily review reminders.

The workflow is simple and powerful:

> Learn something cool → write or upload a Markdown file (with LaTeX support) → use an AI provider (Gemini, Anthropic) or a local Ollama instance to generate relevant Anki cards → review, edit, and approve the AI-generated cards → the cards are added to your deck, and the spaced repetition algorithm schedules them for review → receive a daily reminder on Telegram with a link to the cards that are due.

## Key Features

*   **Course & Card Management:** Easily create, edit, delete, and download courses and flashcards through an intuitive and mobile-responsive web interface.
*   **Markdown & LaTeX Support:** Write your course content and flashcards using Markdown for formatting and LaTeX for mathematical and scientific notation.
*   **AI-Powered Card Generation:**
    *   **Multi-Provider Support:** Automatically generate flashcards from your course notes using multiple AI providers, including Google's Gemini, Anthropic's Claude, and local models via Ollama.
    *   **Approval Workflow:** Review, edit, and approve each AI-generated card before it's added to your deck, ensuring the quality of your study material.
*   **Spaced Repetition System (SRS):** Utilizes an algorithm inspired by SM-2 to schedule card reviews at optimal intervals, maximizing memory retention.
*   **Secure, Multi-User Architecture:** Built on [Supabase](https://supabase.com/) for authentication and database, ensuring your data is private and isolated.
*   **Telegram Integration:** Receive daily review reminders via a dedicated Telegram bot. You can also interact with your cards using commands like `/random` to get a random card.

## Core Technologies

*   **Backend:** Python 3.12+ with [FastAPI](https://fastapi.tiangolo.com/)
*   **Frontend:** [Jinja2](https://jinja.palletsprojects.com/) Templates with [Bootstrap 5](https://getbootstrap.com/)
*   **Database & Auth:** [Supabase](https://supabase.com/) (PostgreSQL + Authentication)
*   **Deployment:** [Vercel](https://vercel.com/)
*   **LLM Integration:** `google-generativeai`, `anthropic`, `ollama`
*   **Telegram Bot:** `python-telegram-bot`

## Project Structure

```
/
├── main.py             # The main FastAPI application file.
├── bot.py              # Contains the logic for the Telegram bot.
├── crud.py             # Database create, read, update, and delete operations.
├── database.py         # Database connection pool management.
├── database.sql        # SQL schema for Supabase.
├── middleware.py       # CSRF protection middleware.
├── scheduler.py        # Logic for sending daily review notifications.
├── requirements.txt    # Python dependencies.
├── vercel.json         # Vercel deployment configuration.
├── api/
│   └── cron.py         # Vercel cron job handler for daily notifications.
├── static/             # Static assets (favicon, etc.).
├── templates/          # Jinja2 HTML templates.
├── tests/              # Test suite.
└── utils/              # Utility scripts (backup, restore, parsing).
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
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    Create a `.env` file in the project root with the following variables:
    ```
    SECRET_KEY=your-secret-key
    DATABASE_URL=your-supabase-postgres-connection-string
    SUPABASE_URL=https://your-project.supabase.co
    SUPABASE_KEY=your-supabase-anon-key
    SCHEDULER_SECRET=your-scheduler-secret
    TELEGRAM_BOT_TOKEN=your-telegram-bot-token
    TELEGRAM_WEBHOOK_SECRET=your-webhook-secret
    TELEGRAM_BOT_USERNAME=your-bot-username
    APP_URL=http://localhost:8000
    ```

4.  **Run the web server:**
    ```bash
    uvicorn main:app --reload
    ```
    The application will be available at `http://127.0.0.1:8000`.

5.  **Run tests:**
    ```bash
    pytest
    ```

## Deployment on Vercel

The application is deployed on Vercel with the following configuration:

*   **Region:** Singapore (`sin1`) - configured in `vercel.json`
*   **Cron Job:** Daily scheduler runs at 01:00 UTC via Vercel Crons

### Environment Variables

Set the following environment variables in your Vercel project settings:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Secret key for session management |
| `DATABASE_URL` | Supabase PostgreSQL connection string |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/public key |
| `SCHEDULER_SECRET` | Secret for triggering the scheduler |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Secret for webhook validation |
| `TELEGRAM_BOT_USERNAME` | Your Telegram bot's username |
| `APP_URL` | Your deployed app URL (e.g., `https://bad-anki.vercel.app`) |
| `ENVIRONMENT` | Set to `production` |

## Database Management

The project includes scripts for backing up and restoring the PostgreSQL database.

*   **Backup:** To create a full backup of the database:
    ```bash
    python utils/full_backup.py
    ```

*   **Restore:** To restore the database from a backup file:
    ```bash
    python utils/full_restore.py <backup-file.sql>
    ```

## Caveats

*   Currently only handles Markdown files. Support for other formats like PDFs could be added in the future.
*   Vibe coded! There may be some undiscovered bugs.
*   The link between courses is based on a rudimentary tagging system.
*   Local LLM calls for card generation can sometimes fail due to JSON parsing issues.
