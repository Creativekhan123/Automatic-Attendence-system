"""Unit tests for the pre-production audit fixes and single daily attendance rule:
1. Supabase Security (offline security gates, zero biometric transmission, safe fallbacks)
2. Single Daily Attendance (strict uniqueness per student, date, and bus; rejection of duplicate attempts regardless of time)
3. Offline Student Registration (pending queue, upload dependency ordering, retry safety)
"""
import os
import sys
import uuid
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Ensure project root is in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.database import Database
from src.attendance import AttendanceEngine
from src.supabase_service import SupabaseService, IdCrosswalk
from src.sync_worker import SyncWorker


class TestFix1SupabaseSecurity(unittest.TestCase):
    """Verify security controls, biometric privacy, and client credential safety."""

    def test_biometric_cloud_sync_disabled_by_default(self):
        """Verify biometric cloud sync is strictly False by default to keep embeddings local."""
        service = SupabaseService(url="https://fake.supabase.co", key="anon-key")
        self.assertFalse(service.biometric_sync_enabled)
        # Attempting upload without flag must fail
        ok = service.upload_student_biometrics("101", b"\x00" * 2048)
        self.assertFalse(ok)
        self.assertIn("disabled", service._last_error.lower())

    def test_cloud_attendance_payload_excludes_biometrics_and_session_type(self):
        """Verify that attendance payload formatting never includes embeddings, photos, or session_type."""
        service = SupabaseService(url="https://fake.supabase.co", key="anon-key")
        raw_record = {
            "event_id": str(uuid.uuid4()),
            "student_id": "1",
            "bus_id": "BUS01",
            "attendance_date": "2026-10-15",
            "attendance_time": "08:15:00",
            "status": "Present",
            "device_id": "BUS01_DEV_01",
            "photo": b"fake_image_bytes",
            "face_embedding": b"fake_embedding_bytes",
            "secret_key": "leak_attempt",
            "session_type": "Morning"
        }
        cloud_payload = service._to_cloud_attendance(raw_record)
        self.assertNotIn("photo", cloud_payload)
        self.assertNotIn("face_embedding", cloud_payload)
        self.assertNotIn("secret_key", cloud_payload)
        self.assertNotIn("session_type", cloud_payload)
        # ID crosswalk maps '1' -> '01'
        self.assertEqual(cloud_payload["student_id"], "01")
        self.assertEqual(cloud_payload["bus_id"], "Bus01")


