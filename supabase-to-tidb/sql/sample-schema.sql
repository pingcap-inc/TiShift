-- TiShift Supabase → TiDB sample schema
--
-- This schema is the demo fixture for all TiShift phases (scan, convert, load, check).
-- It intentionally exercises every blocker and warning the tool must detect:
--
--   BLOCKER-1/2  three RLS patterns + one deny-all-RLS table
--   BLOCKER-3    user function calling auth.uid()
--   BLOCKER-7    trigger calling net.http_post() (commented; uncomment only on live Supabase)
--   BLOCKER-9    array column (TEXT[])
--   BLOCKER-10   JSONB column used with @> operator
--   BLOCKER-13   PL/pgSQL function
--   BLOCKER-14   trigger
--   WARNING-7    Postgres-style CREATE TYPE ... AS ENUM
--   WARNING-8    sequence
--   WARNING-9    RETURNING clause in a function
--   WARNING-10   uuid column with gen_random_uuid() default
--   WARNING-11   SERIAL column
--   WARNING-19   extensions.gen_random_uuid() qualified call in view
--   WARNING-20   SECURITY DEFINER function
--
-- Also exercises btree and GIN indexes, a TEXT column with large content,
-- a GRANT to `authenticated` (PostgREST heuristic), and a TiDB-FK-enforceable
-- reference chain (users → posts → comments).

-- =========================================================================
-- Named ENUM type (WARNING-7)
-- =========================================================================
CREATE TYPE post_status AS ENUM ('draft', 'published', 'archived');

-- =========================================================================
-- Sequence (WARNING-8)
-- =========================================================================
CREATE SEQUENCE invoice_number_seq START 10000 INCREMENT 1;

-- =========================================================================
-- Users — multi-tenant SaaS shape. auth.users lives in the auth schema
-- (Supabase-internal, NOT migrated). We create a mirror in public that
-- the application joins against auth.uid().
-- =========================================================================
CREATE TABLE public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),     -- WARNING-10
    tenant_id UUID NOT NULL,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    tags TEXT[],                                        -- BLOCKER-9
    profile JSONB DEFAULT '{}'::jsonb,                  -- BLOCKER-10 (operator usage below)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_users_tenant ON public.users(tenant_id);
CREATE INDEX idx_users_profile_gin ON public.users USING GIN (profile);  -- GIN index
CREATE INDEX idx_users_email ON public.users(email);

