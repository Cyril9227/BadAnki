# crud.py
# This file contains functions for Create, Read, Update, Delete (CRUD) operations.
# It helps separate the database interaction logic from the API routing logic.

import os
import frontmatter
from datetime import datetime, timedelta
from psycopg2 import extras
from database import get_db_connection

# --- Course CRUD Functions ---

def get_courses_tree_from_db(conn):
    """
    Builds a hierarchical tree of courses from the 'courses' table in the database.
    """
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT path, content FROM courses ORDER BY path")
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
                        current_level[part]['__data'] = {
                            "name": part, "path": path, "type": "directory", "depth": i, "children": []
                        }
                else:
                    try:
                        post = frontmatter.loads(course['content'])
                        title = post.metadata.get('title', part)
                    except Exception:
                        title = part
                    
                    current_level[part]['__data'] = {
                        "name": part, "path": path, "type": "file", "depth": i, "title": title
                    }
            else:
                if '__data' not in current_level[part]:
                    dir_path = os.path.join(*path_parts[:i+1])
                    current_level[part]['__data'] = {
                        "name": part, "path": dir_path, "type": "directory", "depth": i, "children": []
                    }
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

# --- Card CRUD Functions ---

def update_card(conn, card_id: int, remembered: bool):
    """
    Updates a card's review data based on the SM-2 algorithm.
    """
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
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