class TestSingleDailyAttendance(unittest.TestCase):
    """Verify strict single daily attendance rule: (student_id, attendance_date, bus_id)."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        self.db = Database(db_path=self.temp_db_path)
        dummy_embedding = np.ones(512, dtype=np.float32)
        self.db.register_student("101", "Alice Student", "5A", "BUS01", dummy_embedding)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_single_daily_attendance_rejection_regardless_of_time(self):
        """A second attendance attempt on the same date and bus must be rejected, regardless of time."""
        date_str = "2026-10-15"
        bus_id = "BUS01"

        # 1. First attendance in morning (07:45:00) -> SUCCEEDS
        first_eid = str(uuid.uuid4())
        ok_first = self.db.mark_student_present(
            student_id="101",
            attendance_date=date_str,
            attendance_time="07:45:00",
            bus_id=bus_id,
            status="Present",
            event_id=first_eid
        )
        self.assertTrue(ok_first, "First daily attendance mark should succeed")
        self.assertTrue(self.db.is_student_marked_present("101", date_str, bus_id))

        # 2. Second attendance attempt in early afternoon (13:30:00) -> MUST BE REJECTED
        second_eid = str(uuid.uuid4())
        ok_second = self.db.mark_student_present(
            student_id="101",
            attendance_date=date_str,
            attendance_time="13:30:00",
            bus_id=bus_id,
            status="Present",
            event_id=second_eid
        )
        self.assertFalse(ok_second, "Second attendance attempt at 13:30:00 must be rejected")

        # 3. Third attendance attempt in evening (17:45:00) -> MUST BE REJECTED
        third_eid = str(uuid.uuid4())
        ok_third = self.db.mark_student_present(
            student_id="101",
            attendance_date=date_str,
            attendance_time="17:45:00",
            bus_id=bus_id,
            status="Present",
            event_id=third_eid
        )
        self.assertFalse(ok_third, "Third attendance attempt at 17:45:00 must be rejected")

        # Verify exactly one record exists for today
        records = self.db.get_attendance_for_date(date_str, bus_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event_id"], first_eid)
        self.assertEqual(records[0]["attendance_time"], "07:45:00")

        # Attendance on the NEXT date (2026-10-16) must succeed
        next_date_eid = str(uuid.uuid4())
        ok_next_date = self.db.mark_student_present(
            student_id="101",
            attendance_date="2026-10-16",
            attendance_time="07:50:00",
            bus_id=bus_id,
            status="Present",
            event_id=next_date_eid
        )
        self.assertTrue(ok_next_date, "Attendance on the next date must succeed")

    def test_attendance_engine_blocks_second_daily_marking(self):
        """AttendanceEngine marks student Present once, and marks ALREADY PRESENT on all subsequent recognitions."""
        student_candidate = {"student_id": "101", "name": "Alice Student"}

        engine = AttendanceEngine(
            db=self.db,
            bus_id="BUS01",
            required_confirmations=2,
            confirmation_window_seconds=2.0
        )

        # Confirm first daily attendance
        engine.process_recognition(student_candidate)
        status, count, newly_marked = engine.process_recognition(student_candidate)
        self.assertEqual(status, "PRESENT")
        self.assertTrue(newly_marked)

        # Any later recognition attempt on the same day reports ALREADY PRESENT
        status, count, newly_marked = engine.process_recognition(student_candidate)
        self.assertEqual(status, "ALREADY PRESENT")
        self.assertFalse(newly_marked)

        summary = engine.get_attendance_summary()
        self.assertEqual(summary["total_present"], 1)

    def test_safe_duplicate_consolidation_and_archival(self):
        """Existing duplicate records are archived safely without data loss, and constraint enforced."""
        with self.db._get_connection() as conn:
            cur = conn.cursor()
            # Drop attendance and recreate as unconstrained legacy table to simulate duplicate records
            cur.execute("PRAGMA foreign_keys = OFF")
            cur.execute("DROP TABLE attendance")
            cur.execute("""
                CREATE TABLE attendance (
                    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    student_id TEXT NOT NULL,
                    attendance_date TEXT NOT NULL,
                    attendance_time TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    device_id TEXT,
                    sync_status TEXT DEFAULT 'pending',
                    synced_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    session_type TEXT
                )
            """)
            cur.execute("""
                INSERT INTO attendance (event_id, student_id, attendance_date, attendance_time, bus_id, status, session_type)
                VALUES ('eid-1', '101', '2026-10-15', '08:00:00', 'BUS01', 'Present', 'Morning')
            """)
            cur.execute("""
                INSERT INTO attendance (event_id, student_id, attendance_date, attendance_time, bus_id, status, session_type)
                VALUES ('eid-2', '101', '2026-10-15', '14:00:00', 'BUS01', 'Present', 'Afternoon')
            """)
            conn.commit()

        # Re-initialize Database to trigger consolidation logic and table rebuild
        db_reloaded = Database(db_path=self.temp_db_path)

        with db_reloaded._get_connection() as conn:
            cur = conn.cursor()
            # Verify primary attendance table has exactly 1 row
            att_rows = cur.execute("""
                SELECT * FROM attendance WHERE student_id = '101' AND attendance_date = '2026-10-15'
            """).fetchall()
            self.assertEqual(len(att_rows), 1)
            self.assertEqual(att_rows[0]["attendance_time"], "08:00:00")

            # Verify duplicate archive table has the second row
            arch_rows = cur.execute("""
                SELECT * FROM attendance_duplicates_archive WHERE student_id = '101' AND attendance_date = '2026-10-15'
            """).fetchall()
            self.assertEqual(len(arch_rows), 1)
            self.assertEqual(arch_rows[0]["attendance_time"], "14:00:00")
            self.assertIn("single-daily rule", arch_rows[0]["consolidation_reason"])


class TestOfflineStudentRegistration(unittest.TestCase):
    """Verify offline student registration queue, dependency-ordered sync, and retry safety."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        self.db = Database(db_path=self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_offline_student_registration_queues_pending(self):
        """Newly registered student is marked pending in local SQLite."""
        dummy_embedding = np.ones(512, dtype=np.float32)
        success = self.db.register_student("999", "New Student", "1st", "BUS01", dummy_embedding)
        self.assertTrue(success)

        # Verify pending count
        pending_students = self.db.get_pending_students()
        self.assertEqual(len(pending_students), 1)
        self.assertEqual(pending_students[0]["student_id"], "999")
        self.assertEqual(self.db.get_pending_students_count(), 1)

        # Updating student keeps or re-queues as pending
        self.db.update_student("999", "New Student Updated", "2nd", "BUS01")
        pending_after_update = self.db.get_pending_students()
        self.assertEqual(len(pending_after_update), 1)
        self.assertEqual(pending_after_update[0]["name"], "New Student Updated")

    def test_sync_worker_uploads_bus_first_student_second_attendance_third(self):
        """Verify strict dependency ordering: bus metadata, student metadata, then attendance."""
        dummy_embedding = np.ones(512, dtype=np.float32)
        self.db.register_student("888", "Bob Builder", "4B", "BUS02", dummy_embedding)
        eid = str(uuid.uuid4())
        self.db.mark_student_present(
            student_id="888",
            attendance_date="2026-10-15",
            attendance_time="08:00:00",
            bus_id="BUS02",
            status="Present",
            event_id=eid,
            sync_status="pending"
        )

        call_order = []

        mock_supabase = MagicMock(spec=SupabaseService)
        mock_supabase.is_configured.return_value = True
        mock_supabase.test_connection.return_value = (True, "OK")

        def fake_ensure_bus(bus_id):
            call_order.append(f"ensure_bus:{bus_id}")
            return True
        mock_supabase.ensure_bus.side_effect = fake_ensure_bus

        def fake_upsert_student(student_id, name, class_name, bus_id, is_active=True, insert_only=False):
            call_order.append(f"upsert_student:{student_id}")
            return True
        mock_supabase.upsert_student.side_effect = fake_upsert_student

        def fake_upload_attendance_batch(records):
            call_order.append(f"upload_attendance:{len(records)}")
            return len(records), [r["event_id"] for r in records], None
        mock_supabase.upload_attendance_batch.side_effect = fake_upload_attendance_batch

        mock_supabase.get_all_buses.return_value = []
        mock_supabase.get_all_students.return_value = []
        mock_supabase.get_all_biometrics.return_value = []

        worker = SyncWorker(db=self.db, supabase_service=mock_supabase, interval_seconds=100.0)
        worker._perform_sync_cycle()

        # Check call order
        self.assertTrue(len(call_order) >= 3, f"Calls recorded: {call_order}")
        first_bus_idx = next(i for i, c in enumerate(call_order) if c.startswith("ensure_bus:BUS02"))
        first_student_idx = next(i for i, c in enumerate(call_order) if c.startswith("upsert_student:888"))
        first_att_idx = next(i for i, c in enumerate(call_order) if c.startswith("upload_attendance:"))

        self.assertLess(first_bus_idx, first_student_idx, "Bus must be ensured before student upload")
        self.assertLess(first_student_idx, first_att_idx, "Student must be uploaded before attendance upload")

        # After sync cycle, pending counts must be zero
        self.assertEqual(self.db.get_pending_students_count(), 0)
        self.assertEqual(self.db.get_pending_sync_count(), 0)

    def test_sync_worker_network_failure_leaves_records_pending_without_duplicates(self):
        """Network drop during student sync leaves student pending for recovery."""
        dummy_embedding = np.ones(512, dtype=np.float32)
        self.db.register_student("777", "David Copperfield", "3A", "BUS01", dummy_embedding)

        mock_supabase = MagicMock(spec=SupabaseService)
        mock_supabase.is_configured.return_value = True
        mock_supabase.test_connection.return_value = (True, "OK")
        mock_supabase.ensure_bus.return_value = True
        # Simulate network failure on upsert_student
        mock_supabase.upsert_student.return_value = False
        mock_supabase.upload_attendance_batch.return_value = (0, [], "Network error")
        mock_supabase.get_all_buses.return_value = []
        mock_supabase.get_all_students.return_value = []
        mock_supabase.get_all_biometrics.return_value = []

        worker = SyncWorker(db=self.db, supabase_service=mock_supabase, interval_seconds=100.0)
        worker._perform_sync_cycle()

        # Student should remain pending
        self.assertEqual(self.db.get_pending_students_count(), 1)

        # Network recovers
        mock_supabase.upsert_student.return_value = True
        worker._perform_sync_cycle()

        # Student is now synced
        self.assertEqual(self.db.get_pending_students_count(), 0)


