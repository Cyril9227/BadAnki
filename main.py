from dotenv import load_dotenv
load_dotenv()

# Standard library
import json
import logging
import os
import secrets
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
from jose import JWTError, jwt
from pydantic import BaseModel
from telegram import Update

# Local application
import crud
from bot import setup_bot
from database import get_db_connection, release_db_connection
from scheduler import run_scheduler
from utils.json_parsing import normalize_cards, robust_json_loads


# --- JWT Configuration ---
SECRET_KEY = os.environ.get("SECRET_KEY")
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")

if not SECRET_KEY:
    raise ValueError("No SECRET_KEY set for JWT. Please set this environment variable.")
if not SCHEDULER_SECRET:
    raise ValueError("No SCHEDULER_SECRET set. Please set this environment variable.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Bot Setup ---
bot_app = setup_bot()
logger = logging.getLogger(__name__)

# --- FastAPI App ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- App Events ---
@app.on_event("startup")
async def startup_event():
    if bot_app:
        try:
            await bot_app.initialize()
            await bot_app.start()
            
            # In production, set the webhook
            if os.environ.get("ENVIRONMENT") == "production":
                # Use a secret in the URL instead of the raw token
                webhook_secret = TELEGRAM_WEBHOOK_SECRET
                if not webhook_secret:
                    logger.warning("TELEGRAM_WEBHOOK_SECRET not set. Please set this for production.")

                webhook_url = f"{os.environ.get('APP_URL')}/webhook/{webhook_secret}"
                logger.info(f"Attempting to set webhook to: {webhook_url}")
                await bot_app.bot.set_webhook(url=webhook_url)
                logger.info("Webhook set successfully.")
            # In development, start polling
            else:
                logger.info("Starting bot in polling mode for local development.")
                await bot_app.updater.start_polling()
                logger.info("Bot started polling.")
        except Exception as e:
            logger.error(f"CRITICAL ERROR during bot startup: {e}", exc_info=True)

@app.on_event("shutdown")
async def shutdown_event():
    if bot_app:
        # In production, delete the webhook
        if os.environ.get("ENVIRONMENT") == "production":
            logger.info("Deleting webhook.")
            await bot_app.bot.delete_webhook()
            logger.info("Webhook deleted.")
        # In development, stop the polling
        else:
            logger.info("Stopping bot polling.")
            await bot_app.updater.stop()
            logger.info("Bot polling stopped.")
        await bot_app.stop()

# --- Webhook Endpoint ---
@app.post("/webhook/{secret}")
async def webhook(request: Request, secret: str):
    # Validate the secret
    expected_secret = TELEGRAM_WEBHOOK_SECRET
    if not expected_secret or not secrets.compare_digest(secret, expected_secret):
        logger.warning("Invalid secret received in webhook request.")
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    logger.info("Webhook endpoint received a valid request.")
    if bot_app:
        try:
            data = await request.json()
            logger.debug(f"Webhook received data: {data}")
            update = Update.de_json(data, bot_app.bot)
            await bot_app.update_queue.put(update)
            logger.debug("Update successfully put into queue.")
        except Exception as e:
            logger.error(f"Error processing webhook update: {e}", exc_info=True)
    
    return Response(status_code=200)


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
        if user:
            api_keys = crud.get_api_keys_for_user(conn, user['id'])
            request.state.api_keys = api_keys
        else:
            request.state.api_keys = None
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
            if api_key:
                genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash", 
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
    return templates.TemplateResponse("api_keys.html", {"request": request, "api_keys": request.state.api_keys})



# --- FastAPI Routes ---

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_for_access_token(response: Response, form_data: OAuth2PasswordRequestForm = Depends(), conn: psycopg2.extensions.connection = Depends(get_db)):
    user = crud.get_user_by_username(conn, form_data.username)
    if not user or not crud.verify_password(form_data.password, user['password_hash']):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
async def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register_user(username: str = Form(...), password: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db)):
    user = crud.get_user_by_username(conn, username)
    if user:
        raise HTTPException(status_code=400, detail="Username already registered")
    crud.create_user(conn, username, password)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/courses", response_class=HTMLResponse)
async def list_courses(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse("courses_list.html", {"request": request})

@app.get("/edit-course/{course_path:path}", response_class=HTMLResponse)
async def edit_course(request: Request, course_path: str, user: User = Depends(get_current_active_user)):
    gemini_api_key_exists = False
    anthropic_api_key_exists = False
    if request.state.api_keys:
        if request.state.api_keys.get('gemini_api_key'):
            gemini_api_key_exists = True
        if request.state.api_keys.get('anthropic_api_key'):
            anthropic_api_key_exists = True
    
    return templates.TemplateResponse("course_editor.html", {
        "request": request, 
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
    return templates.TemplateResponse("course_viewer.html", {"request": request, "metadata": post.metadata, "content": post.content, "course_path": course_path})

# --- API for Courses ---
@app.get("/api/courses-tree")
async def api_get_courses_tree(conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    return crud.get_courses_tree_for_user(conn, user['id'])

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
    return templates.TemplateResponse("tag_courses.html", {"request": request, "tag": tag_name, "courses": courses})

# --- Scheduler ---
@app.get("/api/trigger-scheduler")
async def trigger_scheduler(secret: str):
    if secret != SCHEDULER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    result = await run_scheduler()
    return JSONResponse(content={"status": "completed", "result": result})

# --- Card Management Routes ---
@app.get("/card/{card_id}", response_class=HTMLResponse)
async def view_card(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_card_for_user(conn, card_id, user['id'])
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse("card_viewer.html", {"request": request, "card": card})

@app.get("/review", response_class=HTMLResponse)
async def review(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_review_cards_for_user(conn, user['id'])
    stats = crud.get_review_stats_for_user(conn, user['id'])
    
    if card is None:
        return templates.TemplateResponse("no_cards.html", {"request": request})

    return templates.TemplateResponse("review.html", {
        "request": request, 
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
    return templates.TemplateResponse("manage_cards.html", {"request": request, "cards": cards})

@app.get("/new", response_class=HTMLResponse)
async def new_card_form(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse("new_card.html", {"request": request})

@app.post("/new")
async def create_new_card(question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.create_card_for_user(conn, question, answer, user['id'])
    return RedirectResponse(url="/", status_code=303)

@app.get("/edit-card/{card_id}", response_class=HTMLResponse)
async def edit_card_form(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_card_for_user(conn, card_id, user['id'])
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse("edit_card.html", {"request": request, "card": card})

@app.post("/edit-card/{card_id}")
async def update_existing_card(card_id: int, question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.update_card_content_for_user(conn, card_id, user['id'], question, answer)
    return RedirectResponse(url="/manage", status_code=303)

@app.post("/delete/{card_id}")
async def delete_card(card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.delete_card_for_user(conn, card_id, user['id'])
    return RedirectResponse(url="/manage", status_code=303)
