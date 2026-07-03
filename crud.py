# crud.py
# This file contains functions for Create, Read, Update, Delete (CRUD) operations.
# It helps separate the database interaction logic from the API routing logic.

import logging
import os
import posixpath
import random
import frontmatter
import psycopg2
from datetime import date, datetime, timedelta
from psycopg2 import extras
from parsing import sanitize_tags

logger = logging.getLogger(__name__)

# --- Spaced Repetition Constants ---
EASE_FACTOR_MODIFIER = 0.1
MIN_EASE_FACTOR = 1.3
EASE_FACTOR_PENALTY = 0.2
INITIAL_INTERVAL = 1

# How much of a course document to fetch when only the frontmatter matters
# (titles, tags). Frontmatter blocks are tiny; documents can reach 1 MB.
FRONTMATTER_HEAD_LEN = 2048

# --- User CRUD Functions ---

def get_profile_by_auth_id(conn, auth_user_id: str):
    """Fetches a profile using the Supabase auth user ID."""
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM profiles WHERE auth_user_id = %s", (auth_user_id,))
        return cursor.fetchone()

def create_profile(conn, username: str, auth_user_id: str) -> bool:
    """
    Creates a new profile linked to a Supabase auth user.
    If the GEMINI_API_KEY environment variable is set, it will be used
    as the default key for the new user.
    This function is idempotent.
    Returns True if a new profile was created, False otherwise.
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO profiles (username, auth_user_id, gemini_api_key)
                VALUES (%s, %s, %s)
                ON CONFLICT (auth_user_id) DO NOTHING
                """,
                (username, auth_user_id, os.environ.get("GEMINI_API_KEY"))
            )
            # rowcount is 1 if a row was inserted, 0 if ON CONFLICT happened.
            is_new_user = cursor.rowcount > 0
        conn.commit()
        return is_new_user
    except Exception:
        conn.rollback()
        logger.exception("Failed to create profile for auth_user_id=%s", auth_user_id)
        return False

def get_user_by_telegram_chat_id(conn, chat_id: int):
    """Fetches a user by their Telegram chat ID."""
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM profiles WHERE telegram_chat_id = %s", (str(chat_id),))
        return cursor.fetchone()


# --- Course & Folder CRUD Functions ---

# Explicitly created folders live in the standalone folders table (see
# database.sql); folders that contain files are implicit in course paths.
# Access is best-effort so the app keeps working until the folders migration
# has been applied — legacy `.placeholder` rows keep rendering as folders in
# the meantime.

