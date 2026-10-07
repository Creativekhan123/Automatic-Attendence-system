import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from src.database import Database
from src.config import (
    DEFAULT_BUS_ID,
    REQUIRED_CONFIRMATIONS,
    CONFIRMATION_WINDOW_SECONDS
)


class AttendanceEngine:
    """Manages multi-frame confirmation, duplicate prevention, and attendance recording.

    Prevents transient false positives by tracking consecutive observations per student
    within a sliding time window before committing a 'Present' record to SQLite.
    """

    def __init__(
        self,
        db: Database,
        bus_id: str = DEFAULT_BUS_ID,
        required_confirmations: int = REQUIRED_CONFIRMATIONS,
        confirmation_window_seconds: float = CONFIRMATION_WINDOW_SECONDS
    ) -> None:
        """Initialize the AttendanceEngine.

        Args:
            db: Database instance for queries and insertions.
            bus_id: Identifier of the bus conducting attendance.
            required_confirmations: Number of consistent recognitions required.
            confirmation_window_seconds: Time window in seconds for confirmations.
        """
        self.db = db
        self.bus_id = bus_id
        self.required_confirmations = required_confirmations
        self.confirmation_window_seconds = confirmation_window_seconds

        # In-memory tracking of recent recognition observations per student_id
        # Structure: { student_id: [timestamp_1, timestamp_2, ...] }
        self._student_observations: Dict[str, List[float]] = {}

        # Cache of student_ids already marked present for (today_date, bus_id)
        # Allows instantaneous O(1) checks without hitting SQLite on every frame.
        self._marked_cache: set = set()
        self._current_cache_date: str = ""
        self._refresh_marked_cache()

    def _get_current_date_str(self) -> str:
        """Get current local system date formatted as YYYY-MM-DD."""
        return datetime.now().strftime("%Y-%m-%d")

    def _get_current_time_str(self) -> str:
        """Get current local system time formatted as HH:MM:SS."""
        return datetime.now().strftime("%H:%M:%S")

    def _refresh_marked_cache(self) -> None:
        """Synchronize in-memory cache with database for today's session."""
        today_str = self._get_current_date_str()
        if today_str != self._current_cache_date:
            self._marked_cache.clear()
            self._current_cache_date = today_str

        # Query DB for all present students on this date & bus
        records = self.db.get_attendance_for_date(today_str, self.bus_id)
        for r in records:
            if r.get("status") == "Present":
                self._marked_cache.add(r["student_id"])

    def is_marked_present(self, student_id: str) -> bool:
        """Check whether a student is already marked present today on this bus."""
        today_str = self._get_current_date_str()
        if today_str != self._current_cache_date:
            self._refresh_marked_cache()
        return student_id in self._marked_cache

    def process_recognition(
        self,
        student: Optional[Dict[str, Any]]
    ) -> Tuple[str, int, bool]:
        """Process a recognition candidate and update confirmation tracking.

        Args:
            student: Dictionary of matched student (or None if UNKNOWN).

        Returns:
            Tuple of:
            (status_label, current_confirmation_count, newly_marked_flag)
            status_label is one of: 'ALREADY PRESENT', 'CONFIRMED', 'CONFIRMING', 'UNKNOWN'.
        """
        if student is None:
            return "UNKNOWN", 0, False

        student_id = student.get("student_id")
        if not student_id:
            return "UNKNOWN", 0, False

        # If already marked present today on this bus, skip confirmation
        if self.is_marked_present(student_id):
            return "ALREADY PRESENT", self.required_confirmations, False

        now = time.time()
        # Retrieve and prune expired observations outside sliding window
        obs_list = self._student_observations.get(student_id, [])
        valid_obs = [t for t in obs_list if (now - t) <= self.confirmation_window_seconds]
        valid_obs.append(now)
        self._student_observations[student_id] = valid_obs

        count = len(valid_obs)

        # Check if confirmation threshold is reached
        if count >= self.required_confirmations:
            # Attempt to commit attendance to database
            attendance_date = self._get_current_date_str()
            attendance_time = self._get_current_time_str()

            success = self.db.mark_student_present(
                student_id=student_id,
                attendance_date=attendance_date,
                attendance_time=attendance_time,
                bus_id=self.bus_id,
                status="Present"
            )

            if success:
                self._marked_cache.add(student_id)
                # Clear observation list after successful mark
                self._student_observations.pop(student_id, None)
                return "PRESENT", count, True
            else:
                # If mark_student_present returned False, it was either duplicate or DB error
                if self.db.is_student_marked_present(student_id, attendance_date, self.bus_id):
                    self._marked_cache.add(student_id)
                    return "ALREADY PRESENT", count, False
                else:
                    return "DB ERROR", count, False

        return "CONFIRMING", count, False

    def get_attendance_summary(self) -> Dict[str, Any]:
        """Generate a summary of today's attendance session.

        Calculates registered count, present count, not-yet-present count,
        and the list of marked attendance records.
        """
        today_str = self._get_current_date_str()
        all_students = self.db.get_all_students()
        attendance_records = self.db.get_attendance_for_date(today_str, self.bus_id)

        present_ids = {r["student_id"] for r in attendance_records if r.get("status") == "Present"}
        not_yet_present = [s for s in all_students if s["student_id"] not in present_ids]

        return {
            "date": today_str,
            "bus_id": self.bus_id,
            "total_registered": len(all_students),
            "total_present": len(present_ids),
            "not_yet_present_count": len(not_yet_present),
            "present_records": attendance_records,
            "not_yet_present_students": not_yet_present
        }
