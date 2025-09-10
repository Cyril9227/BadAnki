# crud.py
# This file contains functions for Create, Read, Update, Delete (CRUD) operations.
# It helps separate the database interaction logic from the API routing logic.

import os
import frontmatter
from datetime import datetime, timedelta
from psycopg2 import extras
from database import get_db_connection
from passlib.context import CryptContext

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# --- User CRUD Functions ---

def get_user_by_username(conn, username: str):
    """Fetches a user by their username."""
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    return user

def create_user(conn, username: str, password: str):
    """Creates a new user with a hashed password."""
    hashed_password = get_password_hash(password)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
            (username, hashed_password)
        )
        user_id = cursor.fetchone()[0]
        conn.commit()
        return user_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

# --- Course CRUD Functions ---

def get_courses_tree_for_user(conn, user_id: int):
    """
    Builds a hierarchical tree of courses for a specific user.
    """
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT path, content FROM courses WHERE user_id = %s ORDER BY path", (user_id,))
    courses = cursor.fetchall()
    cursor.close()

    root = {}
    for course in courses:
        path = course['path']
        is_placeholder = os.path.basename(path) == '.placeholder'
        if is_placeholder:
            path = os.path.dirname(path)
            if not path:
                continue

        path_parts = path.split(os.sep)
        current_level = root
        
        for i, part in enumerate(path_parts):
            if part not in current_level:
                current_level[part] = {}
            
            if i == len(path_parts) - 1:
                if is_placeholder:
                    if '__data' not in current_level[part]:
                        current_level[part]['__data'] = {"name": part, "path": path, "type": "directory", "depth": i, "children": []}
                else:
                    try:
                        post = frontmatter.loads(course['content'])
                        title = post.metadata.get('title', part)
                    except Exception:
                        title = part
                    current_level[part]['__data'] = {"name": part, "path": path, "type": "file", "depth": i, "title": title}
            else:
                if '__data' not in current_level[part]:
                    dir_path = os.path.join(*path_parts[:i+1])
                    current_level[part]['__data'] = {"name": part, "path": dir_path, "type": "directory", "depth": i, "children": []}
                if '__children' not in current_level[part]:
                    current_level[part]['__children'] = {}
                current_level = current_level[part]['__children']

    def build_final_tree(tree_dict):
        final_list = []
        for key, value in sorted(tree_dict.items()):
            if '__data' in value:
                node_data = value['__data']
                if '__children' in value:
                    node_data['children'] = build_final_tree(value['__children'])
                final_list.append(node_data)
        return final_list

    return build_final_tree(root)

def get_course_content_for_user(conn, course_path: str, user_id: int):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE path = %s AND user_id = %s", (course_path, user_id))
    course = cursor.fetchone()
    cursor.close()
    return course

def save_course_content_for_user(conn, path: str, content: str, user_id: int):
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO courses (path, content, user_id, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (path) DO UPDATE SET
                content = EXCLUDED.content,
                updated_at = EXCLUDED.updated_at
            """,
            (path, content, user_id, datetime.now())
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def create_course_item_for_user(conn, path: str, item_type: str, user_id: int):
    cursor = conn.cursor()
    try:
        if item_type == 'file':
            cursor.execute(
                "INSERT INTO courses (path, content, user_id) VALUES (%s, %s, %s) ON CONFLICT (path) DO NOTHING",
                (path, "---\ntitle: New Course\ntags: \n---\n\n", user_id)
            )
        elif item_type == 'folder':
            placeholder_path = os.path.join(path, ".placeholder")
            cursor.execute(
                "INSERT INTO courses (path, content, user_id) VALUES (%s, %s, %s) ON CONFLICT (path) DO NOTHING",
                (placeholder_path, "This is a placeholder file.", user_id)
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def delete_course_item_for_user(conn, path: str, item_type: str, user_id: int):
    cursor = conn.cursor()
    try:
        if item_type == 'file':
            cursor.execute("DELETE FROM courses WHERE path = %s AND user_id = %s", (path, user_id))
        elif item_type == 'folder':
            placeholder_path = os.path.join(path, ".placeholder")
            cursor.execute("DELETE FROM courses WHERE (path = %s OR path LIKE %s) AND user_id = %s", (placeholder_path, f"{path}/%", user_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

# --- Card CRUD Functions ---

def get_review_cards_for_user(conn, user_id: int):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE user_id = %s AND due_date <= %s ORDER BY due_date LIMIT 1", (user_id, datetime.now()))
    card = cursor.fetchone()
    cursor.close()
    return card

def get_all_cards_for_user(conn, user_id: int):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE user_id = %s ORDER BY due_date", (user_id,))
    cards = cursor.fetchall()
    cursor.close()
    return cards

def update_card_for_user(conn, card_id: int, user_id: int, remembered: bool):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE id = %s AND user_id = %s", (card_id, user_id))
    card = cursor.fetchone()
    if not card:
        cursor.close()
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

def create_card_for_user(conn, question: str, answer: str, user_id: int):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cards (question, answer, due_date, user_id) VALUES (%s, %s, %s, %s)",
        (question, answer, datetime.now(), user_id)
    )
    conn.commit()
    cursor.close()

def get_card_for_user(conn, card_id: int, user_id: int):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE id = %s AND user_id = %s", (card_id, user_id))
    card = cursor.fetchone()
    cursor.close()
    return card

def update_card_content_for_user(conn, card_id: int, user_id: int, question: str, answer: str):
    cursor = conn.cursor()
    cursor.execute("UPDATE cards SET question = %s, answer = %s WHERE id = %s AND user_id = %s", (question, answer, card_id, user_id))
    conn.commit()
    cursor.close()

def delete_card_for_user(conn, card_id: int, user_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cards WHERE id = %s AND user_id = %s", (card_id, user_id))
    conn.commit()
    cursor.close()

def save_generated_cards_for_user(conn, cards: list, user_id: int):
    cursor = conn.cursor()
    try:
        card_data = [(card.question, card.answer, datetime.now(), user_id) for card in cards]
        extras.execute_values(
            cursor,
            "INSERT INTO cards (question, answer, due_date, user_id) VALUES %s",
            card_data
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()