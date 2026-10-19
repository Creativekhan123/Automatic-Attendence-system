"""Embedded Master Supabase Database Setup Script for Fleet Attendance System.

Embedded directly into the application executable so that administrators can
initialize a brand-new Supabase project for a new school branch with 1-click
copy-to-clipboard, without needing any external files or folders.
"""

MASTER_SUPABASE_SETUP_SQL = """-- =============================================================================
-- AUTOMATIC ATTENDANCE SYSTEM - MASTER FRESH SETUP SCRIPT
-- =============================================================================
-- All-in-one setup for NEW school branch projects.
-- Paste in Supabase SQL Editor and click RUN.
-- =============================================================================

-- 1. Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Tables
CREATE TABLE IF NOT EXISTS public.buses (
    bus_id TEXT PRIMARY KEY,
    bus_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.students (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    bus_id TEXT NOT NULL REFERENCES public.buses(bus_id),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

CREATE TABLE IF NOT EXISTS public.student_biometrics (
    student_id TEXT PRIMARY KEY REFERENCES public.students(student_id) ON DELETE CASCADE,
    embedding BYTEA NOT NULL,
    dimension INTEGER NOT NULL DEFAULT 512,
    model_name TEXT NOT NULL DEFAULT 'buffalo_sc',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Constraints & Indexes
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

CREATE INDEX IF NOT EXISTS idx_attendance_date ON public.attendance (attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_bus_date ON public.attendance (bus_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_student_date ON public.attendance (student_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_students_bus_active ON public.students (bus_id, is_active);

-- 4. Permissions (Grant All to App Roles)
GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.buses TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.students TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.attendance TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.student_biometrics TO anon, authenticated;

-- 5. Row Level Security (RLS) Policies
ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_biometrics ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    DROP POLICY IF EXISTS "Allow read buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow insert buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow update bus metadata" ON public.buses;
    DROP POLICY IF EXISTS "Allow delete buses" ON public.buses;

    DROP POLICY IF EXISTS "Allow read students" ON public.students;
    DROP POLICY IF EXISTS "Allow insert students" ON public.students;
    DROP POLICY IF EXISTS "Allow update students" ON public.students;
    DROP POLICY IF EXISTS "Allow delete students" ON public.students;

    DROP POLICY IF EXISTS "Allow read attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow insert attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow update attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow delete attendance" ON public.attendance;

    DROP POLICY IF EXISTS "Allow read biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow insert biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow update biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow delete biometrics" ON public.student_biometrics;
END $$;

-- Buses
CREATE POLICY "Allow read buses" ON public.buses FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert buses" ON public.buses FOR INSERT TO anon, authenticated WITH CHECK (bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow update bus metadata" ON public.buses FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow delete buses" ON public.buses FOR DELETE TO anon, authenticated USING (true);

-- Students
CREATE POLICY "Allow read students" ON public.students FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert students" ON public.students FOR INSERT TO anon, authenticated 
    WITH CHECK (student_id IS NOT NULL AND length(trim(student_id)) > 0 AND name IS NOT NULL AND length(trim(name)) > 0 AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow update students" ON public.students FOR UPDATE TO anon, authenticated 
    USING (true)
    WITH CHECK (student_id IS NOT NULL AND length(trim(student_id)) > 0 AND name IS NOT NULL AND length(trim(name)) > 0 AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow delete students" ON public.students FOR DELETE TO anon, authenticated USING (true);

-- Attendance
CREATE POLICY "Allow read attendance" ON public.attendance FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert attendance" ON public.attendance FOR INSERT TO anon, authenticated 
    WITH CHECK (event_id IS NOT NULL AND student_id IS NOT NULL AND length(trim(student_id)) > 0 AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0);
CREATE POLICY "Allow update attendance" ON public.attendance FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow delete attendance" ON public.attendance FOR DELETE TO anon, authenticated USING (true);

-- Biometrics
CREATE POLICY "Allow read biometrics" ON public.student_biometrics FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow insert biometrics" ON public.student_biometrics FOR INSERT TO anon, authenticated WITH CHECK (student_id IS NOT NULL AND embedding IS NOT NULL);
CREATE POLICY "Allow update biometrics" ON public.student_biometrics FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (student_id IS NOT NULL AND embedding IS NOT NULL);
CREATE POLICY "Allow delete biometrics" ON public.student_biometrics FOR DELETE TO anon, authenticated USING (true);

-- 6. Stored Procedures (Smart Purge & Archival)
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
        RETURN jsonb_build_object('success', false, 'action', 'not_found', 'message', format('Bus "%s" does not exist.', target_bus_id));
    END IF;

    SELECT count(*) INTO v_student_count FROM public.students WHERE bus_id = target_bus_id;
    SELECT count(*) INTO v_attendance_count FROM public.attendance WHERE bus_id = target_bus_id;

    IF v_attendance_count > 0 OR v_student_count > 0 THEN
        UPDATE public.buses SET is_active = false WHERE bus_id = target_bus_id;
        RETURN jsonb_build_object('success', true, 'action', 'deactivated', 'message', format('Bus "%s" archived safely.', target_bus_id));
    ELSE
        DELETE FROM public.buses WHERE bus_id = target_bus_id;
        RETURN jsonb_build_object('success', true, 'action', 'deleted', 'message', format('Bus "%s" permanently deleted.', target_bus_id));
    END IF;
END;
$$;
GRANT EXECUTE ON FUNCTION public.delete_or_deactivate_bus(TEXT) TO anon, authenticated;

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
        RETURN jsonb_build_object('success', false, 'action', 'not_found', 'message', format('Student "%s" not found.', target_student_id));
    END IF;

    SELECT count(*) INTO v_att_count FROM public.attendance WHERE student_id = target_student_id;
    IF to_regclass('public.student_biometrics') IS NOT NULL THEN
        SELECT count(*) INTO v_bio_count FROM public.student_biometrics WHERE student_id = target_student_id;
        DELETE FROM public.student_biometrics WHERE student_id = target_student_id;
    END IF;

    DELETE FROM public.attendance WHERE student_id = target_student_id;
    DELETE FROM public.students WHERE student_id = target_student_id;

    RETURN jsonb_build_object('success', true, 'action', 'deleted', 'message', format('Student "%s" permanently purged.', target_student_id));
END;
$$;
GRANT EXECUTE ON FUNCTION public.delete_student_permanently(TEXT) TO anon, authenticated;

-- 7. Seed Default Bus
INSERT INTO public.buses (bus_id, bus_name, is_active)
VALUES ('BUS01', 'School Route 1', true)
ON CONFLICT (bus_id) DO NOTHING;
"""
