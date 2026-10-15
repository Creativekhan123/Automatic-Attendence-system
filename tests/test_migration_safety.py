"""Offline tests for migration-safety behaviour (crosswalk, conflicts, gates, retries).

All Supabase interaction is mocked. No network access and no real database is touched.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np

from src.database import Database
from src.supabase_service import SupabaseService, IdCrosswalk
from src.sync_worker import SyncWorker


class FakeAPIError(Exception):
    """Mimics postgrest APIError (carries a PostgreSQL error code via .json())."""

    def __init__(self, code: str, message: str = "boom") -> None:
        super().__init__({"message": message, "code": code})
        self._payload = {"message": message, "code": code}

    def json(self):
        return self._payload


def make_service(crosswalk=None):
    """Build a SupabaseService backed by a MagicMock client."""
    with patch("src.supabase_service.create_client") as mock_create:
        client = MagicMock()
        mock_create.return_value = client
        svc = SupabaseService(
            url="https://xyz.supabase.co",
            key="test-key",
            crosswalk=crosswalk if crosswalk is not None else IdCrosswalk(
                students={"1": "01"}, buses={"BUS01": "Bus01"}
            ),
        )
    return svc, client


def rec(event_id, student_id="1", bus_id="BUS01", date="2026-10-14", status="Present", device_id=None):
    return {
        "event_id": event_id, "student_id": student_id, "attendance_date": date,
        "attendance_time": "08:00:00", "bus_id": bus_id, "status": status, "device_id": device_id,
    }


class TestCrosswalk(unittest.TestCase):
    def test_explicit_mapping_and_identity(self):
        cw = IdCrosswalk(students={"1": "01"}, buses={"BUS01": "Bus01"})
        self.assertEqual(cw.student_to_cloud("1"), "01")
        self.assertEqual(cw.bus_to_cloud("BUS01"), "Bus01")
        # Gautham's local ID must NEVER be silently padded to Ahtesham's cloud ID
        self.assertEqual(cw.student_to_cloud("2"), "2")
        self.assertNotEqual(cw.student_to_cloud("2"), "02")
        self.assertEqual(cw.bus_to_cloud("2241"), "2241")

    def test_reverse_mapping_preserves_leading_zero(self):
        cw = IdCrosswalk(students={"1": "01"}, buses={"BUS01": "Bus01"})
        self.assertEqual(cw.student_to_local("01"), "1")
        self.assertEqual(cw.bus_to_local("Bus01"), "BUS01")
        self.assertEqual(cw.student_to_local("02"), "02")  # unmapped cloud-only student untouched

    def test_load_missing_or_bad_file_gives_identity(self):
        self.assertEqual(IdCrosswalk.load(os.path.join(tempfile.gettempdir(), "nope_xyz.json")).student_to_cloud("1"), "1")
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, "w") as f:
                f.write("{not json")
            self.assertEqual(IdCrosswalk.load(path).bus_to_cloud("BUS01"), "BUS01")
        finally:
            os.remove(path)

    def test_project_crosswalk_file_is_as_approved(self):
        cw = IdCrosswalk.load(os.path.join(_PROJECT_ROOT, "id_crosswalk.json"))
        self.assertEqual(cw.students, {"1": "01"})
        self.assertEqual(cw.buses, {"BUS01": "Bus01"})


class TestUploadMappingAndIsolation(unittest.TestCase):
    def test_payload_is_mapped_and_normalized(self):
        svc, client = make_service()
        count, ids, err = svc.upload_attendance_batch([
            rec("e1", status="present", device_id="Null"),
            rec("e2", student_id="3", device_id="BUS01_DEV_01"),
        ])
        self.assertEqual((count, ids, err), (2, ["e1", "e2"], None))
        sent = client.table().upsert.call_args[0][0]
        self.assertEqual(sent[0]["student_id"], "01")
        self.assertEqual(sent[0]["bus_id"], "Bus01")
        self.assertEqual(sent[0]["status"], "Present")
        self.assertIsNone(sent[0]["device_id"])
        self.assertEqual(sent[1]["student_id"], "3")
        self.assertEqual(sent[1]["device_id"], "BUS01_DEV_01")
        self.assertEqual(client.table().upsert.call_args[1], {"on_conflict": "event_id"})

    def test_network_error_confirms_nothing_and_does_not_fan_out(self):
        svc, client = make_service()
        client.table().upsert().execute.side_effect = ConnectionError("no route")
        client.table().upsert.reset_mock()
        count, ids, err = svc.upload_attendance_batch([rec("e1"), rec("e2")])
        self.assertEqual((count, ids), (0, []))
        self.assertIn("e1", err)
        self.assertTrue(all(s == "network" for s, _ in svc.last_upload_results.values()))
        # Only the single batch attempt, no per-record hammering while offline
        self.assertEqual(client.table().upsert.call_count, 1)

    def test_duplicate_triple_with_other_event_is_a_conflict_not_overwritten(self):
        svc, client = make_service()
        up = MagicMock()
        up.execute.side_effect = [FakeAPIError("23505"), FakeAPIError("23505")]
        client.table.return_value.upsert.return_value = up
        existing = MagicMock()
        existing.data = [{"event_id": "91fefea4-cloud", "student_id": "01"}]
        (client.table.return_value.select.return_value.eq.return_value.eq.return_value
         .eq.return_value.limit.return_value.execute.return_value) = existing
        count, ids, err = svc.upload_attendance_batch([rec("local-30")])
        self.assertEqual((count, ids), (0, []))
        self.assertEqual(svc.last_upload_results["local-30"][0], "conflict")
        self.assertIn("91fefea4-cloud", svc.last_upload_results["local-30"][1])

    def test_duplicate_triple_with_same_event_counts_as_synced(self):
        svc, client = make_service()
        up = MagicMock()
        up.execute.side_effect = [FakeAPIError("23505"), FakeAPIError("23505")]
        client.table.return_value.upsert.return_value = up
        existing = MagicMock()
        existing.data = [{"event_id": "e1"}]
        (client.table.return_value.select.return_value.eq.return_value.eq.return_value
         .eq.return_value.limit.return_value.execute.return_value) = existing
        count, ids, err = svc.upload_attendance_batch([rec("e1")])
        self.assertEqual((count, ids, err), (1, ["e1"], None))

    def test_mixed_batch_isolation(self):
        svc, client = make_service()
        up = MagicMock()
        # 1: whole batch rejected; 2: e1 ok; 3: e2 FK-rejected; 4: e3 ok
        up.execute.side_effect = [FakeAPIError("23503"), MagicMock(), FakeAPIError("23503"), MagicMock()]
        client.table.return_value.upsert.return_value = up
        count, ids, err = svc.upload_attendance_batch([rec("e1"), rec("e2"), rec("e3")])
        self.assertEqual(ids, ["e1", "e3"])
        self.assertEqual(svc.last_upload_results["e2"][0], "rejected")
        self.assertIsNotNone(err)


class TestNoImplicitCloudWrites(unittest.TestCase):
    def test_upsert_student_requires_existing_bus_and_never_creates_it(self):
        svc, client = make_service()
        lookup = MagicMock()
        lookup.data = []  # bus does not exist in cloud
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = lookup
        ok = svc.upsert_student("2", "Gautham", "5A", "2241")
        self.assertFalse(ok)
        # no insert/upsert of anything (no bus, no student) happened
        client.table.return_value.upsert.assert_not_called()

    def test_upsert_student_maps_ids_when_bus_exists(self):
        svc, client = make_service()
        lookup = MagicMock()
        lookup.data = [{"bus_id": "Bus01"}]
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = lookup
        self.assertTrue(svc.upsert_student("1", "Mohd Zeeshan", "5A", "BUS01"))
        payload = client.table.return_value.upsert.call_args[0][0]
        self.assertEqual(payload["student_id"], "01")
        self.assertEqual(payload["bus_id"], "Bus01")

    def test_biometrics_are_never_uploaded_or_pulled_by_default(self):
        svc, client = make_service()
        self.assertFalse(svc.biometric_sync_enabled)
        self.assertFalse(svc.upload_student_biometrics("1", b"\x00" * 2048))
        self.assertEqual(svc.get_all_biometrics(), [])
        client.table.assert_not_called()


class TestWorkerSafety(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(db_path=self.path)
        self.db.register_student("1", "Mohd Zeeshan", "5A", "BUS01", np.ones(512, dtype=np.float32))
        self.db.mark_student_present("1", "2026-10-15", "11:53:22", "BUS01", "Present",
                                     event_id="local-30", device_id="D", sync_status="pending")

    def tearDown(self):
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass

    def _worker(self, svc, **kw):
        return SyncWorker(db=self.db, supabase_service=svc, interval_seconds=100.0, **kw)

    def test_disabled_worker_does_not_start_thread(self):
        svc = MagicMock(spec=SupabaseService)
        svc.is_configured.return_value = True
        w = self._worker(svc, enabled=False)
        w.start()
        self.assertIsNone(w._thread)
        self.assertEqual(w.get_status()["state_text"], "Cloud sync disabled (Local SQLite)")
        svc.upload_attendance_batch.assert_not_called()

    def test_conflict_leaves_queue_but_is_not_marked_synced(self):
        svc = MagicMock(spec=SupabaseService)
        svc.is_configured.return_value = True
        svc.test_connection.return_value = (True, "OK")
        svc.upload_attendance_batch.return_value = (0, [], "local-30: conflict (dup)")
        svc.last_upload_results = {"local-30": ("conflict", "dup")}
        svc.get_all_biometrics.return_value = []
        w = self._worker(svc, enabled=True)
        w._perform_sync_cycle()
        conn = self.db._get_connection()
        row = conn.execute("SELECT sync_status, synced_at FROM attendance WHERE event_id='local-30'").fetchone()
        conn.close()
        self.assertEqual(row["sync_status"], "conflict")
        self.assertIsNone(row["synced_at"])
        self.assertEqual(self.db.get_pending_sync_count(), 0)

    def test_pulls_are_off_by_default(self):
        svc = MagicMock(spec=SupabaseService)
        svc.is_configured.return_value = True
        svc.test_connection.return_value = (True, "OK")
        svc.upload_attendance_batch.return_value = (1, ["local-30"], None)
        svc.get_all_biometrics.return_value = []
        w = self._worker(svc, enabled=True)
        w._perform_sync_cycle()
        svc.get_all_students.assert_not_called()
        svc.get_all_buses.assert_not_called()

    def test_network_failure_keeps_record_pending_and_backs_off(self):
        svc = MagicMock(spec=SupabaseService)
        svc.is_configured.return_value = True
        svc.test_connection.return_value = (False, "offline")
        w = self._worker(svc, enabled=True)
        w._perform_sync_cycle()
        w._perform_sync_cycle()
        self.assertEqual(self.db.get_pending_sync_count(), 1)
        self.assertEqual(w._consecutive_failures, 2)
        self.assertEqual(w._current_wait_seconds(), 300.0)  # 100s * 2^2 = 400s, capped at 300s
        svc.upload_attendance_batch.assert_not_called()

    def test_repeatedly_rejected_record_is_excluded_after_max_retries(self):
        from src import sync_worker as sw
        svc = MagicMock(spec=SupabaseService)
        svc.is_configured.return_value = True
        svc.test_connection.return_value = (True, "OK")
        svc.upload_attendance_batch.return_value = (0, [], "local-30: rejected (fk)")
        svc.last_upload_results = {"local-30": ("rejected", "fk")}
        svc.get_all_biometrics.return_value = []
        w = self._worker(svc, enabled=True)
        for _ in range(sw.SYNC_MAX_RETRIES):
            w._perform_sync_cycle()
        self.assertIn("local-30", w._skipped_events)
        calls = svc.upload_attendance_batch.call_count
        w._perform_sync_cycle()
        self.assertEqual(svc.upload_attendance_batch.call_count, calls)  # no more attempts
        self.assertEqual(self.db.get_pending_sync_count(), 1)  # still pending, never dropped


if __name__ == "__main__":
    unittest.main()
