from dotenv import load_dotenv
load_dotenv()

# Standard library
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

# Third-party
import frontmatter
import google.generativeai as genai
import ollama
import psycopg2
import anthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from pydantic import BaseModel
from telegram import Update

# Local application
import crud
from bot import get_bot_application
from database import get_db_connection, release_db_connection
from scheduler import run_scheduler
from utils.parsing import normalize_cards, robust_json_loads, sanitize_tags


# --- JWT Configuration ---
SECRET_KEY = os.environ.get("SECRET_KEY")
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME")

if not SECRET_KEY:
    raise ValueError("No SECRET_KEY set for JWT. Please set this environment variable.")
if not SCHEDULER_SECRET:
    raise ValueError("No SCHEDULER_SECRET set. Please set this environment variable.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# --- FastAPI App ---
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- Webhook Endpoint ---
@app.post("/webhook/{secret}")
async def webhook(request: Request, secret: str):
    """
    Handle incoming Telegram webhook updates.
    This is called by Telegram servers when users interact with the bot.
    """
    logger.info("Webhook endpoint was hit!")
    
    # Validate the secret
    expected_secret = TELEGRAM_WEBHOOK_SECRET or "default_secret"
    if not secrets.compare_digest(secret, expected_secret):
        logger.warning("Invalid secret received in webhook request.")
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    try:
        # Get the update data from Telegram
        data = await request.json()
        logger.info(f"Received webhook data: {json.dumps(data, indent=2)}")
        
        # Create a fresh bot application for this request (serverless pattern)
        bot_app = get_bot_application()
        if not bot_app:
            logger.error("Failed to create bot application")
            return Response(status_code=500)
        
        # Initialize the bot for this request
        await bot_app.initialize()
        
        # Parse the update
        update = Update.de_json(data, bot_app.bot)
        
        # Process the update through the bot's handlers
        await bot_app.process_update(update)
        
        logger.info("Successfully processed webhook update.")
        
        # Clean up
        await bot_app.shutdown()
        
        return Response(status_code=200)
        
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}", exc_info=True)
        return Response(status_code=500)



async def _ensure_webhook():
    """Helper function to ensure the Telegram webhook is set correctly."""
    bot_app = get_bot_application()
    await bot_app.initialize()
    webhook_url = f"{os.environ.get('APP_URL')}/webhook/{os.environ.get('TELEGRAM_WEBHOOK_SECRET')}"
    info = await bot_app.bot.get_webhook_info()

    if info.url != webhook_url:
        await bot_app.bot.set_webhook(url=webhook_url, drop_pending_updates=False)
        return {"status": "webhook (re)set", "url": webhook_url}
    else:
        return {"status": "already correct", "url": info.url}


@app.get("/api/ensure-webhook")
async def ensure_webhook(secret: str):
    if secret != os.environ.get("SCHEDULER_SECRET"):
        raise HTTPException(status_code=403, detail="Invalid secret")
    return await _ensure_webhook()



