import sqlite3
import os
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
        """Create required tables and indexes if they do not already exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Students table (biometrics and profile)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    face_embedding BLOB NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # 2. Attendance table with uniqueness constraint on (student_id, attendance_date, bus_id)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL,
                    attendance_date TEXT NOT NULL,
                    attendance_time TEXT NOT NULL,
                    bus_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (student_id) REFERENCES students(student_id),
                    UNIQUE (student_id, attendance_date, bus_id)
                )
            """)
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
        face_embedding: np.ndarray
    ) -> bool:
        """Insert or replace student registration record with face embedding."""
        embedding_blob = self.serialize_embedding(face_embedding)
        created_at = datetime.now().isoformat()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO students 
                    (student_id, name, class_name, bus_id, face_embedding, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (student_id, name, class_name, bus_id, embedding_blob, created_at))
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Database error during registration: {e}")
            return False

    def get_all_students(self) -> List[Dict[str, Any]]:
        """Retrieve all registered students with deserialized face embeddings."""
        students = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT student_id, name, class_name, bus_id, face_embedding, created_at
                    FROM students
                """)
                rows = cursor.fetchall()
                for row in rows:
                    embedding = self.deserialize_embedding(row["face_embedding"])
                    students.append({
                        "student_id": row["student_id"],
                        "name": row["name"],
                        "class_name": row["class_name"],
                        "bus_id": row["bus_id"],
                        "face_embedding": embedding,
                        "created_at": row["created_at"],
                    })
        except sqlite3.Error as e:
            print(f"Database error during student retrieval: {e}")

        return students

    def get_students_by_bus(self, bus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve registered students filtered by assigned bus_id (or all students if bus_id is None)."""
        all_students = self.get_all_students()
        if not bus_id:
            return all_students
        return [s for s in all_students if s.get("bus_id") == bus_id]

    def get_student_by_id(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific student by student_id."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT student_id, name, class_name, bus_id, face_embedding, created_at
                    FROM students
                    WHERE student_id = ?
                """, (student_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        "student_id": row["student_id"],
                        "name": row["name"],
                        "class_name": row["class_name"],
                        "bus_id": row["bus_id"],
                        "face_embedding": self.deserialize_embedding(row["face_embedding"]),
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
        bus_id: Optional[str] = None
    ) -> bool:
        """Update student metadata (name, class, assigned bus).

        Does NOT modify or delete face embeddings or historical attendance records.
        """
        existing = self.get_student_by_id(student_id)
        if not existing:
            return False

        new_name = name.strip() if name is not None else existing["name"]
        new_class = class_name.strip() if class_name is not None else existing["class_name"]
        new_bus = bus_id.strip() if bus_id is not None else existing["bus_id"]

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE students
                    SET name = ?, class_name = ?, bus_id = ?
                    WHERE student_id = ?
                """, (new_name, new_class, new_bus, student_id))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error updating student {student_id}: {e}")
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
                    SELECT attendance_id, student_id, attendance_date, attendance_time, bus_id, status, created_at
                    FROM attendance
                    WHERE student_id = ?
                    ORDER BY attendance_date DESC, attendance_time DESC
                """, (student_id,))
                for row in cursor.fetchall():
                    history.append(dict(row))
        except sqlite3.Error as e:
            print(f"Database error fetching attendance history for {student_id}: {e}")
        return history

    def delete_student(self, student_id: str) -> bool:
        """Delete student and their biometric data by student_id (privacy compliance).

        Does NOT delete rows from the attendance table, preserving historical records.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error deleting student {student_id}: {e}")
            return False

    # ==================== Attendance Methods ====================

    def is_student_marked_present(
        self,
        student_id: str,
        attendance_date: str,
        bus_id: str
    ) -> bool:
        """Check whether a student is already marked present for a specific date and bus.

        Args:
            student_id: The student ID to verify.
            attendance_date: Date formatted as YYYY-MM-DD.
            bus_id: Identifier for the bus.

        Returns:
            True if an attendance record exists, False otherwise.
        """
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

    def mark_student_present(
        self,
        student_id: str,
        attendance_date: str,
        attendance_time: str,
        bus_id: str,
        status: str = "Present"
    ) -> bool:
        """Insert a new attendance record if not already recorded.

        Validates that student_id exists in the students table first.
        Relies on UNIQUE(student_id, attendance_date, bus_id) constraint.

        Args:
            student_id: Student unique ID.
            attendance_date: Date in YYYY-MM-DD format.
            attendance_time: Time in HH:MM:SS format.
            bus_id: Bus identifier.
            status: Controlled status string (default: 'Present').

        Returns:
            True if a new record was inserted, False if already marked or on error.
        """
        # Validate that student exists
        student = self.get_student_by_id(student_id)
        if not student:
            print(f"Validation error: Cannot mark attendance. Student {student_id} not registered.")
            return False

        created_at = datetime.now().isoformat()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO attendance 
                    (student_id, attendance_date, attendance_time, bus_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (student_id, attendance_date, attendance_time, bus_id, status, created_at))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            # Caught duplicate insertion violation
            return False
        except sqlite3.Error as e:
            print(f"Database error saving attendance for {student_id}: {e}")
            return False

    def get_attendance_for_date(
        self,
        attendance_date: str,
        bus_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve all attendance records for a specific date (and optionally a specific bus).

        Uses LEFT JOIN with students table so historical attendance records are never hidden
        even if a student profile is later deleted.

        Args:
            attendance_date: Date string (YYYY-MM-DD).
            bus_id: Optional bus ID to filter.

        Returns:
            List of attendance record dictionaries sorted by attendance_time.
        """
        records = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if bus_id:
                    cursor.execute("""
                        SELECT a.attendance_id, a.student_id,
                               COALESCE(s.name, a.student_id || ' (Deleted)') AS name,
                               COALESCE(s.class_name, '--') AS class_name,
                               a.attendance_date, a.attendance_time, a.bus_id, a.status, a.created_at
                        FROM attendance a
                        LEFT JOIN students s ON a.student_id = s.student_id
                        WHERE a.attendance_date = ? AND a.bus_id = ?
                        ORDER BY a.attendance_time ASC
                    """, (attendance_date, bus_id))
                else:
                    cursor.execute("""
                        SELECT a.attendance_id, a.student_id,
                               COALESCE(s.name, a.student_id || ' (Deleted)') AS name,
                               COALESCE(s.class_name, '--') AS class_name,
                               a.attendance_date, a.attendance_time, a.bus_id, a.status, a.created_at
                        FROM attendance a
                        LEFT JOIN students s ON a.student_id = s.student_id
                        WHERE a.attendance_date = ?
                        ORDER BY a.attendance_time ASC
                    """, (attendance_date,))

                for row in cursor.fetchall():
                    records.append({
                        "attendance_id": row["attendance_id"],
                        "student_id": row["student_id"],
                        "name": row["name"],
                        "class_name": row["class_name"],
                        "attendance_date": row["attendance_date"],
                        "attendance_time": row["attendance_time"],
                        "bus_id": row["bus_id"],
                        "status": row["status"],
                        "created_at": row["created_at"],
                    })
        except sqlite3.Error as e:
            print(f"Database error retrieving attendance for {attendance_date}: {e}")

        return records

    def get_today_attendance(self, bus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Convenience method to retrieve attendance records for today's local date."""
        today_date = datetime.now().strftime("%Y-%m-%d")
        return self.get_attendance_for_date(today_date, bus_id)

    def get_registered_students_not_present_today(self, bus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve registered students who have not yet been marked present today.

        Args:
            bus_id: Optional bus ID to filter.

        Returns:
            List of student profile dictionaries.
        """
        all_students = self.get_all_students()
        today_records = self.get_today_attendance(bus_id=bus_id)
        present_ids = {r["student_id"] for r in today_records if r.get("status") == "Present"}
        return [s for s in all_students if s["student_id"] not in present_ids]

    def clear_today_attendance(self, bus_id: str, attendance_date: Optional[str] = None) -> int:
        """Delete attendance records for a specific date and bus ID (defaults to today).

        Student records and biometrics remain untouched.

        Args:
            bus_id: Bus identifier.
            attendance_date: Optional date (YYYY-MM-DD). Defaults to today.

        Returns:
            Number of rows deleted.
        """
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
        """Delete ALL records from the attendance table.

        Student records, IDs, names, and face embeddings are completely preserved.

        Returns:
            Number of rows deleted.
        """
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
        """Retrieve all distinct bus IDs assigned to students or found in attendance records."""
        bus_ids = {"BUS01"}
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT bus_id FROM students WHERE bus_id IS NOT NULL AND bus_id != ''")
                for row in cursor.fetchall():
                    bus_ids.add(row["bus_id"])
                cursor.execute("SELECT DISTINCT bus_id FROM attendance WHERE bus_id IS NOT NULL AND bus_id != ''")
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


