-- =============================================================================
-- Migration 005: Fix Bus Deletion, Permissions & Foreign Key Safeguards
-- =============================================================================
-- Problem solved:
-- 1. In migration 002/004, REVOKE DELETE stripped delete permissions from 'anon',
--    causing HTTP 401 "permission denied for table buses" on bus deletion.
-- 2. The UPDATE policy had WITH CHECK (is_active = true), which blocked soft-deactivation.
-- 3. Foreign key constraints on students and attendance block hard delete if records exist.
--
-- This migration grants DELETE permissions, updates RLS, and creates a smart RPC
-- function that safely hard-deletes empty/test buses and deactivates buses with
-- historical attendance records to preserve data integrity.
--
-- Instructions:
--   Copy and paste this script into your Supabase Dashboard -> SQL Editor and click RUN.
-- =============================================================================

-- 1. Grant table-level DELETE & UPDATE permissions to anon and authenticated roles
GRANT SELECT, INSERT, UPDATE, DELETE ON public.buses TO anon, authenticated;

-- 2. Update Row Level Security Policies for public.buses
ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    DROP POLICY IF EXISTS "Allow delete buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow update active bus metadata" ON public.buses;
    DROP POLICY IF EXISTS "Allow update bus metadata" ON public.buses;
    DROP POLICY IF EXISTS "Allow read active buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow read all buses" ON public.buses;
    DROP POLICY IF EXISTS "Allow read buses" ON public.buses;
END $$;

-- Allow reading all buses (manager displays active and archived buses)
CREATE POLICY "Allow read buses" 
    ON public.buses FOR SELECT 
    TO anon, authenticated 
    USING (true);

-- Allow deleting buses via RLS
CREATE POLICY "Allow delete buses" 
    ON public.buses FOR DELETE 
    TO anon, authenticated 
    USING (true);

-- Allow updating bus metadata AND deactivating (is_active = false)
CREATE POLICY "Allow update bus metadata" 
    ON public.buses FOR UPDATE 
    TO anon, authenticated 
    USING (true)
    WITH CHECK (
        bus_id IS NOT NULL AND length(trim(bus_id)) > 0
    );

-- 3. Stored Procedure: Safe Bus Deletion / Archival
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
    -- Check if bus exists
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
            'message', format('Bus "%s" has %s attendance records and %s students. It was safely deactivated (archived) to preserve historical records.', target_bus_id, v_attendance_count, v_student_count)
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

-- Verification Query: Check active policies on public.buses
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE tablename = 'buses';
