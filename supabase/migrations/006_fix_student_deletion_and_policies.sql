-- =============================================================================
-- Migration 006: Permanent Student Deletion, Biometric Purge & Cascade Cleanup
-- =============================================================================
-- Problem solved:
-- 1. In migration 002/004, REVOKE DELETE stripped delete permissions from 'anon',
--    causing HTTP 401 "permission denied for table students" on student deletion.
-- 2. The client code had a fallback that turned 'is_active = false' instead of
--    permanently removing the record, causing old deleted students to accumulate
--    and bloat the cloud database.
-- 3. The foreign key constraint 'fk_attendance_student' did not have CASCADE,
--    blocking hard deletion if attendance logs existed.
--
-- This migration:
-- - Grants DELETE permissions on students, student_biometrics, and attendance.
-- - Adds RLS policies for DELETE on students and biometrics.
-- - Updates the foreign key on attendance to ON DELETE CASCADE so child records
--   never orphan or block profile removal.
-- - Creates a safe atomic RPC function: delete_student_permanently(target_student_id).
--
-- Instructions:
--   Copy and paste this script into your Supabase Dashboard -> SQL Editor and click RUN.
-- =============================================================================

-- 1. Grant table-level DELETE permissions to anon and authenticated roles
GRANT SELECT, INSERT, UPDATE, DELETE ON public.students TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.student_biometrics TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.attendance TO anon, authenticated;

-- 2. Update Row Level Security Policies
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_biometrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    DROP POLICY IF EXISTS "Allow delete students" ON public.students;
    DROP POLICY IF EXISTS "Allow delete student_biometrics" ON public.student_biometrics;
    DROP POLICY IF EXISTS "Allow delete attendance" ON public.attendance;
END $$;

-- Policy: Allow deleting student profiles
CREATE POLICY "Allow delete students" 
    ON public.students FOR DELETE 
    TO anon, authenticated 
    USING (true);

-- Policy: Allow deleting biometrics
CREATE POLICY "Allow delete student_biometrics" 
    ON public.student_biometrics FOR DELETE 
    TO anon, authenticated 
    USING (true);

-- Policy: Allow deleting attendance
CREATE POLICY "Allow delete attendance" 
    ON public.attendance FOR DELETE 
    TO anon, authenticated 
    USING (true);

-- 3. Ensure Foreign Key fk_attendance_student supports ON DELETE CASCADE
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_attendance_student'
    ) THEN
        ALTER TABLE public.attendance DROP CONSTRAINT fk_attendance_student;
    END IF;

    ALTER TABLE public.attendance 
        ADD CONSTRAINT fk_attendance_student 
        FOREIGN KEY (student_id) REFERENCES public.students(student_id) ON DELETE CASCADE;
END $$;

-- 4. Stored Procedure: Safe Atomic Student Purge
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
    -- Check if student exists
    SELECT EXISTS(SELECT 1 FROM public.students WHERE student_id = target_student_id) INTO v_exists;
    IF NOT v_exists THEN
        RETURN jsonb_build_object(
            'success', false,
            'action', 'not_found',
            'message', format('Student "%s" does not exist in the database.', target_student_id)
        );
    END IF;

    -- Count dependent records
    SELECT count(*) INTO v_att_count FROM public.attendance WHERE student_id = target_student_id;
    IF to_regclass('public.student_biometrics') IS NOT NULL THEN
        SELECT count(*) INTO v_bio_count FROM public.student_biometrics WHERE student_id = target_student_id;
        DELETE FROM public.student_biometrics WHERE student_id = target_student_id;
    END IF;

    -- Delete attendance logs for this student
    DELETE FROM public.attendance WHERE student_id = target_student_id;

    -- Delete student profile row
    DELETE FROM public.students WHERE student_id = target_student_id;

    RETURN jsonb_build_object(
        'success', true,
        'action', 'deleted',
        'message', format('Student "%s" permanently purged (removed %s biometrics and %s attendance records).', target_student_id, v_bio_count, v_att_count)
    );
END;
$$;

GRANT EXECUTE ON FUNCTION public.delete_student_permanently(TEXT) TO anon, authenticated;

-- Verification Query: Check active policies on public.students
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE tablename IN ('students', 'student_biometrics');
