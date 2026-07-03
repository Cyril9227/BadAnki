-- Folders migration: replaces the legacy `.placeholder` rows in courses with
-- the standalone folders table. Run once in the Supabase SQL editor (safe to
-- re-run — every statement is idempotent). The app works before AND after
-- this runs: legacy placeholders keep rendering as folders until they are
-- migrated, and the folders table is accessed best-effort until it exists.
BEGIN;

CREATE TABLE IF NOT EXISTS folders (
    user_id UUID NOT NULL,
    path TEXT NOT NULL,
    PRIMARY KEY (user_id, path)
);
ALTER TABLE folders ENABLE ROW LEVEL SECURITY;

-- Every placeholder row marked an explicitly created folder: keep the folder,
-- drop the fake file.
INSERT INTO folders (user_id, path)
SELECT user_id, left(path, length(path) - length('/.placeholder'))
FROM courses
WHERE path LIKE '%/.placeholder'
ON CONFLICT DO NOTHING;

DELETE FROM courses WHERE path LIKE '%/.placeholder';

COMMIT;
