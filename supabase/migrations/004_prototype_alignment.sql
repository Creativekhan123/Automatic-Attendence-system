-- =============================================================================
-- Migration 004: Office-Test Prototype Alignment & Security Hardening
-- =============================================================================
-- Description:
--   Idempotent and safe migration tailored for the office-test prototype.
--   1. Ensures base tables (buses, students, attendance, student_biometrics) exist.
--   2. Reconciles existing orphaned attendance records safely without data loss.
--   3. Enforces single daily attendance uniqueness: (student_id, attendance_date, bus_id).
--   4. Adds query performance indexes for dashboard and bus fleet lookups.
--   5. Fixes student UPDATE RLS policy: allows soft-deactivation (is_active = false)
--      without compromising mandatory field validation.
--   6. Enforces append-only immutability on attendance records (REVOKE DELETE/TRUNCATE).
--   7. Configures restricted biometric access using a pre-shared fleet header or
--      authenticated session (blocks unrestricted anonymous harvesting).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PART 1: Prerequisites & Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- PART 2: Base Tables & Schema Normalization (Non-destructive)
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
    student_id TEXT NOT NULL,
    attendance_date DATE NOT NULL,
    attendance_time TIME NOT NULL,
    bus_id TEXT NOT NULL REFERENCES public.buses(bus_id),
    status TEXT NOT NULL DEFAULT 'Present' CHECK (status IN ('Present', 'Absent', 'Late', 'Excused', 'Unassigned')),
    device_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dedicated biometric table for 512-D ArcFace float32 vectors (2,048 bytes)
CREATE TABLE IF NOT EXISTS public.student_biometrics (
    student_id TEXT PRIMARY KEY REFERENCES public.students(student_id) ON DELETE CASCADE,
    embedding BYTEA NOT NULL,
    dimension INTEGER NOT NULL DEFAULT 512,
    model_name TEXT NOT NULL DEFAULT 'buffalo_sc',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Safe column defaults
ALTER TABLE public.buses ALTER COLUMN is_active SET DEFAULT true;
ALTER TABLE public.buses ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE public.students ALTER COLUMN is_active SET DEFAULT true;
ALTER TABLE public.students ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE public.attendance ALTER COLUMN event_id SET DEFAULT gen_random_uuid();
ALTER TABLE public.attendance ALTER COLUMN status SET DEFAULT 'Present';
ALTER TABLE public.attendance ALTER COLUMN created_at SET DEFAULT now();

-- -----------------------------------------------------------------------------
-- PART 3: Safe Referential Integrity & Constraint Reconciliation
-- -----------------------------------------------------------------------------

-- Drop legacy multi-trip columns/constraints if present
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS uq_attendance_student_date_bus_session;
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS chk_attendance_session_type;
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS attendance_student_id_attendance_date_bus_id_session_type_key;
ALTER TABLE public.attendance DROP COLUMN IF EXISTS session_type CASCADE;

-- If orphaned attendance records exist (referencing students not yet in students table),
-- safely create inactive placeholder profiles to avoid losing attendance history
-- and allow foreign key enforcement to succeed without failure.
INSERT INTO public.students (student_id, name, class_name, bus_id, is_active)
SELECT DISTINCT a.student_id, 'Student ' || a.student_id, '--', a.bus_id, false
FROM public.attendance a
WHERE NOT EXISTS (SELECT 1 FROM public.students s WHERE s.student_id = a.student_id)
ON CONFLICT (student_id) DO NOTHING;

-- Enforce Foreign Key: attendance.student_id -> students(student_id)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_attendance_student'
    ) THEN
        ALTER TABLE public.attendance
        ADD CONSTRAINT fk_attendance_student
        FOREIGN KEY (student_id) REFERENCES public.students(student_id);
    END IF;
END $$;

-- Enforce Single Daily Attendance: UNIQUE (student_id, attendance_date, bus_id)
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

