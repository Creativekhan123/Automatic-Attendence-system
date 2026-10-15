-- =============================================================================
-- Migration 001: Automatic School Bus Attendance System - Phase B Alignment
-- =============================================================================
-- Description:
--   1. Confirms and preserves existing tables: buses, students, attendance.
--   2. Adds column defaults (gen_random_uuid(), now(), true) safely.
--   3. Creates the separate student_biometrics table for 512-D ArcFace vectors.
--   4. Creates high-performance query indexes for date, bus, and student lookups.
--   5. Applies status integrity constraints and Row Level Security (RLS) policies.
-- =============================================================================

-- 1. Ensure extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Preserve & Enhance existing tables (safe column defaults)
ALTER TABLE IF EXISTS public.buses 
    ALTER COLUMN is_active SET DEFAULT true,
    ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE IF EXISTS public.students 
    ALTER COLUMN is_active SET DEFAULT true,
    ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE IF EXISTS public.attendance 
    ALTER COLUMN event_id SET DEFAULT gen_random_uuid(),
    ALTER COLUMN status SET DEFAULT 'Present',
    ALTER COLUMN created_at SET DEFAULT now();

-- 3. Create student_biometrics table (separate from student metadata)
CREATE TABLE IF NOT EXISTS public.student_biometrics (
    student_id TEXT PRIMARY KEY REFERENCES public.students(student_id) ON DELETE CASCADE,
    embedding BYTEA NOT NULL,
    dimension INTEGER NOT NULL DEFAULT 512,
    model_name TEXT NOT NULL DEFAULT 'buffalo_sc',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.student_biometrics IS 'Encrypted/binary 512-D ArcFace biometric feature vectors for student recognition';
COMMENT ON COLUMN public.student_biometrics.embedding IS 'Raw 2,048-byte float32 numpy vector serialized via ndarray.tobytes()';

-- 4. Create Performance Indexes for Dashboard & Bus queries
CREATE INDEX IF NOT EXISTS idx_attendance_date 
    ON public.attendance (attendance_date DESC);

CREATE INDEX IF NOT EXISTS idx_attendance_bus_date 
    ON public.attendance (bus_id, attendance_date DESC);

CREATE INDEX IF NOT EXISTS idx_attendance_student_date 
    ON public.attendance (student_id, attendance_date DESC);

CREATE INDEX IF NOT EXISTS idx_students_bus_active 
    ON public.students (bus_id, is_active);

-- 5. Status Validation Constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_attendance_status'
    ) THEN
        ALTER TABLE public.attendance
        ADD CONSTRAINT chk_attendance_status 
        CHECK (status IN ('Present', 'Absent', 'Late', 'Excused', 'Unassigned'));
    END IF;
END $$;

-- 6. Updated-At Trigger for Biometrics
CREATE OR REPLACE FUNCTION public.set_biometrics_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_biometrics_updated_at ON public.student_biometrics;
CREATE TRIGGER trg_biometrics_updated_at
BEFORE UPDATE ON public.student_biometrics
FOR EACH ROW
EXECUTE FUNCTION public.set_biometrics_updated_at();

-- 7. Row Level Security (RLS) Configuration
ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_biometrics ENABLE ROW LEVEL SECURITY;

-- Idempotent RLS Policies: Allow client app with anon / service key to query and sync
DO $$
BEGIN
    -- Buses
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app select buses') THEN
        CREATE POLICY "Allow app select buses" ON public.buses FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app insert/update buses') THEN
        CREATE POLICY "Allow app insert/update buses" ON public.buses FOR ALL USING (true) WITH CHECK (true);
    END IF;

    -- Students
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app select students') THEN
        CREATE POLICY "Allow app select students" ON public.students FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app insert/update students') THEN
        CREATE POLICY "Allow app insert/update students" ON public.students FOR ALL USING (true) WITH CHECK (true);
    END IF;

    -- Attendance
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app select attendance') THEN
        CREATE POLICY "Allow app select attendance" ON public.attendance FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app insert attendance') THEN
        CREATE POLICY "Allow app insert attendance" ON public.attendance FOR INSERT WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app update attendance') THEN
        CREATE POLICY "Allow app update attendance" ON public.attendance FOR UPDATE USING (true) WITH CHECK (true);
    END IF;

    -- Student Biometrics
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app select biometrics') THEN
        CREATE POLICY "Allow app select biometrics" ON public.student_biometrics FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow app insert/update biometrics') THEN
        CREATE POLICY "Allow app insert/update biometrics" ON public.student_biometrics FOR ALL USING (true) WITH CHECK (true);
    END IF;
END $$;
