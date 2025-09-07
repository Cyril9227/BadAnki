# main.py
# This file contains the main FastAPI application.

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import psycopg2
from psycopg2 import extras
import os
import shutil
import frontmatter
from database import get_db_connection, create_database
from pydantic import BaseModel
import google.generativeai as genai
import json
import ollama


# --- Gemini API Configuration ---
# Ensure your API key is set as an environment variable
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

# --- Helper Functions ---
def get_courses_tree_from_db():
    """
    Builds a hierarchical tree of courses from the 'courses' table in the database.
    This function simulates a file system structure based on the 'path' column.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT path, content FROM courses ORDER BY path")
    courses = cursor.fetchall()
    cursor.close()
    conn.close()

    tree = []
    nodes = {}

    for course in courses:
        if os.path.basename(course['path']) == '.placeholder':
            continue

        path_parts = course['path'].split(os.sep)
        current_path = ""
        
        for i, part in enumerate(path_parts):
            parent_path = current_path
            current_path = os.path.join(current_path, part)

            if current_path not in nodes:
                is_dir = i < len(path_parts) - 1
                
                node = {
                    "name": part,
                    "path": current_path,
                    "type": "directory" if is_dir else "file",
                    "depth": i,
                    "children": [] if is_dir else None
                }

                if not is_dir:
                    try:
                        post = frontmatter.loads(course['content'])
                        node["title"] = post.metadata.get('title', part)
                    except Exception:
                        node["title"] = part

                nodes[current_path] = node

                if parent_path in nodes:
                    nodes[parent_path]["children"].append(node)
                elif i == 0:
                    tree.append(node)

    return tree

# --- Spaced Repetition Logic ---
def update_card(card_id: int, remembered: bool):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cursor.fetchone()
    if not card: 
        cursor.close()
        conn.close()
        return

    ease_factor, interval = card['ease_factor'], card['interval']
    if remembered:
        interval = int(interval * ease_factor)
        ease_factor += 0.1
    else:
        interval = 1
        ease_factor = max(1.3, ease_factor - 0.2)
    
    next_due_date = datetime.now() + timedelta(days=interval)
    cursor.execute("UPDATE cards SET due_date = %s, ease_factor = %s, interval = %s WHERE id = %s", (next_due_date, ease_factor, interval, card_id))
    conn.commit()
    cursor.close()
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
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/courses", response_class=HTMLResponse)
async def list_courses(request: Request):
    return templates.TemplateResponse("courses_list.html", {"request": request})

@app.get("/edit/{course_path:path}", response_class=HTMLResponse)
async def edit_course(request: Request, course_path: str):
    return templates.TemplateResponse("course_editor.html", {"request": request, "course_path": course_path})

@app.get("/courses/{course_path:path}", response_class=HTMLResponse)
async def view_course(request: Request, course_path: str):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE path = %s", (course_path,))
    course = cursor.fetchone()
    cursor.close()
    conn.close()

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
    """
    Renders a page showing all courses associated with a given tag.
    """
    return templates.TemplateResponse("tag_courses.html", {"request": request, "tag_name": tag_name})

# --- API for Courses ---
@app.get("/api/courses-tree")
async def api_get_courses_tree():
    return get_courses_tree_from_db()

@app.get("/api/course-content/{course_path:path}", response_class=JSONResponse)
async def api_get_course_content(course_path: str):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE path = %s", (course_path,))
    course = cursor.fetchone()
    cursor.close()
    conn.close()
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse(content=course['content'])

@app.post("/api/course-content")
async def api_save_course_content(item: CourseContent):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Use INSERT ... ON CONFLICT to either create a new course or update an existing one
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
        conn.close()

@app.api_route("/api/course-item", methods=["POST", "DELETE"])
async def api_manage_course_item(item: CourseItem, request: Request):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if request.method == "POST":
            if item.type == 'file':
                if not item.path.endswith('.md'):
                    raise HTTPException(status_code=400, detail="File must have a .md extension")
                # Create a new file with default content if it doesn't exist
                cursor.execute(
                    "INSERT INTO courses (path, content) VALUES (%s, %s) ON CONFLICT (path) DO NOTHING",
                    (item.path, "---\ntitle: New Course\ntags: \n---\n\n")
                )
            elif item.type == 'folder':
                if not item.path:
                    raise HTTPException(status_code=400, detail="Folder path cannot be empty.")
                # Create a placeholder file to make the folder appear in the tree
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
                # Delete the folder's placeholder and all courses/subfolders within it
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
        conn.close()

@app.post("/api/generate-cards")
async def api_generate_cards(data: CourseContentForGeneration):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    generated_cards = generate_cards(data.content, mode="gemini")
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/generate-cards-ollama")
async def api_generate_cards_ollama(data: CourseContentForGeneration):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    generated_cards = generate_cards(data.content, mode="ollama")
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/save-cards")
async def api_save_cards(data: GeneratedCards):
    conn = get_db_connection()
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
        conn.close()
    return {"success": True, "message": f"{len(data.cards)} cards saved successfully."}

@app.get("/api/download-course/{course_path:path}")
async def download_course(course_path: str):
    """
    Provides the course content as a downloadable Markdown file.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE path = %s", (course_path,))
    course = cursor.fetchone()
    cursor.close()
    conn.close()

    if not course or not course['content']:
        raise HTTPException(status_code=404, detail="Course not found")

    headers = {
        'Content-Disposition': f'attachment; filename="{os.path.basename(course_path)}"'
    }
    
    return HTMLResponse(content=course['content'], media_type='text/markdown', headers=headers)

