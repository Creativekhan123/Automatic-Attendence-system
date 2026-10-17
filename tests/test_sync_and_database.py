"""Automated test suite for Database, SupabaseService, SyncWorker, and Attendance logic.

Runs offline without requiring a live cloud connection by using an in-memory or
temporary SQLite database and mocking network calls.
"""
import os
import sys
import uuid
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.database import Database
from src.config import DEFAULT_BUS_ID, DEVICE_ID
from src.supabase_service import SupabaseService, IdCrosswalk
from src.sync_worker import SyncWorker
from src.attendance import AttendanceEngine


class TestDatabaseLocalAndSync(unittest.TestCase):
    """Test local SQLite schema, UUID tracking, and sync queue helper methods."""

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

    def test_schema_initialization(self):
        """Verify that buses, students, and attendance tables are created with sync columns."""
        with self.db._get_connection() as conn:
            cur = conn.cursor()
            # Check buses table
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='buses'")
            self.assertIsNotNone(cur.fetchone(), "Buses table should exist")

            # Check attendance table columns
            cur.execute("PRAGMA table_info(attendance)")
            cols = {row[1] for row in cur.fetchall()}
            self.assertIn("event_id", cols, "attendance must have event_id")
            self.assertIn("device_id", cols, "attendance must have device_id")
            self.assertIn("sync_status", cols, "attendance must have sync_status")
            self.assertIn("synced_at", cols, "attendance must have synced_at")

            # Check students table columns
            cur.execute("PRAGMA table_info(students)")
            stu_cols = {row[1] for row in cur.fetchall()}
            self.assertIn("is_active", stu_cols, "students must have is_active")

    def test_add_student_and_record_attendance(self):
        """Test student addition and attendance record insertion with event_id UUID."""
        import numpy as np
        dummy_embedding = np.ones(512, dtype=np.float32)
        success = self.db.register_student("101", "Alice Smith", "Grade 5", "BUS01", dummy_embedding)
        self.assertTrue(success, "Register student should succeed")

        # Record attendance
        eid = str(uuid.uuid4())
        rec_success = self.db.mark_student_present(
            student_id="101",
            attendance_date="2026-10-14",
            attendance_time="08:00:00",
            bus_id="BUS01",
            status="Present",
            event_id=eid,
            device_id="TEST_DEVICE_01",
            sync_status="pending"
        )
        self.assertTrue(rec_success, "Mark student present should succeed")

        # Check pending sync count
        pending_count = self.db.get_pending_sync_count()
        self.assertEqual(pending_count, 1)

        # Retrieve pending records
        pending = self.db.get_pending_attendance(limit=10)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_id"], eid)
        self.assertEqual(pending[0]["student_id"], "101")
        self.assertEqual(pending[0]["bus_id"], "BUS01")
        self.assertEqual(pending[0]["device_id"], "TEST_DEVICE_01")
        self.assertEqual(pending[0]["sync_status"], "pending")

        # Mark as synced
        self.db.mark_attendance_synced([eid])
        self.assertEqual(self.db.get_pending_sync_count(), 0)

    def test_upsert_bus_local(self):
        """Test local SQLite bus upsert logic."""
        self.db.upsert_bus_local("BUS99", "Express Bus 99", True)
        with self.db._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT bus_id, bus_name, is_active FROM buses WHERE bus_id='BUS99'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["bus_id"], "BUS99")
            self.assertEqual(row["bus_name"], "Express Bus 99")
            self.assertEqual(row["is_active"], 1)

    def test_upsert_student_from_cloud(self):
        """Test downstream sync inserting or updating student profile from cloud."""
        self.db.upsert_student_from_cloud("202", "Bob Jones", "Grade 6", "BUS01", True)
        student = self.db.get_student_by_id("202")
        self.assertIsNotNone(student)
        self.assertEqual(student["name"], "Bob Jones")
        self.assertEqual(student["class_name"], "Grade 6")
        self.assertEqual(student["bus_id"], "BUS01")

        # Update student class from cloud
        self.db.upsert_student_from_cloud("202", "Bob Jones", "Grade 7", "BUS01", True)
        student_updated = self.db.get_student_by_id("202")
        self.assertIsNotNone(student_updated)
        assert student_updated is not None
        self.assertEqual(student_updated["class_name"], "Grade 7")

    def test_attendance_engine_confirmations(self):
        """Test AttendanceEngine multi-frame confirmation and pending queue."""
        import numpy as np
        dummy_embedding = np.ones(512, dtype=np.float32)
        self.db.register_student("501", "Emma Watson", "Grade 8", "BUS01", dummy_embedding)

        engine = AttendanceEngine(
            db=self.db,
            bus_id="BUS01",
            required_confirmations=3,
            confirmation_window_seconds=2.0,
            device_id="DEV_ENGINE_01"
        )
        student_candidate = {"student_id": "501", "name": "Emma Watson"}

        # Frame 1: CONFIRMING (1/3)
        status, count, newly_marked = engine.process_recognition(student_candidate)
        self.assertEqual(status, "CONFIRMING")
        self.assertEqual(count, 1)
        self.assertFalse(newly_marked)

        # Frame 2: CONFIRMING (2/3)
        status, count, newly_marked = engine.process_recognition(student_candidate)
        self.assertEqual(status, "CONFIRMING")
        self.assertEqual(count, 2)
        self.assertFalse(newly_marked)

        # Frame 3: PRESENT (3/3)
        status, count, newly_marked = engine.process_recognition(student_candidate)
        self.assertEqual(status, "PRESENT")
        self.assertEqual(count, 3)
        self.assertTrue(newly_marked)

        # Frame 4: ALREADY PRESENT
        status, count, newly_marked = engine.process_recognition(student_candidate)
        self.assertEqual(status, "ALREADY PRESENT")
        self.assertFalse(newly_marked)

        # Verify queued in DB
        pending = self.db.get_pending_attendance()
        self.assertTrue(any(p["student_id"] == "501" for p in pending))


