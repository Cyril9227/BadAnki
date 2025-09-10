# main.py
# This file contains the main FastAPI application.

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
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
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from scheduler import run_scheduler

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
security = HTTPBasic()

# --- Authentication ---
def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    """Dependency to verify basic auth credentials."""
    correct_username = secrets.compare_digest(
        credentials.username, os.environ.get("ADMIN_USERNAME", "admin")
    )
    correct_password = secrets.compare_digest(
        credentials.password, os.environ.get("ADMIN_PASSWORD", "password")
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- Pydantic Models ---
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
def get_db():
    """
    FastAPI dependency to manage database connections.
    Yields a connection for each request and closes it afterwards.
    """
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()

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
@app.get("/api/trigger-scheduler")
async def trigger_scheduler(secret: str):
    """
    A secure endpoint to trigger the daily scheduler.
    Requires a secret key passed as a query parameter.
    """
    SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET")
    if not SCHEDULER_SECRET or not secrets.compare_digest(secret, SCHEDULER_SECRET):
        raise HTTPException(status_code=403, detail="Invalid secret key")
    
    result = await run_scheduler()
    return {"status": "success", "message": result}

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/courses", response_class=HTMLResponse)
async def list_courses(request: Request):
    return templates.TemplateResponse("courses_list.html", {"request": request})

@app.get("/edit-course/{course_path:path}", response_class=HTMLResponse)
async def edit_course(request: Request, course_path: str, user: str = Depends(get_current_user)):
    return templates.TemplateResponse("course_editor.html", {"request": request, "course_path": course_path})

@app.get("/courses/{course_path:path}", response_class=HTMLResponse)
async def view_course(request: Request, course_path: str, conn: psycopg2.extensions.connection = Depends(get_db)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE path = %s", (course_path,))
    course = cursor.fetchone()
    cursor.close()

    if not course or not course['content']:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        post = frontmatter.loads(course['content'])
        return templates.TemplateResponse("course_viewer.html", {
            "request": request,
            "metadata": post.metadata,
            "content": post.content,
            "course_path": course_path
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading course content: {e}")

@app.get("/tags/{tag_name}", response_class=HTMLResponse)
async def view_tag_courses(request: Request, tag_name: str):
    return templates.TemplateResponse("tag_courses.html", {"request": request, "tag_name": tag_name})

# --- API for Courses ---
@app.get("/api/courses-tree")
async def api_get_courses_tree(conn: psycopg2.extensions.connection = Depends(get_db)):
    return crud.get_courses_tree_from_db(conn)

@app.get("/api/course-content/{course_path:path}", response_class=JSONResponse)
async def api_get_course_content(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE path = %s", (course_path,))
    course = cursor.fetchone()
    cursor.close()
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse(content=course['content'])

@app.post("/api/course-content")
async def api_save_course_content(item: CourseContent, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO courses (path, content, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (path) DO UPDATE SET
                content = EXCLUDED.content,
                updated_at = EXCLUDED.updated_at
            """,
            (item.path, item.content, datetime.now())
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@app.api_route("/api/course-item", methods=["POST", "DELETE"])
async def api_manage_course_item(item: CourseItem, request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor()
    try:
        if request.method == "POST":
            if item.type == 'file':
                if not item.path.endswith('.md'):
                    raise HTTPException(status_code=400, detail="File must have a .md extension")
                cursor.execute(
                    "INSERT INTO courses (path, content) VALUES (%s, %s) ON CONFLICT (path) DO NOTHING",
                    (item.path, "---\ntitle: New Course\ntags: \n---\n\n")
                )
            elif item.type == 'folder':
                if not item.path:
                    raise HTTPException(status_code=400, detail="Folder path cannot be empty.")
                placeholder_path = os.path.join(item.path, ".placeholder")
                cursor.execute(
                    "INSERT INTO courses (path, content) VALUES (%s, %s) ON CONFLICT (path) DO NOTHING",
                    (placeholder_path, "This is a placeholder file to make the folder visible.")
                )
            else:
                raise HTTPException(status_code=400, detail="Invalid type")
            conn.commit()
            return {"success": True}

        elif request.method == "DELETE":
            if item.type == 'file':
                cursor.execute("DELETE FROM courses WHERE path = %s", (item.path,))
            elif item.type == 'folder':
                placeholder_path = os.path.join(item.path, ".placeholder")
                cursor.execute("DELETE FROM courses WHERE path = %s OR path LIKE %s", (placeholder_path, f"{item.path}/%"))
            else:
                raise HTTPException(status_code=404, detail="Item not found")
            conn.commit()
            return {"success": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@app.post("/api/generate-cards")
async def api_generate_cards(data: CourseContentForGeneration, user: str = Depends(get_current_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    generated_cards = generate_cards(data.content, mode="gemini")
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/generate-cards-ollama")
async def api_generate_cards_ollama(data: CourseContentForGeneration, user: str = Depends(get_current_user)):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    generated_cards = generate_cards(data.content, mode="ollama")
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/save-cards")
async def api_save_cards(data: GeneratedCards, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor()
    try:
        card_data = [(card.question, card.answer, datetime.now()) for card in data.cards]
        extras.execute_values(
            cursor,
            "INSERT INTO cards (question, answer, due_date) VALUES %s",
            card_data
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        cursor.close()
    return {"success": True, "message": f"{len(data.cards)} cards saved successfully."}

@app.get("/api/download-course/{course_path:path}")
async def download_course(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE path = %s", (course_path,))
    course = cursor.fetchone()
    cursor.close()

    if not course or not course['content']:
        raise HTTPException(status_code=404, detail="Course not found")

    headers = {
        'Content-Disposition': f'attachment; filename="{os.path.basename(course_path)}"'
    }
    
    return HTMLResponse(content=course['content'], media_type='text/markdown', headers=headers)

@app.get("/api/tags")
async def api_get_all_tags(conn: psycopg2.extensions.connection = Depends(get_db)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT name FROM tags ORDER BY name")
    tags = [row["name"] for row in cursor.fetchall()]
    cursor.close()
    return tags

@app.get("/api/courses-by-tag/{tag_name}")
async def api_get_courses_by_tag(tag_name: str, conn: psycopg2.extensions.connection = Depends(get_db)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("""
        SELECT c.path, c.content
        FROM courses c
        JOIN course_tags ct ON c.id = ct.course_id
        JOIN tags t ON ct.tag_id = t.id
        WHERE t.name = %s
        ORDER BY c.path
    """, (tag_name,))
    courses = cursor.fetchall()
    cursor.close()
    
    results = []
    for course in courses:
        try:
            post = frontmatter.loads(course["content"])
            results.append({
                "path": course["path"],
                "title": post.metadata.get("title", os.path.basename(course["path"]))
            })
        except Exception:
            continue
            
    return results

# --- Card Management Routes ---
@app.get("/review", response_class=HTMLResponse)
async def review(request: Request, conn: psycopg2.extensions.connection = Depends(get_db)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    
    cursor.execute("SELECT * FROM cards WHERE due_date <= %s ORDER BY due_date LIMIT 1", (datetime.now(),))
    card = cursor.fetchone()
    
    cursor.execute("SELECT * FROM cards ORDER BY due_date")
    all_cards = cursor.fetchall()
    
    cursor.close()
    
    now = datetime.now()
    due_today_count = sum(1 for c in all_cards if c['due_date'] <= now)
    new_cards_count = sum(1 for c in all_cards if c['interval'] == 1 and c['ease_factor'] == 2.5)

    if card is None:
        return templates.TemplateResponse("no_cards.html", {"request": request})

    return templates.TemplateResponse("review.html", {"request": request, "card": card, "due_today_count": due_today_count, "new_cards_count": new_cards_count, "total_cards": len(all_cards)})

@app.post("/review/{card_id}")
async def update_review(card_id: int, status: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    crud.update_card(conn, card_id, status == "remembered")
    return RedirectResponse(url="/review", status_code=303)

@app.get("/manage", response_class=HTMLResponse)
async def manage_cards(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards ORDER BY due_date")
    cards = cursor.fetchall()
    cursor.close()

    return templates.TemplateResponse("manage_cards.html", {"request": request, "cards": cards})

@app.get("/new", response_class=HTMLResponse)
async def new_card_form(request: Request, user: str = Depends(get_current_user)):
    return templates.TemplateResponse("new_card.html", {"request": request})

@app.post("/new")
async def create_new_card(question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cards (question, answer, due_date) VALUES (%s, %s, %s)",
        (question, answer, datetime.now())
    )
    conn.commit()
    cursor.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/edit-card/{card_id}", response_class=HTMLResponse)
async def edit_card_form(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cursor.fetchone()
    cursor.close()
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse("edit_card.html", {"request": request, "card": card})

@app.post("/edit-card/{card_id}")
async def update_existing_card(card_id: int, question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor()
    cursor.execute("UPDATE cards SET question = %s, answer = %s WHERE id = %s", (question, answer, card_id))
    conn.commit()
    cursor.close()
    return RedirectResponse(url="/manage", status_code=303)

@app.post("/delete/{card_id}")
async def delete_card(card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: str = Depends(get_current_user)):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cards WHERE id = %s", (card_id,))
    conn.commit()
    cursor.close()
    return RedirectResponse(url="/manage", status_code=303)
