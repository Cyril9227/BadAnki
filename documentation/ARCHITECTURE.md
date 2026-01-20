# BadAnki Architecture Documentation

This document provides an in-depth overview of BadAnki's architecture, design decisions, and implementation details. It serves as both developer documentation and educational material for understanding the system design.

## Table of Contents

1. [System Overview](#system-overview)
2. [Technology Stack](#technology-stack)
3. [Project Structure](#project-structure)
4. [Database Design](#database-design)
5. [Course Management System](#course-management-system)
6. [Tags System](#tags-system)
7. [Authentication & Authorization](#authentication--authorization)
8. [API Design](#api-design)
9. [Middleware Architecture](#middleware-architecture)
10. [Frontend Architecture](#frontend-architecture)
11. [LLM Integration](#llm-integration)
12. [Telegram Bot Integration](#telegram-bot-integration)
13. [Background Jobs & Scheduling](#background-jobs--scheduling)
14. [Deployment Architecture](#deployment-architecture)
15. [Testing Strategy](#testing-strategy)
16. [Design Patterns & Principles](#design-patterns--principles)
17. [Security Considerations](#security-considerations)
18. [Performance Considerations](#performance-considerations)
19. [Error Handling Patterns](#error-handling-patterns)
20. [Interview Discussion Points](#interview-discussion-points)
21. [Known Limitations & Future Improvements](#known-limitations--future-improvements)

---

## System Overview

BadAnki is a **spaced repetition learning application** that helps users create, manage, and review flashcards using the scientifically-proven spaced repetition technique. The application supports:

- **Manual card creation** through a web interface
- **AI-powered card generation** from course content using multiple LLM providers
- **Daily review reminders** via Telegram bot integration
- **Course management** with Markdown support and LaTeX rendering

### High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Browser    │    │   Telegram   │    │  Mobile Web  │                   │
│  │   (Desktop)  │    │     App      │    │   Browser    │                   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                   │
└─────────┼───────────────────┼───────────────────┼───────────────────────────┘
          │                   │                   │
          │ HTTPS             │ Webhook           │ HTTPS
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           APPLICATION LAYER (Vercel)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     FastAPI Application (main.py)                     │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │   │
│  │  │   CSRF     │  │  Security  │  │    Auth    │  │     DB     │      │   │
│  │  │ Middleware │──│  Headers   │──│ Middleware │──│ Middleware │      │   │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘      │   │
│  │         │                                                             │   │
│  │         ▼                                                             │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │                        Route Handlers                           │  │   │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │  │   │
│  │  │  │   Auth   │ │  Review  │ │  Courses │ │   Cards  │           │  │   │
│  │  │  │  Routes  │ │  Routes  │ │  Routes  │ │  Routes  │           │  │   │
│  │  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │  Telegram Bot   │  │    Scheduler    │  │   Cron Handler  │              │
│  │    (bot.py)     │  │ (scheduler.py)  │  │  (api/cron.py)  │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    Supabase     │  │   LLM APIs      │  │   Telegram API  │
│  ┌───────────┐  │  │  ┌───────────┐  │  │                 │
│  │PostgreSQL │  │  │  │  Gemini   │  │  │  Bot Commands   │
│  │           │  │  │  │  Claude   │  │  │  Notifications  │
│  │  Auth     │  │  │  │  Ollama   │  │  │  Webhooks       │
│  └───────────┘  │  │  └───────────┘  │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
     DATA LAYER           EXTERNAL             MESSAGING
                          SERVICES             LAYER
```

---

## Technology Stack

### Backend

| Component | Technology | Why This Choice |
|-----------|------------|-----------------|
| **Web Framework** | FastAPI 0.116 | Async support, automatic OpenAPI docs, type hints, dependency injection |
| **ASGI Server** | Uvicorn | High-performance async server, production-ready |
| **Database** | PostgreSQL (via Supabase) | Reliable, scalable, excellent for relational data |
| **ORM/DB Access** | psycopg2 (raw SQL) | Direct control, no ORM overhead, explicit queries |
| **Authentication** | Supabase Auth + JWT | Managed auth service, OAuth support, secure token handling |
| **Template Engine** | Jinja2 | Powerful, familiar, integrates well with FastAPI |

### Frontend

| Component | Technology | Why This Choice |
|-----------|------------|-----------------|
| **CSS Framework** | Bootstrap 5.3 | Responsive, well-documented, rapid development |
| **Icons** | Font Awesome 6.5 | Comprehensive icon library |
| **Markdown** | Marked.js | Fast, extensible markdown parsing |
| **Math Rendering** | MathJax | Industry standard for LaTeX rendering |
| **Alerts** | SweetAlert2 | Beautiful, customizable dialogs |

### External Services

| Service | Purpose |
|---------|---------|
| **Supabase** | Database hosting, authentication, user management |
| **Google Gemini** | Primary LLM for card generation |
| **Anthropic Claude** | Alternative LLM provider |
| **Ollama** | Local/self-hosted LLM option |
| **Telegram Bot API** | Notifications and card review via chat |
| **Vercel** | Serverless hosting with cron support |

---

## Project Structure

```
BadAnki/
├── main.py                 # Application entry point, routes, middleware setup
├── crud.py                 # Database operations (Create, Read, Update, Delete)
├── database.py             # Connection pooling and database utilities
├── database.sql            # Schema definition
├── middleware.py           # CSRF protection, security headers
├── bot.py                  # Telegram bot handlers
├── scheduler.py            # Daily notification scheduler
│
├── api/
│   └── cron.py             # Vercel cron job endpoint
│
├── templates/              # Jinja2 HTML templates
│   ├── layout.html         # Base template with common elements
│   ├── review.html         # Card review interface
│   ├── course_editor.html  # Markdown editor with AI generation
│   └── ...
│
├── static/
│   └── favicon.ico         # Static assets (minimal - CDN for libraries)
│
├── utils/
│   ├── parsing.py          # JSON/LaTeX parsing utilities
│   └── ...
│
├── tests/
│   ├── test_api.py         # Comprehensive API tests
│   └── test_main.py        # Smoke tests
│
├── requirements.txt        # Python dependencies
├── vercel.json             # Deployment configuration
└── pytest.ini              # Test configuration
```

### Design Decision: File Organization

The project uses a **flat structure** for the main application code rather than a deeply nested package structure. This choice was made because:

1. **Simplicity** - For a medium-sized application, flat structure reduces cognitive overhead
2. **Import clarity** - No complex relative imports
3. **Serverless compatibility** - Simpler module resolution in serverless environments
4. **Refactoring ease** - Easy to split into packages later if needed

---

## Database Design

### Entity-Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Supabase auth.users                         │
│  (Managed by Supabase - stores email, password hash, etc.)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 1:1
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         profiles                                 │
├─────────────────────────────────────────────────────────────────┤
│  auth_user_id (PK, FK)  │ UUID    │ Links to Supabase auth      │
│  username               │ TEXT    │ Display name (unique)        │
│  telegram_chat_id       │ TEXT    │ For bot notifications        │
│  gemini_api_key         │ TEXT    │ User's Gemini API key        │
│  anthropic_api_key      │ TEXT    │ User's Anthropic API key     │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │ 1:N                           │ 1:N
              ▼                               ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│          cards              │   │         courses              │
├─────────────────────────────┤   ├─────────────────────────────┤
│  id (PK)      │ SERIAL      │   │  id (PK)      │ SERIAL      │
│  question     │ TEXT        │   │  path         │ TEXT        │
│  answer       │ TEXT        │   │  content      │ TEXT        │
│  due_date     │ TIMESTAMP   │   │  updated_at   │ TIMESTAMP   │
│  interval     │ INT         │   │  user_id (FK) │ UUID        │
│  ease_factor  │ FLOAT4      │   └─────────────────────────────┘
│  user_id (FK) │ UUID        │
└─────────────────────────────┘

Constraints:
- profiles.auth_user_id REFERENCES auth.users(id) ON DELETE CASCADE
- cards.user_id REFERENCES auth.users(id) ON DELETE CASCADE
- courses.user_id REFERENCES auth.users(id) ON DELETE CASCADE
- courses UNIQUE(user_id, path) -- Each user has unique course paths
```

### Spaced Repetition Fields

The `cards` table implements the **SM-2 algorithm** (SuperMemo 2):

| Field | Purpose | Initial Value |
|-------|---------|---------------|
| `due_date` | When the card should be reviewed next | Now (immediate review) |
| `interval` | Days until next review | 0 (new card) |
| `ease_factor` | Multiplier for interval calculation | 2.5 (default difficulty) |

**Algorithm Constants (crud.py):**
```python
EASE_FACTOR_MODIFIER = 0.1   # Increase EF on correct answer
MIN_EASE_FACTOR = 1.3        # Minimum EF (prevents too-easy cards)
EASE_FACTOR_PENALTY = 0.2    # Decrease EF on incorrect answer
INITIAL_INTERVAL = 1         # Reset to 1 day on "forgot"
```

**Review Logic:**
```python
def update_card_for_user(conn, card_id, auth_user_id, remembered: bool):
    if remembered:
        # Increase interval: next_interval = current_interval * ease_factor
        interval = max(1, int(interval * ease_factor))
        ease_factor += EASE_FACTOR_MODIFIER  # Card becomes "easier"
    else:
        # Reset interval to 1 day
        interval = INITIAL_INTERVAL
        ease_factor = max(MIN_EASE_FACTOR, ease_factor - EASE_FACTOR_PENALTY)

    next_due_date = now() + timedelta(days=interval)
```

### Design Decision: Raw SQL vs ORM

We use **raw SQL with psycopg2** instead of an ORM like SQLAlchemy because:

1. **Transparency** - Exact queries are visible and debuggable
2. **Performance** - No ORM overhead, direct database communication
3. **Simplicity** - Schema is simple enough that ORM abstraction adds complexity
4. **Learning** - Understanding raw SQL is valuable for optimization

**Trade-offs:**
- More boilerplate for CRUD operations
- Manual handling of connections and cursors
- No automatic migrations (we use manual SQL scripts)

---

## Course Management System

### Hierarchical Course Structure

Courses are stored as flat rows in the database but presented as a hierarchical file tree in the UI. This design simplifies database queries while providing a familiar folder/file navigation experience.

**Database Storage (Flat):**
```
id | path                          | content    | user_id
---|-------------------------------|------------|--------
1  | Math/Calculus                 | "# Calc.." | uuid-1
2  | Math/LinearAlgebra            | "# LA..."  | uuid-1
3  | Math/.placeholder             | ""         | uuid-1
4  | CS/Algorithms/Sorting         | "# Sort.." | uuid-1
5  | CS/Algorithms/.placeholder    | ""         | uuid-1
```

**UI Presentation (Tree):**
```
Math/
├── Calculus
├── LinearAlgebra
└── (folder marker via .placeholder)
CS/
└── Algorithms/
    ├── Sorting
    └── (folder marker)
```

### The `.placeholder` Pattern

**Problem:** How do you represent empty folders in a database that only stores files?

**Solution:** Create a hidden `.placeholder` file inside empty directories.

```python
def create_course_item_for_user(conn, path: str, item_type: str, auth_user_id: str):
    if item_type == 'file':
        cursor.execute(
            "INSERT INTO courses (path, content, user_id) VALUES (%s, %s, %s)",
            (path, "---\ntitle: New Course\ntags: \n---\n\n", auth_user_id)
        )
    elif item_type in ['directory', 'folder']:
        # Create a placeholder file to represent the folder
        placeholder_path = os.path.join(path, ".placeholder")
        cursor.execute(
            "INSERT INTO courses (path, content, user_id) VALUES (%s, %s, %s)",
            (placeholder_path, "This is a placeholder file.", auth_user_id)
        )
```

**Benefits:**
- No schema changes needed (folders are virtual)
- Cascading deletes work naturally (delete `path/%` removes all children)
- Tree building is purely a presentation concern

### Tree Building Algorithm

The `get_courses_tree_for_user()` function constructs a hierarchical tree from flat paths:

```python
def get_courses_tree_for_user(conn, auth_user_id: str):
    # 1. Fetch all courses sorted by path
    cursor.execute("SELECT path, content FROM courses WHERE user_id = %s ORDER BY path", ...)

    nodes = {}
    for course in courses:
        path = course['path']
        is_placeholder = os.path.basename(path) == '.placeholder'

        # Strip .placeholder from path for directory detection
        if is_placeholder:
            path = os.path.dirname(path)

        # 2. Build nodes for each path segment
        path_parts = path.split(os.sep)
        for i in range(len(path_parts)):
            current_path = os.path.join(*path_parts[:i+1])

            if current_path not in nodes:
                is_dir = (i < len(path_parts) - 1) or is_placeholder
                node = {
                    "name": path_parts[i],
                    "path": current_path,
                    "type": "directory" if is_dir else "file",
                    "depth": i,
                    "children": []
                }

                # 3. Extract title from frontmatter for files
                if not is_dir:
                    post = frontmatter.loads(course['content'])
                    node['title'] = post.metadata.get('title', path_parts[i])

                nodes[current_path] = node

                # 4. Link to parent
                parent_path = os.path.dirname(current_path)
                if parent_path in nodes:
                    nodes[parent_path]['children'].append(node)

    # 5. Return root nodes (no parent)
    return [node for path, node in nodes.items() if os.path.dirname(path) == '']
```

**Time Complexity:** O(n × m) where n = number of courses, m = average path depth

### Frontmatter Markdown Format

Course content uses YAML frontmatter for metadata:

```markdown
---
title: Introduction to Calculus
tags: math, calculus, derivatives
---

## Limits

A limit describes the value a function approaches...

### Definition

$$\lim_{x \to a} f(x) = L$$
```

**Parsing with python-frontmatter:**
```python
import frontmatter

post = frontmatter.loads(course['content'])
title = post.metadata.get('title', 'Untitled')
tags = post.metadata.get('tags', '')  # Can be string or list
body = post.content  # The markdown content
```

**Why Frontmatter?**
- Industry standard (Jekyll, Hugo, Gatsby all use it)
- Clean separation of metadata and content
- Easy to parse and extend
- Human-readable and editable

---

## Tags System

### Overview

Tags provide a cross-cutting way to organize courses beyond the hierarchical folder structure. A course about "Linear Algebra" in the Math folder might be tagged with both `math` and `machine-learning`.

### Tag Storage

Tags are embedded in course frontmatter, not a separate table:

```markdown
---
title: Neural Networks
tags: machine-learning, deep-learning, math
---
```

**Design Decision:** Embedded vs. Normalized Tags

| Approach | Pros | Cons |
|----------|------|------|
| **Embedded (chosen)** | Simple schema, no joins, easy editing | Duplicate storage, harder to rename globally |
| **Normalized (separate table)** | Efficient queries, easy bulk operations | More complex schema, requires joins |

For a personal learning app with modest data volumes, embedded tags are simpler and sufficient.

### Tag Operations

**Extracting All Tags:**
```python
def get_all_tags_for_user(conn, auth_user_id: str):
    cursor.execute("SELECT content FROM courses WHERE user_id = %s", ...)

    all_tags = set()
    for course in courses:
        post = frontmatter.loads(course['content'])
        all_tags.update(sanitize_tags(post.metadata.get('tags')))

    return sorted(list(all_tags))
```

**Tag Sanitization:**
```python
def sanitize_tags(tags):
    """Normalize tags to lowercase, trimmed, unique, sorted list."""
    if not tags:
        return []

    if isinstance(tags, list):
        tag_list = [str(t).strip().lower() for t in tags]
    elif isinstance(tags, str):
        tag_list = [t.strip().lower() for t in tags.split(',')]

    return sorted(list(set(tag_list)))
```

**Why Sanitize?**
- Consistent casing prevents "Math" and "math" being treated as different tags
- Trimming handles user input errors ("  math  " → "math")
- Deduplication ensures clean data
- Sorting provides consistent UI ordering

### Tag-Based Navigation

```python
@app.get("/tags/{tag_name}", response_class=HTMLResponse)
async def view_courses_by_tag(request: Request, tag_name: str, ...):
    courses = crud.get_courses_by_tag_for_user(conn, tag_name, user.auth_user_id)
    return templates.TemplateResponse(request, "tag_courses.html", {
        "tag": tag_name,
        "courses": courses
    })
```

---

## Authentication & Authorization

### Authentication Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        AUTHENTICATION FLOW                                    │
└──────────────────────────────────────────────────────────────────────────────┘

EMAIL/PASSWORD LOGIN:
┌────────┐     POST /auth      ┌────────────┐   sign_in_with_password   ┌──────────┐
│ Client │ ──────────────────► │  FastAPI   │ ────────────────────────► │ Supabase │
│        │                     │            │                           │   Auth   │
│        │ ◄────────────────── │            │ ◄──────────────────────── │          │
│        │   Set-Cookie:       │            │   JWT access_token        │          │
│        │   access_token      │            │   + user info             │          │
└────────┘                     └────────────┘                           └──────────┘

OAUTH LOGIN (Google/GitHub):
┌────────┐    GET /auth         ┌────────────┐                         ┌──────────┐
│ Client │ ───────────────────► │  Supabase  │ ──────────────────────► │  OAuth   │
│        │   (OAuth button)     │   Auth UI  │   Redirect to provider  │ Provider │
│        │                      │            │                         │          │
│        │ ◄─────────────────── │            │ ◄────────────────────── │          │
│        │ Redirect to          │            │   Auth code             │          │
│        │ /auth/callback       │            │                         │          │
└────────┘                      └────────────┘                         └──────────┘
    │
    │ POST /auth/callback (with code)
    ▼
┌────────────┐   exchange_code_for_session   ┌──────────┐
│  FastAPI   │ ────────────────────────────► │ Supabase │
│            │                               │   Auth   │
│            │ ◄──────────────────────────── │          │
│            │   JWT tokens + user info      │          │
└────────────┘                               └──────────┘
```

### Session Management

**Token Storage:**
- JWT stored in `access_token` HttpOnly cookie
- 7-day expiration (configured via Supabase)
- Secure flag enabled in production (HTTPS only)
- SameSite=Lax to prevent CSRF on cross-site requests

**Request Authentication (middleware):**
```python
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    conn = get_db_connection()
    request.state.db = conn

    # Authenticate user from JWT cookie
    user = await get_current_user(request, conn)
    request.state.user = user

    response = await call_next(request)
    release_db_connection(conn)
    return response
```

### Profile Creation (Idempotent)

When a user authenticates, we ensure their profile exists:

```python
def ensure_user_profile(conn, auth_user_id, email, default_gemini_key):
    cursor.execute("""
        INSERT INTO profiles (auth_user_id, username, gemini_api_key)
        VALUES (%s, %s, %s)
        ON CONFLICT (auth_user_id) DO NOTHING
        RETURNING auth_user_id
    """, (auth_user_id, email.split('@')[0], default_gemini_key))

    is_new_user = cursor.fetchone() is not None
    return is_new_user
```

**Why ON CONFLICT DO NOTHING?**
- Safe to call on every request (idempotent)
- No race conditions with concurrent requests
- Returns whether profile was created (for onboarding logic)

---

## API Design

### Route Categories

#### 1. Page Routes (HTML responses)
```
GET  /              → Landing page
GET  /auth          → Login/register page
GET  /review        → Card review interface
GET  /courses       → Course list
GET  /manage        → Card management
```

#### 2. API Routes (JSON responses)
```
GET  /api/courses-tree           → Hierarchical course structure
POST /api/course-content         → Save course markdown
POST /api/generate-cards         → Generate cards with LLM
POST /api/save-cards             → Bulk save generated cards
```

#### 3. Action Routes (Form submissions, redirects)
```
POST /auth                       → Login/register action
POST /review/{card_id}           → Submit review result
POST /new                        → Create new card
POST /delete/{card_id}           → Delete card
```

### REST Conventions

| Operation | HTTP Method | URL Pattern | Response |
|-----------|-------------|-------------|----------|
| List | GET | `/resources` | HTML or JSON array |
| Read | GET | `/resource/{id}` | HTML or JSON object |
| Create | POST | `/resource` or `/new` | Redirect (303) |
| Update | POST | `/resource/{id}` | Redirect (303) |
| Delete | POST | `/delete/{id}` | Redirect (303) |

**Note:** We use POST for updates/deletes instead of PUT/DELETE because:
1. HTML forms only support GET and POST
2. Simpler CSRF handling
3. Progressive enhancement friendly

### Response Patterns

**Success (Page routes):**
```python
return templates.TemplateResponse(request, "page.html", {"data": data})
```

**Success (API routes):**
```python
return JSONResponse({"status": "success", "data": result})
```

**Redirect after action:**
```python
response = RedirectResponse(url="/destination", status_code=303)
response.set_cookie(key="flash", value="success:Message", max_age=5)
return response
```

**Error handling:**
```python
raise HTTPException(status_code=404, detail="Resource not found")
# or
return JSONResponse(status_code=400, content={"detail": "Error message"})
```

---

## Middleware Architecture

### Middleware Stack (Order Matters!)

```
Request
   │
   ▼
┌─────────────────────────────┐
│     CSRFMiddleware          │  ← Validates/generates CSRF tokens
└─────────────────────────────┘
   │
   ▼
┌─────────────────────────────┐
│  SecurityHeadersMiddleware  │  ← Adds security response headers
└─────────────────────────────┘
   │
   ▼
┌─────────────────────────────┐
│   db_session_middleware     │  ← Manages DB connection + auth
└─────────────────────────────┘
   │
   ▼
┌─────────────────────────────┐
│      Route Handler          │
└─────────────────────────────┘
   │
   ▼
Response
```

### CSRF Middleware (Pure ASGI)

**Why Pure ASGI instead of BaseHTTPMiddleware?**

`BaseHTTPMiddleware` has a known issue where reading the request body in middleware consumes it, making it unavailable for route handlers. Our CSRF middleware needs to read form data to extract the CSRF token.

**Solution:** Implement as pure ASGI middleware that:
1. Reads and caches the request body
2. Creates a new `receive` function that replays the cached body
3. Passes the replay function to downstream handlers

```python
class CSRFMiddleware:
    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # For POST requests, read body to extract CSRF token
        body_bytes = b""
        while True:
            message = await receive()
            body_bytes += message.get("body", b"")
            if not message.get("more_body", False):
                break

        # Validate CSRF token from form data
        form_data = parse_qs(body_bytes.decode())
        csrf_token = form_data.get("csrf_token", [None])[0]
        # ... validation ...

        # Create receive function that replays cached body
        async def receive_with_cached_body():
            nonlocal body_consumed
            if not body_consumed:
                body_consumed = True
                return {"type": "http.request", "body": body_bytes}
            return {"type": "http.request", "body": b""}

        await self.app(scope, receive_with_cached_body, send)
```

### Security Headers

```python
response.headers["X-Frame-Options"] = "DENY"
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-XSS-Protection"] = "1; mode=block"
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
response.headers["Permissions-Policy"] = "camera=(), microphone=(), ..."
```

| Header | Purpose |
|--------|---------|
| X-Frame-Options | Prevents clickjacking by disabling iframe embedding |
| X-Content-Type-Options | Prevents MIME-sniffing attacks |
| X-XSS-Protection | Legacy XSS filter for older browsers |
| Referrer-Policy | Controls referrer information leakage |
| Permissions-Policy | Restricts access to browser features |

---

## Frontend Architecture

### Template Inheritance

```
layout.html (Base Template)
├── <head>
│   ├── Bootstrap CSS (CDN)
│   ├── Font Awesome (CDN)
│   ├── Custom theme styles
│   └── {% block head %}{% endblock %}
│
├── <body>
│   ├── Navigation bar (conditional on auth)
│   ├── Flash message display
│   ├── {% block content %}{% endblock %}
│   │
│   └── <scripts>
│       ├── Bootstrap JS
│       ├── Marked.js (Markdown)
│       ├── MathJax (LaTeX)
│       └── Theme toggle logic
│
└── Child templates extend this
    ├── review.html
    ├── course_editor.html
    └── ...
```

### Theme System

**Dark/Light Mode Toggle:**
```javascript
// Stored in localStorage
const theme = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-bs-theme', theme);

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-bs-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-bs-theme', next);
    localStorage.setItem('theme', next);
}
```

### Markdown & LaTeX Rendering

**Client-side rendering pipeline:**
```
Raw Markdown + LaTeX → Marked.js → HTML → MathJax → Rendered Output

Example:
"What is $E = mc^2$?"
         ↓ Marked.js
"<p>What is $E = mc^2$?</p>"
         ↓ MathJax
"<p>What is <span class="math">E = mc²</span>?</p>"
```

### Flash Messages

**Server-side (setting):**
```python
response.set_cookie(
    key="flash",
    value="success:Card created!",  # type:message format
    max_age=5,
    samesite="lax"
)
```

**Client-side (displaying):**
```javascript
const flash = getCookie('flash');
if (flash) {
    const [type, message] = flash.split(':');
    showAlert(type, message);  // SweetAlert2
    deleteCookie('flash');
}
```

---

## LLM Integration

### Multi-Provider Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Card Generation Flow                         │
└─────────────────────────────────────────────────────────────────┘

     User Content (Markdown)
            │
            ▼
┌───────────────────────┐
│   Provider Selection  │
│   (User's choice)     │
└───────────────────────┘
            │
     ┌──────┼──────┐
     │      │      │
     ▼      ▼      ▼
┌───────┐ ┌───────┐ ┌───────┐
│Gemini │ │Claude │ │Ollama │
│  API  │ │  API  │ │(Local)│
└───────┘ └───────┘ └───────┘
     │      │      │
     └──────┼──────┘
            │
            ▼
┌───────────────────────┐
│   JSON Response       │
│   {"cards": [...]}    │
└───────────────────────┘
            │
            ▼
┌───────────────────────┐
│   Parsing & Cleanup   │
│   - Fix LaTeX escapes │
│   - Normalize format  │
└───────────────────────┘
            │
            ▼
     Structured Cards
```

### Common Prompt Template

```python
CARD_GENERATION_PROMPT = """
Based on the following content, generate flashcards for spaced repetition learning.

Requirements:
- Create clear, concise question-answer pairs
- Focus on key concepts and facts
- Use LaTeX for mathematical notation (e.g., $E = mc^2$)
- Return valid JSON: {"cards": [{"question": "...", "answer": "..."}, ...]}

Content:
{content}
"""
```

### Provider-Specific Implementation

**Google Gemini:**
```python
genai.configure(api_key=user.gemini_api_key)
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={
        "temperature": 0.5,
        "top_p": 0.95,
        "top_k": 64,
        "response_mime_type": "application/json",
    }
)
response = model.generate_content(prompt)
```

**Anthropic Claude:**
```python
client = anthropic.Anthropic(api_key=user.anthropic_api_key)
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=2048,
    messages=[{"role": "user", "content": prompt}]
)
```

**Ollama (Local):**
```python
response = ollama.chat(
    model="gpt-oss:20b",
    messages=[{"role": "user", "content": prompt}]
)
```

### JSON Parsing Robustness

LLMs sometimes produce malformed JSON, especially with LaTeX. Our `robust_json_loads()` handles:

```python
def robust_json_loads(text: str) -> dict:
    # 1. Strip markdown code fences
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    # 2. Pre-escape problematic LaTeX backslashes
    # Convert \alpha to \\alpha before JSON parsing
    text = re.sub(r'\\([a-zA-Z])', r'\\\\\\1', text)

    # 3. Restore valid JSON escape sequences
    for seq in ['\\n', '\\t', '\\r', '\\"']:
        text = text.replace('\\' + seq, seq)

    return json.loads(text)
```

---

## Telegram Bot Integration

### Bot Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Telegram Bot Flow                            │
└─────────────────────────────────────────────────────────────────┘

INCOMING MESSAGE:
┌──────────┐    Webhook POST    ┌─────────────┐
│ Telegram │ ─────────────────► │   FastAPI   │
│  Server  │                    │  /webhook/  │
└──────────┘                    │   {secret}  │
                                └──────┬──────┘
                                       │
                                       ▼
                                ┌─────────────┐
                                │   bot.py    │
                                │  Handlers   │
                                └─────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
              ┌──────────┐      ┌──────────┐      ┌──────────┐
              │  /start  │      │ /review  │      │ /random  │
              │ Welcome  │      │  Link    │      │ Get card │
              └──────────┘      └──────────┘      └──────────┘

OUTGOING NOTIFICATION (Scheduler):
┌─────────────┐   Query due cards   ┌────────────┐
│  scheduler  │ ──────────────────► │  Database  │
│    .py      │                     │            │
└──────┬──────┘                     └────────────┘
       │
       │ For each user with telegram_chat_id
       ▼
┌─────────────┐   send_message()   ┌──────────┐
│   Bot API   │ ─────────────────► │ Telegram │
│   Client    │                    │  Server  │
└─────────────┘                    └──────────┘
```

### Command Handlers

```python
# bot.py

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message when user starts the bot."""
    await update.message.reply_text(
        "Welcome to BadAnki! Use /review to study your cards."
    )

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send link to review page."""
    await update.message.reply_text(
        f"Start reviewing: {APP_URL}/review"
    )

async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random card from user's deck."""
    chat_id = update.effective_chat.id
    # Find user by telegram_chat_id
    # Fetch random card
    # Send question, then answer
```

### Webhook vs Polling

| Mode | When Used | How It Works |
|------|-----------|--------------|
| **Webhook** | Production (Vercel) | Telegram POSTs updates to our endpoint |
| **Polling** | Development | Bot polls Telegram API for updates |

**Webhook Setup:**
```python
async def _ensure_webhook():
    bot = Bot(TELEGRAM_BOT_TOKEN)
    webhook_url = f"{APP_URL}/webhook/{TELEGRAM_WEBHOOK_SECRET}"

    current = await bot.get_webhook_info()
    if current.url != webhook_url:
        await bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True  # Ignore old messages
        )
```

---

## Background Jobs & Scheduling

### Daily Notification Flow

```
┌─────────────────────────────────────────────────────────────────┐
│              Vercel Cron (01:00 UTC Daily)                       │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ GET /api/cron
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      api/cron.py                                 │
│  1. Verify request is from Vercel                                │
│  2. Call /api/trigger-scheduler?secret=SCHEDULER_SECRET          │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     scheduler.py                                 │
│                                                                  │
│  async def run_scheduler():                                      │
│      users = get_users_with_telegram()                           │
│      for user in users:                                          │
│          due_count = count_due_cards(user.auth_user_id)          │
│          if due_count > 0:                                       │
│              await send_notification(user, due_count)            │
│          else:                                                   │
│              await send_encouragement(user)                      │
└─────────────────────────────────────────────────────────────────┘
```

### Notification Messages

**Cards due:**
```
👋 You have 5 card(s) due for review today!

Click here to start: https://bad-anki.vercel.app/review
```

**No cards due:**
```
🎉 No cards for review today, good job!

Feel free to jog your memory with /random.
```

### Cron Configuration (vercel.json)

```json
{
    "crons": [
        {
            "path": "/api/cron",
            "schedule": "0 1 * * *"
        }
    ]
}
```

- `0 1 * * *` = At 01:00 UTC, every day
- Vercel automatically calls the endpoint at scheduled time
- Must return response within 10 seconds (Vercel limit)

---

## Deployment Architecture

### Vercel Serverless Model

```
┌─────────────────────────────────────────────────────────────────┐
│                     Vercel Edge Network                          │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ Routes to region: sin1 (Singapore)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Serverless Functions                          │
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │    main.py      │  │   api/cron.py   │  │    (static)     │  │
│  │  FastAPI App    │  │  Cron Handler   │  │   /static/*     │  │
│  │                 │  │                 │  │                 │  │
│  │ Cold start: ~2s │  │ Cold start: ~1s │  │ CDN cached      │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### vercel.json Configuration

```json
{
    "regions": ["sin1"],
    "builds": [
        { "src": "main.py", "use": "@vercel/python" },
        { "src": "api/cron.py", "use": "@vercel/python" }
    ],
    "routes": [
        { "src": "/api/cron", "dest": "api/cron.py" },
        { "src": "/webhook/(.*)", "dest": "main.py" },
        { "src": "/(.*)", "dest": "main.py" }
    ],
    "crons": [
        { "path": "/api/cron", "schedule": "0 1 * * *" }
    ]
}
```

**Key Decisions:**

1. **Single Region (sin1)** - Lower latency for target users, simpler database connection
2. **Catch-all Route** - All requests go through FastAPI for consistent handling
3. **Separate Cron Handler** - Dedicated entry point for scheduled jobs

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | JWT signing, session encryption |
| `DATABASE_URL` | PostgreSQL connection string |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/public key |
| `SCHEDULER_SECRET` | Auth for scheduler endpoint |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook URL secret |
| `APP_URL` | Public application URL |
| `ENVIRONMENT` | "production" or "development" |

---

## Testing Strategy

### Test Infrastructure

```
┌─────────────────────────────────────────────────────────────────┐
│                      Test Architecture                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   pytest        │     │  testcontainers │     │  FastAPI        │
│   Framework     │────►│  PostgreSQL     │────►│  TestClient     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │  Ephemeral DB   │
                        │  (Docker)       │
                        │                 │
                        │  - Real schema  │
                        │  - Isolated     │
                        │  - Auto-cleanup │
                        └─────────────────┘
```

### Test Categories

**1. Authentication Tests**
```python
def test_auth_login_successfully(client, db_conn, mock_supabase_sign_in):
    response = client.post("/auth", data={
        "email": "test@example.com",
        "password": "password123",
        "csrf_token": get_csrf_token(client)
    })
    assert response.status_code == 303  # Redirect
    assert "access_token" in response.cookies
```

**2. CRUD Tests**
```python
def test_create_card(authenticated_client):
    client, user_id, csrf_token = authenticated_client
    response = client.post("/new", data={
        "question": "What is 2+2?",
        "answer": "4",
        "csrf_token": csrf_token
    })
    assert response.status_code == 303
    # Verify card exists in database
```

**3. API Tests**
```python
def test_generate_cards_api_success(authenticated_client, mock_gemini):
    client, user_id, csrf_token = authenticated_client
    response = client.post("/api/generate-cards", json={
        "content": "Python is a programming language."
    })
    assert response.status_code == 200
    assert "cards" in response.json()
```

### Mocking Strategy

```python
@pytest.fixture
def mock_supabase_auth():
    with patch("main.supabase.auth.get_user") as mock:
        mock.return_value = Mock(user=Mock(id="test-uuid", email="test@example.com"))
        yield mock

@pytest.fixture
def mock_gemini_api():
    with patch("main.genai.GenerativeModel") as mock:
        mock.return_value.generate_content.return_value.text = '''
            {"cards": [{"question": "Q1", "answer": "A1"}]}
        '''
        yield mock
```

### CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
name: CI
on: [pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v
    env:
      SUPABASE_URL: "https://test.supabase.co"
      SUPABASE_KEY: "test-key"
      # ... other test env vars
```

---

## Design Patterns & Principles

### 1. Repository Pattern (crud.py)

All database operations are centralized in `crud.py`, providing:
- Single source of truth for data access
- Easier testing (mock one module)
- Consistent error handling

```python
# crud.py
def get_card_by_id(conn, card_id: int, user_id: str) -> Optional[dict]:
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute(
        "SELECT * FROM cards WHERE id = %s AND user_id = %s",
        (card_id, user_id)
    )
    return cursor.fetchone()
```

### 2. Dependency Injection (FastAPI)

```python
def get_db(request: Request):
    return request.state.db

def get_current_active_user(request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/auth"})
    return user

@app.get("/review")
async def review(
    conn: psycopg2.extensions.connection = Depends(get_db),
    user: User = Depends(get_current_active_user)
):
    # conn and user are injected
```

### 3. Middleware Chain

Request processing flows through a defined middleware stack:
1. Each middleware can modify request/response
2. Order determines processing sequence
3. Separation of concerns (auth, security, logging)

### 4. Idempotent Operations

Operations that can be safely repeated:
```python
# Profile creation - safe to call multiple times
INSERT INTO profiles (...) ON CONFLICT DO NOTHING

# Webhook setup - checks current state first
if current_webhook.url != desired_url:
    set_webhook(desired_url)
```

### 5. Factory Pattern (Bot Creation)

```python
def get_bot_application():
    """Create fresh bot instance for each request."""
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("review", review_command))
    return application
```

Why factory instead of singleton?
- Serverless functions may run in parallel
- No shared state between requests
- Clean initialization each time

---

## Security Considerations

### Authentication Security

| Measure | Implementation |
|---------|----------------|
| Password hashing | Supabase (bcrypt) |
| JWT tokens | HttpOnly cookies, secure flag |
| Session expiry | 7-day token lifetime |
| OAuth | Delegated to Supabase |

### CSRF Protection

```
Request Flow with CSRF:

1. GET /review
   → Server generates token, sets cookie
   → Token embedded in form

2. POST /review/123
   → Cookie: csrf_token=abc123
   → Body: csrf_token=abc123
   → Server validates match
```

### Input Validation

- Pydantic models for request validation
- SQL parameterization (no string concatenation)
- HTML escaping in templates (Jinja2 auto-escape)

### API Key Storage

- User API keys stored in database (encrypted at rest by Supabase)
- Keys never exposed in frontend (only masked display)
- Keys scoped to individual users

### Rate Limiting

Currently not implemented. For production scale, consider:
- Redis-based rate limiting
- Vercel's built-in rate limiting
- Per-user API quotas

---

## Performance Considerations

### Database Connection Pooling

**Implementation (database.py):**
```python
db_pool = None

def init_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=os.environ.get("DATABASE_URL")
        )
        register_uuid()  # Register UUID type adapter globally
```

**Why Connection Pooling?**
- Creating database connections is expensive (~50-100ms)
- Pooling reuses connections across requests
- Limits concurrent connections to prevent database overload

**Pool Configuration:**
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `minconn` | 1 | Keep at least one warm connection |
| `maxconn` | 20 | Supabase free tier limit is 60; leave headroom |

### Efficient Random Card Selection

**Problem:** `ORDER BY RANDOM()` scans entire table.

**Solution:** Use COUNT + OFFSET pattern:
```python
def get_random_card_for_user(conn, auth_user_id: str):
    # Get count (uses index, very fast)
    cursor.execute("SELECT COUNT(*) FROM cards WHERE user_id = %s", (auth_user_id,))
    count = cursor.fetchone()[0]

    if count == 0:
        return None

    # Random offset into the result set
    offset = random.randint(0, count - 1)
    cursor.execute(
        "SELECT * FROM cards WHERE user_id = %s LIMIT 1 OFFSET %s",
        (auth_user_id, offset)
    )
    return cursor.fetchone()
```

**Performance Comparison:**
| Approach | 10K cards | 100K cards |
|----------|-----------|------------|
| `ORDER BY RANDOM()` | ~50ms | ~500ms |
| COUNT + OFFSET | ~2ms | ~5ms |

### Batch Card Insertion

When saving AI-generated cards, use batch insert instead of individual queries:

```python
def save_generated_cards_for_user(conn, cards: list, auth_user_id: str):
    card_data = [(card.question, card.answer, datetime.now(), auth_user_id)
                 for card in cards]

    # Single INSERT with multiple values
    extras.execute_values(
        cursor,
        "INSERT INTO cards (question, answer, due_date, user_id) VALUES %s",
        card_data
    )
```

**Benefit:** 10 cards = 1 round-trip instead of 10.

### Query Optimization with Indexes

**Current Indexes (implicit via constraints):**
- `profiles.auth_user_id` (PRIMARY KEY)
- `cards.id` (PRIMARY KEY)
- `courses.id` (PRIMARY KEY)
- `courses(user_id, path)` (UNIQUE constraint)

**Recommended Additional Indexes for Scale:**
```sql
-- Speed up due card queries (most common operation)
CREATE INDEX idx_cards_user_due ON cards(user_id, due_date);

-- Speed up tag filtering (full-text search on content)
CREATE INDEX idx_courses_content_gin ON courses
  USING gin(to_tsvector('english', content));
```

### Serverless Cold Start Optimization

**Challenge:** Vercel cold starts can add 1-3 seconds to first request.

**Mitigations:**
1. **Lazy Initialization:** Database pool created on first use, not module load
2. **Minimal Dependencies:** Only import what's needed
3. **Health Check Endpoint:** `/health` keeps function warm via uptime monitoring
4. **Connection Reuse:** Pool persists across invocations in same container

### Frontend Performance

**CDN for Static Assets:**
- Bootstrap, Font Awesome, MathJax loaded from CDN
- Leverages browser caching and geographic distribution
- No build step required

**Lazy MathJax Loading:**
- MathJax only processes content after page load
- Uses `MathJax.typeset()` on dynamic content

**Markdown Pre-rendering:**
- Marked.js renders markdown client-side
- Keeps server responses lightweight (raw markdown)

---

## Error Handling Patterns

### Database Error Handling

```python
def save_course_content_for_user(conn, path: str, content: str, auth_user_id: str):
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO courses (path, content, user_id, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (path, user_id) DO UPDATE SET
                content = EXCLUDED.content,
                updated_at = EXCLUDED.updated_at
        """, (path, content, auth_user_id, datetime.now()))
        conn.commit()
    except Exception as e:
        conn.rollback()  # Critical: rollback on failure
        raise e
    finally:
        cursor.close()  # Always close cursor
```

**Key Patterns:**
- Always `rollback()` on exception
- Always `close()` cursor in `finally`
- Let exceptions propagate for API layer to handle

### LLM Error Handling

```python
def generate_cards(text: str, mode="gemini", api_key: str = None) -> list[dict]:
    try:
        # ... LLM API call ...
        parsed = robust_json_loads(response_text)
        cards = parsed.get("cards", [])
        return normalize_cards(cards)
    except Exception as e:
        logger.error(f"Error during {mode} API call: {e}")
        return []  # Return empty list, not None
```

**Design Decision:** Return empty list on failure
- Caller can check `if not generated_cards` uniformly
- Avoids NoneType errors downstream
- Frontend shows "no cards generated" message

### HTTP Error Responses

| Status | When Used | Example |
|--------|-----------|---------|
| 303 | Redirect after action | After login, redirect to /review |
| 400 | Bad request data | Empty content for card generation |
| 403 | Auth/CSRF failure | Invalid CSRF token |
| 404 | Resource not found | Card ID doesn't exist |
| 500 | Server error | Database connection failed |

---

## Interview Discussion Points

### System Design Questions

**Q: How would you scale this application to 100K users?**

A: Several changes would be needed:
1. **Database**: Move to read replicas for card queries, connection pooling via PgBouncer
2. **Caching**: Redis for session data, frequently accessed cards
3. **CDN**: Static assets and potentially cached HTML responses
4. **Background Jobs**: Move scheduler to dedicated worker (not cron-triggered)
5. **Rate Limiting**: Per-user limits on API calls and card generation

**Q: Why did you choose Supabase over building your own auth?**

A: Build vs buy tradeoff:
- **Security**: Auth is hard to get right; Supabase handles password hashing, token rotation, OAuth complexity
- **Time**: Focus on core features (spaced repetition) rather than auth infrastructure
- **Compliance**: Supabase handles GDPR, password policies, etc.
- **Trade-off**: Vendor lock-in, less customization

**Q: How does the spaced repetition algorithm work?**

A: SM-2 inspired algorithm:
1. Each card has an `ease_factor` (default 2.5) and `interval` (days until next review)
2. On correct answer: `new_interval = old_interval * ease_factor`, increase ease_factor
3. On incorrect: Reset interval to 1 day, decrease ease_factor
4. Query cards where `due_date <= now()` for review queue

**Q: How do you handle LLM response parsing failures?**

A: Multiple defensive layers:
1. Request JSON response format from LLM
2. Strip markdown code fences from response
3. Pre-escape LaTeX backslashes that break JSON
4. Restore valid JSON escape sequences
5. Return partial results if some cards parse correctly
6. Log failures for debugging

### Code Quality Questions

**Q: Why raw SQL instead of an ORM?**

A: Deliberate choice for this project:
- **Pros**: Full control, no magic, easier debugging, better performance understanding
- **Cons**: More boilerplate, manual migrations
- **Context**: Schema is simple (3 tables), queries are straightforward

**Q: How do you handle errors in the Telegram bot?**

A: Graceful degradation:
- Wrap handlers in try/catch
- Log errors with context (user_id, command)
- Send user-friendly error message
- Bot continues functioning for other users

### Architecture Questions

**Q: Why serverless (Vercel) instead of a traditional server?**

A: Matches the usage pattern:
- **Traffic**: Spiky (reviews cluster around notification time)
- **Cost**: Pay per request, not per hour
- **Ops**: Zero server maintenance
- **Trade-off**: Cold starts (~2s), limited request duration (10s)

**Q: How would you add real-time features (e.g., live collaboration)?**

A: Options:
1. **WebSockets**: Not supported on Vercel serverless, would need different host
2. **Polling**: Simple, works everywhere, higher latency
3. **Supabase Realtime**: Built-in pub/sub, minimal code changes
4. **External service**: Pusher, Ably for real-time layer

### Deep Dive Questions

**Q: Walk me through the CSRF protection implementation.**

A: The CSRF middleware is implemented as pure ASGI (not BaseHTTPMiddleware) to solve the request body consumption problem:

1. **GET requests**: Generate a random 32-char hex token, store in scope state, set as HttpOnly cookie
2. **POST/PUT/DELETE**: Extract token from cookie AND from either `X-CSRF-Token` header or form body
3. **Validation**: Use `secrets.compare_digest()` for timing-attack-safe comparison
4. **Body caching**: After reading body for token extraction, create a `receive_with_cached_body()` function that replays the body for downstream handlers

The pure ASGI approach was necessary because `BaseHTTPMiddleware` consumes the request body, making it unavailable for route handlers that also need to read form data.

**Q: How does the spaced repetition algorithm handle edge cases?**

A: Several edge cases are considered:

1. **New cards**: `interval=1`, `ease_factor=2.5` → first correct answer shows card tomorrow
2. **Very easy cards**: Ease factor grows unbounded (could add cap at 3.0 for realism)
3. **Consistently wrong**: `MIN_EASE_FACTOR=1.3` prevents ease from going too low
4. **Reset on wrong**: `interval=1` ensures immediate re-review
5. **Timezone handling**: Uses server time (UTC on Vercel), could improve with user timezone

**Q: Explain the JSON parsing robustness for LLM responses.**

A: LLMs often produce invalid JSON, especially with LaTeX. The `robust_json_loads()` function handles this:

```python
def robust_json_loads(raw: str) -> Any:
    s = _strip_fences(raw)  # Remove ```json ... ```

    # Fast path: try direct parsing
    try:
        parsed = json.loads(s)
        if not _has_control_chars(parsed):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: pre-escape single backslashes before letters
    # \frac → \\frac (valid JSON escape)
    s_escaped = re.sub(r'\\([a-zA-Z])', r'\\\\\1', s)

    parsed = json.loads(s_escaped)

    # Restore control chars if any slipped through
    if _has_control_chars(parsed):
        parsed = _restore_control_chars(parsed)

    return parsed
```

The key insight is that LaTeX commands like `\frac`, `\alpha` become invalid JSON escape sequences, so we double-escape them before parsing.

**Q: Why use server-side rendering instead of a SPA framework?**

A: Deliberate tradeoffs for this project:

| Factor | SSR (chosen) | SPA (React/Vue) |
|--------|--------------|-----------------|
| Complexity | Low - Jinja2 templates | Higher - build system, state management |
| SEO | Native support | Requires SSR/hydration |
| Initial load | Fast - HTML ready | Slower - JS bundle download |
| Interactivity | Limited - page reloads | Rich - no reloads |
| Development | Fast iteration | More tooling setup |

For a study app with simple interactions (click remember/forgot, navigate courses), SSR is sufficient and simpler.

**Q: How do you handle the multi-tenant data isolation?**

A: Defense in depth:

1. **Query-level filtering**: Every CRUD function takes `auth_user_id` and filters by it
2. **No cross-user joins**: Queries never join across different users' data
3. **Dependency injection**: User comes from validated JWT, not user input
4. **Middleware validation**: User object attached to request state after JWT verification

```python
# Example: Every query includes user filter
cursor.execute(
    "SELECT * FROM cards WHERE id = %s AND user_id = %s",
    (card_id, auth_user_id)  # user_id prevents accessing other users' cards
)
```

**Q: What would you change if you rebuilt this from scratch?**

A:
1. **TypeScript frontend**: Better type safety for JavaScript code
2. **ORM (SQLAlchemy)**: For larger apps, automatic migrations are valuable
3. **Redis caching**: Session data, frequently accessed cards
4. **Dedicated auth service**: More customization than Supabase
5. **Card versioning**: Track edit history for undo/audit
6. **Better card types**: Support image cards, cloze deletions

### Behavioral Questions

**Q: Describe a technical challenge you faced building this.**

A: The CSRF middleware body consumption issue. Initially used `BaseHTTPMiddleware`, but form data couldn't be read by route handlers after middleware validation. Solution required:
1. Researching ASGI lifecycle and request body streaming
2. Understanding that bodies can only be read once without caching
3. Implementing pure ASGI middleware with body replay mechanism

**Q: How did you decide between different LLM providers?**

A: Started with Gemini for cost-effectiveness, then added Claude for quality comparison, and Ollama for privacy-conscious users or offline use. The abstraction emerged naturally - same prompt template, different API calls, unified response format.

---

## Known Limitations & Future Improvements

### Current Limitations

| Limitation | Impact | Potential Solution |
|------------|--------|-------------------|
| No card versioning | Can't undo edits | Add `card_history` table |
| Tags stored in content | Inefficient queries | Normalize to `tags` table |
| Single region (sin1) | Higher latency for distant users | Multi-region with read replicas |
| No rate limiting | Vulnerable to abuse | Add Redis-based limits |
| Synchronous LLM calls | Blocks response | Background jobs with status polling |
| No offline support | Requires internet | PWA with service workers |
| Basic card types | Only Q&A format | Add cloze, image, audio cards |

### Roadmap Ideas

**Short-term:**
- [ ] Add composite index on `(user_id, due_date)` for card queries
- [ ] Implement client-side card caching for offline review
- [ ] Add rate limiting for LLM endpoints
- [ ] Support bulk card import/export (CSV, Anki format)

**Medium-term:**
- [ ] Card statistics dashboard (retention rate, review streaks)
- [ ] Deck/folder sharing between users
- [ ] Mobile app (React Native) with push notifications
- [ ] Integration with PDF reader for automatic card generation

**Long-term:**
- [ ] AI-powered adaptive learning (adjust ease based on content similarity)
- [ ] Collaborative deck creation
- [ ] Marketplace for public decks
- [ ] Voice-based review mode

---

## Appendix: Quick Reference

### Common Commands

```bash
# Development
uvicorn main:app --reload

# Testing
pytest tests/ -v

# Database migrations (manual)
psql $DATABASE_URL -f database.sql

# Telegram webhook setup
curl "$APP_URL/api/ensure-webhook?secret=$SCHEDULER_SECRET"
```

### Key File Locations

| Feature | File(s) |
|---------|---------|
| API routes | `main.py` |
| Database queries | `crud.py` |
| Authentication | `main.py:get_current_user()` |
| CSRF handling | `middleware.py:CSRFMiddleware` |
| Card generation | `main.py:generate_cards()` |
| Telegram bot | `bot.py` |
| Daily scheduler | `scheduler.py` |
| Tests | `tests/test_api.py` |

### Environment Setup

```bash
# Required environment variables
export SECRET_KEY="your-secret-key"
export DATABASE_URL="postgresql://..."
export SUPABASE_URL="https://xxx.supabase.co"
export SUPABASE_KEY="your-anon-key"
export SCHEDULER_SECRET="scheduler-secret"
export TELEGRAM_BOT_TOKEN="bot-token"
export TELEGRAM_WEBHOOK_SECRET="webhook-secret"
export APP_URL="https://your-app.vercel.app"
```