class TestAllowedAndDeniedOperations(unittest.TestCase):
    """Verify allowed and denied database and synchronization operations."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        self.db = Database(db_path=self.temp_db_path)
        dummy_embedding = np.ones(512, dtype=np.float32)
        self.db.register_student("101", "Student One", "5A", "BUS01", dummy_embedding)
        self.db.register_student("102", "Student Two", "5A", "BUS01", dummy_embedding)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    # --- ALLOWED OPERATIONS ---
    def test_allowed_attendance_first_marking(self):
        """ALLOWED: First attendance mark on a date & bus succeeds."""
        eid = str(uuid.uuid4())
        ok = self.db.mark_student_present("101", "2026-10-15", "08:00:00", "BUS01", "Present", eid)
        self.assertTrue(ok)
        self.assertTrue(self.db.is_student_marked_present("101", "2026-10-15", "BUS01"))

    def test_allowed_attendance_different_students_same_date_bus(self):
        """ALLOWED: Different students marking attendance on the same date and bus succeed."""
        ok1 = self.db.mark_student_present("101", "2026-10-15", "08:00:00", "BUS01", "Present", str(uuid.uuid4()))
        ok2 = self.db.mark_student_present("102", "2026-10-15", "08:01:00", "BUS01", "Present", str(uuid.uuid4()))
        self.assertTrue(ok1)
        self.assertTrue(ok2)

    def test_allowed_attendance_next_date_for_same_student(self):
        """ALLOWED: Same student marking attendance on subsequent dates succeeds."""
        ok_d1 = self.db.mark_student_present("101", "2026-10-15", "08:00:00", "BUS01", "Present", str(uuid.uuid4()))
        ok_d2 = self.db.mark_student_present("101", "2026-10-16", "08:05:00", "BUS01", "Present", str(uuid.uuid4()))
        self.assertTrue(ok_d1)
        self.assertTrue(ok_d2)

    def test_allowed_student_registration_metadata_and_embedding(self):
        """ALLOWED: Registering a student locally with 512-D embedding succeeds."""
        emb = np.zeros(512, dtype=np.float32)
        ok = self.db.register_student("103", "Student Three", "6B", "BUS02", emb)
        self.assertTrue(ok)
        s = self.db.get_student_by_id("103")
        self.assertIsNotNone(s)
        self.assertEqual(s["name"], "Student Three")

    # --- DENIED OPERATIONS ---
    def test_denied_duplicate_attendance_same_student_date_bus(self):
        """DENIED: Multiple attendance marks for the same student on the same date & bus are denied."""
        ok1 = self.db.mark_student_present("101", "2026-10-15", "08:00:00", "BUS01", "Present", str(uuid.uuid4()))
        self.assertTrue(ok1)
        # 12:00 mark
        ok2 = self.db.mark_student_present("101", "2026-10-15", "12:00:00", "BUS01", "Present", str(uuid.uuid4()))
        self.assertFalse(ok2)
        # 16:30 mark
        ok3 = self.db.mark_student_present("101", "2026-10-15", "16:30:00", "BUS01", "Present", str(uuid.uuid4()))
        self.assertFalse(ok3)

    def test_denied_direct_sql_duplicate_violates_unique_constraint(self):
        """DENIED: Direct SQL insert violating (student_id, attendance_date, bus_id) raises IntegrityError."""
        import sqlite3
        with self.db._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO attendance (event_id, student_id, attendance_date, attendance_time, bus_id, status)
                VALUES ('e-1', '101', '2026-10-15', '08:00:00', 'BUS01', 'Present')
            """)
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                cur.execute("""
                    INSERT INTO attendance (event_id, student_id, attendance_date, attendance_time, bus_id, status)
                    VALUES ('e-2', '101', '2026-10-15', '14:00:00', 'BUS01', 'Present')
                """)
                conn.commit()

    def test_denied_attendance_missing_fields(self):
        """DENIED: Attendance missing student_id, date, or bus_id fails safely."""
        ok_no_student = self.db.mark_student_present("", "2026-10-15", "08:00:00", "BUS01", "Present", str(uuid.uuid4()))
        self.assertFalse(ok_no_student)
        ok_no_bus = self.db.mark_student_present("101", "2026-10-15", "08:00:00", "", "Present", str(uuid.uuid4()))
        self.assertFalse(ok_no_bus)

    def test_denied_biometric_cloud_sync(self):
        """DENIED: Uploading biometrics to cloud is rejected when BIOMETRIC_CLOUD_SYNC=False."""
        service = SupabaseService(url="https://test.supabase.co", key="anon-key")
        self.assertFalse(service.biometric_sync_enabled)
        ok = service.upload_student_biometrics("101", b"\x00" * 2048)
        self.assertFalse(ok)
        self.assertIn("disabled", service._last_error.lower())

    def test_denied_cloud_overwrite_on_conflict(self):
        """DENIED: Cloud row is never overwritten when 23505 conflict occurs."""
        mock_supabase = MagicMock(spec=SupabaseService)
        mock_supabase.is_configured.return_value = True
        mock_supabase.test_connection.return_value = (True, "OK")
        mock_supabase.ensure_bus.return_value = True
        mock_supabase.get_all_buses.return_value = []
        mock_supabase.get_all_students.return_value = []
        mock_supabase.get_all_biometrics.return_value = []
        # Simulate conflict on attendance upload
        mock_supabase.upload_attendance_batch.return_value = (0, [], "conflict: already exists")
        mock_supabase.last_upload_results = {"eid-conflict": ("conflict", "already exists in cloud")}

        eid = "eid-conflict"
        self.db.mark_student_present("101", "2026-10-15", "08:00:00", "BUS01", "Present", eid, sync_status="pending")

        worker = SyncWorker(db=self.db, supabase_service=mock_supabase, interval_seconds=100.0)
        worker._perform_sync_cycle()

        # Record must be marked 'conflict' and not retried forever
        pending = self.db.get_pending_attendance()
        self.assertEqual(len(pending), 0)
        with self.db._get_connection() as conn:
            row = conn.cursor().execute("SELECT sync_status FROM attendance WHERE event_id = ?", (eid,)).fetchone()
            self.assertEqual(row["sync_status"], "conflict")


