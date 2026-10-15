"""Safe Local SQLite Database Reset Utility for Controlled Fresh Starts.

Default mode is a preview (read-only): reports exact counts of records that will
be removed. Nothing is modified unless --confirm-reset is explicitly passed.

When --confirm-reset is passed:
1. Creates a verified, timestamped SQLite backup in backups/ with integrity check.
2. Clears all test records in atomic dependency order:
   - attendance (and outbox queue)
   - attendance_duplicates_archive
   - students (and local face embeddings)
   - buses
3. Resets autoincrement sequences.
4. Preserves all tables, constraints, column defaults, and indexes.
"""
import os
import sys
import argparse
import sqlite3
import datetime
from typing import Dict, Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import DEFAULT_DB_PATH


def backup_database(db_path: str) -> str:
    """Create a verified, timestamped backup using SQLite's backup API."""
    backup_dir = os.path.join(_PROJECT_ROOT, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"pre_reset_backup_api_{ts}.db")
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


def inspect_counts(db_path: str) -> Dict[str, int]:
    """Inspect row counts for all application tables."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    counts = {}
    try:
        tables = ["students", "buses", "attendance", "attendance_duplicates_archive"]
        for t in tables:
            try:
                c = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                counts[t] = c
            except sqlite3.OperationalError:
                counts[t] = 0
    finally:
        conn.close()
    return counts


def reset_local_db(db_path: str, confirm_reset: bool = False) -> None:
    print("=================================================================")
    print("     AUTOMATIC ATTENDANCE SYSTEM - LOCAL DATABASE RESET          ")
    print("=================================================================")
    print(f"Target Database : {db_path}")
    print(f"Mode            : {'RESET (destructive write)' if confirm_reset else 'PREVIEW (read-only)'}")
    print("-----------------------------------------------------------------")

    if not os.path.exists(db_path):
        print(f"[ERROR] Database file not found at {db_path}")
        sys.exit(1)

    counts = inspect_counts(db_path)
    print("Current local record counts:")
    for tbl, count in counts.items():
        print(f"  - {tbl:30s}: {count} records")
    print("-----------------------------------------------------------------")

    if not confirm_reset:
        print("[INFO] Preview mode. No records were deleted.")
        print("[INFO] To perform the reset, run with --confirm-reset.")
        return

    # Create backup first
    backup_file = backup_database(db_path)

    # Perform atomic reset
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM attendance;")
            cursor.execute("DELETE FROM attendance_duplicates_archive;")
            cursor.execute("DELETE FROM students;")
            cursor.execute("DELETE FROM buses;")
            try:
                cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('attendance', 'attendance_duplicates_archive');")
            except sqlite3.OperationalError:
                pass
        conn.execute("VACUUM;")
    finally:
        conn.close()

    # Verify post-reset health
    verify_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ok = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"Database integrity check failed post-reset: {ok}")
        post_counts = inspect_counts(db_path)
    finally:
        verify_conn.close()

    print("[OK] Local database successfully reset to clean state.")
    print("Post-reset record counts:")
    for tbl, count in post_counts.items():
        print(f"  - {tbl:30s}: {count} records")
    print(f"[OK] Schemas, indexes, and constraints preserved. Backup stored at {backup_file}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Safely reset local attendance database for fresh start")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--confirm-reset", action="store_true", help="Execute the deletion (requires explicit confirmation)")
    args = parser.parse_args()
    reset_local_db(db_path=args.db_path, confirm_reset=args.confirm_reset)
