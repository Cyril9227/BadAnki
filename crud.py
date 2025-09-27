# crud.py
# This file contains functions for Create, Read, Update, Delete (CRUD) operations.
# It helps separate the database interaction logic from the API routing logic.

import os
import frontmatter
from datetime import datetime, timedelta
from psycopg2 import extras
from passlib.context import CryptContext

# --- Spaced Repetition Constants ---
EASE_FACTOR_MODIFIER = 0.1
MIN_EASE_FACTOR = 1.3
EASE_FACTOR_PENALTY = 0.2
INITIAL_INTERVAL = 1

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password[:72], hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password[:72])

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

def get_user_by_telegram_chat_id(conn, chat_id: int):
    """Fetches a user by their Telegram chat ID."""
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM users WHERE telegram_chat_id = %s", (str(chat_id),))
    user = cursor.fetchone()
    cursor.close()
    return user



# --- Course CRUD Functions ---

def get_courses_tree_for_user(conn, user_id: int):
    """
    Builds a hierarchical tree of courses for a specific user.
    """
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT path, content FROM courses WHERE user_id = %s ORDER BY path", (user_id,))
    courses = cursor.fetchall()
    cursor.close()

    nodes = {}

    for course in courses:
        path = course['path']
        is_placeholder = os.path.basename(path) == '.placeholder'
        if is_placeholder:
            path = os.path.dirname(path)
            if not path:
                continue
        
        path_parts = path.split(os.sep)
        for i in range(len(path_parts)):
            current_path = os.path.join(*path_parts[:i+1])
            if current_path not in nodes:
                part = path_parts[i]
                is_dir = (i < len(path_parts) - 1) or (is_placeholder)

                node = {
                    "name": part,
                    "path": current_path,
                    "type": "directory" if is_dir else "file",
                    "depth": i,
                    "children": []
                }
                
                if not is_dir:
                    try:
                        post = frontmatter.loads(course['content'])
                        node['title'] = post.metadata.get('title', part)
                    except Exception:
                        node['title'] = part

                nodes[current_path] = node
                
                parent_path = os.path.dirname(current_path)
                if parent_path in nodes:
                    nodes[parent_path]['children'].append(node)

    # This is a simplified way to get the root nodes
    root_nodes = [node for path, node in nodes.items() if os.path.dirname(path) == '']
    
    # Sort children recursively
    def sort_children(node):
        node['children'].sort(key=lambda x: x['name'])
        for child in node['children']:
            sort_children(child)

    for root_node in root_nodes:
        sort_children(root_node)

    return sorted(root_nodes, key=lambda x: x['name'])

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
            ON CONFLICT (path, user_id) DO UPDATE SET
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
                "INSERT INTO courses (path, content, user_id, type) VALUES (%s, %s, %s, 'file') ON CONFLICT (path, user_id) DO NOTHING",
                (path, "---\ntitle: New Course\ntags: \n---\n\n", user_id)
            )
        elif item_type == 'folder':
            placeholder_path = os.path.join(path, ".placeholder")
            cursor.execute(
                "INSERT INTO courses (path, content, user_id, type) VALUES (%s, %s, %s, 'directory') ON CONFLICT (path, user_id) DO NOTHING",
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

def get_all_tags_for_user(conn, user_id: int):
    """Fetches all unique tags for a user from their courses."""
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT content FROM courses WHERE user_id = %s", (user_id,))
    courses = cursor.fetchall()
    cursor.close()

    all_tags = set()
    for course in courses:
        try:
            post = frontmatter.loads(course['content'])
            tags = post.metadata.get('tags')
            if isinstance(tags, list):
                all_tags.update([str(tag).strip().lower() for tag in tags])
            elif isinstance(tags, str):
                # Split string by comma and strip whitespace
                all_tags.update([tag.strip().lower() for tag in tags.split(',')])
        except Exception:
            # Ignore content that can't be parsed
            continue
            
    return sorted(list(all_tags))

def get_courses_by_tag_for_user(conn, tag: str, user_id: int):
    """Fetches all courses for a user that have a specific tag."""
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT path, content FROM courses WHERE user_id = %s", (user_id,))
    courses = cursor.fetchall()
    cursor.close()

    tagged_courses = []
    for course in courses:
        try:
            post = frontmatter.loads(course['content'])
            tags = post.metadata.get('tags')
            
            # Normalize tags to a list of strings
            tag_list = []
            if isinstance(tags, list):
                tag_list = [str(t).strip().lower() for t in tags]
            elif isinstance(tags, str):
                tag_list = [t.strip().lower() for t in tags.split(',')]

            if tag.lower() in tag_list:
                course_info = {
                    'path': course['path'],
                    'title': post.metadata.get('title', os.path.basename(course['path']).replace('.md', ''))
                }
                tagged_courses.append(course_info)
        except Exception:
            continue
            
    return tagged_courses

# --- Card CRUD Functions ---

def get_review_cards_for_user(conn, user_id: int):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE user_id = %s AND due_date <= %s ORDER BY due_date LIMIT 1", (user_id, datetime.now()))
    card = cursor.fetchone()
    cursor.close()
    return card

def get_review_stats_for_user(conn, user_id: int):
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    query = """
    SELECT
        (SELECT COUNT(*) FROM cards WHERE user_id = %s AND due_date <= %s) AS due_today,
        (SELECT COUNT(*) FROM cards WHERE user_id = %s AND interval = 1 AND ease_factor = 2.5) AS new_cards,
        (SELECT COUNT(*) FROM cards WHERE user_id = %s) AS total_cards;
    """
    cursor.execute(query, (user_id, datetime.now(), user_id, user_id))
    stats = cursor.fetchone()
    cursor.close()
    return stats




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
        ease_factor += EASE_FACTOR_MODIFIER
    else:
        interval = INITIAL_INTERVAL
        ease_factor = max(MIN_EASE_FACTOR, ease_factor - EASE_FACTOR_PENALTY)
    
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

def get_random_card_for_user(conn, user_id: int):
    """Fetches a random card from the database for a specific user."""
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE user_id = %s ORDER BY RANDOM() LIMIT 1", (user_id,))
    card = cursor.fetchone()
    cursor.close()
    return card

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

# --- API Key and Secrets CRUD Functions ---

def save_api_keys_for_user(conn, user_id: int, gemini_api_key: str, anthropic_api_key: str):
    """Saves or updates the API keys for a specific user."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE users
            SET gemini_api_key = %s, anthropic_api_key = %s
            WHERE id = %s
            """,
            (gemini_api_key, anthropic_api_key, user_id)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def save_secrets_for_user(conn, user_id: int, telegram_chat_id: str):
    """Saves or updates the Telegram chat ID for a specific user."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE users
            SET telegram_chat_id = %s
            WHERE id = %s
            """,
            (telegram_chat_id, user_id)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
