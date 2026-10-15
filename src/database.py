import sqlite3
import os
import uuid
from typing import List, Dict, Optional, Any
from datetime import datetime
import numpy as np


class Database:
    """Manages local SQLite database operations for student registration, embeddings, and attendance records."""

    def __init__(self, db_path: str = "data/attendance.db") -> None:
        """Initialize the database connection and schema.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        # Ensure parent directory exists
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create and return a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create required tables, indexes, and perform safe non-destructive migrations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 0. Master Buses table (mirrors Supabase buses table for offline validation)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS buses (
                    bus_id TEXT PRIMARY KEY,
                    bus_name TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)

            # 1. Students table (biometrics, profiles, and activation status)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    face_embedding BLOB,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    sync_status TEXT NOT NULL DEFAULT 'synced',
                    synced_at TEXT
                )
            """)

            # 2. Attendance table with event UUID and sync telemetry (UNIQUE per student, date, bus)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    student_id TEXT NOT NULL,
                    attendance_date TEXT NOT NULL,
                    attendance_time TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Present',
                    device_id TEXT,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    synced_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (student_id) REFERENCES students(student_id),
                    UNIQUE (student_id, attendance_date, bus_id)
                )
            """)

            # Ensure duplicate archive table exists for non-destructive consolidation
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attendance_duplicates_archive (
                    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_attendance_id INTEGER,
                    event_id TEXT,
                    student_id TEXT NOT NULL,
                    attendance_date TEXT NOT NULL,
                    attendance_time TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    status TEXT,
                    device_id TEXT,
                    sync_status TEXT,
                    synced_at TEXT,
                    created_at TEXT,
                    session_type TEXT,
                    archived_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    consolidation_reason TEXT
                )
            """)

            # Ensure columns exist on students (safe migration for existing databases)
            cursor.execute("PRAGMA table_info(students)")
            stu_cols = {col["name"] for col in cursor.fetchall()}
            if "is_active" not in stu_cols:
                cursor.execute("ALTER TABLE students ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
            if "updated_at" not in stu_cols:
                cursor.execute("ALTER TABLE students ADD COLUMN updated_at TEXT")
            if "sync_status" not in stu_cols:
                cursor.execute("ALTER TABLE students ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced'")
            if "synced_at" not in stu_cols:
                cursor.execute("ALTER TABLE students ADD COLUMN synced_at TEXT")

            # Ensure columns exist on attendance (safe migration for existing databases)
            cursor.execute("PRAGMA table_info(attendance)")
            att_cols = {col["name"] for col in cursor.fetchall()}
            if "event_id" not in att_cols:
                cursor.execute("ALTER TABLE attendance ADD COLUMN event_id TEXT")
            if "device_id" not in att_cols:
                cursor.execute("ALTER TABLE attendance ADD COLUMN device_id TEXT")
            if "sync_status" not in att_cols:
                cursor.execute("ALTER TABLE attendance ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'pending'")
            if "synced_at" not in att_cols:
                cursor.execute("ALTER TABLE attendance ADD COLUMN synced_at TEXT")

            # Safely consolidate any duplicate attendance records that violate the single-daily-attendance rule
            dup_groups = cursor.execute("""
                SELECT student_id, attendance_date, bus_id, COUNT(*) as cnt
                FROM attendance
                GROUP BY student_id, attendance_date, bus_id
                HAVING COUNT(*) > 1
            """).fetchall()

            for g in dup_groups:
                s_id, a_date, b_id = g["student_id"], g["attendance_date"], g["bus_id"]
                rows = cursor.execute("""
                    SELECT * FROM attendance
                    WHERE student_id = ? AND attendance_date = ? AND bus_id = ?
                    ORDER BY attendance_time ASC, attendance_id ASC
                """, (s_id, a_date, b_id)).fetchall()

                # Keep the first attendance mark of the day, archive subsequent duplicates
                keeper = rows[0]
                for dup in rows[1:]:
                    dup_dict = dict(dup)
                    cursor.execute("""
                        INSERT INTO attendance_duplicates_archive (
                            original_attendance_id, event_id, student_id, attendance_date, attendance_time,
                            bus_id, status, device_id, sync_status, synced_at, created_at, session_type,
                            consolidation_reason
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        dup_dict.get("attendance_id"), dup_dict.get("event_id"), dup_dict["student_id"],
                        dup_dict["attendance_date"], dup_dict["attendance_time"], dup_dict["bus_id"],
                        dup_dict.get("status"), dup_dict.get("device_id"), dup_dict.get("sync_status"),
                        dup_dict.get("synced_at"), dup_dict.get("created_at"), dup_dict.get("session_type"),
                        f"Consolidated into daily attendance record id={keeper['attendance_id']} (single-daily rule)"
                    ))
                    cursor.execute("DELETE FROM attendance WHERE attendance_id = ?", (dup_dict["attendance_id"],))

            # Ensure schema has UNIQUE (student_id, attendance_date, bus_id) and NO session_type
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attendance'")
            att_sql_row = cursor.fetchone()
            table_sql = att_sql_row[0] if att_sql_row and att_sql_row[0] else ""
            if "session_type" in att_cols or "session_type" in table_sql or "UNIQUE (student_id, attendance_date, bus_id, session_type)" in table_sql:
                cursor.execute("PRAGMA foreign_keys = OFF")
                cursor.execute("""
                    CREATE TABLE attendance_clean (
                        attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE,
                        student_id TEXT NOT NULL,
                        attendance_date TEXT NOT NULL,
                        attendance_time TEXT NOT NULL,
                        bus_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'Present',
                        device_id TEXT,
                        sync_status TEXT NOT NULL DEFAULT 'pending',
                        synced_at TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (student_id) REFERENCES students(student_id),
                        UNIQUE (student_id, attendance_date, bus_id)
                    )
                """)
                cursor.execute("""
                    INSERT INTO attendance_clean (
                        attendance_id, event_id, student_id, attendance_date, attendance_time,
                        bus_id, status, device_id, sync_status, synced_at, created_at
                    )
                    SELECT 
                        attendance_id, event_id, student_id, attendance_date, attendance_time,
                        bus_id, status, device_id, sync_status, synced_at, created_at
                    FROM attendance
                """)
                cursor.execute("DROP TABLE attendance")
                cursor.execute("ALTER TABLE attendance_clean RENAME TO attendance")
                cursor.execute("PRAGMA foreign_keys = ON")

            # Backfill any existing attendance records with missing event_id
            cursor.execute("SELECT attendance_id FROM attendance WHERE event_id IS NULL OR event_id = ''")
            for row in cursor.fetchall():
                cursor.execute(
                    "UPDATE attendance SET event_id = ? WHERE attendance_id = ?",
                    (str(uuid.uuid4()), row["attendance_id"])
                )

            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_event_id ON attendance(event_id)")

            # Seed buses table from existing distinct buses in students and attendance
            cursor.execute("SELECT DISTINCT bus_id FROM students WHERE bus_id IS NOT NULL AND bus_id != ''")
            for r in cursor.fetchall():
                b_id = r["bus_id"]
                cursor.execute(
                    "INSERT OR IGNORE INTO buses (bus_id, bus_name, is_active, created_at) VALUES (?, ?, 1, ?)",
                    (b_id, f"Bus {b_id}", datetime.now().isoformat())
                )
            cursor.execute("SELECT DISTINCT bus_id FROM attendance WHERE bus_id IS NOT NULL AND bus_id != ''")
            for r in cursor.fetchall():
                b_id = r["bus_id"]
                cursor.execute(
                    "INSERT OR IGNORE INTO buses (bus_id, bus_name, is_active, created_at) VALUES (?, ?, 1, ?)",
                    (b_id, f"Bus {b_id}", datetime.now().isoformat())
                )

            conn.commit()

    @staticmethod
    def serialize_embedding(embedding: np.ndarray) -> bytes:
        """Serialize a float32 numpy embedding array to raw bytes (BLOB)."""
        arr = np.asarray(embedding, dtype=np.float32)
        return arr.tobytes()

    @staticmethod
    def deserialize_embedding(blob: bytes) -> np.ndarray:
        """Deserialize raw byte BLOB back into float32 numpy embedding array."""
        return np.frombuffer(blob, dtype=np.float32)

    def register_student(
        self,
        student_id: str,
        name: str,
        class_name: str,
        bus_id: str,
        face_embedding: np.ndarray,
        is_active: bool = True,
        sync_status: str = "pending"
    ) -> bool:
        """Insert or replace student registration record with face embedding.
        
        New or updated registrations are tagged with sync_status='pending' so
        the background SyncWorker can push student metadata to the cloud.
        """
        embedding_blob = self.serialize_embedding(face_embedding)
        now_str = datetime.now().isoformat()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Ensure bus exists in local buses table
                cursor.execute(
                    "INSERT OR IGNORE INTO buses (bus_id, bus_name, is_active, created_at) VALUES (?, ?, 1, ?)",
                    (bus_id, f"Bus {bus_id}", now_str)
                )
                cursor.execute("""
                    INSERT OR REPLACE INTO students 
                    (student_id, name, class_name, bus_id, face_embedding, is_active, created_at, updated_at, sync_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (student_id, name, class_name, bus_id, embedding_blob, int(is_active), now_str, now_str, sync_status))
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Database error during registration: {e}")
            return False

    def get_all_students(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Retrieve all registered students with deserialized face embeddings."""
        students = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT student_id, name, class_name, bus_id, face_embedding, is_active, created_at FROM students"
                if active_only:
                    query += " WHERE is_active = 1"
                cursor.execute(query)
                rows = cursor.fetchall()
                for row in rows:
                    raw_emb = row["face_embedding"]
                    embedding = self.deserialize_embedding(raw_emb) if raw_emb else None
                    students.append({
                        "student_id": row["student_id"],
                        "name": row["name"],
                        "class_name": row["class_name"],
                        "bus_id": row["bus_id"],
                        "face_embedding": embedding,
                        "is_active": bool(row["is_active"]),
                        "created_at": row["created_at"],
                    })
        except sqlite3.Error as e:
            print(f"Database error during student retrieval: {e}")

        return students

    def get_students_by_bus(self, bus_id: Optional[str] = None, active_only: bool = True) -> List[Dict[str, Any]]:
        """Retrieve registered students filtered by assigned bus_id."""
        all_students = self.get_all_students(active_only=active_only)
        if not bus_id:
            return all_students
        return [s for s in all_students if s.get("bus_id") == bus_id]

    def get_student_by_id(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific student by student_id."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT student_id, name, class_name, bus_id, face_embedding, is_active, created_at
                    FROM students
                    WHERE student_id = ?
                """, (student_id,))
                row = cursor.fetchone()
                if row:
                    raw_emb = row["face_embedding"]
                    embedding = self.deserialize_embedding(raw_emb) if raw_emb else None
                    return {
                        "student_id": row["student_id"],
                        "name": row["name"],
                        "class_name": row["class_name"],
                        "bus_id": row["bus_id"],
                        "face_embedding": embedding,
                        "is_active": bool(row["is_active"]),
                        "created_at": row["created_at"],
                    }
        except sqlite3.Error as e:
            print(f"Database error fetching student {student_id}: {e}")
        return None

    def update_student(
        self,
        student_id: str,
        name: Optional[str] = None,
        class_name: Optional[str] = None,
        bus_id: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> bool:
        """Update student metadata without altering face embeddings or historical attendance records."""
        existing = self.get_student_by_id(student_id)
        if not existing:
            return False

        new_name = name.strip() if name is not None else existing["name"]
        new_class = class_name.strip() if class_name is not None else existing["class_name"]
        new_bus = bus_id.strip() if bus_id is not None else existing["bus_id"]
        new_active = int(is_active) if is_active is not None else (1 if existing.get("is_active", True) else 0)
        now_str = datetime.now().isoformat()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE students
                    SET name = ?, class_name = ?, bus_id = ?, is_active = ?, updated_at = ?, sync_status = 'pending'
                    WHERE student_id = ?
                """, (new_name, new_class, new_bus, new_active, now_str, student_id))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error updating student {student_id}: {e}")
            return False

    def delete_student(self, student_id: str, soft_delete: bool = True) -> bool:
        """Delete or deactivate student record (privacy compliance).

        Args:
            student_id: Unique student ID.
            soft_delete: If True, marks is_active = 0 to allow sync to propagate.
                         If False, removes the student row from students table.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if soft_delete:
                    cursor.execute(
                        "UPDATE students SET is_active = 0, updated_at = ?, sync_status = 'pending' WHERE student_id = ?",
                        (datetime.now().isoformat(), student_id)
                    )
                else:
                    cursor.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error deleting student {student_id}: {e}")
            return False

    def get_student_attendance_count(self, student_id: str) -> int:
        """Count the total number of attendance records associated with a student."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) AS cnt FROM attendance WHERE student_id = ?", (student_id,))
                row = cursor.fetchone()
                return row["cnt"] if row else 0
        except sqlite3.Error as e:
            print(f"Database error counting attendance for {student_id}: {e}")
            return 0

    def get_student_attendance_history(self, student_id: str) -> List[Dict[str, Any]]:
        """Retrieve full attendance history for a specific student."""
        history = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT attendance_id, event_id, student_id, attendance_date, attendance_time, bus_id, status, sync_status, created_at
                    FROM attendance
                    WHERE student_id = ?
                    ORDER BY attendance_date DESC, attendance_time DESC
                """, (student_id,))
                for row in cursor.fetchall():
                    history.append(dict(row))
        except sqlite3.Error as e:
            print(f"Database error fetching attendance history for {student_id}: {e}")
        return history

    # ==================== Attendance Methods ====================

    def is_student_marked_present(
        self,
        student_id: str,
        attendance_date: str,
        bus_id: str
    ) -> bool:
        """Check whether a student is already marked present for a specific date and bus."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 1 FROM attendance
                    WHERE student_id = ? AND attendance_date = ? AND bus_id = ?
                    LIMIT 1
                """, (student_id, attendance_date, bus_id))
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            print(f"Database error checking attendance for {student_id}: {e}")
            return False

    def is_student_marked(
        self,
        student_id: str,
        attendance_date: str,
        bus_id: str
    ) -> bool:
        """Convenience alias for is_student_marked_present."""
        return self.is_student_marked_present(student_id, attendance_date, bus_id)

    def mark_student_present(
        self,
        student_id: str,
        attendance_date: str,
        attendance_time: str,
        bus_id: str,
        status: str = "Present",
        event_id: Optional[str] = None,
        device_id: Optional[str] = None,
        sync_status: str = "pending"
    ) -> bool:
        """Insert a single daily attendance record for a student on a specific bus and date.

        Uniqueness is strictly enforced on (student_id, attendance_date, bus_id).
        Assigns a stable UUID event_id and queues for cloud synchronization.
        """
        if not student_id or not str(student_id).strip():
            return False
        if not attendance_date or not str(attendance_date).strip():
            return False
        if not bus_id or not str(bus_id).strip():
            return False

        student = self.get_student_by_id(student_id)
        if not student:
            print(f"Validation error: Cannot mark attendance. Student {student_id} not registered.")
            return False

        assigned_event_id = event_id if event_id else str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO attendance 
                    (event_id, student_id, attendance_date, attendance_time, bus_id, status, device_id, sync_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (assigned_event_id, student_id, attendance_date, attendance_time, bus_id, status, device_id, sync_status, created_at))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            # Duplicate violation caught by UNIQUE (student_id, attendance_date, bus_id)
            return False
        except sqlite3.Error as e:
            print(f"Database error saving attendance for {student_id}: {e}")
            return False

    def get_attendance_for_date(
        self,
        attendance_date: str,
        bus_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve attendance records for a specific date (and optional bus filter)."""
        records = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT a.attendance_id, a.event_id, a.student_id,
                           COALESCE(s.name, a.student_id || ' (Deleted)') AS name,
                           COALESCE(s.class_name, '--') AS class_name,
                           a.attendance_date, a.attendance_time, a.bus_id, a.status,
                           a.sync_status, a.created_at
                    FROM attendance a
                    LEFT JOIN students s ON a.student_id = s.student_id
                    WHERE a.attendance_date = ?
                """
                params = [attendance_date]

                if bus_id and bus_id not in ("ALL BUSES", "All Buses"):
                    query += " AND a.bus_id = ?"
                    params.append(bus_id)

                query += " ORDER BY a.attendance_time ASC"
                cursor.execute(query, params)

                for row in cursor.fetchall():
                    records.append(dict(row))
        except sqlite3.Error as e:
            print(f"Database error retrieving attendance for {attendance_date}: {e}")

        return records

    def get_today_attendance(self, bus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Convenience method to retrieve attendance records for today's local date."""
        today_date = datetime.now().strftime("%Y-%m-%d")
        return self.get_attendance_for_date(today_date, bus_id)

    def get_registered_students_not_present_today(self, bus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve active registered students who have not yet been marked present today."""
        all_students = self.get_all_students(active_only=True)
        today_records = self.get_today_attendance(bus_id=bus_id)
        present_ids = {r["student_id"] for r in today_records if r.get("status") == "Present"}
        return [s for s in all_students if s["student_id"] not in present_ids]

    def clear_today_attendance(self, bus_id: str, attendance_date: Optional[str] = None) -> int:
        """Delete attendance records for a specific date and bus ID."""
        if attendance_date is None:
            attendance_date = datetime.now().strftime("%Y-%m-%d")

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM attendance
                    WHERE attendance_date = ? AND bus_id = ?
                """, (attendance_date, bus_id))
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Database error clearing today's attendance for bus {bus_id}: {e}")
            return 0

    def clear_all_attendance(self) -> int:
        """Delete ALL records from the attendance table."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM attendance")
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Database error clearing all attendance records: {e}")
            return 0

    def get_distinct_bus_ids(self) -> List[str]:
        """Retrieve all distinct bus IDs."""
        bus_ids = set()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT bus_id FROM buses WHERE is_active = 1")
                for row in cursor.fetchall():
                    bus_ids.add(row["bus_id"])
                cursor.execute("SELECT DISTINCT bus_id FROM students WHERE bus_id IS NOT NULL AND bus_id != ''")
                for row in cursor.fetchall():
                    bus_ids.add(row["bus_id"])
        except sqlite3.Error as e:
            print(f"Database error fetching bus IDs: {e}")

        sorted_buses = sorted(list(bus_ids))
        return sorted_buses if sorted_buses else ["BUS01"]

    def get_attendance_dates(self) -> List[str]:
        """Retrieve distinct attendance dates formatted as YYYY-MM-DD in descending order."""
        dates = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT attendance_date FROM attendance ORDER BY attendance_date DESC")
                for row in cursor.fetchall():
                    dates.append(row["attendance_date"])
        except sqlite3.Error as e:
            print(f"Database error fetching attendance dates: {e}")
        return dates

    # ==================== Cloud Synchronization Queue Methods ====================

    def get_pending_attendance(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve pending attendance records queued for Supabase upload."""
        records = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT attendance_id, event_id, student_id, attendance_date, attendance_time,
                           bus_id, status, device_id, sync_status, created_at
                    FROM attendance
                    WHERE sync_status = 'pending'
                    ORDER BY attendance_id ASC
                    LIMIT ?
                """, (limit,))
                for row in cursor.fetchall():
                    records.append(dict(row))
        except sqlite3.Error as e:
            print(f"Database error fetching pending attendance queue: {e}")
        return records

    def mark_attendance_synced(self, event_ids: List[str]) -> int:
        """Mark a list of attendance event UUIDs as successfully synced to Supabase."""
        if not event_ids:
            return 0
        now_str = datetime.now().isoformat()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    UPDATE attendance
                    SET sync_status = 'synced', synced_at = ?
                    WHERE event_id = ?
                """, [(now_str, eid) for eid in event_ids])
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Database error marking attendance synced: {e}")
            return 0

    def mark_attendance_sync_state(self, event_ids: List[str], state: str) -> int:
        """Set a non-'synced' sync_status (e.g. 'conflict') for the given event UUIDs.

        Records leave the 'pending' upload queue but are never reported as synced.
        'synced_at' is left untouched.
        """
        if not event_ids or state in ("synced", "pending"):
            return 0
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(
                    "UPDATE attendance SET sync_status = ? WHERE event_id = ?",
                    [(state, eid) for eid in event_ids]
                )
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Database error setting attendance sync state: {e}")
            return 0

    def get_pending_sync_count(self) -> int:
        """Return total count of local attendance events pending cloud upload."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) AS cnt FROM attendance WHERE sync_status = 'pending'")
                row = cursor.fetchone()
                return row["cnt"] if row else 0
        except sqlite3.Error:
            return 0

    # ==================== Student Metadata Cloud Sync Methods ====================

    def get_pending_students(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve student profiles pending cloud upload (metadata only, NO biometrics)."""
        students = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT student_id, name, class_name, bus_id, is_active, sync_status, created_at
                    FROM students
                    WHERE sync_status = 'pending'
                    ORDER BY student_id ASC
                    LIMIT ?
                """, (limit,))
                for row in cursor.fetchall():
                    students.append({
                        "student_id": row["student_id"],
                        "name": row["name"],
                        "class_name": row["class_name"],
                        "bus_id": row["bus_id"],
                        "is_active": bool(row["is_active"]),
                        "sync_status": row["sync_status"],
                        "created_at": row["created_at"],
                    })
        except sqlite3.Error as e:
            print(f"Database error fetching pending students queue: {e}")
        return students

    def mark_student_synced(self, student_ids: List[str]) -> int:
        """Mark student metadata as successfully synchronized to Supabase."""
        if not student_ids:
            return 0
        now_str = datetime.now().isoformat()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" for _ in student_ids)
                cursor.execute(f"""
                    UPDATE students
                    SET sync_status = 'synced', synced_at = ?
                    WHERE student_id IN ({placeholders})
                """, [now_str] + student_ids)
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Database error marking students synced: {e}")
            return 0

    def mark_student_sync_state(self, student_ids: List[str], state: str) -> int:
        """Set a non-'synced' sync_status (e.g. 'conflict') for given student IDs."""
        if not student_ids:
            return 0
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" for _ in student_ids)
                cursor.execute(f"""
                    UPDATE students
                    SET sync_status = ?
                    WHERE student_id IN ({placeholders})
                """, [state] + student_ids)
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Database error setting student sync state: {e}")
            return 0

    def get_pending_students_count(self) -> int:
        """Return total count of local student profiles pending cloud upload."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) AS cnt FROM students WHERE sync_status = 'pending'")
                row = cursor.fetchone()
                return row["cnt"] if row else 0
        except sqlite3.Error:
            return 0

    def upsert_bus_local(self, bus_id: str, bus_name: Optional[str] = None, is_active: bool = True) -> bool:
        """Upsert a bus definition into the local SQLite buses table."""
        now_str = datetime.now().isoformat()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO buses (bus_id, bus_name, is_active, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(bus_id) DO UPDATE SET
                        bus_name = excluded.bus_name,
                        is_active = excluded.is_active
                """, (bus_id.strip(), bus_name.strip() if bus_name else f"Bus {bus_id}", int(is_active), now_str))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"Database error upserting bus locally: {e}")
            return False

    def upsert_student_from_cloud(
        self,
        student_id: str,
        name: str,
        class_name: str,
        bus_id: str,
        is_active: bool = True
    ) -> bool:
        """Update or insert student metadata received from cloud sync.

        Preserves existing local biometric embedding if already cached locally.
        """
        now_str = datetime.now().isoformat()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Ensure bus exists
                cursor.execute(
                    "INSERT OR IGNORE INTO buses (bus_id, bus_name, is_active, created_at) VALUES (?, ?, 1, ?)",
                    (bus_id, f"Bus {bus_id}", now_str)
                )
                cursor.execute("""
                    INSERT INTO students (student_id, name, class_name, bus_id, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(student_id) DO UPDATE SET
                        name = excluded.name,
                        class_name = excluded.class_name,
                        bus_id = excluded.bus_id,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at
                """, (student_id, name, class_name, bus_id, int(is_active), now_str, now_str))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"Database error upserting student from cloud: {e}")
            return False

    def update_student_biometrics_if_missing(self, student_id: str, embedding_bytes: bytes) -> bool:
        """Cache face embedding for an existing student if local embedding is currently missing."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT face_embedding FROM students WHERE student_id = ?", (student_id,))
                row = cursor.fetchone()
                if row and not row["face_embedding"]:
                    cursor.execute("""
                        UPDATE students SET face_embedding = ?, updated_at = ?
                        WHERE student_id = ?
                    """, (embedding_bytes, datetime.now().isoformat(), student_id))
                    conn.commit()
                    return True
        except sqlite3.Error as e:
            print(f"Database error updating student biometrics: {e}")
        return False