class TestSupabaseService(unittest.TestCase):
    """Test SupabaseService when unconfigured and with mocked client."""

    def test_unconfigured_service(self):
        """Verify that an unconfigured service reports offline safely without throwing."""
        service = SupabaseService(url="", key="")
        self.assertFalse(service.is_configured())
        ok, msg = service.test_connection()
        self.assertFalse(ok)
        self.assertIn("not configured", msg)
        self.assertEqual(service.get_all_buses(), [])
        self.assertEqual(service.get_all_students(), [])
        self.assertEqual(service.get_all_biometrics(), [])

    @patch("src.supabase_service.create_client")
    def test_mocked_attendance_upload(self, mock_create):
        """Verify upload_attendance_batch formats and executes batch upsert."""
        mock_client = MagicMock()
        mock_create.return_value = mock_client

        service = SupabaseService(url="https://xyz.supabase.co", key="test-key", crosswalk=IdCrosswalk())
        self.assertTrue(service.is_configured())

        records = [
            {
                "event_id": "test-uuid-1",
                "student_id": "101",
                "attendance_date": "2026-10-14",
                "attendance_time": "08:30:00",
                "bus_id": "BUS01",
                "status": "Present",
                "device_id": "DEV_01"
            }
        ]

        count, uploaded_ids, err = service.upload_attendance_batch(records)
        self.assertEqual(count, 1)
        self.assertEqual(uploaded_ids, ["test-uuid-1"])
        self.assertIsNone(err)
        # Verify table calls
        mock_client.table.assert_any_call("attendance")
        mock_client.table().upsert.assert_called_with(records, on_conflict="event_id")


class TestSyncWorker(unittest.TestCase):
    """Test background SyncWorker lifecycle and queue draining."""

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

    def test_worker_status_unconfigured(self):
        """Verify worker status reflects unconfigured mode."""
        unconfigured_service = SupabaseService(url="", key="")
        worker = SyncWorker(db=self.db, supabase_service=unconfigured_service, interval_seconds=100.0)

        status = worker.get_status()
        self.assertFalse(status["is_configured"])
        self.assertIn("Offline Mode", status["state_text"])

    def test_worker_sync_cycle_mocked(self):
        """Verify worker drains pending local records when online."""
        # Insert student and pending attendance
        import numpy as np
        self.db.register_student("301", "Charlie", "Grade 3", "BUS01", np.ones(512, dtype=np.float32))
        eid = str(uuid.uuid4())
        self.db.mark_student_present("301", "2026-10-14", "08:15:00", "BUS01", "Present", event_id=eid, device_id="TEST_DEV", sync_status="pending")
        self.assertEqual(self.db.get_pending_sync_count(), 1)

        # Mock SupabaseService
        mock_service = MagicMock(spec=SupabaseService)
        mock_service.is_configured.return_value = True
        mock_service.test_connection.return_value = (True, "OK")
        mock_service.upload_attendance_batch.return_value = (1, [eid], None)
        mock_service.get_all_buses.return_value = [{"bus_id": "BUS01", "bus_name": "Bus BUS01", "is_active": True}]
        mock_service.get_all_students.return_value = []
        mock_service.get_all_biometrics.return_value = []

        worker = SyncWorker(db=self.db, supabase_service=mock_service, interval_seconds=100.0)
        worker._perform_sync_cycle()

        # After sync cycle, pending count should be 0
        self.assertEqual(self.db.get_pending_sync_count(), 0)
        status = worker.get_status()
        self.assertEqual(status["state_text"], "Cloud Synced")


if __name__ == "__main__":
    unittest.main()
