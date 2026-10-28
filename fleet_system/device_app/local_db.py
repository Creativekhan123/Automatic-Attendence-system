"""Device-side SQLite Database Layer for Fleet Attendance System.

Maintains local offline roster with face embeddings and local attendance records.
Enforces single-daily attendance rule (UNIQUE(student_id, attendance_date, bus_id)).
"""
import os
import sqlite3
import uuid
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


class DeviceDatabase:
    """Manages local SQLite database for attendance device."""

    def __init__(self, db_path: str = "fleet_system/device_app/data/device.db") -> None:
        self.db_path = db_path
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn

    def _init_db(self) -> None:
        """Create tables if not existing."""
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            cursor = conn.cursor()
            # 1. Students roster cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    face_embedding BLOB,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
            """)

            # 2. Local Attendance records
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    student_id TEXT NOT NULL,
                    attendance_date TEXT NOT NULL,
                    attendance_time TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Present',
                    device_id TEXT NOT NULL,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    synced_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (student_id) REFERENCES students(student_id),
                    UNIQUE (student_id, attendance_date, bus_id)
                )
            """)

            # 3. Local Hardware Device & Bus Configuration
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_date_bus ON attendance (attendance_date, bus_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_sync ON attendance (sync_status)")
            conn.commit()

    # =========================================================================
    # DEVICE CONFIGURATION (BUS ID & DEVICE ID)
    # =========================================================================

    def get_config(self, key: str, default: str = "") -> str:
        """Fetch a persistent configuration string from local database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM device_config WHERE key = ?", (key.strip(),))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_config(self, key: str, value: str) -> None:
        """Store or update a persistent configuration string in local database."""
        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO device_config (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
            """, (key.strip(), value.strip(), now_str))
            conn.commit()


    # =========================================================================
    # ROSTER / STUDENT CACHE METHODS
    # =========================================================================

    def sync_roster_cache(
        self,
        cloud_students: List[Dict[str, Any]],
        cloud_biometrics: Dict[str, bytes],
        bus_id: Optional[str] = None
    ) -> int:
        """Update or insert students and embeddings from cloud, and purge deleted/reassigned ones.

        Args:
            cloud_students: List of student records fetched from Supabase.
            cloud_biometrics: Dict mapping student_id to face embedding bytes.
            bus_id: Current bus ID for roster reconciliation.

        Returns:
            Count of active students with valid embeddings.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            active_cloud_sids = set()

            for s in cloud_students:
                sid = str(s["student_id"]).strip()
                name = str(s.get("name", "")).strip()
                class_name = str(s.get("class_name", "")).strip()
                s_bus = str(s.get("bus_id", "")).strip()
                is_active = 1 if s.get("is_active", True) else 0
                now_str = datetime.now().isoformat()

                if is_active:
                    active_cloud_sids.add(sid)

                emb = cloud_biometrics.get(sid)

                if emb is not None:
                    cursor.execute("""
                        INSERT INTO students (student_id, name, class_name, bus_id, face_embedding, is_active, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(student_id) DO UPDATE SET
                            name=excluded.name,
                            class_name=excluded.class_name,
                            bus_id=excluded.bus_id,
                            face_embedding=excluded.face_embedding,
                            is_active=excluded.is_active,
                            updated_at=excluded.updated_at
                    """, (sid, name, class_name, s_bus, emb, is_active, now_str))
                else:
                    # Update metadata only, preserve existing embedding if not provided
                    cursor.execute("""
                        INSERT INTO students (student_id, name, class_name, bus_id, is_active, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(student_id) DO UPDATE SET
                            name=excluded.name,
                            class_name=excluded.class_name,
                            bus_id=excluded.bus_id,
                            is_active=excluded.is_active,
                            updated_at=excluded.updated_at
                    """, (sid, name, class_name, s_bus, is_active, now_str))

            # Reconcile deletions & reassignments for this bus:
            # Purge any local student assigned to this bus who is no longer active in the cloud
            if bus_id:
                clean_bus = bus_id.strip()
                cursor.execute("SELECT student_id FROM students WHERE bus_id = ?", (clean_bus,))
                local_sids = {str(row["student_id"]).strip() for row in cursor.fetchall()}
                removed_sids = local_sids - active_cloud_sids
                if removed_sids:
                    placeholders = ",".join("?" for _ in removed_sids)
                    params = [clean_bus] + list(removed_sids)
                    cursor.execute(f"DELETE FROM students WHERE bus_id = ? AND student_id IN ({placeholders})", params)
                    logger.info(f"Reconciled roster: purged {len(removed_sids)} deleted/reassigned student(s) locally for {clean_bus}: {list(removed_sids)}")

            conn.commit()

        return len(self.get_active_students_for_bus(bus_id=bus_id))

    def clear_students_cache(self, bus_id: Optional[str] = None) -> int:
        """Clear cached students and face embeddings. Returns number of rows deleted."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if bus_id:
                cursor.execute("DELETE FROM students WHERE bus_id = ?", (bus_id.strip(),))
            else:
                cursor.execute("DELETE FROM students")
            conn.commit()
            deleted_count = cursor.rowcount
            logger.info(f"Cleared students cache: {deleted_count} record(s) removed (bus: {bus_id or 'ALL'}).")
            return deleted_count

    def clear_all_attendance(self, bus_id: Optional[str] = None) -> int:
        """Clear local attendance records. Returns count of rows deleted."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if bus_id:
                cursor.execute("DELETE FROM attendance WHERE bus_id = ?", (bus_id.strip(),))
            else:
                cursor.execute("DELETE FROM attendance")
            conn.commit()
            deleted_count = cursor.rowcount
            logger.info(f"Cleared attendance records: {deleted_count} record(s) removed (bus: {bus_id or 'ALL'}).")
            return deleted_count

    def delete_student(self, student_id: str) -> bool:
        """Permanently delete a student and their face embedding locally."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM students WHERE student_id = ?", (student_id.strip(),))
            conn.commit()
            return cursor.rowcount > 0


    def get_active_students_for_bus(self, bus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return list of active students with valid embeddings. Filter by bus if given."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if bus_id:
                cursor.execute("""
                    SELECT * FROM students 
                    WHERE is_active = 1 AND bus_id = ? AND face_embedding IS NOT NULL AND length(face_embedding) > 0
                """, (bus_id.strip(),))
            else:
                cursor.execute("""
                    SELECT * FROM students 
                    WHERE is_active = 1 AND face_embedding IS NOT NULL AND length(face_embedding) > 0
                """)
            rows = cursor.fetchall()

            result = []
            for r in rows:
                item = dict(r)
                blob = item.get("face_embedding")
                if blob:
                    item["face_embedding"] = np.frombuffer(blob, dtype=np.float32)
                result.append(item)
            return result

    def get_missing_biometric_student_ids(self) -> List[str]:
        """Return list of active student IDs that do not have an embedding locally."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT student_id FROM students 
                WHERE is_active = 1 AND (face_embedding IS NULL OR length(face_embedding) = 0)
            """)
            return [r["student_id"] for r in cursor.fetchall()]

    # =========================================================================
    # ATTENDANCE RECORDING & SYNC QUEUE
    # =========================================================================

    def record_attendance(
        self,
        student_id: str,
        bus_id: str,
        device_id: str,
        status: str = "Present",
        attendance_date: Optional[str] = None,
        attendance_time: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Record attendance with duplicate prevention.
        
        Returns:
            Tuple of (is_new_mark: bool, message: str)
        """
        now = datetime.now()
        att_date = attendance_date or now.strftime("%Y-%m-%d")
        att_time = attendance_time or now.strftime("%H:%M:%S")
        event_id = str(uuid.uuid4())

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check duplicate for today on this bus
            cursor.execute("""
                SELECT attendance_id, attendance_time, sync_status 
                FROM attendance
                WHERE student_id = ? AND attendance_date = ? AND bus_id = ?
            """, (student_id, att_date, bus_id))
            existing = cursor.fetchone()

            if existing:
                return False, f"Already marked present today at {existing['attendance_time']}"

            try:
                cursor.execute("""
                    INSERT INTO attendance (
                        event_id, student_id, attendance_date, attendance_time,
                        bus_id, status, device_id, sync_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """, (
                    event_id, student_id, att_date, att_time,
                    bus_id, status.capitalize(), device_id, now.isoformat()
                ))
                conn.commit()
                return True, "Attendance recorded successfully"
            except sqlite3.IntegrityError:
                return False, "Duplicate mark prevented by database constraint"

    def get_pending_attendance(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch pending attendance rows for cloud upload."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM attendance
                WHERE sync_status = 'pending'
                ORDER BY attendance_date ASC, attendance_time ASC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def mark_attendance_synced(self, event_ids: List[str]) -> None:
        """Mark uploaded events as synced."""
        if not event_ids:
            return
        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in event_ids)
            cursor.execute(f"""
                UPDATE attendance
                SET sync_status = 'synced', synced_at = ?
                WHERE event_id IN ({placeholders})
            """, [now_str] + event_ids)
            conn.commit()

    def get_stats_for_today(self, bus_id: str, att_date: Optional[str] = None) -> Dict[str, int]:
        """Return counts of total assigned, marked present today, and pending sync."""
        date_str = att_date or datetime.now().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Total assigned to this bus
            cursor.execute("SELECT COUNT(*) FROM students WHERE bus_id = ? AND is_active = 1", (bus_id,))
            total_assigned = cursor.fetchone()[0]

            # Present on this bus today
            cursor.execute("""
                SELECT COUNT(*) FROM attendance 
                WHERE bus_id = ? AND attendance_date = ?
            """, (bus_id, date_str))
            total_present = cursor.fetchone()[0]

            # Pending sync queue
            cursor.execute("SELECT COUNT(*) FROM attendance WHERE sync_status = 'pending'")
            pending_sync = cursor.fetchone()[0]

            return {
                "total_assigned": total_assigned,
                "total_present": total_present,
                "pending_sync": pending_sync
            }

    def get_present_student_ids(self, bus_id: str, att_date: Optional[str] = None) -> List[str]:
        """Fetch list of student_ids already marked present on this bus today."""
        date_str = att_date or datetime.now().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT student_id FROM attendance 
                WHERE bus_id = ? AND attendance_date = ?
            """, (bus_id, date_str))
            return [r[0] for r in cursor.fetchall()]