def _escape_like(path: str) -> str:
    return path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _exec_folders(conn, sql: str, params: tuple) -> int:
    """Best-effort statement against the folders table. Returns the affected
    row count, or 0 when the table isn't available yet. Destination conflicts
    (IntegrityError) do surface to the caller."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            affected = cursor.rowcount
        conn.commit()
        return affected
    except psycopg2.IntegrityError:
        _rollback_quietly(conn)
        raise
    except Exception as e:
        logger.info("Folders table unavailable: %s", e)
        _rollback_quietly(conn)
        return 0


def _get_folder_paths(conn, auth_user_id: str) -> list:
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT path FROM folders WHERE user_id = %s", (auth_user_id,))
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.info("Folders table unavailable: %s", e)
        _rollback_quietly(conn)
        return []


def _course_title(head: str, fallback: str) -> str:
    try:
        return frontmatter.loads(head).metadata.get('title', fallback)
    except Exception:
        return fallback


def _build_course_tree(entries) -> list:
    """Builds the nested course tree from {path, head} rows. A row whose
    basename is `.placeholder` marks a directory (explicitly created, possibly
    empty); other rows are files, titled from their frontmatter head."""
    nodes = {}
    for entry in entries:
        path = entry['path']
        is_placeholder = posixpath.basename(path) == '.placeholder'
        if is_placeholder:
            path = posixpath.dirname(path)
            if not path:
                continue

        path_parts = [part for part in path.split('/') if part]
        for i in range(len(path_parts)):
            current_path = "/".join(path_parts[:i + 1])
            if current_path in nodes:
                continue
            is_dir = (i < len(path_parts) - 1) or is_placeholder
            node = {
                "name": path_parts[i],
                "path": current_path,
                "type": "directory" if is_dir else "file",
                "depth": i,
                "children": [],
            }
            if not is_dir:
                node['title'] = _course_title(entry['head'], path_parts[i])
            nodes[current_path] = node

            parent_path = posixpath.dirname(current_path)
            if parent_path in nodes:
                nodes[parent_path]['children'].append(node)

    def sort_children(node):
        node['children'].sort(key=lambda x: x['name'])
        for child in node['children']:
            sort_children(child)

    root_nodes = [node for path, node in nodes.items() if posixpath.dirname(path) == '']
    for root_node in root_nodes:
        sort_children(root_node)
    return sorted(root_nodes, key=lambda x: x['name'])


def get_courses_tree_for_user(conn, auth_user_id: str):
    """Hierarchical course tree for a user. Fetches only each document's head
    (enough for the frontmatter title) instead of streaming whole courses."""
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute(
            "SELECT path, LEFT(content, %s) AS head FROM courses WHERE user_id = %s ORDER BY path",
            (FRONTMATTER_HEAD_LEN, auth_user_id),
        )
        entries = list(cursor.fetchall())
    # Explicit folders render through the same pathway legacy placeholder rows
    # used (and still use, until the folders migration runs).
    entries += [{"path": f"{p}/.placeholder", "head": ""} for p in _get_folder_paths(conn, auth_user_id)]
    return _build_course_tree(entries)

def get_course_content_for_user(conn, course_path: str, auth_user_id: str):
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT content FROM courses WHERE path = %s AND user_id = %s", (course_path, auth_user_id))
        return cursor.fetchone()

def save_course_content_for_user(conn, path: str, content: str, auth_user_id: str):
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO courses (path, content, user_id, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (path, user_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    updated_at = EXCLUDED.updated_at
                """,
                (path, content, auth_user_id, datetime.now())
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def create_course_item_for_user(conn, path: str, item_type: str, auth_user_id: str):
    if item_type in ('directory', 'folder'):
        _exec_folders(
            conn,
            "INSERT INTO folders (user_id, path) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (auth_user_id, path.rstrip('/')),
        )
        return
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO courses (path, content, user_id) VALUES (%s, %s, %s) ON CONFLICT (path, user_id) DO NOTHING",
                (path, "---\ntitle: New Course\ntags: \n---\n\n", auth_user_id)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def delete_course_item_for_user(conn, path: str, item_type: str, auth_user_id: str):
    try:
        with conn.cursor() as cursor:
            if item_type == 'file':
                cursor.execute("DELETE FROM courses WHERE path = %s AND user_id = %s", (path, auth_user_id))
            elif item_type in ['directory', 'folder']:
                # Children, plus any legacy placeholder row for the folder itself.
                cursor.execute(
                    "DELETE FROM courses WHERE (path = %s OR path LIKE %s ESCAPE '\\') AND user_id = %s",
                    (f"{path.rstrip('/')}/.placeholder", f"{_escape_like(path)}/%", auth_user_id)
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if item_type in ('directory', 'folder'):
        # The folder itself and any explicit subfolders.
        _exec_folders(
            conn,
            "DELETE FROM folders WHERE (path = %s OR path LIKE %s ESCAPE '\\') AND user_id = %s",
            (path, f"{_escape_like(path)}/%", auth_user_id),
        )

def rename_course_item_for_user(conn, old_path: str, new_path: str, item_type: str, auth_user_id: str) -> bool:
    """Renames/moves a file, or a folder with everything under it. Returns
    True when something was renamed; raises psycopg2.IntegrityError when the
    destination already exists (UNIQUE (user_id, path))."""
    try:
        with conn.cursor() as cursor:
            if item_type == 'file':
                cursor.execute(
                    "UPDATE courses SET path = %s WHERE path = %s AND user_id = %s",
                    (new_path, old_path, auth_user_id)
                )
            else:
                # substr() is 1-indexed: everything after the old prefix keeps
                # its relative path under the new one.
                cursor.execute(
                    "UPDATE courses SET path = %s || substr(path, %s) WHERE path LIKE %s ESCAPE '\\' AND user_id = %s",
                    (new_path, len(old_path) + 1, f"{_escape_like(old_path)}/%", auth_user_id)
                )
            renamed = cursor.rowcount > 0
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if item_type != 'file':
        # The folder row itself (substr past the end yields '') and subfolders.
        moved = _exec_folders(
            conn,
            "UPDATE folders SET path = %s || substr(path, %s) WHERE (path = %s OR path LIKE %s ESCAPE '\\') AND user_id = %s",
            (new_path, len(old_path) + 1, old_path, f"{_escape_like(old_path)}/%", auth_user_id),
        )
        renamed = renamed or moved > 0
    return renamed

def get_all_tags_for_user(conn, auth_user_id: str):
    """Fetches all unique tags for a user from their courses."""
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute(
            "SELECT LEFT(content, %s) AS content FROM courses WHERE user_id = %s",
            (FRONTMATTER_HEAD_LEN, auth_user_id))
        courses = cursor.fetchall()

    all_tags = set()
    for course in courses:
        try:
            post = frontmatter.loads(course['content'])
            all_tags.update(sanitize_tags(post.metadata.get('tags')))
        except Exception:
            # Ignore content that can't be parsed
            continue

    return sorted(all_tags)

def get_courses_by_tag_for_user(conn, tag: str, auth_user_id: str):
    """Fetches all courses for a user that have a specific tag."""
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute(
            "SELECT path, LEFT(content, %s) AS content FROM courses WHERE user_id = %s",
            (FRONTMATTER_HEAD_LEN, auth_user_id))
        courses = cursor.fetchall()

    tagged_courses = []
    for course in courses:
        try:
            post = frontmatter.loads(course['content'])
            if tag.lower() in sanitize_tags(post.metadata.get('tags')):
                tagged_courses.append({
                    'path': course['path'],
                    'title': post.metadata.get('title', posixpath.basename(course['path']).replace('.md', ''))
                })
        except Exception:
            continue

    return tagged_courses

# --- Card CRUD Functions ---

def get_review_cards_for_user(conn, auth_user_id: str):
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM cards WHERE user_id = %s AND due_date <= %s ORDER BY due_date LIMIT 1", (auth_user_id, datetime.now()))
        return cursor.fetchone()

def get_review_stats_for_user(conn, auth_user_id: str):
    query = """
    SELECT
        (SELECT COUNT(*) FROM cards WHERE user_id = %s AND due_date <= %s) AS due_today,
        (SELECT COUNT(*) FROM cards WHERE user_id = %s AND interval = 1 AND ease_factor = 2.5) AS new_cards,
        (SELECT COUNT(*) FROM cards WHERE user_id = %s) AS total_cards;
    """
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute(query, (auth_user_id, datetime.now(), auth_user_id, auth_user_id))
        return cursor.fetchone()


def get_all_cards_for_user(conn, auth_user_id: str):
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM cards WHERE user_id = %s ORDER BY due_date", (auth_user_id,))
        return cursor.fetchall()

def update_card_for_user(conn, card_id: int, auth_user_id: str, remembered: bool) -> bool:
    """Applies a rating to a card. Returns True when a card was updated."""
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM cards WHERE id = %s AND user_id = %s", (card_id, auth_user_id))
        card = cursor.fetchone()
        if not card:
            return False

        ease_factor, interval = card['ease_factor'], card['interval']
        if remembered:
            interval = max(1, int(interval * ease_factor))
            ease_factor += EASE_FACTOR_MODIFIER
        else:
            interval = INITIAL_INTERVAL
            ease_factor = max(MIN_EASE_FACTOR, ease_factor - EASE_FACTOR_PENALTY)

        next_due_date = datetime.now() + timedelta(days=interval)
        cursor.execute(
            "UPDATE cards SET due_date = %s, ease_factor = %s, interval = %s WHERE id = %s AND user_id = %s",
            (next_due_date, ease_factor, interval, card_id, auth_user_id)
        )
    conn.commit()
    return True

def create_card_for_user(conn, question: str, answer: str, auth_user_id: str, card_type: str = "basic"):
    with conn.cursor() as cursor:
        if _check_card_type_column(conn):
            cursor.execute(
                "INSERT INTO cards (question, answer, card_type, due_date, user_id) VALUES (%s, %s, %s, %s, %s)",
                (question, answer, card_type, datetime.now(), auth_user_id)
            )
        else:
            cursor.execute(
                "INSERT INTO cards (question, answer, due_date, user_id) VALUES (%s, %s, %s, %s)",
                (question, answer, datetime.now(), auth_user_id)
            )
    conn.commit()

def get_card_for_user(conn, card_id: int, auth_user_id: str):
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM cards WHERE id = %s AND user_id = %s", (card_id, auth_user_id))
        return cursor.fetchone()

def get_card_by_id(conn, card_id: int):
    """Fetches a card without an ownership check. Only for internal use where
    access is authorized by other means (e.g. the HMAC-signed render page)."""
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
        return cursor.fetchone()

def get_cached_photo_file_id(conn, content_hash: str):
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute(
            "SELECT telegram_file_id FROM telegram_photo_cache WHERE content_hash = %s",
            (content_hash,),
        )
        row = cursor.fetchone()
        return row["telegram_file_id"] if row else None

def cache_photo_file_id(conn, content_hash: str, telegram_file_id: str, card_id: int):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO telegram_photo_cache (content_hash, telegram_file_id, card_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (content_hash) DO UPDATE SET telegram_file_id = EXCLUDED.telegram_file_id
            """,
            (content_hash, telegram_file_id, card_id),
        )
    conn.commit()

def update_card_content_for_user(conn, card_id: int, auth_user_id: str, question: str, answer: str):
    with conn.cursor() as cursor:
        cursor.execute("UPDATE cards SET question = %s, answer = %s WHERE id = %s AND user_id = %s", (question, answer, card_id, auth_user_id))
    conn.commit()

def delete_card_for_user(conn, card_id: int, auth_user_id: str):
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM cards WHERE id = %s AND user_id = %s", (card_id, auth_user_id))
    conn.commit()

def get_random_card_for_user(conn, auth_user_id: str):
    """Fetches a random card from the database for a specific user.

    Uses COUNT + OFFSET instead of ORDER BY RANDOM() for better performance
    on large tables (avoids sorting all rows).
    """
    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
        cursor.execute("SELECT COUNT(*) FROM cards WHERE user_id = %s", (auth_user_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            return None

        cursor.execute(
            "SELECT * FROM cards WHERE user_id = %s LIMIT 1 OFFSET %s",
            (auth_user_id, random.randint(0, count - 1))
        )
        return cursor.fetchone()

_has_card_type_column = None

def _check_card_type_column(conn):
    """Check once whether the cards table has a card_type column."""
    global _has_card_type_column
    if _has_card_type_column is None:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'cards' AND column_name = 'card_type'"
            )
            _has_card_type_column = cursor.fetchone() is not None
    return _has_card_type_column

def save_generated_cards_for_user(conn, cards: list, auth_user_id: str):
    try:
        with conn.cursor() as cursor:
            if _check_card_type_column(conn):
                card_data = [
                    (card.question, card.answer, getattr(card, 'card_type', 'basic'), datetime.now(), auth_user_id)
                    for card in cards
                ]
                extras.execute_values(
                    cursor,
                    "INSERT INTO cards (question, answer, card_type, due_date, user_id) VALUES %s",
                    card_data
                )
            else:
                card_data = [(card.question, card.answer, datetime.now(), auth_user_id) for card in cards]
                extras.execute_values(
                    cursor,
                    "INSERT INTO cards (question, answer, due_date, user_id) VALUES %s",
                    card_data
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

# --- API Key and Secrets CRUD Functions ---

def save_api_keys_for_user(conn, user_id: str, gemini_api_key: str, anthropic_api_key: str):
    """Saves or updates the API keys for a specific user."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE profiles
                SET gemini_api_key = %s, anthropic_api_key = %s
                WHERE auth_user_id = %s
                """,
                (gemini_api_key, anthropic_api_key, user_id)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def save_secrets_for_user(conn, user_id: str, telegram_chat_id: str):
    """Saves or updates the Telegram chat ID for a specific user."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE profiles
                SET telegram_chat_id = %s
                WHERE auth_user_id = %s
                """,
                (telegram_chat_id, user_id)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

# --- Gamification: streaks & leaderboard ---
# Backed by the standalone review_activity table (one row per user per day,
# see database.sql). Every access is best-effort, mirroring the
# telegram_photo_cache convention: if the table doesn't exist yet, reviews
# keep working and callers get None, which hides the gamification UI.

def _rollback_quietly(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def record_review_activity(conn, auth_user_id: str, remembered: bool):
    """Counts one rated card towards today's activity."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_activity (user_id, day, reviews, remembered)
                VALUES (%s, CURRENT_DATE, 1, %s)
                ON CONFLICT (user_id, day) DO UPDATE SET
                    reviews = review_activity.reviews + 1,
                    remembered = review_activity.remembered + EXCLUDED.remembered
                """,
                (auth_user_id, 1 if remembered else 0),
            )
        conn.commit()
    except Exception as e:
        logger.info("Review activity tracking unavailable: %s", e)
        _rollback_quietly(conn)


def _compute_streaks(days: list, today: date) -> dict:
    """Streak stats from a DESCENDING list of distinct activity dates.

    The current streak counts back from today — or from yesterday when today
    has no activity yet, in which case the streak is alive but at risk.
    """
    current = 0
    if days and (today - days[0]).days <= 1:
        current = 1
        for day, previous_day in zip(days, days[1:]):
            if (day - previous_day).days == 1:
                current += 1
            else:
                break
    longest = run = 1 if days else 0
    for day, previous_day in zip(days, days[1:]):
        run = run + 1 if (day - previous_day).days == 1 else 1
        longest = max(longest, run)
    return {
        "current": current,
        "longest": longest,
        "reviewed_today": bool(days) and days[0] == today,
    }


def get_review_streak_for_user(conn, auth_user_id: str):
    """Returns the user's streak dict, or None when tracking is unavailable."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT day FROM review_activity WHERE user_id = %s ORDER BY day DESC",
                (auth_user_id,),
            )
            days = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.info("Review activity tracking unavailable: %s", e)
        _rollback_quietly(conn)
        return None
    return _compute_streaks(days, date.today())


def get_leaderboard(conn, auth_user_id: str, days: int = 30, limit: int = 10):
    """Most active reviewers over the last `days` days, or None when
    unavailable. Usernames are emails, so only the local part is exposed."""
    try:
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT a.user_id, SUM(a.reviews) AS reviews, p.username
                FROM review_activity a
                LEFT JOIN profiles p ON p.auth_user_id = a.user_id
                WHERE a.day >= CURRENT_DATE - %s
                GROUP BY a.user_id, p.username
                ORDER BY reviews DESC, a.user_id
                LIMIT %s
                """,
                (days, limit),
            )
            rows = cursor.fetchall()
    except Exception as e:
        logger.info("Review activity tracking unavailable: %s", e)
        _rollback_quietly(conn)
        return None
    board = []
    for row in rows:
        streak = get_review_streak_for_user(conn, row["user_id"]) or {"current": 0}
        board.append({
            "name": (row["username"] or "anonymous").split("@")[0],
            "reviews": row["reviews"],
            "streak": streak["current"],
            "is_me": str(row["user_id"]) == str(auth_user_id),
        })
    return board
