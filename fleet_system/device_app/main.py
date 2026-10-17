"""Attendance Device Application Entry Point.

Runs on bus computer / future Raspberry Pi:
- Initializes camera feed (or mock camera in testing).
- Performs ArcFace face recognition with InsightFace.
- Confirms identity using a multi-frame temporal window (anti-false-positive).
- Records attendance locally in SQLite (offline-first).
- Synchronizes with Supabase via background thread (uploads attendance & pulls roster).
- Shows on-screen telemetry overlay (Online/Offline, Pending syncs, Present count).
- Supports --headless mode for Raspberry Pi without GUI display.
"""
import os
import sys
import time
import argparse
import logging
from typing import Dict, Any, List, Optional, Tuple
import cv2
import numpy as np

# Ensure project root is on sys.path so imports resolve cleanly
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CURRENT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.camera import Camera
from src.face_recognizer import FaceRecognizer
from fleet_system.device_app.local_db import DeviceDatabase
from fleet_system.device_app.sync_worker import DeviceSyncWorker
from fleet_system.shared.cloud_client import FleetCloudClient, save_cloud_credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DeviceApp")


class AttendanceDeviceApp:
    """Manages attendance engine, camera loop, and background synchronization."""

    def __init__(
        self,
        bus_id: str = "Bus01",
        device_id: Optional[str] = None,
        db_path: str = "fleet_system/device_app/data/device.db",
        camera_index: int = 0,
        headless: bool = False,
        similarity_threshold: float = 0.50,
        required_confirmations: int = 3,
        confirmation_window: float = 2.0
    ) -> None:
        self.db_path = db_path
        self.camera_index = camera_index
        self.headless = headless
        self.similarity_threshold = similarity_threshold
        self.required_confirmations = required_confirmations
        self.confirmation_window = confirmation_window

        # Initialize local storage
        self.db = DeviceDatabase(db_path=self.db_path)

        # Load persistent Bus ID if saved locally (CLI overrides default)
        saved_bus = self.db.get_config("bus_id", "")

        # If user passed a non-default CLI bus_id, save and use it; otherwise use saved config
        if bus_id != "Bus01" or not saved_bus:
            self.bus_id = bus_id.strip()
            self.db.set_config("bus_id", self.bus_id)
        else:
            self.bus_id = saved_bus.strip()

        # Device ID is always identical to Bus ID
        self.device_id = self.bus_id
        self.db.set_config("device_id", self.device_id)

        # Auto-detect headless mode on Linux if no display is available
        if not self.headless and sys.platform != "win32":
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                self.headless = True

        # Initialize background sync worker
        self.sync_worker = DeviceSyncWorker(db=self.db, bus_id=self.bus_id)

        # Load persistent custom cloud credentials from local database if previously configured
        saved_cloud_url = self.db.get_config("supabase_url", "")
        saved_cloud_key = self.db.get_config("supabase_key", "")
        if saved_cloud_url and saved_cloud_key:
            self.sync_worker.cloud.reconfigure(saved_cloud_url, saved_cloud_key)
            logger.info(f"Loaded persistent cloud credentials from device storage: {saved_cloud_url}")

        # Recognition & Camera
        self.face_recognizer: Optional[FaceRecognizer] = None
        self.camera: Optional[Camera] = None

        # Multi-frame confirmation tracking: {student_id: [timestamp1, timestamp2, ...]}
        self.confirmation_tracker: Dict[str, List[float]] = {}
        # Banner notifications: (text, expire_time, is_error)
        self.banner: Optional[Tuple[str, float, bool]] = None

    def initialize(self) -> bool:
        """Start database, models, sync worker, and camera."""
        logger.info(f"Initializing Attendance Device [Bus: {self.bus_id}, Device: {self.device_id}]")
        
        # 1. Start background sync
        self.sync_worker.start()

        # 2. Load FaceRecognizer model
        try:
            logger.info("Loading InsightFace buffalo_sc model pack...")
            self.face_recognizer = FaceRecognizer(
                model_name="buffalo_sc",
                similarity_threshold=self.similarity_threshold
            )
        except Exception as e:
            logger.error(f"Failed to load FaceRecognizer: {e}")
            return False

        # 3. Open Camera
        self.camera = Camera(camera_index=self.camera_index)
        if not self.camera.start():
            logger.error(f"Failed to open camera index {self.camera_index}")
            return False

        logger.info("Camera started successfully.")
        return True

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Process a single video frame for face detection, tracking, and attendance marking."""
        now = time.time()
        active_students = self.db.get_active_students_for_bus(self.bus_id)

        if not self.face_recognizer:
            return frame

        # Detect faces
        faces = self.face_recognizer.extract_faces(frame)

        for face in faces:
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
            query_emb = face.embedding

            # Match against local roster
            label, matched_student, score = self.face_recognizer.identify_face(
                query_emb,
                active_students
            )

            box_color = (0, 0, 255)  # Red for Unknown
            status_text = "UNKNOWN"

            if matched_student:
                sid = matched_student["student_id"]
                sname = matched_student["name"]

                # Maintain sliding confirmation window
                timestamps = self.confirmation_tracker.get(sid, [])
                # Prune expired timestamps
                timestamps = [t for t in timestamps if (now - t) <= self.confirmation_window]
                timestamps.append(now)
                self.confirmation_tracker[sid] = timestamps

                obs_count = len(timestamps)

                if obs_count >= self.required_confirmations:
                    # Attempt attendance recording
                    is_new, msg = self.db.record_attendance(
                        student_id=sid,
                        bus_id=self.bus_id,
                        device_id=self.device_id,
                        status="Present"
                    )
                    if is_new:
                        box_color = (0, 255, 0)  # Green
                        status_text = f"PRESENT: {sname}"
                        self.banner = (f"ATTENDANCE MARKED: {sname} ({sid})", now + 3.0, False)
                        logger.info(f"Marked attendance for {sname} ({sid}) on {self.bus_id}")
                        self.sync_worker.trigger_immediate_sync()
                    else:
                        box_color = (0, 255, 0)
                        status_text = f"ALREADY PRESENT: {sname}"
                else:
                    box_color = (0, 255, 255)  # Yellow for confirming
                    status_text = f"CONFIRMING ({obs_count}/{self.required_confirmations}): {sname}"

            # Draw bounding box and label if not headless
            if not self.headless:
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                cv2.putText(
                    frame,
                    f"{status_text} ({score:.2f})",
                    (x1, max(20, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    box_color,
                    2
                )

        # Draw overlays if not headless
        if not self.headless:
            self._render_overlay(frame)

        return frame

    def _render_overlay(self, frame: np.ndarray) -> None:
        """Render high-contrast top and bottom telemetry banners on frame."""
        h, w = frame.shape[:2]
        now = time.time()
        telemetry = self.sync_worker.get_status_telemetry()
        stats = self.db.get_stats_for_today(self.bus_id)

        # Top Bar: Bus info & Presence + Shortcut Keys
        cv2.rectangle(frame, (0, 0), (w, 42), (20, 24, 33), -1)
        top_txt = (
            f"BUS: {self.bus_id} | "
            f"PRESENT: {stats['total_present']}/{stats['total_assigned']}"
        )
        cv2.putText(frame, top_txt, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        ctrl_hint = "[C] Bus ID  [S] Cloud Keys  [Q] Exit"
        cv2.putText(frame, ctrl_hint, (max(15, w - 370), 28), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (180, 190, 205), 1)

        # Bottom Bar: Cloud & Sync telemetry
        cv2.rectangle(frame, (0, h - 36), (w, h), (20, 24, 33), -1)
        net_status = "ONLINE" if telemetry["is_online"] else "OFFLINE"
        net_color = (0, 255, 0) if telemetry["is_online"] else (0, 0, 255)
        bot_txt = (
            f"NET: {net_status} | PENDING: {telemetry['pending_count']} | "
            f"LAST SYNC: {telemetry['last_sync_time']}"
        )
        cv2.putText(frame, bot_txt, (15, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, net_color, 2)

        # Center Toast Banner
        if self.banner and now < self.banner[1]:
            msg, _, is_err = self.banner
            bg_color = (0, 0, 180) if is_err else (0, 150, 0)
            cv2.rectangle(frame, (40, h // 2 - 25), (w - 40, h // 2 + 25), bg_color, -1)
            cv2.putText(
                frame,
                msg,
                (60, h // 2 + 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (255, 255, 255),
                2
            )

    def prompt_reconfigure_device(self) -> None:
        """Prompt administrator in a safe Tkinter popup to change Bus ID with confirmation."""
        import tkinter as tk
        from tkinter import simpledialog, messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        new_bus = simpledialog.askstring(
            "Configure Hardware Bus ID",
            f"Current Bus ID: {self.bus_id}\nEnter new Bus ID (e.g. Bus02, Bus03):",
            initialvalue=self.bus_id,
            parent=root
        )

        if not new_bus or not new_bus.strip() or new_bus.strip() == self.bus_id:
            root.destroy()
            return

        new_bus = new_bus.strip()

        # Strict confirmation prompt to prevent accidental changes
        confirmed = messagebox.askyesno(
            "CONFIRM BUS ID CHANGE",
            f"Are you ABSOLUTELY sure you want to change this device to Bus '{new_bus}'?\n\n"
            f"Old Bus ID: {self.bus_id}\n"
            f"New Bus ID: {new_bus}\n\n"
            f"This device will now record attendance and pull students specifically for {new_bus}.",
            parent=root
        )
        root.destroy()

        if confirmed:
            self.bus_id = new_bus
            self.device_id = new_bus
            # Persist in local SQLite configuration table
            self.db.set_config("bus_id", self.bus_id)
            self.db.set_config("device_id", self.device_id)
            # Update sync worker dynamically (also auto-registers new bus in Supabase cloud)
            self.sync_worker.update_bus_id(self.bus_id)
            self.banner = (f"BUS UPDATED: {self.bus_id}", time.time() + 4.0, False)
            logger.info(f"Hardware successfully reconfigured to Bus: {self.bus_id}")

    def prompt_configure_credentials(self) -> None:
        """Prompt administrator to configure Supabase URL & Key with persistent confirmation."""

        cur_url, cur_key = self.sync_worker.cloud.get_current_credentials()

        if self.headless:
            # Console fallback for headless execution / Raspberry Pi SSH terminal
            print("\n" + "=" * 60)
            print("  CONFIGURE SUPABASE CLOUD CREDENTIALS")
            print("=" * 60)
            print(f"Current URL: {cur_url}")
            input_url = input(f"Enter Supabase Project URL [{cur_url}]: ").strip()
            new_url = input_url if input_url else cur_url

            input_key = input("Enter Supabase API Key (press Enter to keep current): ").strip()
            new_key = input_key if input_key else cur_key

            new_url = new_url.strip().rstrip("/")
            new_key = new_key.strip()

            confirm = input(f"\nSave credentials for URL '{new_url}'? (y/n): ").strip().lower()
            if confirm != "y":
                print("Configuration cancelled.")
                return
            confirmed = True
        else:
            import tkinter as tk
            from tkinter import simpledialog, messagebox

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            new_url = simpledialog.askstring(
                "Configure Supabase URL",
                f"Current URL:\n{cur_url}\n\nEnter Supabase Project URL (e.g. https://xyz.supabase.co):",
                initialvalue=cur_url,
                parent=root
            )
            if not new_url or not new_url.strip():
                root.destroy()
                return

            new_key = simpledialog.askstring(
                "Configure Supabase API Key",
                f"Enter Supabase API Key (anon/publishable/service_role):",
                initialvalue=cur_key,
                parent=root
            )
            if not new_key or not new_key.strip():
                root.destroy()
                return

            new_url = new_url.strip().rstrip("/")
            new_key = new_key.strip()

            confirmed = messagebox.askyesno(
                "CONFIRM CLOUD CREDENTIALS UPDATE",
                f"Are you ABSOLUTELY sure you want to update the Cloud Database credentials?\n\n"
                f"New URL: {new_url}\n\n"
                f"The device will now connect to this Supabase project for attendance and roster sync.\n\n"
                f"These credentials will be permanently saved on this device.",
                parent=root
            )
            root.destroy()

        if confirmed:
            self.sync_worker.cloud.reconfigure(new_url, new_key)
            ok, msg = self.sync_worker.cloud.test_connection()
            # 1. Save to .env file
            save_cloud_credentials(new_url, new_key)
            # 2. Persist permanently in local SQLite device_config table
            self.db.set_config("supabase_url", new_url)
            self.db.set_config("supabase_key", new_key)

            if ok:
                self.banner = ("CLOUD CONNECTED & SAVED", time.time() + 4.0, False)
                logger.info(f"Cloud credentials updated, verified, and permanently saved! ({new_url})")
            else:
                self.banner = ("CREDENTIALS SAVED (CHECK CONNECTION)", time.time() + 4.0, True)
                logger.warning(f"Cloud credentials permanently saved but test returned: {msg}")
            self.sync_worker.trigger_immediate_sync()

    def run(self) -> None:
        """Main execution loop."""
        if not self.initialize():
            logger.error("Initialization failed. Exiting.")
            return

        window_name = f"Fleet Attendance Device - {self.bus_id}"
        logger.info(f"Running device loop (Headless={self.headless}).")
        logger.info("Controls: Press 'Q' to quit, Press 'C' to configure Bus ID, Press 'S' to configure Cloud Settings.")

        try:
            while True:
                ret, frame = self.camera.read_frame() if self.camera else (False, None)
                if not ret or frame is None:
                    time.sleep(0.05)
                    continue

                processed = self.process_frame(frame)

                if not self.headless:
                    cv2.imshow(window_name, processed)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord('q'), ord('Q')):
                        logger.info("User requested exit ('Q' pressed).")
                        break
                    elif key in (ord('c'), ord('C')):
                        self.prompt_reconfigure_device()
                        window_name = f"Fleet Attendance Device - {self.bus_id}"
                    elif key in (ord('s'), ord('S')):
                        self.prompt_configure_credentials()
                else:
                    time.sleep(0.01)

        except KeyboardInterrupt:
            logger.info("Interrupted by user (Ctrl+C).")
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Release camera, windows, and stop background thread."""
        logger.info("Cleaning up device resources...")
        if self.camera:
            self.camera.release()
        if not self.headless:
            cv2.destroyAllWindows()
        if self.sync_worker.is_running:
            self.sync_worker.stop()
        logger.info("Device application stopped cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fleet Attendance Device Application")
    parser.add_argument("--bus-id", type=str, default="Bus01", help="Assigned Bus ID (e.g. Bus01)")
    parser.add_argument("--device-id", type=str, default=None, help="Hardware Device ID")
    parser.add_argument("--camera-index", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--db-path", type=str, default="fleet_system/device_app/data/device.db")
    parser.add_argument("--headless", action="store_true", help="Run without GUI/OpenCV display (Raspberry Pi)")
    parser.add_argument("--configure-cloud", action="store_true", help="Open cloud credentials editor before starting")
    args = parser.parse_args()

    app = AttendanceDeviceApp(
        bus_id=args.bus_id,
        device_id=args.device_id,
        db_path=args.db_path,
        camera_index=args.camera_index,
        headless=args.headless
    )
    if args.configure_cloud:
        app.prompt_configure_credentials()
    app.run()


if __name__ == "__main__":
    main()
