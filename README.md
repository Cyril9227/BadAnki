
## TO-DO 

- [x] Add positive feedback in the UI (mobile / Desktop) for actions : register, login, add secrets, add cards etc.
- [x] Add basic security for users, not same username, strong password etc.
- [x] Check that when pple add secrets like telegram chat ID it is correctly added to database, currently can only find mine while i registered my other tg account
- [ ] Blog
- [ ] Ajouter tests + CI/CD
- [ ] Revoir codebase et virer les trucs pour eviter usine a gaz
- [ ] Voir comment backup localement la bdd / avoir un truc facile a spin avec un autre provider


# [(Bad) Anki](https://badanki.onrender.com/)

I'm often forgetting stuff when I solve maths problems for fun, so I thought it would be cool to vibe-code a personal knowledge management tool tailored to my needs, while also learning more about best software engineering practices, agentic coding, and (local) generative AI usage.

I think this project covers each aim quite well: I get some kind of Anki clone connected to my Telegram that forces me to remember maths concepts, theorems etc. while I also get to experiment with a wide range of skills: frontend, backend, database & multi-users management, cloud deployment, cron jobs, Telegram bot scripting, as well as using generative AI through API providers or locally via Ollama.

The workflow is basically: 

>learn something cool → write or upload a Markdown file (with LaTeX support) → use any AI provider or local Ollama to generate relevant Anki cards → delete / edit / approve AI-generated cards → cards are added to the database and the spaced repetition algorithm decides which ones are due for review → I get a daily ping on Telegram with a link to the relevant cards due for review.


## Key Features

*   **Course & Card Management:** Easily create, edit, delete or download courses and flashcards through an intuitive web interface and fully responsive mobile UI.
*   **Markdown & LaTeX Support:** Write or upload your course content and flashcards using Markdown for formatting and LaTeX for mathematical notation.
*   **AI-Powered Card Generation:**
    *   **Multi-Provider Support:** Automatically generate flashcards from your course notes using multiple AI providers.
        *   **Gemini:** Leverage Google's Gemini Pro for high-quality card generation.
        *   **Anthropic:** Use Anthropic's models for another source of AI-generated content.
        *   **Ollama (Local):** Generate cards offline using local language models like Llama 2.
    *   **Approval Workflow:** You can individually edit, delete, and approve each AI-generated card before saving them.
*   **Spaced Repetition System (SRS):** Utilizes an algorithm inspired by SM-2 to schedule card reviews at optimal intervals, maximizing memory retention.
*   **Secure, Multi-User Core:** The application is built on a secure, token-based (JWT) authentication system, with isolated data for each user.
*   **Telegram Integration:** Receive daily review reminders via a dedicated Telegram bot. You can also interact with your saved cards with commands like `/random`.

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


## Caveats 
- Only handles markdown files, would be sweet to have it also parse PDF files etc.
- Entirely vibe-coded without any kind of strong test suite / CI-CD pipeline, it's bound to break at some point lol
- Rudimentary link between courses through tags
- Local LLM call to generate cards *sometimes* bug because of weird JSON parsing, need to take a look / change default ollama model


