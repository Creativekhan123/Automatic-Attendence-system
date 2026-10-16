"""Background Synchronization Engine for Attendance Device.

Continuously runs in background thread:
1. Pulls updated student roster & biometrics for assigned bus.
2. Pushes pending offline attendance records to Supabase.
3. Provides thread-safe telemetry for device UI (network status, pending count, last sync).
"""
import time
import threading
import logging
from typing import Optional, Dict, Any, List

from fleet_system.device_app.local_db import DeviceDatabase
from fleet_system.shared.cloud_client import FleetCloudClient

logger = logging.getLogger(__name__)


class DeviceSyncWorker:
    """Thread-safe background worker for device cloud sync."""

    def __init__(
        self,
        db: DeviceDatabase,
        bus_id: str,
        cloud_client: Optional[FleetCloudClient] = None,
        interval_seconds: float = 15.0
    ) -> None:
        self.db = db
        self.bus_id = bus_id.strip()
        self.cloud = cloud_client or FleetCloudClient()
        self.interval_seconds = interval_seconds

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()

        # Telemetry
        self.is_running = False
        self.is_online = False
        self.last_sync_time: Optional[str] = None
        self.last_error: Optional[str] = None
        self.pending_count = 0
        self.active_students_count = 0

    def update_bus_id(self, new_bus_id: str) -> None:
        """Dynamically update assigned bus_id and trigger sync."""
        with self._lock:
            self.bus_id = new_bus_id.strip()
        self.trigger_immediate_sync()

    def start(self) -> None:
        """Start background sync thread."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="FleetDeviceSyncWorker",
                daemon=True
            )
            self._thread.start()
            logger.info("DeviceSyncWorker started.")

    def stop(self, timeout: float = 2.0) -> None:
        """Stop background sync thread."""
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False
            self._stop_event.set()
            self._wake_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("DeviceSyncWorker stopped.")

    def trigger_immediate_sync(self) -> None:
        """Wake worker thread immediately (e.g. after marking attendance)."""
        self._wake_event.set()

    def _run_loop(self) -> None:
        """Main loop: pulls roster then pushes pending attendance."""
        while not self._stop_event.is_set():
            try:
                self._sync_cycle()
            except Exception as e:
                with self._lock:
                    self.is_online = False
                    self.last_error = str(e)
                logger.error(f"Sync cycle exception: {e}")

            # Sleep until interval or wake event
            self._wake_event.wait(timeout=self.interval_seconds)
            self._wake_event.clear()

    def _sync_cycle(self) -> None:
        """Single sync iteration."""
        if not self.cloud.is_configured():
            with self._lock:
                self.is_online = False
                self.last_error = "Cloud credentials not configured"
            return

        # 1. Connection check
        conn_ok, _ = self.cloud.test_connection()
        if not conn_ok:
            with self._lock:
                self.is_online = False
                self.last_error = "Offline / Connection failed"
            return

        with self._lock:
            self.is_online = True

        # 2. Pull roster updates (Download assigned students for this bus)
        try:
            cloud_students = self.cloud.get_students(bus_id=self.bus_id, active_only=False)
            if cloud_students:
                active_sids = [s["student_id"] for s in cloud_students if s.get("is_active", True)]
                # Check which students lack biometric vectors locally
                missing_sids = self.db.get_missing_biometric_student_ids()
                fetch_sids = list(set(active_sids + missing_sids))

                cloud_biometrics: Dict[str, bytes] = {}
                if fetch_sids:
                    cloud_biometrics = self.cloud.get_biometrics_for_students(fetch_sids)

                total_active = self.db.sync_roster_cache(cloud_students, cloud_biometrics)
                with self._lock:
                    self.active_students_count = total_active
        except Exception as e:
            logger.error(f"Error pulling roster: {e}")

        # 3. Push pending attendance to cloud
        try:
            pending = self.db.get_pending_attendance(limit=50)
            with self._lock:
                self.pending_count = len(pending)

            if pending:
                synced_ids, failed_ids = self.cloud.upload_attendance_batch(pending)
                if synced_ids:
                    self.db.mark_attendance_synced(synced_ids)
                    with self._lock:
                        # Recount pending
                        self.pending_count = len(self.db.get_pending_attendance(limit=50))
                        self.last_sync_time = time.strftime("%H:%M:%S")
        except Exception as e:
            logger.error(f"Error pushing attendance: {e}")
            with self._lock:
                self.last_error = str(e)

        with self._lock:
            self.last_sync_time = time.strftime("%H:%M:%S")

    def get_status_telemetry(self) -> Dict[str, Any]:
        """Return snapshot of worker status."""
        with self._lock:
            return {
                "is_running": self.is_running,
                "is_online": self.is_online,
                "last_sync_time": self.last_sync_time or "Never",
                "pending_count": self.pending_count,
                "active_students": self.active_students_count,
                "last_error": self.last_error
            }
