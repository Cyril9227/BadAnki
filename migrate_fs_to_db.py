# migrate_fs_to_db.py
import os
import frontmatter
from database import get_db_connection

COURSES_DIR = "courses"

def migrate_files_to_db():
    """
    Migrates Markdown files from the local filesystem (courses/ directory)
    into the PostgreSQL database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("Starting migration of course files to the database...")
    
    # Walk through the courses directory
    for root, _, files in os.walk(COURSES_DIR):
        for file in files:
            if file.endswith(".md"):
                fs_path = os.path.join(root, file)
                
                # Create a clean, relative path for the DB
                db_path = os.path.relpath(fs_path, COURSES_DIR)
                
                try:
                    with open(fs_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Use frontmatter to parse metadata (like tags)
                    post = frontmatter.loads(content)
                    
                    # --- Step 1: Insert the course ---
                    # Use ON CONFLICT to avoid duplicates if script is run multiple times
                    cursor.execute(
                        """
                        INSERT INTO courses (path, content)
                        VALUES (%s, %s)
                        ON CONFLICT (path) DO UPDATE SET content = EXCLUDED.content
                        RETURNING id
                        """,
                        (db_path, content)
                    )
                    course_id = cursor.fetchone()[0]
                    print(f"  - Upserted course: {db_path}")

                    # --- Step 2: Handle tags ---
                    tags = post.metadata.get('tags', [])
                    if isinstance(tags, str):
                        tags = [t.strip() for t in tags.split(',')]

                    if tags:
                        # First, remove existing tag associations for this course
                        cursor.execute("DELETE FROM course_tags WHERE course_id = %s", (course_id,))

                        for tag_name in tags:
                            # Get or create the tag
                            cursor.execute(
                                """
                                INSERT INTO tags (name)
                                VALUES (%s)
                                ON CONFLICT (name) DO NOTHING
                                RETURNING id
                                """,
                                (tag_name,)
                            )
                            tag_id_result = cursor.fetchone()
                            
                            if tag_id_result:
                                tag_id = tag_id_result[0]
                            else:
                                # If the tag already existed, fetch its ID
                                cursor.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
                                tag_id = cursor.fetchone()[0]

                            # Associate tag with course
                            cursor.execute(
                                """
                                INSERT INTO course_tags (course_id, tag_id)
                                VALUES (%s, %s)
                                ON CONFLICT DO NOTHING
                                """,
                                (course_id, tag_id)
                            )
                        print(f"    - Associated tags: {', '.join(tags)}")

                except Exception as e:
                    print(f"Error processing file {fs_path}: {e}")
                    conn.rollback()
    
    # Commit all changes
    conn.commit()
    cursor.close()
    conn.close()
    print("\nMigration complete.")

if __name__ == "__main__":
    migrate_files_to_db()