@app.get("/api/tags")
async def api_get_all_tags():
    """
    Retrieves all unique tags from the database.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT name FROM tags ORDER BY name")
    tags = [row["name"] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return tags

@app.get("/api/courses-by-tag/{tag_name}")
async def api_get_courses_by_tag(tag_name: str):
    """
    Retrieves all courses associated with a specific tag.
    """
    conn = get_db_connection()
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
    conn.close()
    
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
async def review(request: Request):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    
    cursor.execute("SELECT * FROM cards WHERE due_date <= %s ORDER BY due_date LIMIT 1", (datetime.now(),))
    card = cursor.fetchone()
    
    cursor.execute("SELECT * FROM cards ORDER BY due_date")
    all_cards = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    now = datetime.now()
    due_today_count = sum(1 for c in all_cards if c['due_date'] <= now)
    new_cards_count = sum(1 for c in all_cards if c['interval'] == 1 and c['ease_factor'] == 2.5)

    if card is None:
        return templates.TemplateResponse("no_cards.html", {"request": request})

    return templates.TemplateResponse("review.html", {"request": request, "card": card, "due_today_count": due_today_count, "new_cards_count": new_cards_count, "total_cards": len(all_cards)})

@app.post("/review/{card_id}")
async def update_review(card_id: int, status: str = Form(...)):
    update_card(card_id, status == "remembered")
    return RedirectResponse(url="/review", status_code=303)

@app.get("/manage", response_class=HTMLResponse)
async def manage_cards(request: Request):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards ORDER BY due_date")
    cards = cursor.fetchall()
    cursor.close()
    conn.close()

    return templates.TemplateResponse("manage_cards.html", {"request": request, "cards": cards})

@app.get("/new", response_class=HTMLResponse)
async def new_card_form(request: Request):
    return templates.TemplateResponse("new_card.html", {"request": request})

@app.post("/new")
async def create_new_card(question: str = Form(...), answer: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cards (question, answer, due_date) VALUES (%s, %s, %s)",
        (question, answer, datetime.now())
    )
    conn.commit()
    cursor.close()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/edit-card/{card_id}", response_class=HTMLResponse)
async def edit_card_form(request: Request, card_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
    card = cursor.fetchone()
    cursor.close()
    conn.close()
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse("edit_card.html", {"request": request, "card": card})

@app.post("/edit-card/{card_id}")
async def update_existing_card(card_id: int, question: str = Form(...), answer: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE cards SET question = %s, answer = %s WHERE id = %s", (question, answer, card_id))
    conn.commit()
    cursor.close()
    conn.close()
    return RedirectResponse(url="/manage", status_code=303)

@app.post("/delete/{card_id}")
async def delete_card(card_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cards WHERE id = %s", (card_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return RedirectResponse(url="/manage", status_code=303)