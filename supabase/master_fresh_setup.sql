-- =============================================================================
-- AUTOMATIC ATTENDANCE SYSTEM - MASTER FRESH SETUP SCRIPT
-- =============================================================================
-- Purpose:
--   Complete, all-in-one database initialization script for NEW school branches.
--   When onboarding a new school branch with a new Supabase project:
--   1. Create the project in Supabase.
--   2. Open Supabase Dashboard -> SQL Editor -> New Query.
--   3. Paste this ENTIRE file and click RUN.
--   4. Copy your project URL & Publishable API key into Manager App / Device App.
--   Everything (Tables, Foreign Keys, Cascade Deletion, RLS, Indexes, Stored Procedures)
--   will be set up automatically in under 5 seconds!
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PART 1: Extensions & Base Tables
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Table 1: Buses
CREATE TABLE IF NOT EXISTS public.buses (
    bus_id TEXT PRIMARY KEY,
    bus_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 2: Students
CREATE TABLE IF NOT EXISTS public.students (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    bus_id TEXT NOT NULL REFERENCES public.buses(bus_id),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 3: Attendance Records
CREATE TABLE IF NOT EXISTS public.attendance (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id TEXT NOT NULL REFERENCES public.students(student_id) ON DELETE CASCADE,
    attendance_date DATE NOT NULL,
    attendance_time TIME NOT NULL,
    bus_id TEXT NOT NULL REFERENCES public.buses(bus_id),
    status TEXT NOT NULL DEFAULT 'Present' CHECK (status IN ('Present', 'Absent', 'Late', 'Excused', 'Unassigned')),
    device_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 4: Student Biometrics (512-D ArcFace float32 vectors)
CREATE TABLE IF NOT EXISTS public.student_biometrics (
    student_id TEXT PRIMARY KEY REFERENCES public.students(student_id) ON DELETE CASCADE,
    embedding BYTEA NOT NULL,
    dimension INTEGER NOT NULL DEFAULT 512,
    model_name TEXT NOT NULL DEFAULT 'buffalo_sc',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- PART 2: Constraints & Indexes
-- -----------------------------------------------------------------------------

-- Single daily attendance constraint: One check-in per student per bus per date
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conrelid = 'public.attendance'::regclass 
          AND contype = 'u' 
          AND conname = 'attendance_student_id_attendance_date_bus_id_key'
    ) THEN
        ALTER TABLE public.attendance 
            ADD CONSTRAINT attendance_student_id_attendance_date_bus_id_key 
            UNIQUE (student_id, attendance_date, bus_id);
    END IF;
END $$;

-- Query performance indexes
CREATE INDEX IF NOT EXISTS idx_attendance_date ON public.attendance (attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_bus_date ON public.attendance (bus_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_student_date ON public.attendance (student_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_students_bus_active ON public.students (bus_id, is_active);

-- -----------------------------------------------------------------------------
-- PART 3: Permissions (API Roles)
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.buses TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.students TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.attendance TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.student_biometrics TO anon, authenticated;

-- -----------------------------------------------------------------------------
-- PART 4: Row Level Security (RLS) Policies
-- -----------------------------------------------------------------------------
ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_biometrics ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    -- Buses
    DROP POLICY IF EXISTS "Allow read buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow insert buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow update bus metadata" ON public.buses;
    DROP POLICY IF EXISTS "Allow delete buses" ON public.buses;

    -- Students
    DROP POLICY IF EXISTS "Allow read students" ON public.students;
    DROP POLICY IF EXISTS "Allow insert students" ON public.students;
    DROP POLICY IF EXISTS "Allow update students" ON public.students;
    DROP POLICY IF EXISTS "Allow delete students" ON public.students;

    -- Attendance
    DROP POLICY IF EXISTS "Allow read attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow insert attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow update attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow delete attendance" ON public.attendance;

    -- Biometrics
    DROP POLICY IF EXISTS "Allow read biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow insert biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow update biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow delete biometrics" ON public.student_biometrics;
END $$;

-- Buses Policies
CREATE POLICY "Allow read buses" ON public.buses FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert buses" ON public.buses FOR INSERT TO anon, authenticated WITH CHECK (bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow update bus metadata" ON public.buses FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow delete buses" ON public.buses FOR DELETE TO anon, authenticated USING (true);

-- Students Policies
CREATE POLICY "Allow read students" ON public.students FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert students" ON public.students FOR INSERT TO anon, authenticated 
    WITH CHECK (student_id IS NOT NULL AND length(trim(student_id)) > 0 AND name IS NOT NULL AND length(trim(name)) > 0 AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow update students" ON public.students FOR UPDATE TO anon, authenticated 
    USING (true)
    WITH CHECK (student_id IS NOT NULL AND length(trim(student_id)) > 0 AND name IS NOT NULL AND length(trim(name)) > 0 AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow delete students" ON public.students FOR DELETE TO anon, authenticated USING (true);

-- Attendance Policies
CREATE POLICY "Allow read attendance" ON public.attendance FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert attendance" ON public.attendance FOR INSERT TO anon, authenticated 
    WITH CHECK (event_id IS NOT NULL AND student_id IS NOT NULL AND length(trim(student_id)) > 0 AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow update attendance" ON public.attendance FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow delete attendance" ON public.attendance FOR DELETE TO anon, authenticated USING (true);

-- Biometrics Policies
CREATE POLICY "Allow read biometrics" ON public.student_biometrics FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert biometrics" ON public.student_biometrics FOR INSERT TO anon, authenticated WITH CHECK (student_id IS NOT NULL AND embedding IS NOT NULL);
CREATE POLICY "Allow update biometrics" ON public.student_biometrics FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (student_id IS NOT NULL AND embedding IS NOT NULL);
CREATE POLICY "Allow delete biometrics" ON public.student_biometrics FOR DELETE TO anon, authenticated USING (true);

-- -----------------------------------------------------------------------------
-- PART 5: Stored Procedures (Smart Deletion & Archival)
-- -----------------------------------------------------------------------------

-- Procedure 1: Safe Bus Deletion / Archival
CREATE OR REPLACE FUNCTION public.delete_or_deactivate_bus(target_bus_id TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_student_count INT;
    v_attendance_count INT;
    v_bus_exists BOOLEAN;
BEGIN
    SELECT EXISTS(SELECT 1 FROM public.buses WHERE bus_id = target_bus_id) INTO v_bus_exists;
    IF NOT v_bus_exists THEN
        RETURN jsonb_build_object(
            'success', false,
            'action', 'not_found',
            'message', format('Bus "%s" does not exist in the fleet.', target_bus_id)
        );
    END IF;

    SELECT count(*) INTO v_student_count FROM public.students WHERE bus_id = target_bus_id;
    SELECT count(*) INTO v_attendance_count FROM public.attendance WHERE bus_id = target_bus_id;

    -- If the bus has historical attendance records or assigned students, soft-deactivate
    IF v_attendance_count > 0 OR v_student_count > 0 THEN
        UPDATE public.buses 
        SET is_active = false 
        WHERE bus_id = target_bus_id;

        RETURN jsonb_build_object(
            'success', true,
            'action', 'deactivated',
            'message', format('Bus "%s" has %s attendance records and %s students. Safely archived to preserve historical records.', target_bus_id, v_attendance_count, v_student_count)
        );
    ELSE
        -- No dependencies: clean permanent delete
        DELETE FROM public.buses WHERE bus_id = target_bus_id;
        RETURN jsonb_build_object(
            'success', true,
            'action', 'deleted',
            'message', format('Bus "%s" permanently deleted from the fleet.', target_bus_id)
        );
    END IF;
END;
$$;

GRANT EXECUTE ON FUNCTION public.delete_or_deactivate_bus(TEXT) TO anon, authenticated;

-- Procedure 2: Safe Atomic Student Purge
CREATE OR REPLACE FUNCTION public.delete_student_permanently(target_student_id TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_exists BOOLEAN;
    v_att_count INT := 0;
    v_bio_count INT := 0;
BEGIN
    SELECT EXISTS(SELECT 1 FROM public.students WHERE student_id = target_student_id) INTO v_exists;
    IF NOT v_exists THEN
        RETURN jsonb_build_object(
            'success', false,
            'action', 'not_found',
            'message', format('Student "%s" does not exist in the database.', target_student_id)
        );
    END IF;

    SELECT count(*) INTO v_att_count FROM public.attendance WHERE student_id = target_student_id;
    IF to_regclass('public.student_biometrics') IS NOT NULL THEN
        SELECT count(*) INTO v_bio_count FROM public.student_biometrics WHERE student_id = target_student_id;
        DELETE FROM public.student_biometrics WHERE student_id = target_student_id;
    END IF;

    DELETE FROM public.attendance WHERE student_id = target_student_id;
    DELETE FROM public.students WHERE student_id = target_student_id;

    RETURN jsonb_build_object(
        'success', true,
        'action', 'deleted',
        'message', format('Student "%s" permanently purged (removed %s biometrics and %s attendance records).', target_student_id, v_bio_count, v_att_count)
    );
END;
$$;

GRANT EXECUTE ON FUNCTION public.delete_student_permanently(TEXT) TO anon, authenticated;

-- -----------------------------------------------------------------------------
-- PART 6: Seed Default Fleet Bus
-- -----------------------------------------------------------------------------
INSERT INTO public.buses (bus_id, bus_name, is_active)
VALUES ('BUS01', 'School Route 1', true)
ON CONFLICT (bus_id) DO NOTHING;

-- Verification output
SELECT 'Setup complete! Tables created:' AS status, count(*) AS table_count 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name IN ('buses', 'students', 'attendance', 'student_biometrics');
