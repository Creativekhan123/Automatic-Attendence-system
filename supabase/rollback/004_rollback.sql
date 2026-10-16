-- =============================================================================
-- Rollback for Migration 004: Prototype Alignment
-- =============================================================================

-- Revert Biometric RLS
DROP POLICY IF EXISTS "Allow authorized fleet biometrics" ON public.student_biometrics;

-- Revert Attendance RLS
DROP POLICY IF EXISTS "Allow verified attendance insert" ON public.attendance;
DROP POLICY IF EXISTS "Allow idempotent retry attendance" ON public.attendance;
DROP POLICY IF EXISTS "Allow read attendance" ON public.attendance;

-- Revert Students RLS
DROP POLICY IF EXISTS "Allow read all students" ON public.students;
DROP POLICY IF EXISTS "Allow enroll student metadata" ON public.students;
DROP POLICY IF EXISTS "Allow update student metadata" ON public.students;

-- Revert Buses RLS
DROP POLICY IF EXISTS "Allow read active buses" ON public.buses;
DROP POLICY IF EXISTS "Allow insert buses" ON public.buses;
DROP POLICY IF EXISTS "Allow update active bus metadata" ON public.buses;

-- Drop foreign key constraint
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS fk_attendance_student;

-- Drop unique constraint
ALTER TABLE public.attendance DROP CONSTRAINT IF EXISTS uq_attendance_student_date_bus;

-- Drop biometric table if desired
-- DROP TABLE IF EXISTS public.student_biometrics CASCADE;
