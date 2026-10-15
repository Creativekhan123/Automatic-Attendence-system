"""Offline tests for the migration planner (tools/migrate_sqlite_to_supabase.py). No I/O to Supabase."""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.supabase_service import IdCrosswalk
from tools import migrate_sqlite_to_supabase as mig

CW = IdCrosswalk(students={"1": "01"}, buses={"BUS01": "Bus01"})


def local_state():
    students = [
        ("1", "Mohd Zeeshan", "5A", "BUS01", 1), ("2", "Gautham", "5A", "2241", 1),
        ("3", "Rakesh", "5A", "BUS01", 1), ("4", "Sai", "5A", "BUS01", 1),
        ("5", "Rithik", "4A", "BUS01", 1), ("7", "Gorge Geo", "7A", "BUS01", 0),
        ("14", "john", "5A", "2241", 1),
    ]
    rows = [  # (attendance_id, event, student, date, time, bus)
        (16, "e16", "1", "2026-10-08", "12:22:58", "BUS01"), (17, "e17", "3", "2026-10-08", "12:37:28", "BUS01"),
        (18, "e18", "2", "2026-10-08", "12:39:30", "BUS01"), (19, "e19", "1", "2026-10-13", "19:16:42", "BUS01"),
        (23, "e23", "1", "2026-10-09", "11:03:12", "BUS01"), (24, "e24", "3", "2026-10-09", "17:42:33", "BUS01"),
        (25, "e25", "4", "2026-10-09", "17:45:09", "BUS01"), (26, "e26", "1", "2026-10-14", "15:49:54", "BUS01"),
        (27, "e27", "4", "2026-10-14", "15:52:23", "BUS01"), (28, "e28", "14", "2026-10-14", "15:53:46", "BUS01"),
        (29, "e29", "7", "2026-10-14", "15:57:18", "BUS01"), (30, "e30", "1", "2026-10-15", "11:53:22", "BUS01"),
        (31, "e31", "7", "2026-10-15", "11:53:50", "BUS01"),
    ]
    return {
        "buses": [{"bus_id": "2241", "bus_name": "Bus 2241", "is_active": 1},
                  {"bus_id": "BUS01", "bus_name": "Bus BUS01", "is_active": 1}],
        "students": [{"student_id": i, "name": n, "class_name": c, "bus_id": b, "is_active": a}
                     for i, n, c, b, a in students],
        "attendance": [{"attendance_id": a, "event_id": e, "student_id": s, "attendance_date": d,
                        "attendance_time": t, "bus_id": b, "status": "Present", "device_id": None,
                        "sync_status": "pending"} for a, e, s, d, t, b in rows],
    }


def cloud_state():
    return {
        "buses": [{"bus_id": "Bus01", "bus_name": "Bus01"}],
        "students": [
            {"student_id": "01", "name": "Mohd Zeeshan", "class_name": "5A", "bus_id": "Bus01"},
            {"student_id": "02", "name": "Ahtesham", "class_name": "12A", "bus_id": "Bus01"},
        ],
        "attendance": [{"event_id": "91fefea4", "student_id": "01", "attendance_date": "2026-10-15",
                        "attendance_time": "11:35:48", "bus_id": "Bus01", "status": "present", "device_id": "Null"}],
    }


