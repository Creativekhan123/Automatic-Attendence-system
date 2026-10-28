"""Fleet Device Database Cache Reset & Cloud Re-sync Utility.

Allows administrators on Raspberry Pi / Bus hardware to:
1. Purge obsolete or deleted students and face embeddings from local SQLite cache.
2. Optionally clear local attendance event logs.
3. Automatically test cloud connectivity and immediately fetch fresh roster from Supabase.
"""

import os
import sys
import argparse
import logging
from typing import Optional, Dict, Any, List

# Ensure project root is in sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fleet_system.device_app.local_db import DeviceDatabase
from fleet_system.shared.cloud_client import FleetCloudClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reset_device_db")

DEFAULT_DEVICE_DB = os.path.join(_ROOT, "fleet_system", "device_app", "data", "device.db")


def reset_and_resync(
    db_path: str = DEFAULT_DEVICE_DB,
    bus_id: Optional[str] = None,
    include_attendance: bool = False,
    factory_reset: bool = False,
    do_resync: bool = True,
    auto_confirm: bool = False
) -> bool:
    print("\n" + "=" * 68)
    print("   FLEET ATTENDANCE DEVICE - CACHE PURGE & CLOUD RE-SYNC TOOL   ")
    print("=" * 68)
    print(f"Target Database : {db_path}")

    if not os.path.exists(db_path):
        print(f"[ERROR] Database file not found at: {db_path}")
        return False

    db = DeviceDatabase(db_path=db_path)
    cur_bus = bus_id or db.get_config("bus_id", "Bus01")
    print(f"Assigned Bus ID : {cur_bus}")

    # Inspect current status
    active_students = db.get_active_students_for_bus(bus_id=None)
    stats = db.get_stats_for_today(bus_id=cur_bus)

    print(f"Current Local Students   : {len(active_students)}")
    print(f"Today's Local Attendance : {stats['total_present']} marked")
    print("-----------------------------------------------------------------")

    if not auto_confirm:
        prompt = "Purge local student roster cache and refresh from Supabase? [y/N]: "
        try:
            choice = input(prompt).strip().lower()
            if choice not in ("y", "yes"):
                print("[CANCELLED] No changes made to local database.")
                return False
        except (KeyboardInterrupt, EOFError):
            print("\n[CANCELLED] Operation aborted.")
            return False

    # 1. Purge student roster cache
    deleted_students = db.clear_students_cache(bus_id=None if factory_reset else cur_bus)
    print(f"[OK] Purged {deleted_students} cached student(s) from local database.")

    # 2. Optionally purge local attendance
    if include_attendance or factory_reset:
        del_att = db.clear_all_attendance(bus_id=None if factory_reset else cur_bus)
        print(f"[OK] Purged {del_att} local attendance record(s).")

    # 3. Optionally factory reset device configuration
    if factory_reset:
        with db._get_connection() as conn:
            conn.execute("DELETE FROM device_config;")
            conn.commit()
        print("[OK] Device configuration table cleared (Factory Reset).")

    # 4. Fresh cloud pull from Supabase
    if do_resync:
        print("\nConnecting to Supabase Cloud...")
        cloud = FleetCloudClient()
        if not cloud.is_configured():
            print("[WARN] Supabase credentials not configured in environment or .env.")
            print("[INFO] Local cache cleared. Once configured, DeviceApp will auto-download.")
            return True

        conn_ok, msg = cloud.test_connection()
        if not conn_ok:
            print(f"[WARN] Cannot reach Supabase Cloud: {msg}")
            print("[INFO] Local cache cleared. Device will auto-download as soon as it gets internet.")
            return True

        print(f"[OK] Supabase connected successfully. Fetching fresh roster for {cur_bus}...")
        ok, cloud_students = cloud.get_students_with_status(bus_id=cur_bus, active_only=False)
        if not ok:
            print("[ERROR] Failed to query students table from Supabase.")
            return False

        active_sids = [str(s["student_id"]).strip() for s in cloud_students if s.get("is_active", True)]
        print(f"[INFO] Cloud returned {len(cloud_students)} total student(s) ({len(active_sids)} active).")

        cloud_biometrics: Dict[str, bytes] = {}
        if active_sids:
            print(f"Downloading 512-D face biometrics for {len(active_sids)} student(s)...")
            cloud_biometrics = cloud.get_biometrics_for_students(active_sids)
            print(f"[OK] Received {len(cloud_biometrics)} face biometrics vectors.")

        synced_count = db.sync_roster_cache(
            cloud_students=cloud_students,
            cloud_biometrics=cloud_biometrics,
            bus_id=cur_bus
        )
        print(f"[SUCCESS] Local database re-synced! Total active students ready: {synced_count}")

    print("=================================================================\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Fleet Device Database Cache Reset & Cloud Re-sync")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DEVICE_DB, help="Path to local device SQLite DB")
    parser.add_argument("--bus-id", type=str, default=None, help="Target Bus ID (defaults to saved config)")
    parser.add_argument("--include-attendance", action="store_true", help="Also clear local attendance records")
    parser.add_argument("--factory-reset", action="store_true", help="Factory reset (clears config + attendance + students)")
    parser.add_argument("--no-resync", action="store_true", help="Only clear local DB without fetching from Supabase")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation prompt")
    args = parser.parse_args()

    success = reset_and_resync(
        db_path=args.db_path,
        bus_id=args.bus_id,
        include_attendance=args.include_attendance,
        factory_reset=args.factory_reset,
        do_resync=not args.no_resync,
        auto_confirm=args.yes
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