class TestMigrationAndRollbackScripts(unittest.TestCase):
    """Verify safety, idempotency, and syntax structure of migration and rollback scripts."""

    def setUp(self):
        self.migration_path = os.path.join(_PROJECT_ROOT, "supabase", "migrations", "002_school_security.sql")
        self.rollback_path = os.path.join(_PROJECT_ROOT, "supabase", "rollback", "002_rollback.sql")

    def test_migration_002_file_properties(self):
        """Migration 002 must exist, be non-empty, and enforce security & single-daily rules."""
        self.assertTrue(os.path.exists(self.migration_path))
        with open(self.migration_path, "r", encoding="utf-8") as f:
            sql = f.read()

        # Single daily attendance constraint
        self.assertIn("uq_attendance_student_date_bus", sql)
        self.assertIn("UNIQUE (student_id, attendance_date, bus_id)", sql)

        # Removal of session_type
        self.assertIn("DROP COLUMN IF EXISTS session_type", sql)
        self.assertIn("DROP CONSTRAINT IF EXISTS uq_attendance_student_date_bus_session", sql)
        self.assertIn("DROP CONSTRAINT IF EXISTS chk_attendance_session_type", sql)

        # Security hardening: revoke destructive actions from anon
        self.assertIn("REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon", sql)
        self.assertIn("REVOKE DELETE, TRUNCATE ON public.attendance FROM anon, authenticated", sql)
        self.assertIn("REVOKE ALL ON public.student_biometrics FROM anon", sql)

        # Attendance write restrictions: requires device_id, non-null fields
        self.assertIn("device_id IS NOT NULL", sql)
        self.assertIn("Allow verified attendance insert", sql)

        # Safety: Must NOT contain destructive drops of production tables
        self.assertNotIn("DROP TABLE public.buses", sql)
        self.assertNotIn("DROP TABLE public.students", sql)
        self.assertNotIn("DROP TABLE public.attendance", sql)
        self.assertNotIn("DELETE FROM public.students", sql)
        self.assertNotIn("DELETE FROM public.attendance", sql)

    def test_rollback_002_file_properties(self):
        """Rollback 002 must cleanly drop 002 policies without destroying data."""
        self.assertTrue(os.path.exists(self.rollback_path))
        with open(self.rollback_path, "r", encoding="utf-8") as f:
            sql = f.read()

        self.assertIn("DROP POLICY IF EXISTS \"Allow verified attendance insert\"", sql)
        self.assertIn("DROP POLICY IF EXISTS \"Allow authenticated read active students\"", sql)
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("DELETE FROM", sql)



