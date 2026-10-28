"""Ultra-Fast Edge Attendance Device Application for Raspberry Pi 4.

Combines:
- OpenCV YuNet (232 KB) for ultra-fast face detection (35+ FPS on RPi 4)
- Decoupled Asynchronous Multi-Threading (Display @ 30 FPS, AI @ ~6-8 FPS)
- Local SQLite attendance storage & Supabase Cloud Sync
- Interactive GUI / Headless deployment for Raspberry Pi 4
"""

import os
import sys
import time
import logging
import argparse
import threading
from typing import Optional, Dict, Any, List, Tuple
import numpy as np
import cv2

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fleet_system.device_app.local_db import DeviceDatabase
from fleet_system.device_app.sync_worker import DeviceSyncWorker
from src.camera import Camera
from ultra_fast_edge.yunet_detector import YuNetDetector
from ultra_fast_edge.sface_recognizer import SFaceRecognizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ultra_device_app")


class UltraAttendanceApp:
    """Ultra-fast edge attendance runner optimized for Raspberry Pi 4 CPU."""

    def __init__(
        self,
        bus_id: str = "Bus01",
        device_id: Optional[str] = None,
        db_path: str = "fleet_system/device_app/data/device.db",
        camera_index: int = 0,
        det_size: int = 320,
        engine: str = "hybrid",
        headless: bool = False
    ) -> None:
        self.bus_id = bus_id
        self.device_id = device_id or bus_id
        self.db_path = db_path
        self.camera_index = camera_index
        self.det_size = det_size
        self.engine = engine.lower()
        self.headless = headless

        self.db = DeviceDatabase(self.db_path)
        self.sync_worker = DeviceSyncWorker(db=self.db, bus_id=self.bus_id, interval_seconds=5.0)

        # Restore persisted configs if available
        saved_bus = self.db.get_config("bus_id")
        if saved_bus:
            self.bus_id = saved_bus
            self.device_id = saved_bus
            self.sync_worker.update_bus_id(self.bus_id)

        # Detectors and Recognizers
        self.detector = YuNetDetector(input_size=(self.det_size, self.det_size))
        self.sface_recognizer: Optional[SFaceRecognizer] = None
        self.insightface_recognizer: Optional[Any] = None

        if self.engine == "sface":
            self.sface_recognizer = SFaceRecognizer()
            logger.info("Using pure OpenCV YuNet + SFace recognition engine.")
        else:
            try:
                from src.face_recognizer import FaceRecognizer
                self.insightface_recognizer = FaceRecognizer(det_size=(self.det_size, self.det_size))
                logger.info("Using Hybrid engine: YuNet detector + MobileFaceNet embedder (compatible with existing DB).")
            except Exception as e:
                logger.warning(f"Failed to load InsightFace ({e}), falling back to SFace.")
                self.engine = "sface"
                self.sface_recognizer = SFaceRecognizer()

        self.camera: Optional[Camera] = None

        # Attendance tracking
        self.confirmation_tracker: Dict[int, List[float]] = {}
        self.confirmation_window: float = 2.0
        self.required_confirmations: int = 3

        # Cached roster matrix for instant vector dot-product matching (<0.05ms)
        self._roster_cache: List[Dict[str, Any]] = []
        self._roster_matrix: Optional[np.ndarray] = None
        self._last_roster_refresh: float = 0.0
        self._already_present_ids: set = set()

        # Telemetry
        self.fps: float = 0.0
        self.ai_fps: float = 0.0
        self._last_frame_time: float = time.perf_counter()
        self._last_health_log: float = time.time()
        self.banner: Optional[Tuple[str, float, bool]] = None

        # Decoupled AI Threading state
        self._ai_thread: Optional[threading.Thread] = None
        self._ai_running: bool = False
        self._ai_lock = threading.Lock()
        self._latest_ai_input_frame: Optional[np.ndarray] = None
        self._current_detections: List[Dict[str, Any]] = []
        self._last_ai_time: float = 0.0
        self.ai_interval: float = 0.12  # Runs AI ~8 times/sec, leaving Pi CPU cool

    def initialize(self) -> bool:
        """Start database, models, sync worker, and camera."""
        logger.info(f"Initializing Ultra Attendance App [Bus: {self.bus_id}, Engine: {self.engine}, Res: {self.det_size}p]")
        self.sync_worker.start()
        self._refresh_roster_cache(force=True)

        self.camera = Camera(camera_index=self.camera_index)
        if not self.camera.start():
            logger.error(f"Failed to open camera index {self.camera_index}")
            return False

        # Start decoupled AI background thread
        self._ai_running = True
        self._ai_thread = threading.Thread(target=self._ai_worker_loop, daemon=True)
        self._ai_thread.start()

        logger.info("Ultra Edge camera and AI worker started successfully.")
        return True

    def _refresh_roster_cache(self, force: bool = False) -> None:
        """Refresh local roster vector matrix and today's attendance status."""
        now = time.time()
        if not force and (now - self._last_roster_refresh) < 5.0:
            return

        self._last_roster_refresh = now
        try:
            students = self.db.get_active_students_for_bus(self.bus_id)
            valid_students = []
            emb_list = []

            for s in students:
                emb_raw = s.get("face_embedding")
                if emb_raw is not None:
                    if isinstance(emb_raw, (bytes, bytearray)):
                        arr = np.frombuffer(emb_raw, dtype=np.float32)
                    else:
                        arr = np.array(emb_raw, dtype=np.float32)
                    arr = arr.flatten()
                    if arr.size in (128, 512):
                        norm = np.linalg.norm(arr)
                        if norm > 0:
                            arr = arr / norm
                        emb_list.append(arr)
                        valid_students.append(s)

            if emb_list:
                self._roster_matrix = np.vstack(emb_list).astype(np.float32)
                self._roster_cache = valid_students
            else:
                self._roster_matrix = None
                self._roster_cache = []

            today_str = time.strftime("%Y-%m-%d")
            present_ids = self.db.get_present_student_ids(self.bus_id, today_str)
            self._already_present_ids = set(present_ids)
        except Exception as e:
            logger.error(f"Error refreshing roster cache: {e}")

    def _ai_worker_loop(self) -> None:
        """Background worker executing YuNet AI inference without blocking video display."""
        while self._ai_running:
            frame_to_process = None
            with self._ai_lock:
                if self._latest_ai_input_frame is not None:
                    frame_to_process = self._latest_ai_input_frame.copy()
                    self._latest_ai_input_frame = None

            if frame_to_process is None:
                time.sleep(0.01)
                continue

            t0 = time.perf_counter()
            try:
                new_detections = self._run_ai_pipeline(frame_to_process)
            except Exception as e:
                logger.error(f"Error in background AI worker: {e}")
                new_detections = []

            dt = time.perf_counter() - t0
            if dt > 0:
                inst = 1.0 / dt
                self.ai_fps = (0.8 * self.ai_fps + 0.2 * inst) if self.ai_fps > 0 else inst

            with self._ai_lock:
                self._current_detections = new_detections
                self._last_ai_time = time.time()

            # Throttle to allow CPU idle intervals
            time.sleep(self.ai_interval)

    def _run_ai_pipeline(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Run YuNet detection and recognition matching."""
        now = time.time()
        self._refresh_roster_cache()

        # Ultra-fast YuNet face detection (~3ms on PC, ~25ms on RPi 4)
        detected_faces = self.detector.detect(frame, min_size=35)
        detections: List[Dict[str, Any]] = []

        for face_dict in detected_faces:
            x1, y1, x2, y2 = face_dict["bbox"]
            label = "Unknown"
            matched_student = None
            score = 0.0

            if self.engine == "hybrid" and self.insightface_recognizer:
                # Hybrid: crop detected face and extract InsightFace 512-D embedding
                face_crop = frame[y1:y2, x1:x2]
                if face_crop.size > 0:
                    faces = self.insightface_recognizer.extract_faces(face_crop, min_size=20)
                    if faces:
                        query_emb = faces[0].embedding
                        label, matched_student, score = self.insightface_recognizer.identify_face_vectorized(
                            query_emb,
                            self._roster_matrix,
                            self._roster_cache,
                            threshold=0.48
                        )
            elif self.sface_recognizer:
                # Pure OpenCV SFace: extract 128-D embedding directly using 5 landmarks
                query_emb = self.sface_recognizer.extract_feature(frame, face_dict["raw"])
                label, matched_student, score = self.sface_recognizer.identify_vectorized(
                    query_emb,
                    self._roster_matrix,
                    self._roster_cache,
                    threshold=0.363
                )

            box_color = (0, 0, 255)  # Red for unknown
            status_text = label

            if matched_student:
                sid = matched_student["student_id"]
                sname = matched_student.get("name", f"ID {sid}")

                if sid in self._already_present_ids:
                    box_color = (0, 255, 0)  # Green for present
                    status_text = f"PRESENT: {sname}"
                else:
                    # Multi-frame confirmation window
                    timestamps = self.confirmation_tracker.get(sid, [])
                    timestamps = [t for t in timestamps if (now - t) <= self.confirmation_window]
                    timestamps.append(now)
                    self.confirmation_tracker[sid] = timestamps

                    obs_count = len(timestamps)
                    if obs_count >= self.required_confirmations:
                        is_new, msg = self.db.record_attendance(
                            student_id=sid,
                            bus_id=self.bus_id,
                            device_id=self.device_id,
                            status="Present"
                        )
                        if is_new:
                            self._already_present_ids.add(sid)
                            logger.info(f"Attendance MARKED for {sname} ({sid}) on Bus {self.bus_id} [Conf: {score:.2f}]")
                            self.banner = (f"MARKED PRESENT: {sname}", time.time() + 3.0, False)
                            self.sync_worker.trigger_immediate_sync()
                        else:
                            self._already_present_ids.add(sid)
                        box_color = (0, 255, 0)
                        status_text = f"MARKED: {sname}"
                    else:
                        box_color = (0, 255, 255)  # Yellow for confirming
                        status_text = f"CONFIRMING ({obs_count}/{self.required_confirmations}): {sname}"

            detections.append({
                "bbox": (x1, y1, x2, y2),
                "color": box_color,
                "text": f"{status_text} ({score:.2f})",
                "score": score
            })

        return detections

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Render recent AI detections onto frame in <1ms without blocking."""
        now = time.time()

        with self._ai_lock:
            self._latest_ai_input_frame = frame
            is_fresh = (now - self._last_ai_time) <= 0.8
            detections = list(self._current_detections) if is_fresh else []

        if not self.headless:
            for det in detections:
                x1, y1, x2, y2 = det["bbox"]
                box_color = det["color"]
                text = det["text"]
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                cv2.putText(
                    frame,
                    text,
                    (x1, max(20, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    box_color,
                    2
                )
            self._render_overlay(frame)

        return frame

    def _render_overlay(self, frame: np.ndarray) -> None:
        """Render high-contrast telemetry bars on frame."""
        h, w = frame.shape[:2]
        now = time.time()
        telemetry = self.sync_worker.get_status_telemetry()
        stats = self.db.get_stats_for_today(self.bus_id)

        # Top Bar: Bus info, Video FPS, AI FPS, Engine, Present count
        cv2.rectangle(frame, (0, 0), (w, 42), (20, 24, 33), -1)
        top_txt = (
            f"BUS: {self.bus_id} | "
            f"FPS: {self.fps:.1f} (AI: {self.ai_fps:.1f}) | "
            f"ENGINE: YuNet ({self.engine.upper()}) | "
            f"PRESENT: {stats['total_present']}/{stats['total_assigned']}"
        )
        cv2.putText(frame, top_txt, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        ctrl_hint = "[C] Bus ID  [S] Cloud  [Q] Exit"
        cv2.putText(frame, ctrl_hint, (max(15, w - 300), 28), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 190, 205), 1)

        # Bottom Bar: Cloud status & pending events
        cv2.rectangle(frame, (0, h - 36), (w, h), (20, 24, 33), -1)
        net_status = "ONLINE" if telemetry["is_online"] else "OFFLINE"
        net_color = (0, 255, 0) if telemetry["is_online"] else (0, 0, 255)
        bot_txt = (
            f"NET: {net_status} | PENDING: {telemetry['pending_count']} | "
            f"LAST SYNC: {telemetry['last_sync_time']}"
        )
        cv2.putText(frame, bot_txt, (15, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, net_color, 2)

        # Center Toast Notification
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

    def run(self) -> None:
        """Main camera execution loop."""
        if not self.initialize():
            logger.error("Initialization failed. Exiting.")
            return

        window_name = f"Ultra-Fast Attendance - {self.bus_id} (YuNet Edge)"
        logger.info(f"Running Ultra Edge loop (Engine={self.engine}, Headless={self.headless}).")

        try:
            while True:
                ret, frame = self.camera.read_frame() if self.camera else (False, None)
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                now_t = time.perf_counter()
                dt = now_t - self._last_frame_time
                self._last_frame_time = now_t
                if dt > 0:
                    inst_fps = 1.0 / dt
                    self.fps = (0.9 * self.fps + 0.1 * inst_fps) if self.fps > 0 else inst_fps

                if self.headless and (time.time() - self._last_health_log) >= 10.0:
                    self._last_health_log = time.time()
                    stats = self.db.get_stats_for_today(self.bus_id)
                    is_on = self.sync_worker.is_online
                    logger.info(
                        f"[TELEMETRY] Video FPS: {self.fps:.1f} | AI FPS: {self.ai_fps:.1f} | "
                        f"Present: {stats['total_present']}/{stats['total_assigned']} | "
                        f"Net: {'ONLINE' if is_on else 'OFFLINE'}"
                    )

                processed = self.process_frame(frame)

                if not self.headless:
                    cv2.imshow(window_name, processed)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord('q'), ord('Q')):
                        logger.info("User requested exit ('Q' pressed).")
                        break
                else:
                    time.sleep(0.005)

        except KeyboardInterrupt:
            logger.info("Interrupted by user (Ctrl+C).")
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Clean up threads and hardware handles."""
        logger.info("Cleaning up Ultra Edge resources...")
        self._ai_running = False
        if self._ai_thread and self._ai_thread.is_alive():
            self._ai_thread.join(timeout=2.0)
        if self.camera:
            self.camera.release()
        if not self.headless:
            cv2.destroyAllWindows()
        if self.sync_worker.is_running:
            self.sync_worker.stop()
        logger.info("Ultra Edge application stopped cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ultra-Fast Attendance Engine for Raspberry Pi 4")
    parser.add_argument("--bus-id", type=str, default="Bus01", help="Assigned Bus ID")
    parser.add_argument("--device-id", type=str, default=None, help="Hardware Device ID")
    parser.add_argument("--camera-index", type=int, default=0, help="Camera index")
    parser.add_argument("--det-size", type=int, default=320, choices=[320, 480, 640], help="YuNet input resolution")
    parser.add_argument("--engine", type=str, default="hybrid", choices=["hybrid", "sface"],
                        help="Engine: 'hybrid' (YuNet + MobileFaceNet, compatible with existing DB) or 'sface' (Pure OpenCV)")
    parser.add_argument("--db-path", type=str, default="fleet_system/device_app/data/device.db")
    parser.add_argument("--headless", action="store_true", help="Run in headless terminal mode")
    args = parser.parse_args()

    app = UltraAttendanceApp(
        bus_id=args.bus_id,
        device_id=args.device_id,
        db_path=args.db_path,
        camera_index=args.camera_index,
        det_size=args.det_size,
        engine=args.engine,
        headless=args.headless
    )
    app.run()


if __name__ == "__main__":
    main()
