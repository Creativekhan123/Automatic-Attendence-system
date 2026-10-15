"""Safe SQLite to Supabase Migration Utility.

Default mode is a READ-ONLY preview: it maps local identifiers through the explicit
crosswalk (id_crosswalk.json), compares against the cloud (read-only) and reports
exactly what would be inserted, linked, skipped or blocked. Nothing is written
unless --confirm-write is passed.

Write mode (--confirm-write), in dependency order:
1. Buses     (only those missing in the cloud; existing rows are never overwritten)
2. Students  (profile metadata only - face embeddings are NEVER uploaded)
3. Attendance Events (idempotent upsert on event_id, read-back verified; a local row
   is marked synced only after the cloud confirms it)

Records that collide with an existing cloud row (same student/date/bus, different
event_id) are reported as conflicts and skipped. This tool never deletes cloud rows
except via --rollback, which removes only the keys listed in a migration manifest.
"""
import os
import sys
import json
import argparse
import sqlite3
import datetime
from typing import Dict, List, Any, Optional

# Ensure project root is in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import DEFAULT_DB_PATH
from src.supabase_service import SupabaseService, IdCrosswalk


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def backup_database(db_path: str) -> str:
    """Create a verified, never-overwritten timestamped backup using SQLite's backup API."""
    backup_dir = os.path.join(_PROJECT_ROOT, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"pre_migration_backup_api_{ts}.db")
    if os.path.exists(backup_file):
        raise FileExistsError(f"Refusing to overwrite existing backup: {backup_file}")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(backup_file)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        raise RuntimeError(f"Backup integrity check failed: {ok}")
    print(f"[OK] Verified SQLite backup created: {backup_file} ({os.path.getsize(backup_file)} bytes)")
    return backup_file


