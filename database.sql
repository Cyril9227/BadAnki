-- Create the profiles table (linked 1:1 to auth.users)
CREATE TABLE IF NOT EXISTS profiles (
    auth_user_id UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    username TEXT UNIQUE NOT NULL,
    telegram_chat_id TEXT,
    gemini_api_key TEXT,
    anthropic_api_key TEXT
);

-- Create the cards table
CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    due_date TIMESTAMP NOT NULL,
    interval INT NOT NULL DEFAULT 0,
    ease_factor FLOAT4 NOT NULL DEFAULT 2.5,
    user_id UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE
);

-- Create the courses table
CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    content TEXT,
    updated_at TIMESTAMP,
    user_id UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    UNIQUE (user_id, path)
);

-- Cache of Telegram file_ids for rendered card-answer screenshots.
-- Deliberately standalone (no FK into cards): rows are keyed by a hash of the
-- answer content, so editing a card produces a new key and stale rows are
-- simply never read again. The bot treats this table as best-effort — if it
-- is missing or unreachable, photos are re-rendered as usual.
CREATE TABLE IF NOT EXISTS telegram_photo_cache (
    content_hash TEXT PRIMARY KEY,
    telegram_file_id TEXT NOT NULL,
    card_id INT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Per-user daily review counts powering streaks and the leaderboard
-- (gamification). Standalone and additive like telegram_photo_cache: no FKs
-- into existing tables, and the app treats it as best-effort — if the table
-- is missing, reviews keep working and the gamification UI silently hides.
CREATE TABLE IF NOT EXISTS review_activity (
    user_id UUID NOT NULL,
    day DATE NOT NULL,
    reviews INT NOT NULL DEFAULT 0,
    remembered INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

-- Explicitly created course folders. Folders that contain files are implicit
-- in course paths; this table only records the (possibly empty) ones the user
-- created on purpose. It replaces the legacy `.placeholder` rows in courses
-- (backfilled by a one-off migration run in the Supabase SQL editor).
-- Standalone and additive: no FKs into existing tables, best-effort access.
CREATE TABLE IF NOT EXISTS folders (
    user_id UUID NOT NULL,
    path TEXT NOT NULL,
    PRIMARY KEY (user_id, path)
);

-- Supabase Data API hardening:
-- The browser only needs Supabase Auth, not direct table access. Enabling RLS
-- keeps the public anon key from exposing tables through PostgREST. The backend
-- still uses its direct DATABASE_URL connection for application data access.
-- profiles intentionally has no Data API policies because it stores API keys.
-- The role/function guards keep local test Postgres compatible; Supabase
-- already provides these roles and auth.uid().
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'auth' AND p.proname = 'uid'
    ) THEN
        CREATE FUNCTION auth.uid() RETURNS uuid
        LANGUAGE sql STABLE
        AS 'SELECT NULL::uuid';
    END IF;
END $$;

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
-- Like profiles, telegram_photo_cache intentionally has no Data API policies:
-- only the backend's direct connection should ever touch it.
ALTER TABLE telegram_photo_cache ENABLE ROW LEVEL SECURITY;
-- review_activity and folders likewise: backend-only, no Data API policies.
ALTER TABLE review_activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE folders ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    DROP POLICY IF EXISTS profiles_select_own ON profiles;
    DROP POLICY IF EXISTS profiles_update_own ON profiles;
    DROP POLICY IF EXISTS profiles_insert_own ON profiles;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'cards' AND policyname = 'cards_select_own'
    ) THEN
        CREATE POLICY cards_select_own ON cards
            FOR SELECT TO authenticated
            USING ((select auth.uid()) = user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'cards' AND policyname = 'cards_insert_own'
    ) THEN
        CREATE POLICY cards_insert_own ON cards
            FOR INSERT TO authenticated
            WITH CHECK ((select auth.uid()) = user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'cards' AND policyname = 'cards_update_own'
    ) THEN
        CREATE POLICY cards_update_own ON cards
            FOR UPDATE TO authenticated
            USING ((select auth.uid()) = user_id)
            WITH CHECK ((select auth.uid()) = user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'cards' AND policyname = 'cards_delete_own'
    ) THEN
        CREATE POLICY cards_delete_own ON cards
            FOR DELETE TO authenticated
            USING ((select auth.uid()) = user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'courses' AND policyname = 'courses_select_own'
    ) THEN
        CREATE POLICY courses_select_own ON courses
            FOR SELECT TO authenticated
            USING ((select auth.uid()) = user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'courses' AND policyname = 'courses_insert_own'
    ) THEN
        CREATE POLICY courses_insert_own ON courses
            FOR INSERT TO authenticated
            WITH CHECK ((select auth.uid()) = user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'courses' AND policyname = 'courses_update_own'
    ) THEN
        CREATE POLICY courses_update_own ON courses
            FOR UPDATE TO authenticated
            USING ((select auth.uid()) = user_id)
            WITH CHECK ((select auth.uid()) = user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'courses' AND policyname = 'courses_delete_own'
    ) THEN
        CREATE POLICY courses_delete_own ON courses
            FOR DELETE TO authenticated
            USING ((select auth.uid()) = user_id);
    END IF;
END $$;
