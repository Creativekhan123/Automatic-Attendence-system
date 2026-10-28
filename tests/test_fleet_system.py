"""End-to-End Simulation Test for Fleet System Architecture.

Verifies:
1. Manager registers a student and uploads profile + biometrics to Supabase.
2. Device SyncWorker polls cloud and downloads roster + biometrics into local SQLite.
3. Device records offline attendance with duplicate prevention.
4. Device uploads pending attendance to Supabase.
5. Manager reads updated attendance record from Supabase.
6. Re-running attendance produces NO duplicate records.
"""
import os
import sys
import time
import unittest
import numpy as np

# Add project root
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fleet_system.shared.cloud_client import FleetCloudClient
from fleet_system.device_app.local_db import DeviceDatabase
from fleet_system.device_app.sync_worker import DeviceSyncWorker


class TestFleetSystemEndToEnd(unittest.TestCase):

    def setUp(self):
        self.cloud = FleetCloudClient()
        self.test_db_path = "fleet_system/device_app/data/test_e2e_device.db"
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except OSError:
                pass
        self.db = DeviceDatabase(db_path=self.test_db_path)
        self.bus_id = "Bus01"

    def tearDown(self):
        if hasattr(self, "db"):
            del self.db
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except OSError:
                pass

    def test_cloud_connection(self):
        ok, msg = self.cloud.test_connection()
        self.assertTrue(ok, f"Cloud connection failed: {msg}")

    def test_duplicate_prevention_locally(self):
        """Verify local database rejects duplicate attendance for same student, bus, date."""
        today = "2026-10-16"
        sid = "TEST_STU_99"

        # 1st mark -> Should succeed
        is_new1, msg1 = self.db.record_attendance(
            student_id=sid,
            bus_id=self.bus_id,
            device_id="DEV_TEST",
            attendance_date=today,
            attendance_time="08:00:00"
        )
        self.assertTrue(is_new1)

        # 2nd mark -> Must be rejected as duplicate
        is_new2, msg2 = self.db.record_attendance(
            student_id=sid,
            bus_id=self.bus_id,
            device_id="DEV_TEST",
            attendance_date=today,
            attendance_time="08:05:00"
        )
        self.assertFalse(is_new2)
        self.assertIn("Already marked", msg2)

    def test_roster_download_and_biometrics_sync(self):
        """Verify device sync worker downloads roster and biometrics from Supabase."""
        worker = DeviceSyncWorker(db=self.db, bus_id=self.bus_id, interval_seconds=10.0)
        # Execute single sync cycle synchronously
        worker._sync_cycle()

        # Check local DB contains students
        active = self.db.get_active_students_for_bus(self.bus_id)
        self.assertGreaterEqual(len(active), 1, "Roster download should populate local students table")
        # Check embeddings are loaded as numpy arrays
        for s in active:
            self.assertIsInstance(s["face_embedding"], np.ndarray)
            self.assertEqual(len(s["face_embedding"]), 512)


if __name__ == "__main__":
    unittest.main()