class TestStudentDeletionAndIdReuse(unittest.TestCase):
    """Verify that deleting a student purges biometrics, allows ID reuse, and retains attendance history."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        self.db = Database(db_path=self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_deleted_student_biometrics_cleared_and_id_reusable(self):
        """Deleting a student clears biometrics and marks inactive; same ID can then be reused."""
        emb1 = np.ones(512, dtype=np.float32)
        stu_id = "STU_REUSE_01"

        # 1. Register student Alice
        self.db.register_student(stu_id, "Alice Old", "5A", "BUS01", emb1)
        alice = self.db.get_student_by_id(stu_id)
        self.assertIsNotNone(alice)
        self.assertTrue(alice["is_active"])
        self.assertIsNotNone(alice["face_embedding"])

        # 2. Add an attendance record
        self.db.mark_student_present(stu_id, "2026-10-15", "08:00:00", "BUS01", "Present", "eid-hist-1", "DEV-1")
        self.assertEqual(self.db.get_student_attendance_count(stu_id), 1)

        # 3. Delete student Alice (soft_delete=True)
        ok_del = self.db.delete_student(stu_id, soft_delete=True)
        self.assertTrue(ok_del)

        # 4. Verify Alice is inactive and biometric face embedding is wiped
        alice_del = self.db.get_student_by_id(stu_id, active_only=False)
        self.assertIsNotNone(alice_del)
        self.assertFalse(alice_del["is_active"])
        self.assertIsNone(alice_del["face_embedding"])  # Biometric purged

        # Active-only query must return None
        self.assertIsNone(self.db.get_student_by_id(stu_id, active_only=True))

        # Active students list must NOT contain deleted student
        active_list = self.db.get_all_students(active_only=True)
        self.assertFalse(any(s["student_id"] == stu_id for s in active_list))

        # Historical attendance records must be preserved
        self.assertEqual(self.db.get_student_attendance_count(stu_id), 1)

        # 5. Reuse the ID for Bob
        emb2 = np.zeros(512, dtype=np.float32)
        ok_reg = self.db.register_student(stu_id, "Bob New", "6B", "BUS02", emb2)
        self.assertTrue(ok_reg)

        # 6. Verify Bob is now the active owner of that ID
        bob = self.db.get_student_by_id(stu_id, active_only=True)
        self.assertIsNotNone(bob)
        self.assertTrue(bob["is_active"])
        self.assertEqual(bob["name"], "Bob New")
        self.assertEqual(bob["class_name"], "6B")
        self.assertEqual(bob["bus_id"], "BUS02")
        self.assertIsNotNone(bob["face_embedding"])

        # Historical attendance record remains in database
        self.assertEqual(self.db.get_student_attendance_count(stu_id), 1)


if __name__ == "__main__":
    unittest.main()