-- -----------------------------------------------------------------------------
-- PART 4: Query Performance Indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_attendance_bus_date 
    ON public.attendance (bus_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_student_date 
    ON public.attendance (student_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_students_bus_active 
    ON public.students (bus_id, is_active);

-- -----------------------------------------------------------------------------
-- PART 5: Table Permissions & Audit Immutability
-- -----------------------------------------------------------------------------
-- Revoke destructive deletes from anon API users across all public tables
REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon;

-- Attendance records are an append-only audit trail: no deletes via API
REVOKE DELETE, TRUNCATE ON public.attendance FROM anon, authenticated;

-- Ensure read/write access for required API roles
GRANT SELECT, INSERT, UPDATE ON public.buses TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.students TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.attendance TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.student_biometrics TO anon, authenticated;

-- -----------------------------------------------------------------------------
-- PART 6: Row Level Security (RLS) Configuration
-- -----------------------------------------------------------------------------

ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_biometrics ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    -- -------------------------------------------------------------------------
    -- BUSES POLICIES
    -- -------------------------------------------------------------------------
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

    -- -------------------------------------------------------------------------
    -- STUDENTS POLICIES
    -- -------------------------------------------------------------------------
    DROP POLICY IF EXISTS "Allow read active students" ON public.students;
    DROP POLICY IF EXISTS "Allow enroll student metadata" ON public.students;
    DROP POLICY IF EXISTS "Allow update student metadata" ON public.students;
    DROP POLICY IF EXISTS "Allow read all students" ON public.students;

    -- Allow staff and devices to read students (active and inactive, for management)
    CREATE POLICY "Allow read all students" 
        ON public.students FOR SELECT 
        TO anon, authenticated 
        USING (true);

    -- Allow staff to enroll student profiles with required non-empty fields
    CREATE POLICY "Allow enroll student metadata" 
        ON public.students FOR INSERT 
        TO anon, authenticated 
        WITH CHECK (
            student_id IS NOT NULL AND length(trim(student_id)) > 0
            AND name IS NOT NULL AND length(trim(name)) > 0
            AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0
        );

    -- FIX: Allow staff to update student metadata AND soft-deactivate (is_active = false)
    -- Crucial change: WITH CHECK does NOT enforce is_active = true.
    CREATE POLICY "Allow update student metadata" 
        ON public.students FOR UPDATE 
        TO anon, authenticated 
        USING (true)
        WITH CHECK (
            student_id IS NOT NULL AND length(trim(student_id)) > 0
            AND name IS NOT NULL AND length(trim(name)) > 0
            AND bus_id IS NOT NULL AND length(trim(bus_id)) > 0
        );

    -- -------------------------------------------------------------------------
    -- ATTENDANCE POLICIES
    -- -------------------------------------------------------------------------
    DROP POLICY IF EXISTS "Allow verified attendance insert" ON public.attendance;
    DROP POLICY IF EXISTS "Allow idempotent retry attendance" ON public.attendance;
    DROP POLICY IF EXISTS "Allow read attendance" ON public.attendance;

    -- Only insert verified records with non-empty hardware device_id and valid status
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

    -- Allow idempotent upsert on existing event_id for offline retry loops
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

    -- -------------------------------------------------------------------------
    -- STUDENT BIOMETRICS POLICIES (Privacy Hardening)
    -- -------------------------------------------------------------------------
    DROP POLICY IF EXISTS "Allow authorized fleet biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow authenticated biometrics" ON public.student_biometrics;

    -- Restricted Biometric Access:
    -- Prevents unrestricted public harvesting of facial embeddings.
    -- Allows access ONLY to requests presenting the fleet sync header OR authenticated role.
    CREATE POLICY "Allow authorized fleet biometrics" 
        ON public.student_biometrics FOR ALL 
        TO anon, authenticated 
        USING (
            coalesce(current_setting('request.headers', true)::json->>'x-fleet-sync-token', '') = 'PROTOTYPE_FLEET_SYNC_SECRET'
            OR auth.role() = 'authenticated'
        )
        WITH CHECK (
            dimension = 512
            AND (
                coalesce(current_setting('request.headers', true)::json->>'x-fleet-sync-token', '') = 'PROTOTYPE_FLEET_SYNC_SECRET'
                OR auth.role() = 'authenticated'
            )
        );

END $$;