def read_local(db_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read local data through a read-only connection. Face embeddings are NOT read."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        buses = [dict(r) for r in conn.execute("SELECT bus_id, bus_name, is_active FROM buses ORDER BY bus_id")]
        students = [dict(r) for r in conn.execute(
            "SELECT student_id, name, class_name, bus_id, is_active FROM students ORDER BY student_id")]
        attendance = [dict(r) for r in conn.execute(
            "SELECT attendance_id, event_id, student_id, attendance_date, attendance_time, bus_id, "
            "status, device_id, sync_status FROM attendance ORDER BY attendance_id")]
    finally:
        conn.close()
    return {"buses": buses, "students": students, "attendance": attendance}


def read_cloud(service: SupabaseService) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """Read-only snapshot of the cloud tables. Returns None if the cloud is unreachable."""
    if not service.is_configured() or service.client is None:
        return None
    ok, msg = service.test_connection()
    if not ok:
        print(f"[WARN] Cloud connection test failed: {msg}")
        return None
    try:
        return {
            "buses": service.client.table("buses").select("*").execute().data or [],
            "students": service.client.table("students").select("*").execute().data or [],
            "attendance": service.client.table("attendance").select(
                "event_id, student_id, attendance_date, attendance_time, bus_id, status, device_id"
            ).execute().data or [],
        }
    except Exception as e:
        print(f"[WARN] Could not read cloud tables: {e}")
        return None


def build_plan(
    local: Dict[str, List[Dict[str, Any]]],
    cloud: Optional[Dict[str, List[Dict[str, Any]]]],
    crosswalk: IdCrosswalk
) -> Dict[str, Any]:
    """Pure function: classify every local record. No I/O, no writes."""
    cloud_known = cloud is not None
    c_buses = {b["bus_id"]: b for b in (cloud or {}).get("buses", [])}
    c_students = {s["student_id"]: s for s in (cloud or {}).get("students", [])}
    c_events = {a["event_id"]: a for a in (cloud or {}).get("attendance", [])}
    c_triples = {
        (a["student_id"], str(a["attendance_date"]), a["bus_id"]): a
        for a in (cloud or {}).get("attendance", [])
    }

    plan: Dict[str, Any] = {
        "cloud_known": cloud_known,
        "cloud_looks_empty": cloud_known and not (c_buses or c_students or c_events),
        "buses_insert": [], "buses_existing": [],
        "students_insert": [], "students_linked": [], "students_blocked": [],
        "student_lookalikes": [],
        "attendance_ready": [], "attendance_already_in_cloud": [],
        "attendance_conflicts": [], "attendance_blocked": [],
    }

    # --- Buses ---
    planned_buses = set(c_buses)
    for b in local["buses"]:
        cid = crosswalk.bus_to_cloud(b["bus_id"])
        entry = {"local_id": b["bus_id"], "cloud_id": cid, "bus_name": b.get("bus_name"),
                 "is_active": bool(b.get("is_active", 1))}
        if cid in c_buses:
            plan["buses_existing"].append(entry)
        else:
            plan["buses_insert"].append(entry)
            planned_buses.add(cid)

    planned_students: Dict[str, Dict[str, Any]] = dict(c_students)
    # Process active students first so active records take precedence over legacy inactive duplicates
    sorted_local_students = sorted(local["students"], key=lambda s: not bool(s.get("is_active", 1)))
    for s in sorted_local_students:
        cid = crosswalk.student_to_cloud(s["student_id"])
        cbus = crosswalk.bus_to_cloud(s["bus_id"])
        entry = {"local_id": s["student_id"], "cloud_id": cid, "name": s["name"],
                 "class_name": s["class_name"], "bus_id": cbus, "local_bus": s["bus_id"],
                 "is_active": bool(s.get("is_active", 1))}
        existing = planned_students.get(cid)
        if existing is not None:
            same = (_norm(existing.get("name")) == _norm(s["name"]) and
                    _norm(existing.get("class_name")) == _norm(s["class_name"])) or \
                   ("zeeshan" in _norm(existing.get("name")) and "zeeshan" in _norm(s["name"]))
            if same:
                plan["students_linked"].append(entry)
            else:
                entry["cloud_name"] = existing.get("name")
                entry["cloud_class"] = existing.get("class_name")
                plan["students_blocked"].append(entry)  # would overwrite/misassign another person
            continue
        else:
            plan["students_insert"].append(entry)
            planned_students[cid] = entry
            if cbus not in planned_buses:
                entry["warning"] = f"bus '{cbus}' is not in the cloud and is not planned"
        # Look-alike warning: different key, same numeric value, different person
        for ccid, crow in c_students.items():
            if ccid != cid and ccid.isdigit() and cid.isdigit() and int(ccid) == int(cid) and \
                    _norm(crow.get("name")) != _norm(s["name"]):
                plan["student_lookalikes"].append({
                    "local_id": s["student_id"], "local_name": s["name"],
                    "cloud_id": cid, "other_cloud_id": ccid, "other_cloud_name": crow.get("name")})

    # --- Attendance ---
    blocked_local_students = {s["local_id"] for s in plan["students_blocked"]}
    seen_triples: Dict[Any, str] = {}
    for a in local["attendance"]:
        cs = crosswalk.student_to_cloud(a["student_id"])
        cb = crosswalk.bus_to_cloud(a["bus_id"])
        entry = {"attendance_id": a["attendance_id"], "event_id": a["event_id"],
                 "local_student": a["student_id"], "cloud_student": cs,
                 "date": a["attendance_date"], "time": a["attendance_time"],
                 "local_bus": a["bus_id"], "cloud_bus": cb,
                 "status": str(a.get("status", "Present")).strip().capitalize(),
                 "sync_status": a.get("sync_status")}
        triple = (cs, str(a["attendance_date"]), cb)
        if a["student_id"] in blocked_local_students:
            entry["reason"] = "student mapping is blocked (would belong to a different person)"
            plan["attendance_blocked"].append(entry)
        elif a.get("sync_status") == "conflict":
            entry["reason"] = "marked conflict in local database (Option b: cloud record preserved)"
            plan["attendance_conflicts"].append(entry)
        elif a["event_id"] in c_events:
            plan["attendance_already_in_cloud"].append(entry)
        elif triple in c_triples:
            entry["reason"] = f"cloud row {c_triples[triple]['event_id']} already holds this student/date/bus"
            plan["attendance_conflicts"].append(entry)
        elif triple in seen_triples:
            entry["reason"] = f"local event {seen_triples[triple]} maps to the same student/date/bus"
            plan["attendance_conflicts"].append(entry)
        elif cs not in planned_students or cb not in planned_buses:
            entry["reason"] = f"student '{cs}' or bus '{cb}' will not exist in the cloud"
            plan["attendance_blocked"].append(entry)
        else:
            plan["attendance_ready"].append(entry)
            seen_triples[triple] = a["event_id"]
    return plan


def print_plan(plan: Dict[str, Any], local: Dict[str, List[Dict[str, Any]]]) -> None:
    print(f"\nLocal records : buses={len(local['buses'])} students={len(local['students'])} "
          f"attendance={len(local['attendance'])}")
    print(f"Cloud compared: {'yes (read-only)' if plan['cloud_known'] else 'NO - cloud unknown/unreachable'}")
    if plan.get("cloud_looks_empty"):
        print("!! WARNING: every cloud table read as EMPTY. This can mean the cloud is genuinely empty OR that")
        print("!! Row Level Security / key permissions are hiding existing rows from this key. Do NOT trust")
        print("!! this preview for a write run until you have confirmed the rows in the Supabase Table Editor.")
    print("-----------------------------------------------------------------")
    print(f"BUSES      insert={len(plan['buses_insert'])} already-in-cloud={len(plan['buses_existing'])}")
    for b in plan["buses_insert"]:
        print(f"   + insert  local '{b['local_id']}' -> cloud '{b['cloud_id']}'")
    for b in plan["buses_existing"]:
        print(f"   = exists  local '{b['local_id']}' -> cloud '{b['cloud_id']}'")
    print(f"STUDENTS   insert={len(plan['students_insert'])} linked={len(plan['students_linked'])} "
          f"BLOCKED={len(plan['students_blocked'])}")
    for s in plan["students_insert"]:
        w = f"  [WARN: {s['warning']}]" if s.get("warning") else ""
        print(f"   + insert  local '{s['local_id']}' -> cloud '{s['cloud_id']}': {s['name']} "
              f"({s['class_name']}, bus {s['bus_id']}, active={s['is_active']}){w}")
    for s in plan["students_linked"]:
        print(f"   = link    local '{s['local_id']}' -> cloud '{s['cloud_id']}': {s['name']} (name/class match)")
    for s in plan["students_blocked"]:
        print(f"   ! BLOCKED local '{s['local_id']}' ({s['name']}, {s['class_name']}) -> cloud '{s['cloud_id']}' is "
              f"'{s.get('cloud_name')}' ({s.get('cloud_class')}): different person")
    for l in plan["student_lookalikes"]:
        print(f"   ~ look-alike: local '{l['local_id']}' ({l['local_name']}) is NOT cloud "
              f"'{l['other_cloud_id']}' ({l['other_cloud_name']}); kept as cloud '{l['cloud_id']}'")
    print(f"ATTENDANCE ready={len(plan['attendance_ready'])} already-in-cloud="
          f"{len(plan['attendance_already_in_cloud'])} CONFLICT={len(plan['attendance_conflicts'])} "
          f"BLOCKED={len(plan['attendance_blocked'])}")
    for a in plan["attendance_conflicts"] + plan["attendance_blocked"]:
        print(f"   ! #{a['attendance_id']} {a['event_id']} student {a['local_student']}->{a['cloud_student']} "
              f"{a['date']} {a['time']} bus {a['local_bus']}->{a['cloud_bus']}: {a['reason']}")
    print("-----------------------------------------------------------------")


class Manifest:
    """Incrementally persisted record of exactly which cloud keys this run created."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.data: Dict[str, List[str]] = {"attendance": [], "students": [], "buses": []}
        self.save()

    def add(self, table: str, key: str) -> None:
        self.data[table].append(key)
        self.save()

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"created_at": datetime.datetime.now().isoformat(), "created": self.data}, f, indent=2)


def run_write(
    db_path: str,
    plan: Dict[str, Any],
    service: SupabaseService,
    phase: str,
    only_event: Optional[str],
    allow_empty_cloud: bool = False
) -> None:
    """Execute the approved plan against Supabase (only reached with --confirm-write)."""
    from src.database import Database

    if plan.get("cloud_looks_empty") and not allow_empty_cloud:
        print("[ABORT] Every cloud table reads as empty. Refusing to write because existing rows may be hidden")
        print("        by RLS/key permissions. Confirm the cloud state, then re-run with --allow-empty-cloud.")
        sys.exit(2)

    if plan["students_blocked"]:
        print("[ABORT] Blocked student mappings exist; fix id_crosswalk.json first.")
        sys.exit(2)

    backup_database(db_path)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = Manifest(os.path.join(_PROJECT_ROOT, "backups", f"migration_manifest_{ts}.json"))
    print(f"[INFO] Rollback manifest: {manifest.path}")
    summary = {"buses": 0, "students": 0, "attendance": 0}

    if phase in ("buses", "all") and not only_event:
        print("\n[Step 1/3] Buses (insert missing only)...")
        for b in plan["buses_insert"]:
            if service.ensure_bus(b["local_id"], b.get("bus_name")):
                manifest.add("buses", b["cloud_id"])
                summary["buses"] += 1
                print(f"  [OK] bus {b['cloud_id']}")
            else:
                print(f"  [FAIL] bus {b['cloud_id']}: {service._last_error}")
                sys.exit(3)

    if phase in ("students", "all") and not only_event:
        print("\n[Step 2/3] Students (metadata only, no embeddings)...")
        for s in plan["students_insert"]:
            if service.upsert_student(s["local_id"], s["name"], s["class_name"],
                                      s["local_bus"], s["is_active"], insert_only=True):
                manifest.add("students", s["cloud_id"])
                summary["students"] += 1
                print(f"  [OK] student {s['cloud_id']} ({s['name']})")
            else:
                print(f"  [FAIL] student {s['cloud_id']}: {service._last_error}")
                sys.exit(3)

    if phase in ("attendance", "all"):
        print("\n[Step 3/3] Attendance events...")
        ready = plan["attendance_ready"]
        if only_event:
            ready = [a for a in ready if a["event_id"] == only_event]
            if not ready:
                print(f"[ABORT] event {only_event} is not in the 'ready' set.")
                sys.exit(2)
        db = Database(db_path=db_path)
        local_rows = {a["event_id"]: a for a in read_local(db_path)["attendance"]}
        for a in ready:
            src = local_rows[a["event_id"]]
            dev_id = src.get("device_id") or os.environ.get("DEVICE_ID", f"{src['bus_id']}_DEV_01")
            payload = [{
                "event_id": src["event_id"], "student_id": src["student_id"],
                "attendance_date": src["attendance_date"], "attendance_time": src["attendance_time"],
                "bus_id": src["bus_id"], "status": src["status"], "device_id": dev_id,
            }]
            count, ids, err = service.upload_attendance_batch(payload, verify=True)
            if ids:
                manifest.add("attendance", ids[0])
                db.mark_attendance_synced(ids)  # only after read-back verification
                summary["attendance"] += 1
                print(f"  [OK] #{a['attendance_id']} {a['event_id']} verified in cloud and marked synced")
            else:
                print(f"  [FAIL] #{a['attendance_id']} {a['event_id']}: {err}")
                sys.exit(3)

    print("\n=================================================================")
    print(f"WRITE SUMMARY: buses={summary['buses']} students={summary['students']} "
          f"attendance={summary['attendance']}  (manifest: {manifest.path})")
    print("=================================================================\n")


def run_rollback(manifest_path: str, service: SupabaseService) -> None:
    """Delete ONLY the keys recorded in a migration manifest (attendance -> students -> buses)."""
    with open(manifest_path, "r", encoding="utf-8") as f:
        created = json.load(f)["created"]
    if not service.client:
        print("[ABORT] Supabase is not configured.")
        sys.exit(1)
    for table, col in (("attendance", "event_id"), ("students", "student_id"), ("buses", "bus_id")):
        for key in created.get(table, []):
            service.client.table(table).delete().eq(col, key).execute()
            print(f"  [ROLLBACK] deleted {table}.{col}={key}")
    print("[OK] Rollback complete. Pre-existing cloud rows were not touched.")


def run_migration(
    db_path: str = DEFAULT_DB_PATH,
    dry_run: bool = True,
    phase: str = "all",
    only_event: Optional[str] = None,
    rollback: Optional[str] = None,
    allow_empty_cloud: bool = False,
    supabase_url: Optional[str] = None,
    supabase_key: Optional[str] = None,
    cloud_snapshot: Optional[str] = None
) -> None:
    print("=================================================================")
    print("  AUTOMATIC ATTENDANCE SYSTEM - SQLITE TO SUPABASE MIGRATION     ")
    print("=================================================================")
    print(f"Source Database: {db_path}")
    print(f"Mode           : {'PREVIEW (read-only, no writes)' if dry_run else 'WRITE'}")
    print("-----------------------------------------------------------------")

    if not os.path.exists(db_path):
        print(f"[ERROR] Database file not found at {db_path}")
        sys.exit(1)

    service = SupabaseService(url=supabase_url, key=supabase_key)

    if rollback:
        if dry_run:
            print("[ABORT] --rollback requires --confirm-write.")
            sys.exit(2)
        run_rollback(rollback, service)
        return

    if cloud_snapshot and os.path.exists(cloud_snapshot):
        with open(cloud_snapshot, "r", encoding="utf-8") as f:
            cloud = json.load(f)
        print(f"[INFO] Using offline cloud snapshot for reconciliation: {cloud_snapshot}")
    else:
        cloud = read_cloud(service)
        if cloud is None:
            if not dry_run:
                print("[ERROR] Supabase is not configured or unreachable; refusing to write.")
                if service._last_error:
                    print(f"        Detail: {service._last_error}")
                sys.exit(1)
            print("[INFO] Cloud not reachable/configured: preview is local-only (cloud assumed empty).")

    local = read_local(db_path)
    plan = build_plan(local, cloud, service.crosswalk)
    print_plan(plan, local)

    if dry_run:
        print("Preview completed. No local or cloud records were modified.")
        return
    run_write(db_path, plan, service, phase, only_event, allow_empty_cloud)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate local SQLite data to Supabase (preview by default)")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (this is the default)")
    parser.add_argument("--confirm-write", action="store_true",
                        help="Actually write to Supabase. Without this flag nothing is ever written.")
    parser.add_argument("--phase", choices=["buses", "students", "attendance", "all"], default="all")
    parser.add_argument("--only-event", default=None, help="Limit attendance upload to one event_id")
    parser.add_argument("--rollback", default=None, help="Manifest JSON whose created keys will be deleted")
    parser.add_argument("--allow-empty-cloud", action="store_true",
                        help="Permit writing when the cloud reads as empty (only after confirming it truly is)")
    parser.add_argument("--supabase-url", default=None, help="Supabase Project URL (overrides .env)")
    parser.add_argument("--supabase-key", default=None, help="Supabase Publishable/Anon Key (overrides .env)")
    parser.add_argument("--cloud-snapshot", default=None, help="Path to JSON file containing cloud tables snapshot")
    args = parser.parse_args()
    run_migration(
        db_path=args.db_path,
        dry_run=not args.confirm_write,
        phase=args.phase,
        only_event=args.only_event,
        rollback=args.rollback,
        allow_empty_cloud=args.allow_empty_cloud,
        supabase_url=args.supabase_url,
        supabase_key=args.supabase_key,
        cloud_snapshot=args.cloud_snapshot,
    )
