-- Run this in the Supabase Dashboard SQL Editor.
-- It does not read, update, or delete user rows. It only enables RLS and
-- replaces the RLS policies owned by this app.

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.courses ENABLE ROW LEVEL SECURITY;

-- profiles stores provider API keys. Keep it inaccessible through the
-- Supabase Data API; the FastAPI backend reads/writes it through DATABASE_URL.
DROP POLICY IF EXISTS profiles_select_own ON public.profiles;
DROP POLICY IF EXISTS profiles_insert_own ON public.profiles;
DROP POLICY IF EXISTS profiles_update_own ON public.profiles;
DROP POLICY IF EXISTS profiles_delete_own ON public.profiles;

DROP POLICY IF EXISTS cards_select_own ON public.cards;
DROP POLICY IF EXISTS cards_insert_own ON public.cards;
DROP POLICY IF EXISTS cards_update_own ON public.cards;
DROP POLICY IF EXISTS cards_delete_own ON public.cards;

CREATE POLICY cards_select_own ON public.cards
    FOR SELECT TO authenticated
    USING ((select auth.uid()) = user_id);

CREATE POLICY cards_insert_own ON public.cards
    FOR INSERT TO authenticated
    WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY cards_update_own ON public.cards
    FOR UPDATE TO authenticated
    USING ((select auth.uid()) = user_id)
    WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY cards_delete_own ON public.cards
    FOR DELETE TO authenticated
    USING ((select auth.uid()) = user_id);

DROP POLICY IF EXISTS courses_select_own ON public.courses;
DROP POLICY IF EXISTS courses_insert_own ON public.courses;
DROP POLICY IF EXISTS courses_update_own ON public.courses;
DROP POLICY IF EXISTS courses_delete_own ON public.courses;

CREATE POLICY courses_select_own ON public.courses
    FOR SELECT TO authenticated
    USING ((select auth.uid()) = user_id);

CREATE POLICY courses_insert_own ON public.courses
    FOR INSERT TO authenticated
    WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY courses_update_own ON public.courses
    FOR UPDATE TO authenticated
    USING ((select auth.uid()) = user_id)
    WITH CHECK ((select auth.uid()) = user_id);

CREATE POLICY courses_delete_own ON public.courses
    FOR DELETE TO authenticated
    USING ((select auth.uid()) = user_id);

-- Verification: profiles should show RLS enabled with no app-created policies.
-- cards/courses should show the eight owner-scoped policies above. If this
-- query shows any other permissive policy, inspect it before considering the
-- public anon key safe.
SELECT
    c.relname AS table_name,
    c.relrowsecurity AS rls_enabled,
    p.policyname,
    p.cmd,
    p.roles,
    p.qual,
    p.with_check
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_policies p
    ON p.schemaname = n.nspname
    AND p.tablename = c.relname
WHERE n.nspname = 'public'
  AND c.relname IN ('profiles', 'cards', 'courses')
ORDER BY c.relname, p.policyname;
