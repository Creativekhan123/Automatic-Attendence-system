-- =============================================================================
-- AUTOMATIC ATTENDANCE SYSTEM - CONTROLLED CLOUD RESET SCRIPT
-- =============================================================================
-- Purpose: Clear old test data in Supabase while strictly preserving:
-- 1. Table schemas and data types
-- 2. Foreign keys and unique constraints (e.g. single-daily attendance rule)
-- 3. Row Level Security (RLS) enforcement on all tables
-- 4. Audit trail immutability (REVOKE DELETE, TRUNCATE from API users)
-- 5. Biometric privacy protections
--
-- Instructions: Run this script directly in the Supabase Dashboard SQL Editor
-- (it executes as superuser/postgres role so it can clear test rows).
-- =============================================================================

-- Step 1: Delete all records in strict dependency order (child -> parent)
DELETE FROM public.attendance;
DELETE FROM public.students;
DELETE FROM public.buses;

DO $$
BEGIN
    IF to_regclass('public.student_biometrics') IS NOT NULL THEN
        DELETE FROM public.student_biometrics;
    END IF;
END $$;

-- Step 2: Ensure correct RLS policies for fresh registration
DO $$
BEGIN
    -- Ensure active students can be read and verified by desktop app (anon & authenticated)
    DROP POLICY IF EXISTS "Allow authenticated read active students" ON public.students;
    DROP POLICY IF EXISTS "Allow read active students" ON public.students;

    CREATE POLICY "Allow read active students" 
        ON public.students FOR SELECT 
        TO anon, authenticated 
        USING (is_active = true);

    -- Ensure attendance verified insert policy is active
    DROP POLICY IF EXISTS "Allow verified attendance insert" ON public.attendance;

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
END $$;

-- Verification query: confirm all tables are empty and schemas intact
SELECT 'buses' AS table_name, count(*) AS row_count FROM public.buses
UNION ALL
SELECT 'students', count(*) FROM public.students
UNION ALL
SELECT 'attendance', count(*) FROM public.attendance;
