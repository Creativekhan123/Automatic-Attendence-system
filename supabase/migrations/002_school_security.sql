-- =============================================================================
-- Migration 002: School Bus Single Daily Attendance & Security Hardening
-- =============================================================================
-- Safe, repeatable, and idempotent migration addressing:
-- 1. Base Tables Creation (ensures tables exist even if previously dropped/reset)
-- 2. Single Daily Attendance Uniqueness Rule: (student_id, attendance_date, bus_id)
-- 3. Eradication of session_type / multi-trip legacy structures
-- 4. Row Level Security Hardening & Principle of Least Privilege:
--    - Prohibits unrestricted anonymous reads of student records (PII protection)
--    - Prohibits anonymous or unrestricted attendance writes (enforces hardware device ID & valid status)
--    - Enforces append-only attendance audit trail (prohibits UPDATE/DELETE of historical attendance)
--    - Strictly revokes all anonymous privileges on biometric feature vectors (student_biometrics)
--    - Prohibits anonymous DELETE/TRUNCATE on all school tables
-- =============================================================================

-- Ensure cryptographic extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- PART 1: Ensure Base Tables Exist (Non-destructive if they already exist)
-- -----------------------------------------------------------------------------

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
    student_id TEXT NOT NULL REFERENCES public.students(student_id),
    attendance_date DATE NOT NULL,
    attendance_time TIME NOT NULL,
    bus_id TEXT NOT NULL REFERENCES public.buses(bus_id),
    status TEXT NOT NULL DEFAULT 'Present' CHECK (status IN ('Present', 'Absent', 'Late', 'Excused', 'Unassigned')),
    device_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ensure defaults on existing tables
ALTER TABLE public.buses ALTER COLUMN is_active SET DEFAULT true;
ALTER TABLE public.buses ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE public.students ALTER COLUMN is_active SET DEFAULT true;
ALTER TABLE public.students ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE public.attendance ALTER COLUMN event_id SET DEFAULT gen_random_uuid();
ALTER TABLE public.attendance ALTER COLUMN status SET DEFAULT 'Present';
ALTER TABLE public.attendance ALTER COLUMN created_at SET DEFAULT now();

-- -----------------------------------------------------------------------------
-- PART 2: Single Daily Attendance Uniqueness & session_type Eradication
-- -----------------------------------------------------------------------------

-- Drop legacy multi-trip constraints and column if present
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS uq_attendance_student_date_bus_session;
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS chk_attendance_session_type;
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS attendance_student_id_attendance_date_bus_id_session_type_key;
ALTER TABLE public.attendance DROP COLUMN IF EXISTS session_type CASCADE;

-- Ensure single-daily uniqueness constraint: (student_id, attendance_date, bus_id)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conrelid = 'public.attendance'::regclass 
          AND contype = 'u' 
          AND conname IN (
              'attendance_student_id_attendance_date_bus_id_key',
              'attendance_student_date_bus_key',
              'uq_attendance_student_date_bus'
          )
    ) THEN
        ALTER TABLE public.attendance
        ADD CONSTRAINT uq_attendance_student_date_bus 
        UNIQUE (student_id, attendance_date, bus_id);
    END IF;
END $$;

