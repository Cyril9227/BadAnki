# Gemini Agent Session Documentation

This document provides a comprehensive overview of the Anki Clone project, its structure, and the development session history. It is intended to be a reference for future Gemini agents and developers.

## 1. Project Overview

This project is a web-based, simplified clone of the Anki flashcard application. It uses a spaced repetition system (inspired by SM-2) to help users study and remember information efficiently. The application is built with Python using the FastAPI framework for the backend and Jinja2 templates for the frontend. It also includes a Telegram bot for user interaction.

## 2. Core Technologies

- **Backend:** Python 3.10+ with FastAPI
- **Frontend:** Jinja2 Templates with Bootstrap 5 CSS
- **Database:** SQLite
- **Telegram Bot:** `python-telegram-bot` library
- **Markdown Parsing:** `frontmatter` library for reading course files.
- **LLM Integration:** `google-generativeai` for card generation, `ollama` for local card generation.

## 3. Project Structure

```
/
├── anki.db             # The SQLite database file.
├── bot.py              # Contains the logic for the Telegram bot.
├── database.py         # Script to initialize the database schema.
├── main.py             # The main FastAPI application file.
├── gemini.md           # This documentation file.
├── courses/            # Directory containing course notes in Markdown.
│   └── ...
└── templates/          # Directory for all Jinja2 HTML templates.
    ├── layout.html         # Base template with navigation.
    ├── home.html           # The home page.
    ├── courses_list.html   # Page to list all courses.
    ├── course_viewer.html  # Page to display a single course.
    ├── course_editor.html  # The interactive course editor.
    ├── review.html         # The main card review interface.
    ├── new_card.html       # Form to create a new card.
    ├── manage_cards.html   # Page to view, edit, and delete all cards.
    ├── edit_card.html      # Form to edit an existing card.
    └── ...
```

## 4. Setup and Running the Application

### 1. Environment Setup with `uv`

It is recommended to use a virtual environment to manage project dependencies. This project uses `uv`, a fast Python package installer and resolver.

1.  **Create a Virtual Environment:**
    ```bash
    uv venv
    ```

2.  **Activate the Virtual Environment:**
    - On macOS and Linux: `source .venv/bin/activate`
    - On Windows (Git Bash): `source .venv/Scripts/activate`

3.  **Install Dependencies:**
    ```bash
    uv pip install -r requirements.txt
    ```

### 2. Running the Application

The application consists of two main components that must be run separately in two different terminals (after activating the virtual environment in each).

**Terminal 1: Run the FastAPI Web Server**

1.  **Set the Environment Variable:**
    You must set your Gemini API key as an environment variable.
    ```bash
    export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
    ```
2.  **Run the Server:**
    This command starts the web application. The `--reload` flag automatically restarts the server when code changes are detected.
    ```bash
    uvicorn main:app --reload
    ```
    The application will be available at `http://127.0.0.1:8000`.

**Terminal 2: Run the Telegram Bot**

1.  **Set the Environment Variable:**
    You must set your Telegram bot token as an environment variable.
    ```bash
    export TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_TOKEN"
    ```
2.  **Run the Bot Script:**
    ```bash
    python bot.py
    ```

## 5. Agent Session Summary (As of 2025-09-06)

This documentation is kept current with the latest agentic coding session. Key actions performed recently include:

1.  **UI Overhaul:**
    - Replaced the old Bootstrap navigation with a modern, animated menu inspired by the `animated-menu` components.
    - Implemented a new color scheme with support for both light and dark modes, including a theme toggle switch.
    - Updated the home page and other components to use a consistent, modern card-based design.

2.  **Local Card Generation with Ollama:**
    - Integrated the `ollama` library to enable local, private card generation as an alternative to the Gemini API.
    - Added a new `/api/generate-cards-ollama` endpoint to the backend to handle requests.
    - Added a "Generate with Ollama" button to the course editor UI for a seamless user experience.

3.  **Deployment Preparation:**
    - Implemented a `scheduler.py` script that checks for due cards and sends a daily review reminder via Telegram.
    - Added a `/myid` command to the Telegram bot (`bot.py`) for users to easily retrieve their chat ID.
    - Prepared the application for production deployment by adding `gunicorn`, externalizing all secrets and configurations to use environment variables.
    - Created a `Procfile` to define the web and worker processes for the hosting platform.
    - Created a `render.yaml` file to enable "Infrastructure as Code" deployment on the Render platform, defining the web server, bot, persistent disk, and cron job.
    - Modified the database connection logic (`database.py`, `scheduler.py`) to use a persistent disk path when deployed, ensuring data is not lost on restarts.

4.  **Live Deployment and Data Management:**
    - Successfully deployed the entire application stack (web app, bot, cron job) to the Render platform.
    - Resolved database connection issues by enforcing SSL and correcting table creation sequences.
    - Created robust data management scripts:
        - `migrate_db.py`: For migrating data from a local SQLite DB to the production PostgreSQL DB.
        - `backup_db.py`: For creating a local CSV backup of the production database.
        - `restore_db.py`: For restoring data from a CSV backup to a new database instance, ensuring data persistence beyond the limits of free hosting plans.

## 6. Local Card Generation with Ollama

To use a local model for card generation, you need to have Ollama installed and running on your machine.

### 1. Install Ollama

Follow the official instructions to download and install Ollama for your operating system: [https://ollama.ai/](https://ollama.ai/)

### 2. Run a Model

Once Ollama is installed, you need to pull and run a model. We recommend `llama2` for this application.

```bash
ollama run llama2
```

This command will download the model (if you don't have it already) and start the Ollama server. You must keep this terminal window open while using the local generation feature.

### 3. Generate Cards

With the Ollama server running, you can now use the "Generate with Ollama" button in the course editor to generate cards locally.

## 7. Next Steps & Known Issues

The application is live, but there are several areas for improvement and features to address.

### 1. Priority: Activate Telegram Cron Job
The highest priority is to ensure the daily review notification cron job, defined in `render.yaml` and `scheduler.py`, is running correctly on the live server and sending messages via Telegram. This is a core feature of the application's feedback loop.

### 2. Fix Card Management Bugs
- **Edit Functionality:** The "Edit" button in the "Manage Cards" menu is currently not working. This needs to be fixed to allow users to correct or update their flashcards.

### 3. Rework the Course Editor
- **Filesystem Dependency:** The current course editor is designed to work with the local filesystem (the `courses/` directory), which does not work on a stateless hosting platform like Render.
- **Future Work:** This entire feature needs to be re-architected. A potential solution is to store course content in the database instead of in Markdown files. This is a larger project for a future session.

### 4. Future UI Enhancements
- A new, more modern frontend built with Next.js and TypeScript has been proposed as a long-term goal to replace the current Jinja2 templates.

## 8. Next Steps

Progress has been made towards fixing the folders / tree stucture in deployment scenarios. Issues are still present. Once it's fixed, need to setup cronjob on https://cron-job.org/en/ and refactor code to use Next.js and TypeScript