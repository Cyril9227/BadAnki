# (Bad) Anki

[intro to write] + [gif showing the app]


## Key Features

*   **Spaced Repetition System (SRS):** Utilizes an algorithm inspired by SM-2 to schedule card reviews at optimal intervals, maximizing memory retention.
*   **Secure, Multi-User Core:** The application is built on a secure, token-based (JWT) authentication system, with isolated data for each user.
*   **Course & Card Management:** Easily create, edit, and delete courses and flashcards through an intuitive web interface.
*   **Markdown & LaTeX Support:** Write or upload your course content and flashcards using Markdown for formatting and LaTeX for mathematical notation.
*   **AI-Powered Card Generation:**
    *   **Multi-Provider Support:** Automatically generate flashcards from your course notes using multiple AI providers.
        *   **Gemini:** Leverage Google's Gemini Pro for high-quality card generation.
        *   **Anthropic:** Use Anthropic's models for another source of AI-generated content.
        *   **Ollama (Local):** Generate cards offline using local language models like Llama 2.
    *   **Approval Workflow:** You can individually edit, delete, and approve each AI-generated card before saving them.
*   **Telegram Integration:** Receive daily review reminders via a dedicated Telegram bot. You can also interact with your saved cards with commands like `/random`.

## Core Technologies

*   **Backend:** Python 3.10+ with [FastAPI](https://fastapi.tiangolo.com/)
*   **Frontend:** [Jinja2](https://jinja.palletsprojects.com/) Templates with [Bootstrap 5](https://getbootstrap.com/)
*   **Database:** PostgreSQL (Production) / SQLite (Local)
*   **Deployment:** [Render.com](https://render.com/) (Free Tier)
*   **LLM Integration:** `google-generativeai`, `ollama`
*   **Telegram Bot:** `python-telegram-bot`

## Project Structure
```
/
├── main.py             # The main FastAPI application file.
├── bot.py              # Contains the logic for the Telegram bot.
├── crud.py             # Contains database create, read, update, and delete operations.
├── database.py         # Script to initialize the database schema.
├── scheduler.py        # Logic for sending daily review notifications.
├── GEMINI.md           # Gemini session documentation.
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
    Create a `.env` file in the project root. You will need to provide your own `SECRET_KEY`, and other keys for external services.

4.  **Initialize the database:**
    ```bash
    python database.py
    ```

5.  **Run the web server:**
    ```bash
    uvicorn main:app --reload
    ```
    The application will be available at `http://127.0.0.1:8000`.

6.  **Run the Telegram Bot (for local testing):**
    The bot can be tested independently by running:
    ```bash
    python bot.py
    ```

## Deployment on Render (Free Tier)

The application is designed to be deployed as a single web service on Render's free tier (or equivalent).

*   **Start Command:** To ensure the Telegram bot's webhook initializes correctly, you must use a single Gunicorn worker. Set your start command on the Render dashboard to:
    ```
    gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
    ```

*   **Scheduler:** The daily scheduler is triggered by an API endpoint. You can use a free external cron job service (like [cron-job.org](https://cron-job.org/)) to send a daily GET request to the following endpoint:
    ```
    https://<your-app-url>/api/trigger-scheduler?secret=<your-secret>
    ```
    You must set a `SCHEDULER_SECRET` environment variable for this to work.

## Next Steps

*   **Modern Frontend with Next.js:** Plan and execute a complete rewrite of the frontend using Next.js and TypeScript, leveraging a component-based architecture for a modern, fast, and maintainable UI.
*   **Code Quality & Security Audit:** Review and refactor the codebase to improve "snappiness", security, readability, and maintainability.
