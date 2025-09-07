# Gemini Agent Session Documentation

This document provides a comprehensive overview of the Anki Clone project, its structure, and the development session history. It is intended to be a reference for future Gemini agents and developers.

## 1. Project Overview

This project is a web-based, simplified clone of the Anki flashcard application. It uses a spaced repetition system (inspired by SM-2) to help users study and remember information efficiently. The application is built with Python using the FastAPI framework for the backend and Jinja2 templates for the frontend. It also includes a Telegram bot for user interaction.

## 2. Core Technologies

- **Backend:** Python 3.10+ with FastAPI
- **Frontend:** Jinja2 Templates with Bootstrap 5 CSS
- **Database:** PostgreSQL (production), SQLite (local)
- **Telegram Bot:** `python-telegram-bot` library
- **Markdown Parsing:** `frontmatter` library for course content.
- **LLM Integration:** `google-generativeai` for card generation, `ollama` for local card generation.
- **Deployment:** Render.com

## 3. Project Structure

The project is organized into a main FastAPI application (`main.py`), a Telegram bot (`bot.py`), database scripts, and Jinja2 templates. Course content, previously stored in local Markdown files, is now managed in a PostgreSQL database to support a stateless deployment environment.

```
/
├── main.py             # The main FastAPI application file.
├── bot.py              # Contains the logic for the Telegram bot.
├── crud.py             # Contains database create, read, update, and delete operations.
├── database.py         # Script to initialize the database schema.
├── scheduler.py        # Logic for sending daily review notifications.
├── GEMINI.md           # This documentation file.
├── requirements.txt    # Python dependencies.
├── render.yaml         # Infrastructure as Code for deployment on Render.
└── templates/          # Directory for all Jinja2 HTML templates.
    └── ...
```

## 4. Setup and Running the Application

(Instructions for local setup with `uv` and environment variables remain the same and can be found in previous versions if needed.)

## 5. Current Status (As of 2025-09-07)

The application is live and core features are fully functional. The recent development sessions have focused on stabilizing the application, migrating to a database-driven architecture, and fixing bugs.

### Key Accomplishments:
- **Database-driven Courses:** The application now stores and manages all course content and flashcards directly in the production PostgreSQL database, removing the dependency on the local filesystem. This was a critical step for successful deployment.
- **Functional Core Components:**
    - **Card & Course Management:** Users can successfully create, view, edit, and delete courses and their associated flashcards.
    - **Review System:** The spaced repetition logic for reviewing cards is operational.
    - **Telegram Cron Job:** The daily scheduler is active and correctly sends review notifications to users via Telegram.
    - **LaTeX Rendering:** Mathematical formulas written in LaTeX are correctly rendered on the frontend.
- **Bug Fixes:** Resolved a critical routing bug that prevented the "Edit Course" functionality from working correctly.
- **Deployment:** The application, including the web server, Telegram bot, and cron job, is successfully deployed and running on Render.

## 6. Next Steps & Future Vision

With the core functionality now stable, the next development phase will focus on enhancing the application's security, performance, and user experience.

### Immediate Priorities for the Next Session:
1.  **Implement Authentication:** Introduce a robust authentication module to protect the application. Currently, all endpoints are public, allowing anyone with the URL to modify data. This is the highest priority.
2.  **Code Quality & Security Audit:**
    - Review the codebase to implement best practices for security (e.g., input validation, preventing SQL injection, securing endpoints).
    - Refactor and clean up the code to improve readability and maintainability.
3.  **Performance Optimization:** Analyze and address performance bottlenecks to improve the application's "snapiness" and overall user experience.

### Long-Term Vision:
- **Modern Frontend with Next.js:** Plan and execute a complete rewrite of the frontend using Next.js and TypeScript. The goal is to create a beautiful, modern, and highly interactive user interface, moving away from the current server-side rendered Jinja2 templates.
