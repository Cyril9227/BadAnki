from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Form, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import psycopg2
from psycopg2 import extras
import os
import frontmatter
from database import get_db_connection
import crud
from pydantic import BaseModel
import google.generativeai as genai
import json
import ollama
import secrets
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

# --- JWT Configuration ---
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("No SECRET_KEY set for JWT. Please set this environment variable.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Gemini API Configuration ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

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

# --- FastAPI App ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")

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
        request.state.user = await get_current_user(request, conn)
        response = await call_next(request)
    finally:
        if conn:
            conn.close()
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

def generate_cards(text: str, mode="gemini") -> list[dict]:
    prompt = f"""
        Analyze the following text and generate a list of question-and-answer pairs for flashcards.
        **Instructions:**
        1.  **Language:** Generate the cards in the same language as the provided text.
        2.  **Focus:** Concentrate on the core concepts, definitions, and key formulas. Avoid trivial details.
        3.  **LaTeX:** Use LaTeX for all mathematical formulas. Enclose inline math with `$` and block math with `$$`.
        4.  **Format:** Return a JSON object with a "cards" key, containing a list of objects, each with "question" and "answer" keys.
        **Text to Analyze:**
        ---
        {text}
        ---
        """
    try:
        if mode == "gemini":
            model = genai.GenerativeModel(model_name="gemini-1.5-flash", safety_settings=safety_settings, generation_config=generation_config)
            response = model.generate_content(prompt)
            response_text = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(response_text).get("cards", [])
        elif mode == "ollama":
            response = ollama.chat(model='llama2', messages=[{'role': 'user', 'content': prompt}])
            response_text = response['message']['content'].strip().replace("```json", "").replace("```", "")
            return json.loads(response_text).get("cards", [])
    except Exception as e:
        print(f"An error occurred during {mode} API call: {e}")
        return []


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
    return templates.TemplateResponse("course_editor.html", {"request": request, "course_path": course_path})

@app.get("/courses/{course_path:path}", response_class=HTMLResponse)
async def view_course(request: Request, course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course = crud.get_course_content_for_user(conn, course_path, user['id'])
    if not course or not course['content']:
        raise HTTPException(status_code=404, detail="Course not found")
    
    content = course['content']
    # It seems the content might be stored as a JSON string (e.g., '"---\\n..."')
    # Try to parse it as JSON first.
    try:
        content = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        # If it's not a valid JSON string, use it as is.
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
async def api_generate_cards(data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    generated_cards = generate_cards(data.content, mode="gemini")
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

@app.post("/api/save-cards")
async def api_save_cards(data: GeneratedCards, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_generated_cards_for_user(conn, data.cards, user['id'])
    return {"success": True, "message": f"{len(data.cards)} cards saved successfully."}

# --- Card Management Routes ---
@app.get("/review", response_class=HTMLResponse)
async def review(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_review_cards_for_user(conn, user['id'])
    all_cards = crud.get_all_cards_for_user(conn, user['id'])
    
    now = datetime.now()
    due_today_count = sum(1 for c in all_cards if c['due_date'] <= now)
    new_cards_count = sum(1 for c in all_cards if c['interval'] == 1 and c['ease_factor'] == 2.5)

    if card is None:
        return templates.TemplateResponse("no_cards.html", {"request": request})

    return templates.TemplateResponse("review.html", {"request": request, "card": card, "due_today_count": due_today_count, "new_cards_count": new_cards_count, "total_cards": len(all_cards)})

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