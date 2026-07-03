# [(Bad) Anki](https://bad-anki.vercel.app/)

So it's like Anki but badly vibe-coded. Main interesting thing is that you get daily updates / reminders on telegram, and the cards support $LaTeX$ / code blocks. There is also an experimental feature where you can upload a markdown file (let's say notes from a maths course) and have an AI automatically generate the relevant Anki cards. 

## 🔄 The Learning Loop

> **Learn something cool**
> 
> → Write Markdown (LaTeX, code blocks etc.)  
> → AI generates Anki cards  
> → You review & approve  
> → Spaced repetition schedules reviews  
> → Daily Telegram reminder  
> → **Back to learning !**


## Key Features

*   **Cards & Courses:** Create, edit and review Markdown/LaTeX flashcards (basic and cloze) through a mobile-friendly web UI.
*   **AI Card Generation:** Generate cards from your course notes with Gemini or Claude — review and approve each card before it lands in your deck.
*   **Spaced Repetition:** SM-2-inspired scheduling decides when each card comes back.
*   **Streaks & Leaderboard:** Daily review streaks (with a Telegram nudge when one is at stake) and a 30-day leaderboard keep the habit fun.
*   **Telegram Bot:** Daily review reminders and in-chat reviews, with fully rendered LaTeX/code answers and tap-to-reveal cloze blanks.
*   **Multi-User:** [Supabase](https://supabase.com/) auth + row-level security keep each user's data isolated.

## Tech Stack

Python 3.12+ / [FastAPI](https://fastapi.tiangolo.com/) · [Jinja2](https://jinja.palletsprojects.com/) + [Bootstrap 5](https://getbootstrap.com/) · [Supabase](https://supabase.com/) (PostgreSQL + Auth) · `python-telegram-bot` · deployed on [Vercel](https://vercel.com/)

## Project Structure

```
/
├── main.py             # FastAPI app and routes
├── bot.py              # Telegram bot logic
├── crud.py             # Database operations
├── database.py         # Connection pool management
├── database.sql        # Supabase schema (tables + RLS policies)
├── middleware.py       # CSRF and request-size protection
├── scheduler.py        # Daily review notifications
├── telegram_format.py  # Card rendering for Telegram (MarkdownV2, cloze)
├── render_auth.py      # Signed tokens for the card image renderer
├── api/
│   ├── cron.py         # Vercel cron entrypoint
│   └── render-card.js  # Renders card answers to images (Puppeteer)
├── templates/          # Jinja2 templates
├── tests/              # Test suite (see documentation/TESTING.md)
└── utils/              # Parsing helpers + backup/restore scripts
```

## Local Development

```bash
git clone https://github.com/Cyril9227/BadAnki.git
cd BadAnki
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload  # app at http://127.0.0.1:8000
pytest                     # run the tests
```

Create the database by running `database.sql` in the Supabase SQL Editor (it creates the tables and RLS policies), and add a `.env` file with the variables below.

## Environment Variables

The same set is used locally (`.env`) and in the Vercel project settings:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Secret key for session management |
| `DATABASE_URL` | Supabase PostgreSQL connection string |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anon/publishable key (see note below) |
| `SCHEDULER_SECRET` | Secret for triggering the scheduler |
| `CRON_SECRET` | Secret protecting the Vercel cron endpoint |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Secret for webhook validation |
| `TELEGRAM_BOT_USERNAME` | Your Telegram bot's username |
| `APP_URL` | App URL (`http://localhost:8000` locally, deployed URL in prod) |
| `ENVIRONMENT` | Set to `production` on Vercel |

`SUPABASE_ANON_KEY` must be the public anon/publishable key, never the
service-role or `sb_secret_...` key (`SUPABASE_KEY` is still accepted as a
legacy fallback). Optional: `GEMINI_API_KEY` seeds new user profiles with a
default Gemini key.

## Deployment

Deployed on Vercel (region `sin1`, configured in `vercel.json`). A Vercel cron
hits `/api/cron` daily at 01:00 UTC to send review reminders.

## Backup & Restore

```bash
python utils/full_backup.py                     # pg_dump the whole database
python utils/full_restore.py <backup-file.sql>  # restore from a backup
```

## Caveats

*   Currently only handles Markdown files. Support for other formats like PDFs could be added in the future.
*   Vibe coded! There may be some undiscovered bugs.
*   Local LLM calls for card generation can sometimes fail due to JSON parsing issues.


## TODO / IDEAS:
- [ ] Better links between courses etc rather than basic tags
- [ ] Better documentation
- [x] Gamified experience (streaks + leaderboard) — more running user statistics could follow
- [ ] Make LLM calls as robust as possible / handle different providers
- [ ] Handle different doc type PDF etc.
- [ ] Maybe notebookLM integration to turn courses into podcasts ?
- [ ] Quizz to solidify learning
- [ ] Refactor app with NextJS / tailwind etc. to leverage beautiful community templates @ v0