-- =========================================================================
-- Posts — child of users, references post_status enum
-- =========================================================================
CREATE TABLE public.posts (
    id SERIAL PRIMARY KEY,                              -- WARNING-11
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    title TEXT NOT NULL,
    body TEXT,                                          -- large TEXT column
    status post_status DEFAULT 'draft',
    meta JSONB DEFAULT '{}'::jsonb,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_posts_user ON public.posts(user_id);
CREATE INDEX idx_posts_tenant_status ON public.posts(tenant_id, status);

-- =========================================================================
-- Comments — two-level FK chain
-- =========================================================================
CREATE TABLE public.comments (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_comments_post ON public.comments(post_id);

-- =========================================================================
-- Invoices — exercises sequence default
-- =========================================================================
CREATE TABLE public.invoices (
    id INTEGER PRIMARY KEY DEFAULT nextval('invoice_number_seq'),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES public.users(id),
    amount_cents BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- =========================================================================
-- RLS — three policy patterns + one deny-all table
-- =========================================================================

-- Pattern 1: user-owned rows (BLOCKER-1)
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_self_select ON public.users
    FOR SELECT
    TO authenticated
    USING ((select auth.uid()) = id);

CREATE POLICY users_self_update ON public.users
    FOR UPDATE
    TO authenticated
    USING ((select auth.uid()) = id)
    WITH CHECK ((select auth.uid()) = id);

-- Pattern 2: role-gated table-wide read (BLOCKER-1)
ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;

CREATE POLICY posts_public_read ON public.posts
    FOR SELECT
    TO anon, authenticated
    USING (status = 'published');

CREATE POLICY posts_author_write ON public.posts
    FOR ALL
    TO authenticated
    USING ((select auth.uid()) = user_id)
    WITH CHECK ((select auth.uid()) = user_id);

-- Pattern 3: tenant isolation via JWT claim (BLOCKER-1 — complex expression)
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;

CREATE POLICY invoices_tenant_isolation ON public.invoices
    FOR SELECT
    TO authenticated
    USING (
        tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
        AND (select auth.uid()) IS NOT NULL
    );

-- Deny-all pattern: RLS enabled, no policies (BLOCKER-2)
ALTER TABLE public.comments ENABLE ROW LEVEL SECURITY;
-- Intentionally no CREATE POLICY — effectively denies all access.
-- Real Supabase apps sometimes ship this by accident and discover it weeks later.

-- =========================================================================
-- PL/pgSQL function referencing auth.uid() (BLOCKER-3, BLOCKER-13, WARNING-9)
-- =========================================================================
CREATE OR REPLACE FUNCTION public.create_user_post(
    p_title TEXT,
    p_body TEXT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_user_id UUID;
    v_post_id INTEGER;
BEGIN
    v_user_id := auth.uid();                            -- BLOCKER-3

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Not authenticated';
    END IF;

    INSERT INTO public.posts (user_id, tenant_id, title, body, status)
    SELECT v_user_id, tenant_id, p_title, p_body, 'draft'
    FROM public.users
    WHERE id = v_user_id
    RETURNING id INTO v_post_id;                        -- WARNING-9

    RETURN v_post_id;
END;
$$;

-- =========================================================================
-- SECURITY DEFINER function (WARNING-20) — exercises JSONB @> operator
-- (BLOCKER-10) and the extensions.* qualifier pattern (WARNING-19)
-- =========================================================================
CREATE OR REPLACE FUNCTION public.find_users_with_tag(p_tag TEXT)
RETURNS TABLE (user_id UUID, email TEXT, match_meta JSONB)
LANGUAGE plpgsql
SECURITY DEFINER                                        -- WARNING-20
AS $$
BEGIN
    RETURN QUERY
    SELECT u.id, u.email, u.profile
    FROM public.users u
    WHERE u.profile @> jsonb_build_object('tags', jsonb_build_array(p_tag))  -- BLOCKER-10
       OR p_tag = ANY(u.tags);                          -- BLOCKER-9 op usage
END;
$$;

-- =========================================================================
-- Trigger (BLOCKER-14)
-- =========================================================================
CREATE OR REPLACE FUNCTION public.update_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER users_touch_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW
    EXECUTE FUNCTION public.update_timestamp();

-- Optional: pg_net webhook trigger (BLOCKER-7). Commented because creating
-- this on a live Supabase project will fire real HTTP requests from the DB.
-- Uncomment to exercise BLOCKER-7 detection in integration tests against a
-- sandbox project.
--
-- CREATE OR REPLACE FUNCTION public.notify_post_webhook()
-- RETURNS TRIGGER
-- LANGUAGE plpgsql
-- AS $$
-- BEGIN
--     PERFORM net.http_post(                           -- BLOCKER-7
--         url := 'https://example.com/webhooks/posts',
--         body := jsonb_build_object('id', NEW.id, 'title', NEW.title)::text
--     );
--     RETURN NEW;
-- END;
-- $$;
--
-- CREATE TRIGGER posts_webhook
--     AFTER INSERT ON public.posts
--     FOR EACH ROW
--     EXECUTE FUNCTION public.notify_post_webhook();

-- =========================================================================
-- View using extensions.* qualifier (WARNING-19) and gen_random_uuid default
-- =========================================================================
CREATE OR REPLACE VIEW public.active_user_summary AS
SELECT
    u.id,
    u.email,
    u.display_name,
    extensions.gen_random_uuid() AS request_id,         -- WARNING-19
    count(p.id) AS post_count,
    count(p.id) FILTER (WHERE p.status = 'published') AS published_count
FROM public.users u
LEFT JOIN public.posts p ON p.user_id = u.id
GROUP BY u.id, u.email, u.display_name;

-- =========================================================================
-- GRANTs to anon / authenticated (drives PostgREST-likely-in-use heuristic)
-- =========================================================================
GRANT SELECT ON public.active_user_summary TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.users TO authenticated;
GRANT SELECT ON public.users TO anon;
GRANT SELECT, INSERT ON public.posts TO authenticated;
GRANT SELECT ON public.posts TO anon;
GRANT SELECT ON public.invoices TO authenticated;
GRANT USAGE ON SEQUENCE invoice_number_seq TO authenticated;
GRANT EXECUTE ON FUNCTION public.create_user_post TO authenticated;
GRANT EXECUTE ON FUNCTION public.find_users_with_tag TO authenticated;