# --- Middleware ---
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Manages the database connection lifecycle for each request and
    attaches the user object to the request state.
    """
    conn = None
    try:
        conn = get_db_connection()
        request.state.db = conn
        user = await get_current_user(request, conn)
        request.state.user = user
        # API keys are now part of the user model
        request.state.api_keys = user
        response = await call_next(request)
    finally:
        if conn:
            release_db_connection(conn)
    return response

# --- Pydantic Models ---
class User(BaseModel):
    id: int
    username: str

class CourseContent(BaseModel):
    path: str
    content: str

class CourseItem(BaseModel):
    path: str
    type: str

class GeneratedCard(BaseModel):
    question: str
    answer: str

class CourseContentForGeneration(BaseModel):
    content: str

class GeneratedCards(BaseModel):
    cards: list[GeneratedCard]

class ApiKeys(BaseModel):
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None

class Secrets(BaseModel):
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    scheduler_secret: str | None = None

# --- Database Dependency ---
def get_db(request: Request):
    """
    FastAPI dependency that retrieves the database connection
    from the request state, managed by the middleware.
    """
    return request.state.db

# --- Authentication ---

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request, conn: psycopg2.extensions.connection):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None
    user = crud.get_user_by_username(conn, username=username)
    return user

def generate_csrf_token(session_id: str):
    """Generate a CSRF token."""
    return jwt.encode({"session_id": session_id}, SECRET_KEY, algorithm=ALGORITHM)

async def csrf_protect(request: Request):
    """A dependency to protect against CSRF attacks."""
    if request.method == "POST":
        csrf_token = request.headers.get("X-CSRF-Token")
        if not csrf_token:
            raise HTTPException(status_code=403, detail="Missing CSRF token")
        try:
            jwt.decode(csrf_token, SECRET_KEY, algorithms=[ALGORITHM])
        except JWTError:
            raise HTTPException(status_code=403, detail="Invalid CSRF token")

async def get_current_active_user(request: Request):
    if not request.state.user:
        # Redirect to login page if user is not authenticated
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return request.state.user

# --- LLM & Card Generation ---

generation_config = {
  "temperature": 0.5,
  "top_p": 0.95,
  "top_k": 64,
  "max_output_tokens": 8192,
  "response_mime_type": "application/json",
}
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


def generate_cards(text: str, mode="gemini", api_key: str = None) -> list[dict]:
    prompt = f"""
        Analyze the following text and generate a list of question-and-answer pairs for flashcards.
        **Instructions:**
        1.  **Language:** Generate the cards in the same language as the provided text.
        2.  **Focus:** Concentrate on the core concepts, definitions, and key formulas. Avoid trivial details.
        3.  **LaTeX:** Use LaTeX for all mathematical formulas. Enclose inline math with `$` and block math with `$$`.
        4.  **Format:** Return ONLY a raw JSON object with a "cards" key, containing a list of objects, each with "question" and "answer" keys. Do not include markdown formatting like ```json.
        5.  **JSON Escaping:** CRITICALLY IMPORTANT: Ensure that any backslashes `\\` within the question or answer strings are properly escaped as `\\\\`. This is essential for valid JSON, especially for LaTeX content like `\\\\frac` or `\\\\mathbb`.

        **Text to Analyze:**
        ---
        {text}
        ---
        """
    
    try:
        if mode == "gemini":
            if not api_key:
                raise ValueError("Gemini API key is required.")
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name="gemini-flash-latest", 
                safety_settings=safety_settings, 
                generation_config=generation_config
            )
            response = model.generate_content(prompt)
            response_text = response.text.strip()
            
        elif mode == "ollama":
            response = ollama.chat(
                model='gemma3:4b', 
                messages=[{'role': 'user', 'content': prompt}]
            )
            response_text = response['message']['content']
        
        elif mode == "anthropic":
            if not api_key:
                raise ValueError("Anthropic API key is required.")
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            response_text = message.content[0].text
        
        # Need to carefully escape latex for JSON parsing and then for frontend rendering...
        parsed = robust_json_loads(response_text)
        cards = parsed.get("cards", [])
        return normalize_cards(cards)
            
    except Exception as e:
        logger.error(f"An error occurred during {mode} API call: {e}")
        return []


@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_form(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse(request, "api_keys.html", {"api_keys": request.state.api_keys})

@app.get("/secrets", response_class=HTMLResponse)
async def secrets_form(request: Request, user: User = Depends(get_current_active_user)):
    csrf_token = generate_csrf_token(user['username'])
    return templates.TemplateResponse(request, "secrets.html", {
        "secrets": user, 
        "csrf_token": csrf_token,
        "telegram_bot_username": TELEGRAM_BOT_USERNAME
    })

@app.post("/secrets", dependencies=[Depends(csrf_protect)])
async def save_secrets(request: Request, user: User = Depends(get_current_active_user), telegram_chat_id: str = Form(None)):
    # If the chat ID is an empty string, treat it as None
    if telegram_chat_id == "":
        telegram_chat_id = None
        
    crud.save_secrets_for_user(request.state.db, user['id'], telegram_chat_id)
    return JSONResponse(content={"success": True})


# --- FastAPI Routes ---

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.post("/login")
async def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), conn: psycopg2.extensions.connection = Depends(get_db)):
    user = crud.get_user_by_username(conn, form_data.username)
    if not user or not crud.verify_password(form_data.password, user['password_hash']):
        return templates.TemplateResponse(request, "login.html", {"error": "Incorrect username or password"})
        
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['username']}, expires_delta=access_token_expires
    )
    response = RedirectResponse(url="/courses", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request, error: str = None):
    return templates.TemplateResponse(request, "register.html", {"error": error})

@app.post("/register")
async def register_user(request: Request, username: str = Form(...), password: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db)):
    # Username validation
    user = crud.get_user_by_username(conn, username)
    if user:
        return templates.TemplateResponse(request, "register.html", {"error": "Username already registered"})

    # Password validation
    if len(password) < 8:
        return templates.TemplateResponse(request, "register.html", {"error": "Password must be at least 8 characters long"})
    if not any(char.isdigit() for char in password):
        return templates.TemplateResponse(request, "register.html", {"error": "Password must contain at least one number"})

    crud.create_user(conn, username, password)
    response = RedirectResponse(url="/login", status_code=303)
    response.set_cookie(key="flash", value="success:Registered successfully! Please log in.", max_age=5)
    return response


@app.get("/health", response_class=JSONResponse)
async def health_check():
    """A simple endpoint to keep the service alive."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "home.html", {"telegram_bot_username": TELEGRAM_BOT_USERNAME})

@app.get("/courses", response_class=HTMLResponse)
async def list_courses(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse(request, "courses_list.html")

@app.get("/edit-course/{course_path:path}", response_class=HTMLResponse)
async def edit_course(request: Request, course_path: str, user: User = Depends(get_current_active_user)):
    gemini_api_key_exists = False
    anthropic_api_key_exists = False
    if request.state.api_keys:
        if request.state.api_keys.get('gemini_api_key'):
            gemini_api_key_exists = True
        if request.state.api_keys.get('anthropic_api_key'):
            anthropic_api_key_exists = True
    
    return templates.TemplateResponse(request, "course_editor.html", {
        "course_path": course_path,
        "gemini_api_key_exists": gemini_api_key_exists,
        "anthropic_api_key_exists": anthropic_api_key_exists
    })

@app.get("/courses/{course_path:path}", response_class=HTMLResponse)
async def view_course(request: Request, course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course = crud.get_course_content_for_user(conn, course_path, user['id'])
    if not course or not course['content']:
        raise HTTPException(status_code=404, detail="Course not found")
    
    content = course['content']
    try:
        content = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    post = frontmatter.loads(content)

    if 'tags' in post.metadata: 
        post.metadata['tags'] = sanitize_tags(post.metadata['tags'])

    return templates.TemplateResponse(request, "course_viewer.html", {"metadata": post.metadata, "content": post.content, "course_path": course_path})

# --- API for Courses ---
@app.get("/api/courses-tree")
async def api_get_courses_tree(conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    return crud.get_courses_tree_for_user(conn, user['id'])

@app.get("/api/download-course/{course_path:path}")
async def download_course(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course = crud.get_course_content_for_user(conn, course_path, user['id'])
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
    
    content = course['content']
    # Ensure the filename is safe and has a .md extension
    safe_filename = os.path.basename(course_path)
    if not safe_filename.endswith('.md'):
        safe_filename += '.md'
        
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"}
    )

@app.get("/api/course-content/{course_path:path}", response_class=JSONResponse)
async def api_get_course_content(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course = crud.get_course_content_for_user(conn, course_path, user['id'])
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse(content=course['content'])

@app.post("/api/course-content")
async def api_save_course_content(item: CourseContent, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_course_content_for_user(conn, item.path, item.content, user['id'])
    return {"success": True}

@app.api_route("/api/course-item", methods=["POST", "DELETE"])
async def api_manage_course_item(item: CourseItem, request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    if request.method == "POST":
        crud.create_course_item_for_user(conn, item.path, item.type, user['id'])
    elif request.method == "DELETE":
        crud.delete_course_item_for_user(conn, item.path, item.type, user['id'])
    return {"success": True}

@app.post("/api/generate-cards")
async def api_generate_cards(request: Request, data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    
    api_key = None
    if request.state.api_keys:
        api_key = request.state.api_keys.get('gemini_api_key')

    generated_cards = generate_cards(data.content, mode="gemini", api_key=api_key)
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/generate-cards-ollama")
async def api_generate_cards_ollama(data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    generated_cards = generate_cards(data.content, mode="ollama")
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}


@app.post("/api/generate-cards-anthropic")
async def api_generate_cards_anthropic(request: Request, data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    
    api_key = None
    if request.state.api_keys:
        api_key = request.state.api_keys.get('anthropic_api_key')

    generated_cards = generate_cards(data.content, mode="anthropic", api_key=api_key)
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/save-cards")
async def api_save_cards(data: GeneratedCards, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_generated_cards_for_user(conn, data.cards, user['id'])
    return {"success": True, "message": f"{len(data.cards)} cards saved successfully."}

@app.get("/api/tags")
async def api_get_tags(conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    tags = crud.get_all_tags_for_user(conn, user['id'])
    return JSONResponse(content=tags)

@app.post("/api/save-api-keys")
async def api_save_api_keys(data: ApiKeys, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_api_keys_for_user(conn, user['id'], data.gemini_api_key, data.anthropic_api_key)
    return {"success": True}

# --- Tag-based Views ---
@app.get("/tags/{tag_name}", response_class=HTMLResponse)
async def view_courses_by_tag(request: Request, tag_name: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    courses = crud.get_courses_by_tag_for_user(conn, tag_name, user['id'])
    return templates.TemplateResponse(request, "tag_courses.html", {"tag": tag_name, "courses": courses})

# --- Scheduler ---
@app.get("/api/trigger-scheduler")
async def trigger_scheduler(secret: str):
    if secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    webhook_status = await _ensure_webhook()
    logger.info(f"Webhook status: {webhook_status}")
    
    result = await run_scheduler()
    return JSONResponse(content={"status": "completed", "result": result, "webhook_status": webhook_status})

# --- Card Management Routes ---
@app.get("/card/{card_id}", response_class=HTMLResponse)
async def view_card(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_card_for_user(conn, card_id, user['id'])
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse(request, "card_viewer.html", {"card": card})

@app.get("/review", response_class=HTMLResponse)
async def review(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_review_cards_for_user(conn, user['id'])
    stats = crud.get_review_stats_for_user(conn, user['id'])
    
    if card is None:
        return templates.TemplateResponse(request, "no_cards.html")

    return templates.TemplateResponse(request, "review.html", {
        "card": card, 
        "due_today_count": stats['due_today'], 
        "new_cards_count": stats['new_cards'], 
        "total_cards": stats['total_cards']
    })

@app.post("/review/{card_id}")
async def update_review(card_id: int, status: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.update_card_for_user(conn, card_id, user['id'], status == "remembered")
    return RedirectResponse(url="/review", status_code=303)

@app.get("/manage", response_class=HTMLResponse)
async def manage_cards(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    cards = crud.get_all_cards_for_user(conn, user['id'])
    return templates.TemplateResponse(request, "manage_cards.html", {"cards": cards})

@app.get("/new", response_class=HTMLResponse)
async def new_card_form(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse(request, "new_card.html")

@app.post("/new")
async def create_new_card(question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.create_card_for_user(conn, question, answer, user['id'])
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="flash", value="success:Card created successfully!", max_age=5)
    return response

@app.get("/edit-card/{card_id}", response_class=HTMLResponse)
async def edit_card_form(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_card_for_user(conn, card_id, user['id'])
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse(request, "edit_card.html", {"card": card})

@app.post("/edit-card/{card_id}")
async def update_existing_card(card_id: int, question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.update_card_content_for_user(conn, card_id, user['id'], question, answer)
    return RedirectResponse(url="/manage", status_code=303)

@app.post("/delete/{card_id}")
async def delete_card(card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.delete_card_for_user(conn, card_id, user['id'])
    response = RedirectResponse(url="/manage", status_code=303)
    response.set_cookie(key="flash", value="success:Card deleted successfully!", max_age=5)
    return response