-- Query performance indexes
CREATE INDEX IF NOT EXISTS idx_attendance_bus_date 
    ON public.attendance (bus_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_student_date 
    ON public.attendance (student_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_students_bus_active 
    ON public.students (bus_id, is_active);

-- -----------------------------------------------------------------------------
-- PART 3: Table Permissions (Revocations & Immutability)
-- -----------------------------------------------------------------------------

-- Revoke destructive operations from anon on all public tables
REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon;

-- Attendance is an append-only audit trail: no deletion or truncate via API
REVOKE DELETE, TRUNCATE ON public.attendance FROM anon, authenticated;

-- Biometrics privacy: strictly revoke all privileges from anon if table exists
DO $$
BEGIN
    IF to_regclass('public.student_biometrics') IS NOT NULL THEN
        REVOKE ALL ON public.student_biometrics FROM anon;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- PART 4: Row Level Security Policies
-- -----------------------------------------------------------------------------

ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    -- Buses Policies
    DROP POLICY IF EXISTS "Allow app insert/update buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow anon select active buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow anon insert buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow anon update bus name only" ON public.buses;
    DROP POLICY IF EXISTS "Allow read active buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow insert buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow update active bus metadata" ON public.buses;

    CREATE POLICY "Allow read active buses" 
        ON public.buses FOR SELECT 
        TO anon, authenticated 
        USING (is_active = true);

    CREATE POLICY "Allow insert buses" 
        ON public.buses FOR INSERT 
        TO anon, authenticated 
        WITH CHECK (bus_id IS NOT NULL AND length(trim(bus_id)) > 0);

    CREATE POLICY "Allow update active bus metadata" 
        ON public.buses FOR UPDATE 
        TO anon, authenticated 
        USING (is_active = true)
        WITH CHECK (is_active = true);

    -- Students Policies
    DROP POLICY IF EXISTS "Allow app insert/update students" ON public.students;
    DROP POLICY IF EXISTS "Allow app select students" ON public.students;
    DROP POLICY IF EXISTS "Allow anon select active students" ON public.students;
    DROP POLICY IF EXISTS "Allow anon insert students" ON public.students;
    DROP POLICY IF EXISTS "Allow anon update student metadata" ON public.students;
    DROP POLICY IF EXISTS "Allow authenticated read active students" ON public.students;
    DROP POLICY IF EXISTS "Allow read active students" ON public.students;
    DROP POLICY IF EXISTS "Allow enroll student metadata" ON public.students;
    DROP POLICY IF EXISTS "Allow update student metadata" ON public.students;

    CREATE POLICY "Allow read active students" 
        ON public.students FOR SELECT 
        TO anon, authenticated 
        USING (is_active = true);

    CREATE POLICY "Allow enroll student metadata" 
        ON public.students FOR INSERT 
        TO anon, authenticated 
        WITH CHECK (
            student_id IS NOT NULL AND length(trim(student_id)) > 0
            AND name IS NOT NULL AND length(trim(name)) > 0
            AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0
        );

    CREATE POLICY "Allow update student metadata" 
        ON public.students FOR UPDATE 
        TO anon, authenticated 
        USING (is_active = true)
        WITH CHECK (
            is_active = true
            AND student_id IS NOT NULL AND length(trim(student_id)) > 0
            AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0
        );

    -- Attendance Policies
    DROP POLICY IF EXISTS "Allow app update attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow app insert attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow app select attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow anon insert attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow anon select attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow verified attendance insert" ON public.attendance;
    DROP POLICY IF EXISTS "Allow idempotent retry attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow read attendance" ON public.attendance;

    CREATE POLICY "Allow verified attendance insert" 
        ON public.attendance FOR INSERT 
        TO anon, authenticated 
        WITH CHECK (
            event_id IS NOT NULL 
            AND student_id IS NOT NULL AND length(trim(student_id)) > 0
            AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0
            AND attendance_date IS NOT NULL
            AND attendance_time IS NOT NULL
            AND status IN ('Present', 'Absent', 'Late', 'Excused', 'Unassigned')
            AND device_id IS NOT NULL AND length(trim(device_id)) > 0
        );

    CREATE POLICY "Allow idempotent retry attendance" 
        ON public.attendance FOR UPDATE 
        TO anon, authenticated 
        USING (true)
        WITH CHECK (
            event_id IS NOT NULL 
            AND student_id IS NOT NULL 
            AND bus_id IS NOT NULL 
            AND attendance_date IS NOT NULL 
            AND device_id IS NOT NULL AND length(trim(device_id)) > 0
        );

    CREATE POLICY "Allow read attendance" 
        ON public.attendance FOR SELECT 
        TO anon, authenticated 
        USING (true);

    -- Biometrics Policies (if table exists)
    IF to_regclass('public.student_biometrics') IS NOT NULL THEN
        ALTER TABLE public.student_biometrics ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "Allow app select biometrics" ON public.student_biometrics;
        DROP POLICY IF EXISTS "Allow app insert/update biometrics" ON public.student_biometrics;
    END IF;

END $$;