class TestPlanner(unittest.TestCase):
    def test_plan_matches_observed_state(self):
        plan = mig.build_plan(local_state(), cloud_state(), CW)
        self.assertEqual([b["cloud_id"] for b in plan["buses_insert"]], ["2241"])
        self.assertEqual([b["cloud_id"] for b in plan["buses_existing"]], ["Bus01"])
        self.assertEqual(sorted(s["local_id"] for s in plan["students_insert"]), ["14", "2", "3", "4", "5", "7"])
        self.assertEqual([(s["local_id"], s["cloud_id"]) for s in plan["students_linked"]], [("1", "01")])
        self.assertEqual(plan["students_blocked"], [])
        self.assertEqual(len(plan["attendance_ready"]), 12)
        self.assertEqual([a["event_id"] for a in plan["attendance_conflicts"]], ["e30"])
        self.assertEqual(plan["attendance_blocked"], [])
        self.assertEqual(plan["attendance_already_in_cloud"], [])

    def test_gautham_is_never_assigned_to_ahtesham(self):
        plan = mig.build_plan(local_state(), cloud_state(), CW)
        gautham = [s for s in plan["students_insert"] if s["name"] == "Gautham"][0]
        self.assertEqual(gautham["cloud_id"], "2")
        self.assertTrue(any(l["local_id"] == "2" and l["other_cloud_id"] == "02" for l in plan["student_lookalikes"]))
        row18 = [a for a in plan["attendance_ready"] if a["event_id"] == "e18"][0]
        self.assertEqual(row18["cloud_student"], "2")

    def test_wrong_mapping_to_another_person_is_blocked(self):
        bad = IdCrosswalk(students={"1": "01", "2": "02"}, buses={"BUS01": "Bus01"})
        plan = mig.build_plan(local_state(), cloud_state(), bad)
        self.assertEqual([s["local_id"] for s in plan["students_blocked"]], ["2"])
        e18 = [a for a in plan["attendance_blocked"] if a["event_id"] == "e18"]
        self.assertEqual(len(e18), 1)
        self.assertIn("blocked", e18[0]["reason"])

    def test_unmapped_case_mismatch_would_be_a_new_bus(self):
        plan = mig.build_plan(local_state(), cloud_state(), IdCrosswalk())
        self.assertIn("BUS01", [b["cloud_id"] for b in plan["buses_insert"]])  # shows why crosswalk is needed

    def test_already_uploaded_event_is_not_reuploaded(self):
        cloud = cloud_state()
        cloud["attendance"].append({"event_id": "e16", "student_id": "01", "attendance_date": "2026-10-08",
                                    "attendance_time": "12:22:58", "bus_id": "Bus01"})
        plan = mig.build_plan(local_state(), cloud, CW)
        self.assertEqual([a["event_id"] for a in plan["attendance_already_in_cloud"]], ["e16"])
        self.assertEqual(len(plan["attendance_ready"]), 11)

    def test_cloud_unknown_still_produces_a_plan(self):
        plan = mig.build_plan(local_state(), None, CW)
        self.assertFalse(plan["cloud_known"])
        self.assertEqual(len(plan["attendance_ready"]), 13)


class TestSafety(unittest.TestCase):
    def test_default_mode_never_writes(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        import sqlite3
        c = sqlite3.connect(path)
        c.executescript("""
            CREATE TABLE buses(bus_id TEXT PRIMARY KEY, bus_name TEXT, is_active INTEGER, created_at TEXT);
            CREATE TABLE students(student_id TEXT PRIMARY KEY, name TEXT, class_name TEXT, bus_id TEXT,
                                  face_embedding BLOB, is_active INTEGER, created_at TEXT, updated_at TEXT);
            CREATE TABLE attendance(attendance_id INTEGER PRIMARY KEY, event_id TEXT, student_id TEXT,
                attendance_date TEXT, attendance_time TEXT, bus_id TEXT, status TEXT, device_id TEXT,
                sync_status TEXT, synced_at TEXT, created_at TEXT);
        """)
        c.commit(); c.close()
        try:
            with patch.object(mig, "run_write") as rw, patch.object(mig, "SupabaseService") as svc:
                svc.return_value.is_configured.return_value = False
                svc.return_value.crosswalk = CW
                mig.run_migration(db_path=path, dry_run=True)
                rw.assert_not_called()
        finally:
            os.remove(path)

    def test_local_read_excludes_embeddings(self):
        import inspect
        src = inspect.getsource(mig.read_local)
        self.assertNotIn("SELECT *", src)
        self.assertNotIn("face_embedding", src.replace("NOT read", ""))

    def test_rollback_deletes_only_manifest_keys(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            json.dump({"created": {"attendance": ["e16"], "students": ["3"], "buses": ["2241"]}}, f)
        svc = MagicMock()
        try:
            mig.run_rollback(path, svc)
        finally:
            os.remove(path)
        deleted = [(c.args[0]) for c in svc.client.table.call_args_list]
        self.assertEqual(deleted, ["attendance", "students", "buses"])  # dependency-safe order
        eq_args = [c.args for c in svc.client.table.return_value.delete.return_value.eq.call_args_list]
        self.assertEqual(eq_args, [("event_id", "e16"), ("student_id", "3"), ("bus_id", "2241")])


if __name__ == "__main__":
    unittest.main()
