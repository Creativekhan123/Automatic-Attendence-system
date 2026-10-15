-- =============================================================================
-- Rollback for Migration 001: Automatic School Bus Attendance System
-- =============================================================================
-- WARNING: This will drop the student_biometrics table and newly added indexes.
-- Existing tables (buses, students, attendance) and their columns will be preserved.
-- =============================================================================

-- 1. Drop Biometrics trigger and table
DROP TRIGGER IF EXISTS trg_biometrics_updated_at ON public.student_biometrics;
DROP FUNCTION IF EXISTS public.set_biometrics_updated_at();
DROP TABLE IF EXISTS public.student_biometrics CASCADE;

-- 2. Drop Check constraint
ALTER TABLE IF EXISTS public.attendance DROP CONSTRAINT IF EXISTS chk_attendance_status;

-- 3. Drop Indexes
DROP INDEX IF EXISTS public.idx_attendance_date;
DROP INDEX IF EXISTS public.idx_attendance_bus_date;
DROP INDEX IF EXISTS public.idx_attendance_student_date;
DROP INDEX IF EXISTS public.idx_students_bus_active;

-- 4. Drop Policies (if needed to reset RLS)
DROP POLICY IF EXISTS "Allow app select buses" ON public.buses;
DROP POLICY IF EXISTS "Allow app insert/update buses" ON public.buses;
DROP POLICY IF EXISTS "Allow app select students" ON public.students;
DROP POLICY IF EXISTS "Allow app insert/update students" ON public.students;
DROP POLICY IF EXISTS "Allow app select attendance" ON public.attendance;
DROP POLICY IF EXISTS "Allow app insert attendance" ON public.attendance;
DROP POLICY IF EXISTS "Allow app update attendance" ON public.attendance;
