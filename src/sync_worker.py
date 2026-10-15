"""Background Synchronization Worker for Automatic School Bus Attendance System.

Runs in a separate daemon thread to ensure zero UI freezes or camera stalls.
Handles offline-first local queue draining, exponential backoff, retry management,
and bi-directional synchronization between local SQLite and central Supabase.
"""
import time
import threading
import logging
from typing import Dict, Any, Optional, List, Set
from datetime import datetime

from src.database import Database
from src.supabase_service import SupabaseService
from src.config import (
    SYNC_INTERVAL_SECONDS,
    SYNC_BATCH_SIZE,
    SYNC_MAX_RETRIES,
    SYNC_ENABLED,
    PULL_STUDENTS,
    PULL_BUSES,
)

logger = logging.getLogger(__name__)

# Upper bound for the exponential backoff wait between failed cycles (seconds)
MAX_BACKOFF_SECONDS = 300.0


class SyncWorker:
    """Threaded background synchronization manager."""

    def __init__(
        self,
        db: Database,
        supabase_service: Optional[SupabaseService] = None,
        interval_seconds: float = SYNC_INTERVAL_SECONDS,
        enabled: Optional[bool] = None,
        pull_students: Optional[bool] = None,
        pull_buses: Optional[bool] = None
    ) -> None:
        self.db = db
        self.supabase = supabase_service or SupabaseService()
        self.interval_seconds = interval_seconds
        # Safety gates (default to the config flags, all off unless opted in)
        self.enabled = SYNC_ENABLED if enabled is None else enabled
        self.pull_students = PULL_STUDENTS if pull_students is None else pull_students
        self.pull_buses = PULL_BUSES if pull_buses is None else pull_buses

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()

        # Thread-safe status telemetry
        self._lock = threading.Lock()
        self._is_running = False
        self._is_online = False
        self._last_sync_time: Optional[str] = None
        self._last_error: Optional[str] = None
        self._sync_state: str = "Initializing"  # "Online (Synced)", "Pending Upload", "Offline", "Error"

        # Retry / backoff bookkeeping (worker thread only)
        self._consecutive_failures: int = 0
        self._retry_counts: Dict[str, int] = {}
        self._skipped_events: Set[str] = set()

    def start(self) -> None:
        """Start the background synchronization thread."""
        if not self.enabled:
            with self._lock:
                self._sync_state = "Disabled"
            logger.info("Cloud synchronization is disabled (SYNC_ENABLED=false); running local-only.")
            return
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="SupabaseSyncWorker",
                daemon=True
            )
            self._thread.start()
            logger.info("Background synchronization worker started.")

    def stop(self, timeout: float = 2.0) -> None:
        """Gracefully stop the background worker thread."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            self._stop_event.set()
            self._wake_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("Background synchronization worker stopped.")

    @property
    def is_running(self) -> bool:
        """Return True if background sync thread is running."""
        with self._lock:
            return self._is_running

    def enable(self) -> None:
        """Dynamically enable and start the sync worker thread."""
        self.enabled = True
        self.start()

    def trigger_immediate_sync(self) -> None:
        """Signal the worker thread to perform a sync immediately."""
        self._wake_event.set()

    def get_status(self) -> Dict[str, Any]:
        """Retrieve thread-safe telemetry for UI indicators matching: Disabled, Syncing, Pending, Synced, Error."""
        pending_attendance = self.db.get_pending_sync_count()
        pending_students = self.db.get_pending_students_count()
        total_pending = pending_attendance + pending_students
        with self._lock:
            if not self.supabase.is_configured():
                state_text = "Offline Mode (Local SQLite)"
                badge_color = "#94a3b8"  # Slate neutral
                status_name = "Disabled"
            elif self._sync_state == "Disabled":
                state_text = "Cloud sync disabled (Local SQLite)"
                badge_color = "#94a3b8"  # Slate neutral
                status_name = "Disabled"
            elif not self._is_online:
                state_text = f"Offline ({total_pending} pending)" if total_pending else "Offline (No connection)"
                badge_color = "#ef4444"  # Red
                status_name = "Error"
            elif self._sync_state == "Syncing":
                state_text = f"Syncing ({total_pending} pending)" if total_pending else "Syncing"
                badge_color = "#3b82f6"  # Blue
                status_name = "Syncing"
            elif self._sync_state == "Error":
                state_text = f"Sync Error ({total_pending} pending)" if total_pending else "Sync Error"
                badge_color = "#ef4444"  # Red
                status_name = "Error"
            elif total_pending > 0:
                state_text = f"Uploading ({total_pending} pending)"
                badge_color = "#f59e0b"  # Amber
                status_name = "Pending"
            else:
                state_text = "Cloud Synced"
                badge_color = "#10b981"  # Emerald green
                status_name = "Synced"

            return {
                "is_running": self._is_running,
                "is_configured": self.supabase.is_configured(),
                "is_online": self._is_online,
                "pending_count": total_pending,
                "pending_attendance": pending_attendance,
                "pending_students": pending_students,
                "last_sync_time": self._last_sync_time,
                "last_error": self._last_error,
                "state_text": state_text,
                "status_name": status_name,
                "badge_color": badge_color,
            }

    # =========================================================================
    # INTERNAL SYNCHRONIZATION LOOP
    # =========================================================================

    def _current_wait_seconds(self) -> float:
        """Interval after a healthy cycle; exponential backoff (capped) after failures."""
        if self._consecutive_failures <= 0:
            return self.interval_seconds
        return min(self.interval_seconds * (2 ** self._consecutive_failures), MAX_BACKOFF_SECONDS)

    def _run_loop(self) -> None:
        """Main periodic loop executed in worker thread."""
        # Initial brief delay so application GUI can fully render
        time.sleep(1.0)

        while not self._stop_event.is_set():
            try:
                self._perform_sync_cycle()
            except Exception as e:
                logger.error(f"Unexpected error during sync cycle: {e}")
                self._consecutive_failures += 1
                with self._lock:
                    self._last_error = str(e)
                    self._is_online = False

            # Wait for interval/backoff or until immediate trigger/stop
            self._wake_event.wait(timeout=self._current_wait_seconds())
            self._wake_event.clear()

    def _perform_sync_cycle(self) -> None:
        """Execute one complete upload and download synchronization pass.

        Upload order strictly follows database foreign key constraints:
        1. Bus metadata (ensured before dependent students/attendance)
        2. Student metadata (excluding facial biometrics)
        3. Dependent attendance events
        """
        if not self.supabase.is_configured():
            with self._lock:
                self._is_online = False
                self._sync_state = "Unconfigured"
            return

        # 1. Test connectivity
        is_ok, msg = self.supabase.test_connection()
        with self._lock:
            self._is_online = is_ok
            if not is_ok:
                self._last_error = msg
                self._sync_state = "Offline"
        if not is_ok:
            self._consecutive_failures += 1
            return

        with self._lock:
            self._sync_state = "Syncing"

        # 2. Push Pending Local Students (Bus metadata uploaded first, then student metadata)
        students_ok = self._upload_pending_students()

        # 3. Push Pending Local Attendance Events (Dependent on buses and students existing)
        attendance_ok = self._upload_pending_attendance()

        # 4. Pull Master Buses from Cloud (Downstream Sync, opt-in)
        if self.pull_buses:
            self._download_buses()

        # 5. Pull Active Students from Cloud (Downstream Sync, opt-in)
        if self.pull_students:
            self._download_students()

        # 6. Pull Any Missing Biometrics from Cloud (no-op unless BIOMETRIC_CLOUD_SYNC is enabled)
        self._download_biometrics()

        if students_ok and attendance_ok:
            self._consecutive_failures = 0
            with self._lock:
                self._last_sync_time = datetime.now().strftime("%H:%M:%S")
                self._last_error = None
                self._sync_state = "Synced"
        else:
            self._consecutive_failures += 1
            with self._lock:
                self._sync_state = "Error"

    def _upload_pending_students(self) -> bool:
        """Upload pending local student registrations/updates to Supabase.

        Ensures parent bus metadata exists first, then uploads student metadata.
        Biometric face embeddings are NEVER uploaded.
        """
        pending_students = self.db.get_pending_students()
        if not pending_students:
            return True

        all_ok = True
        synced_ids = []
        for s in pending_students:
            s_id = s["student_id"]
            bus_id = s.get("bus_id") or "Bus01"
            name = s.get("name") or f"Student {s_id}"
            class_name = s.get("class_name") or "--"

            # 1. Ensure parent bus exists in cloud
            bus_ok = self.supabase.ensure_bus(bus_id)
            if not bus_ok:
                logger.warning(f"Could not ensure bus '{bus_id}' for pending student {s_id}")
                all_ok = False
                continue

            # 2. Upload student metadata (face embedding is NEVER included)
            student_ok = self.supabase.upsert_student(
                student_id=s_id,
                name=name,
                class_name=class_name,
                bus_id=bus_id,
                is_active=True,
                insert_only=False
            )
            if student_ok:
                synced_ids.append(s_id)
            else:
                logger.warning(f"Failed to upsert pending student {s_id}: {getattr(self.supabase, '_last_error', 'unknown error')}")
                all_ok = False

        if synced_ids:
            self.db.mark_student_synced(synced_ids)
            logger.info(f"Successfully synced {len(synced_ids)} students to Supabase.")

        return all_ok

    def _upload_pending_attendance(self) -> bool:
        """Batch upload pending local attendance records to Supabase.

        Returns True when nothing was left failing this cycle.
        """
        # Over-fetch so records skipped after too many rejections do not starve the queue
        pending_records = self.db.get_pending_attendance(limit=SYNC_BATCH_SIZE + len(self._skipped_events))
        pending_records = [r for r in pending_records if r["event_id"] not in self._skipped_events]
        pending_records = pending_records[:SYNC_BATCH_SIZE]
        if not pending_records:
            return True

        # Ensure all referenced buses exist in cloud before uploading events
        distinct_buses = {r["bus_id"] for r in pending_records if r.get("bus_id")}
        for b_id in distinct_buses:
            self.supabase.ensure_bus(b_id)

        # Prepare payload (local identifiers; SupabaseService maps them via the crosswalk)
        payload = []
        for r in pending_records:
            payload.append({
                "event_id": r["event_id"],
                "student_id": r["student_id"],
                "attendance_date": r["attendance_date"],
                "attendance_time": r["attendance_time"],
                "bus_id": r["bus_id"],
                "status": r.get("status", "Present"),
                "device_id": r.get("device_id"),
            })

        try:
            count, uploaded_ids, err = self.supabase.upload_attendance_batch(payload, verify=True)
        except TypeError:
            count, uploaded_ids, err = self.supabase.upload_attendance_batch(payload)

        # Only events confirmed by the cloud are marked synced
        if uploaded_ids:
            self.db.mark_attendance_synced(uploaded_ids)
            for eid in uploaded_ids:
                self._retry_counts.pop(eid, None)
            logger.info(f"Successfully synced {len(uploaded_ids)} attendance events to Supabase.")

        if err is None:
            return True

        logger.warning(f"Failed to sync attendance batch: {err}")
        results = getattr(self.supabase, "last_upload_results", None)
        if isinstance(results, dict):
            conflict_ids = [eid for eid, (state, _) in results.items() if state == "conflict"]
            if conflict_ids:
                # Never overwrite the cloud row; take the record out of the retry queue.
                self.db.mark_attendance_sync_state(conflict_ids, "conflict")
                for eid in conflict_ids:
                    logger.warning(f"Attendance event {eid} marked 'conflict': {results[eid][1]}")
            for eid, (state, detail) in results.items():
                if state == "rejected":
                    self._retry_counts[eid] = self._retry_counts.get(eid, 0) + 1
                    if self._retry_counts[eid] >= SYNC_MAX_RETRIES:
                        self._skipped_events.add(eid)
                        logger.error(
                            f"Attendance event {eid} rejected {self._retry_counts[eid]} times "
                            f"({detail}); excluded from retries until restart (record kept as pending)."
                        )
        return False

    def _download_buses(self) -> None:
        """Fetch cloud buses and update local SQLite cache."""
        cloud_buses = self.supabase.get_all_buses()
        for b in cloud_buses:
            self.db.upsert_bus_local(
                bus_id=self.supabase.crosswalk.bus_to_local(b["bus_id"]),
                bus_name=b.get("bus_name"),
                is_active=b.get("is_active", True)
            )

    def _download_students(self) -> None:
        """Fetch cloud student roster and update local SQLite profiles."""
        cloud_students = self.supabase.get_all_students(active_only=False)
        for s in cloud_students:
            self.db.upsert_student_from_cloud(
                student_id=self.supabase.crosswalk.student_to_local(s["student_id"]),
                name=s["name"],
                class_name=s["class_name"],
                bus_id=self.supabase.crosswalk.bus_to_local(s["bus_id"]),
                is_active=s.get("is_active", True)
            )

    def _download_biometrics(self) -> None:
        """Fetch any cloud biometric templates missing from local SQLite cache."""
        all_cloud_bio = self.supabase.get_all_biometrics()
        for bio in all_cloud_bio:
            s_id = bio["student_id"]
            emb_bytes = bio.get("embedding")
            if emb_bytes:
                self.db.update_student_biometrics_if_missing(s_id, emb_bytes)
