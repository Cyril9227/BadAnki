# Bad Anki - A Spaced Repetition Flashcard App

Bad Anki is a web-based flashcard application inspired by Anki, designed to help you study and remember information efficiently using a spaced repetition system. It features a clean, modern interface, multi-user support, and powerful tools for creating and managing your study materials.

![Bad Anki Screenshot](placeholder.png) <!-- Add a screenshot of the app here -->

## Key Features

*   **Spaced Repetition System (SRS):** Utilizes an algorithm inspired by SM-2 to schedule card reviews at optimal intervals, maximizing memory retention.
*   **Multi-User Authentication:** Securely manage your own private collection of courses and cards with a robust JWT-based authentication system.
*   **Course & Card Management:** Easily create, edit, and delete courses and flashcards through an intuitive web interface.
*   **Markdown & LaTeX Support:** Write your course content and flashcards using Markdown for formatting and LaTeX for mathematical notation.
*   **AI-Powered Card Generation:**
    *   **Gemini:** Leverage Google's Gemini Pro to automatically generate high-quality flashcards from your course notes.
    *   **Ollama (Local):** Generate cards offline using local language models like Llama 2.
*   **Telegram Integration:** Receive daily review reminders and interact with your cards via a dedicated Telegram bot.
*   **Themeable UI:** Switch between light and dark modes for a comfortable viewing experience.

## Tech Stack

*   **Backend:** Python 3.10+ with [FastAPI](https://fastapi.tiangolo.com/)
*   **Frontend:** [Jinja2](https://jinja.palletsprojects.com/) Templates with [Bootstrap 5](https://getbootstrap.com/)
*   **Database:** PostgreSQL (Production) / SQLite (Local)
*   **Deployment:** [Render.com](https://render.com/)
*   **LLM Integration:** `google-generativeai`, `ollama`
*   **Telegram Bot:** `python-telegram-bot`

## Getting Started

### Prerequisites

*   Python 3.10+
*   [uv](https://github.com/astral-sh/uv) (or pip) for package management
*   PostgreSQL (for production)

### Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/BadAnki.git
    cd BadAnki
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    uv pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    Create a `.env` file in the project root and add the following variables. A `SECRET_KEY` is required.

    ```env
    # Generate a secret key with: python -c 'import secrets; print(secrets.token_urlsafe(32))'
    SECRET_KEY="your_super_secret_key"

    # Required for AI card generation
    GEMINI_API_KEY="your_gemini_api_key"

    # Required for Telegram bot
    TELEGRAM_TOKEN="your_telegram_bot_token"
    TELEGRAM_CHAT_ID="your_telegram_chat_id"

    # Database URL (defaults to local SQLite if not set)
    # Example for PostgreSQL: DATABASE_URL="postgresql://user:password@host:port/dbname"
    ```

4.  **Initialize the database:**
    ```bash
    python database.py
    ```

5.  **Run the application:**
    ```bash
    uvicorn main:app --reload
    ```
    The application will be available at `http://127.0.0.1:8000`.

## Future Development

We're constantly working to improve Bad Anki. Here's a look at our long-term vision:

*   **Modern Frontend with Next.js:** A complete frontend rewrite using Next.js and TypeScript to create a beautiful, modern, and highly interactive user interface.
*   **Code Quality & Security Audit:** Ongoing efforts to refactor code, improve security, and enhance maintainability.
*   **Performance Optimization:** Analyzing and addressing performance bottlenecks to ensure a snappy user experience.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue to discuss your ideas.
