-- =============================================================================
-- Rollback for Migration 002: School Bus Single Daily Attendance & Security Hardening
-- =============================================================================
-- Safely and idempotently reverts Migration 002 policies and restores baseline
-- configuration without deleting any existing data or failing if tables do not exist.
-- =============================================================================

DO $$
BEGIN
    -- 1. Buses Table
    IF to_regclass('public.buses') IS NOT NULL THEN
        DROP POLICY IF EXISTS "Allow read active buses" ON public.buses;
        DROP POLICY IF EXISTS "Allow insert buses" ON public.buses;
        DROP POLICY IF EXISTS "Allow update active bus metadata" ON public.buses;

        GRANT SELECT, INSERT, UPDATE, DELETE ON public.buses TO anon;

        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'buses' AND policyname = 'Allow app select buses') THEN
            CREATE POLICY "Allow app select buses" ON public.buses FOR SELECT USING (true);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'buses' AND policyname = 'Allow app insert/update buses') THEN
            CREATE POLICY "Allow app insert/update buses" ON public.buses FOR ALL USING (true) WITH CHECK (true);
        END IF;
    END IF;

    -- 2. Students Table
    IF to_regclass('public.students') IS NOT NULL THEN
        DROP POLICY IF EXISTS "Allow authenticated read active students" ON public.students;
        DROP POLICY IF EXISTS "Allow enroll student metadata" ON public.students;
        DROP POLICY IF EXISTS "Allow update student metadata" ON public.students;

        GRANT SELECT, INSERT, UPDATE, DELETE ON public.students TO anon;

        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'students' AND policyname = 'Allow app select students') THEN
            CREATE POLICY "Allow app select students" ON public.students FOR SELECT USING (true);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'students' AND policyname = 'Allow app insert/update students') THEN
            CREATE POLICY "Allow app insert/update students" ON public.students FOR ALL USING (true) WITH CHECK (true);
        END IF;
    END IF;

    -- 3. Attendance Table
    IF to_regclass('public.attendance') IS NOT NULL THEN
        DROP POLICY IF EXISTS "Allow verified attendance insert" ON public.attendance;
        DROP POLICY IF EXISTS "Allow idempotent retry attendance" ON public.attendance;
        DROP POLICY IF EXISTS "Allow read attendance" ON public.attendance;

        GRANT SELECT, INSERT, UPDATE ON public.attendance TO anon;

        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'attendance' AND policyname = 'Allow app select attendance') THEN
            CREATE POLICY "Allow app select attendance" ON public.attendance FOR SELECT USING (true);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'attendance' AND policyname = 'Allow app insert attendance') THEN
            CREATE POLICY "Allow app insert attendance" ON public.attendance FOR INSERT WITH CHECK (true);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'attendance' AND policyname = 'Allow app update attendance') THEN
            CREATE POLICY "Allow app update attendance" ON public.attendance FOR UPDATE USING (true) WITH CHECK (true);
        END IF;
    END IF;

    -- 4. Student Biometrics Table
    IF to_regclass('public.student_biometrics') IS NOT NULL THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.student_biometrics TO anon;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'student_biometrics' AND policyname = 'Allow app select biometrics') THEN
            CREATE POLICY "Allow app select biometrics" ON public.student_biometrics FOR SELECT USING (true);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'student_biometrics' AND policyname = 'Allow app insert/update biometrics') THEN
            CREATE POLICY "Allow app insert/update biometrics" ON public.student_biometrics FOR ALL USING (true) WITH CHECK (true);
        END IF;
    END IF;
END $$;
