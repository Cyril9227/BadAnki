from dotenv import load_dotenv
load_dotenv()

# Standard library
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
import uuid
from urllib.parse import unquote, quote

# Third-party
import frontmatter
from google import genai
import ollama
import psycopg2
import anthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client
from jose import JWTError, jwt
from pydantic import BaseModel
from telegram import Update
from supabase_auth.errors import AuthApiError

# Local application
import crud
from bot import get_bot_application
from database import get_db_connection, release_db_connection
from scheduler import run_scheduler
from utils.parsing import normalize_cards, robust_json_loads, sanitize_tags
from middleware import CSRFMiddleware, SecurityHeadersMiddleware


# --- Supabase & JWT Configuration ---
SECRET_KEY = os.environ.get("SECRET_KEY")
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not all([SECRET_KEY, SCHEDULER_SECRET, SUPABASE_URL, SUPABASE_KEY]):
    raise ValueError("One or more critical environment variables are not set.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# --- FastAPI App ---
app = FastAPI()
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
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
    auth_user_id: uuid.UUID
    username: str
    telegram_chat_id: Optional[str] = None
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

class CourseContent(BaseModel):
    path: str
    content: str

class CourseItem(BaseModel):
    path: str
    type: str

class GeneratedCard(BaseModel):
    question: str
    answer: str
    card_type: str = "basic"  # "basic" or "cloze"

class CourseContentForGeneration(BaseModel):
    content: str
    card_type: str = "basic"  # "basic" or "cloze"

class GeneratedCards(BaseModel):
    cards: list[GeneratedCard]

class ApiKeys(BaseModel):
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None

class Secrets(BaseModel):
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    scheduler_secret: str | None = None

class AuthCallback(BaseModel):
    access_token: str
    refresh_token: str | None = None

# --- Database Dependency ---
def get_db(request: Request):
    """
    FastAPI dependency that retrieves the database connection
    from the request state, managed by the middleware.
    """
    return request.state.db

# --- Authentication ---
async def get_current_user(request: Request, conn: psycopg2.extensions.connection) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        user_response = supabase.auth.get_user(token)
        auth_user = user_response.user
        if auth_user:
            # This is the key change: ensure a profile exists for any valid Supabase user.
            # It's idempotent, so it's safe to call on every authenticated request.
            crud.create_profile(conn, username=auth_user.email, auth_user_id=auth_user.id)
            
            profile = crud.get_profile_by_auth_id(conn, auth_user.id)
            if profile:
                return User(**profile)
    except Exception:
        return None
    return None

@app.get("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("access_token")
    if token:
        try:
            supabase.auth.sign_out(token)
        except Exception as e:
            logger.error(f"Supabase sign out failed: {e}")
    
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response

async def get_current_active_user(request: Request):
    if not request.state.user:
        # Redirect to the unified auth page if user is not authenticated
        raise HTTPException(status_code=303, headers={"Location": "/auth"})
    return request.state.user

# --- LLM & Card Generation ---

def generate_cards(text: str, mode="gemini", api_key: str = None, card_type: str = "basic") -> list[dict]:
    if card_type == "cloze":
        prompt = f"""
        Analyze the following text and generate cloze deletion flashcards.
        **Instructions:**
        1.  **Language:** Generate the cards in the same language as the provided text.
        2.  **Focus:** Concentrate on the core concepts, definitions, key terms, and formulas. Avoid trivial details.
        3.  **Cloze Format:** Create fill-in-the-blank cards using the {{{{c1::answer}}}} syntax.
            - The "question" field contains the full sentence with cloze deletions, e.g., "The {{{{c1::mitochondria}}}} is the powerhouse of the cell."
            - The "answer" field contains ONLY the hidden word(s), e.g., "mitochondria"
            - Each card should have exactly ONE cloze deletion.
        4.  **LaTeX:** Use LaTeX for mathematical formulas. Enclose inline math with `$` and block math with `$$`.
        5.  **Format:** Return ONLY a raw JSON object with a "cards" key, containing a list of objects, each with "question", "answer", and "card_type" keys. The "card_type" must be "cloze". Do not include markdown formatting like ```json.
        6.  **JSON Escaping:** CRITICALLY IMPORTANT: Ensure that any backslashes `\\` within strings are properly escaped as `\\\\`. This is essential for valid JSON, especially for LaTeX content.

        **Example Output:**
        {{"cards": [{{"question": "The {{{{c1::mitochondria}}}} is the powerhouse of the cell.", "answer": "mitochondria", "card_type": "cloze"}}]}}

        **Text to Analyze:**
        ---
        {text}
        ---
        """
    else:
        prompt = f"""
        Analyze the following text and generate a list of question-and-answer pairs for flashcards.
        **Instructions:**
        1.  **Language:** Generate the cards in the same language as the provided text.
        2.  **Focus:** Concentrate on the core concepts, definitions, and key formulas. Avoid trivial details.
        3.  **LaTeX:** Use LaTeX for all mathematical formulas. Enclose inline math with `$` and block math with `$$`.
        4.  **Format:** Return ONLY a raw JSON object with a "cards" key, containing a list of objects, each with "question", "answer", and "card_type" keys. The "card_type" must be "basic". Do not include markdown formatting like ```json.
        5.  **JSON Escaping:** CRITICALLY IMPORTANT: Ensure that any backslashes `\\` within the question or answer strings are properly escaped as `\\`. This is essential for valid JSON, especially for LaTeX content like `\\frac` or `\\mathbb`.

        **Text to Analyze:**
        ---
        {text}
        ---
        """

    try:
        if mode == "gemini":
            if not api_key:
                raise ValueError("Gemini API key is required.")
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={
                    'temperature': 0.5,
                    'top_p': 0.95,
                    'top_k': 64,
                    'max_output_tokens': 8192,
                    'response_mime_type': 'application/json',
                },
            )
            response_text = response.text.strip()
            
        elif mode == "ollama":
            response = ollama.chat(
                model='gpt-oss:20b',
                messages=[{'role': 'user', 'content': prompt}]
            )
            response_text = response['message']['content']
        
        elif mode == "anthropic":
            if not api_key:
                raise ValueError("Anthropic API key is required.")
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model='claude-sonnet-4-5-20250929',
                max_tokens=2048,
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
    return templates.TemplateResponse(request, "api_keys.html", {
        "api_keys": request.state.api_keys,
        "csrf_token": request.state.csrf_token,
        "user": user
    })

@app.get("/secrets", response_class=HTMLResponse)
async def secrets_form(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse(request, "secrets.html", {
        "secrets": user, 
        "csrf_token": request.state.csrf_token,
        "telegram_bot_username": TELEGRAM_BOT_USERNAME
    })

@app.post("/secrets")
async def save_secrets(request: Request, user: User = Depends(get_current_active_user), telegram_chat_id: str = Form(None)):
    # If the chat ID is an empty string, treat it as None
    if telegram_chat_id == "":
        telegram_chat_id = None
        
    crud.save_secrets_for_user(request.state.db, user.auth_user_id, telegram_chat_id)
    return JSONResponse(content={"success": True})


# --- Auth Routes (Supabase email-based login/register) ---
@app.get("/auth", response_class=HTMLResponse)
async def auth_form(request: Request):
    """Display the unified authentication form."""
    return templates.TemplateResponse(request, "auth.html", {
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_KEY,
        "csrf_token": request.state.csrf_token
    })

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """Redirect to the main authentication page for backward compatibility."""
    return RedirectResponse(url="/auth")

@app.post("/auth")
async def handle_auth(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    action: str = Form("login"), # Can be "login" or "register"
    conn: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Handles both login and registration with a unified, intelligent endpoint.
    - For login: attempts sign-in directly, handles errors appropriately
    - For register: validates password, creates user, auto-logs in
    - Returns JSON with redirect URL for frontend navigation
    """
    def error_response(error: str, prompt_register: bool = False, message: str = None):
        """Helper to return consistent error responses."""
        return JSONResponse(content={
            "success": False,
            "error": error,
            "prompt_register": prompt_register,
            "message": message,
            "email": email
        })

    def success_response(redirect_url: str, access_token: str, flash_message: str):
        """Helper to return successful auth response with cookies."""
        response = JSONResponse(content={
            "success": True,
            "redirect_url": redirect_url
        })
        response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=3600 * 24 * 7, samesite="lax")
        response.set_cookie(key="flash", value=f"success:{flash_message}", max_age=5, samesite="lax")
        return response

    try:
        if action == "register":
            # --- REGISTRATION FLOW ---
            if len(password) < 8 or not any(char.isdigit() for char in password):
                return error_response("Password must be at least 8 characters and contain one number.")

            try:
                # Create user in Supabase
                auth_response = supabase.auth.sign_up({"email": email, "password": password})
                if not auth_response.user:
                    return error_response("Could not create account. The email may be invalid.")

                # Create local profile and auto-login
                crud.create_profile(conn, username=email, auth_user_id=auth_response.user.id)
                auto_login_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                access_token = auto_login_response.session.access_token

                return success_response("/", access_token, "Account created successfully!")

            except AuthApiError as e:
                error_msg = str(e)
                if "already registered" in error_msg.lower() or "already exists" in error_msg.lower():
                    return error_response("An account with this email already exists. Please login instead.")
                return error_response(f"Registration failed: {error_msg}")
        else:
            # --- LOGIN FLOW ---
            try:
                auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                if auth_response.session:
                    access_token = auth_response.session.access_token
                    return success_response("/", access_token, "Welcome back!")
                else:
                    return error_response("Login failed. Please try again.")

            except AuthApiError as e:
                error_msg = str(e)
                # Supabase returns "Invalid login credentials" for both wrong password and non-existent user
                # We prompt to register since we can't distinguish between the two
                if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
                    return error_response(
                        "Invalid email or password.",
                        prompt_register=True,
                        message="If you don't have an account, you can register below."
                    )
                return error_response(f"Login failed: {error_msg}")

    except Exception as e:
        logger.error(f"General auth error: {e}", exc_info=True)
        return error_response("An unexpected error occurred. Please try again.")

@app.post("/auth/callback")
async def auth_callback(
    request: Request,
    data: AuthCallback,
    conn: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Handles the callback from the frontend after a successful Supabase OAuth login.
    Receives tokens, validates them, creates a local user profile if needed,
    and sets a session cookie.
    """
    try:
        user_response = supabase.auth.get_user(data.access_token)
        auth_user = user_response.user

        if not auth_user:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Create a profile if it doesn't exist.
        crud.create_profile(conn, username=auth_user.email, auth_user_id=auth_user.id)

        redirect_url = "/"

        # Set the session cookie to log the user in
        response = JSONResponse(content={"success": True, "redirect_url": redirect_url})
        response.set_cookie(
            key="access_token",
            value=data.access_token,
            httponly=True,
            max_age=3600 * 24 * 7,  # 1 week
            samesite="lax"
        )
        response.set_cookie(key="flash", value="success:Logged in successfully!", max_age=5, samesite="lax") # Flash message
        return response

    except Exception as e:
        logger.error(f"Auth callback error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Authentication callback failed.")

@app.get("/health", response_class=JSONResponse)
async def health_check():
    """A simple endpoint to keep the service alive."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "home.html", {
        "telegram_bot_username": TELEGRAM_BOT_USERNAME,
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_KEY
    })

@app.get("/courses", response_class=HTMLResponse)
async def list_courses(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse(request, "courses_list.html")

@app.get("/edit-course/{course_path:path}", response_class=HTMLResponse)
async def edit_course(request: Request, course_path: str, user: User = Depends(get_current_active_user)):
    course_path = unquote(course_path)
    gemini_api_key_exists = False
    anthropic_api_key_exists = False
    
    try:
        if request.state.api_keys:
            # Correctly access attributes on the Pydantic User model
            if request.state.api_keys.gemini_api_key:
                gemini_api_key_exists = True
            if request.state.api_keys.anthropic_api_key:
                anthropic_api_key_exists = True
        
        csrf_token = request.state.csrf_token
        
        return templates.TemplateResponse(request, "course_editor.html", {
            "course_path": course_path,
            "gemini_api_key_exists": gemini_api_key_exists,
            "anthropic_api_key_exists": anthropic_api_key_exists,
            "csrf_token": csrf_token
        })
        
    except Exception as e:
        logger.error(f"CRITICAL ERROR in edit_course: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred while loading the course editor.")

@app.get("/courses/{course_path:path}", response_class=HTMLResponse)
async def view_course(request: Request, course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course_path = unquote(course_path)
    course = crud.get_course_content_for_user(conn, course_path, auth_user_id=user.auth_user_id)
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

    gemini_api_key_exists = False
    anthropic_api_key_exists = False
    if request.state.api_keys:
        if request.state.api_keys.gemini_api_key:
            gemini_api_key_exists = True
        if request.state.api_keys.anthropic_api_key:
            anthropic_api_key_exists = True

    return templates.TemplateResponse(request, "course_viewer.html", {
        "metadata": post.metadata,
        "content": post.content,
        "course_path": course_path,
        "gemini_api_key_exists": gemini_api_key_exists,
        "anthropic_api_key_exists": anthropic_api_key_exists,
        "csrf_token": request.state.csrf_token
    })

# --- API for Courses ---
@app.get("/api/courses-tree")
async def api_get_courses_tree(conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    return crud.get_courses_tree_for_user(conn, auth_user_id=user.auth_user_id)

@app.get("/api/download-course/{course_path:path}")
async def download_course(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course_path = unquote(course_path)
    course = crud.get_course_content_for_user(conn, course_path, auth_user_id=user.auth_user_id)
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
  
    # Create a safe filename for the Content-Disposition header
    filename = os.path.basename(course_path)
    if not filename.endswith('.md'):
        filename += '.md'
        
    # For cross-browser compatibility with special characters, we create a complex header.
    # 1. A simple ASCII version of the filename for older browsers.
    ascii_filename = filename.encode('ascii', 'ignore').decode()
    # 2. The properly URL-encoded UTF-8 version for modern browsers.
    utf8_filename = quote(filename)
    
    disposition = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}'
    
    return Response(
        content=course['content'],
        media_type="text/markdown",
        headers={"Content-Disposition": disposition}
    )

@app.get("/api/course-content/{course_path:path}", response_class=JSONResponse)
async def api_get_course_content(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course_path = unquote(course_path)
    course = crud.get_course_content_for_user(conn, course_path, auth_user_id=user.auth_user_id)
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse(content=course['content'])

@app.post("/api/course-content")
async def api_save_course_content(item: CourseContent, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_course_content_for_user(conn, item.path, item.content, auth_user_id=user.auth_user_id)
    return {"success": True}

@app.api_route("/api/course-item", methods=["POST", "DELETE"])
async def api_manage_course_item(item: CourseItem, request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    if request.method == "POST":
        crud.create_course_item_for_user(conn, item.path, item.type, auth_user_id=user.auth_user_id)
    elif request.method == "DELETE":
        crud.delete_course_item_for_user(conn, item.path, item.type, auth_user_id=user.auth_user_id)
    return {"success": True}

@app.post("/api/generate-cards")
async def api_generate_cards(request: Request, data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")

    api_key = None
    if request.state.api_keys:
        api_key = request.state.api_keys.gemini_api_key

    generated_cards = generate_cards(data.content, mode="gemini", api_key=api_key, card_type=data.card_type)
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/generate-cards-ollama")
async def api_generate_cards_ollama(data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    generated_cards = generate_cards(data.content, mode="ollama", card_type=data.card_type)
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}


@app.post("/api/generate-cards-anthropic")
async def api_generate_cards_anthropic(request: Request, data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")

    api_key = None
    if request.state.api_keys:
        api_key = request.state.api_keys.anthropic_api_key

    generated_cards = generate_cards(data.content, mode="anthropic", api_key=api_key, card_type=data.card_type)
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/save-cards")
async def api_save_cards(data: GeneratedCards, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_generated_cards_for_user(conn, data.cards, user.auth_user_id)
    return {"success": True, "message": f"{len(data.cards)} cards saved successfully."}

@app.get("/api/tags")
async def api_get_tags(conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    tags = crud.get_all_tags_for_user(conn, auth_user_id=user.auth_user_id)
    return JSONResponse(content=tags)

@app.post("/api/save-api-keys")
async def api_save_api_keys(data: ApiKeys, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_api_keys_for_user(conn, user.auth_user_id, data.gemini_api_key, data.anthropic_api_key)
    return {"success": True}

# --- Tag-based Views ---
@app.get("/tags/{tag_name}", response_class=HTMLResponse)
async def view_courses_by_tag(request: Request, tag_name: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    tag_name = unquote(tag_name)
    courses = crud.get_courses_by_tag_for_user(conn, tag_name, auth_user_id=user.auth_user_id)
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
    card = crud.get_card_for_user(conn, card_id, user.auth_user_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse(request, "card_viewer.html", {"card": card})

@app.get("/review", response_class=HTMLResponse)
async def review(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_review_cards_for_user(conn, user.auth_user_id)
    stats = crud.get_review_stats_for_user(conn, user.auth_user_id)
    
    if card is None:
        return templates.TemplateResponse(request, "no_cards.html")

    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "review.html", {
        "card": card, 
        "due_today_count": stats['due_today'], 
        "new_cards_count": stats['new_cards'], 
        "total_cards": stats['total_cards'],
        "csrf_token": csrf_token
    })

@app.post("/review/{card_id}")
async def update_review(card_id: int, status: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.update_card_for_user(conn, card_id, user.auth_user_id, status == "remembered")
    return RedirectResponse(url="/review", status_code=303)

@app.get("/manage", response_class=HTMLResponse)
async def manage_cards(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    cards = crud.get_all_cards_for_user(conn, user.auth_user_id)
    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "manage_cards.html", {"cards": cards, "csrf_token": csrf_token})

@app.get("/new", response_class=HTMLResponse)
async def new_card_form(request: Request, user: User = Depends(get_current_active_user)):
    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "new_card.html", {"csrf_token": csrf_token})

@app.post("/new")
async def create_new_card(question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.create_card_for_user(conn, question, answer, user.auth_user_id)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="flash", value="success:Card created successfully!", max_age=5, samesite="lax")
    return response

@app.get("/edit-card/{card_id}", response_class=HTMLResponse)
async def edit_card_form(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_card_for_user(conn, card_id, user.auth_user_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "edit_card.html", {"card": card, "csrf_token": csrf_token})

@app.post("/edit-card/{card_id}")
async def update_existing_card(card_id: int, question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.update_card_content_for_user(conn, card_id, user.auth_user_id, question, answer)
    return RedirectResponse(url="/manage", status_code=303)

@app.post("/delete/{card_id}")
async def delete_card(card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.delete_card_for_user(conn, card_id, user.auth_user_id)
    response = RedirectResponse(url="/manage", status_code=303)
    response.set_cookie(key="flash", value="success:Card deleted successfully!", max_age=5, samesite="lax")
    return response