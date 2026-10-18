"""Biometric Bridge Server for FleetPass Web & Mobile Applications.

Provides high-performance ArcFace (InsightFace buffalo_sc) 512-D biometric feature
vector generation and Supabase synchronization for registrations made from
Web Browser, Android APK, and PC Executable.
"""
import os
import sys
import json
import base64
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional, Dict, Any
import cv2
import numpy as np

# Ensure project root is on sys.path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.face_recognizer import FaceRecognizer
from fleet_system.shared.cloud_client import FleetCloudClient
from fleet_system.device_app.local_db import DeviceDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Bridge] %(levelname)s: %(message)s")
logger = logging.getLogger("BiometricBridge")

PORT = int(os.environ.get("BRIDGE_PORT", "5050"))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads for concurrent multi-device registrations."""
    daemon_threads = True


class BiometricBridgeHandler(BaseHTTPRequestHandler):
    recognizer: Optional[FaceRecognizer] = None
    cloud: Optional[FleetCloudClient] = None
    device_db: Optional[DeviceDatabase] = None

    def _set_cors_headers(self, status: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-fleet-sync-token")
        self.send_header("Content-Type", content_type)
        self.end_headers()

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests from Web & Mobile browsers."""
        self._set_cors_headers(204)

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("", "/api/status", "/api/health"):
            # Health check & status
            status_data = {
                "status": "online",
                "service": "FleetPass Biometric Bridge",
                "engine": "InsightFace ArcFace (buffalo_sc)",
                "embedding_dimension": 512,
                "cloud_configured": self.cloud.is_configured() if self.cloud else False,
            }
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
            return

        if path == "/api/missing-biometrics":
            # List students in cloud that lack biometrics
            try:
                students = self.cloud.get_students() if self.cloud else []
                sids = [s["student_id"] for s in students]
                existing_bios = self.cloud.get_biometrics_for_students(sids) if (self.cloud and sids) else {}
                missing = [s for s in students if s["student_id"] not in existing_bios]

                self._set_cors_headers(200)
                self.wfile.write(json.dumps({
                    "total_students": len(students),
                    "missing_count": len(missing),
                    "missing_students": missing
                }).encode("utf-8"))
            except Exception as e:
                self._set_cors_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        self._set_cors_headers(404)
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"success": False, "error": "Empty request body"}).encode("utf-8"))
            return

        try:
            body_bytes = self.rfile.read(content_length)
            body = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"success": False, "error": f"Invalid JSON payload: {e}"}).encode("utf-8"))
            return

        if path == "/api/register":
            self._handle_register(body)
        elif path == "/api/generate-biometrics":
            self._handle_generate_biometrics(body)
        else:
            self._set_cors_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def _decode_photo_to_cv2(self, photo_data: str) -> Optional[np.ndarray]:
        """Decode a base64 Data URL or raw base64 string into an OpenCV BGR frame."""
        if not photo_data:
            return None
        try:
            # Strip data URL header if present
            if "," in photo_data:
                photo_data = photo_data.split(",", 1)[1]
            raw_bytes = base64.b64decode(photo_data)
            np_arr = np.frombuffer(raw_bytes, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            logger.error(f"Failed to decode photo base64: {e}")
            return None

    def _handle_register(self, body: Dict[str, Any]) -> None:
        sid = str(body.get("student_id", "")).strip()
        name = str(body.get("name", "")).strip()
        cname = str(body.get("class_name", "")).strip()
        bus_id = str(body.get("bus_id", "")).strip()
        photo_data = body.get("photo")

        if not sid or not name or not cname or not bus_id:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"success": False, "error": "Missing student_id, name, class_name, or bus_id"}).encode("utf-8"))
            return

        if not photo_data:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"success": False, "error": "Photo is required for biometric face registration"}).encode("utf-8"))
            return

        # 1. Decode image
        frame = self._decode_photo_to_cv2(photo_data)
        if frame is None or frame.size == 0:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"success": False, "error": "Invalid or corrupted image format"}).encode("utf-8"))
            return

        # 2. Extract 512-D ArcFace embedding using InsightFace
        if not self.recognizer:
            self._set_cors_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": "FaceRecognizer model not loaded"}).encode("utf-8"))
            return

        try:
            faces = self.recognizer.extract_faces(frame)
        except Exception as e:
            logger.error(f"InsightFace error: {e}")
            self._set_cors_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": f"Recognition engine error: {e}"}).encode("utf-8"))
            return

        if len(faces) == 0:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({
                "success": False,
                "error": "No face detected in photo. Please ensure face is clearly visible and well-lit."
            }).encode("utf-8"))
            return

        if len(faces) > 1:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({
                "success": False,
                "error": f"Multiple faces ({len(faces)}) detected in photo. Exactly 1 face is required for registration."
            }).encode("utf-8"))
            return

        # Extract float32 512-D vector
        emb = faces[0].embedding
        arr = np.asarray(emb, dtype=np.float32)
        emb_bytes = arr.tobytes()

        # 3. Upload to Supabase Cloud
        cloud_success = False
        bio_success = False
        cloud_error = None

        if self.cloud and self.cloud.is_configured():
            try:
                # 3a. Save student profile
                cloud_success = self.cloud.upsert_student(sid, name, cname, bus_id, is_active=True)
                if not cloud_success:
                    cloud_error = self.cloud._last_error or "Failed to upload student profile to Supabase"
                else:
                    # 3b. Save biometric vector
                    bio_success = self.cloud.upload_biometrics(sid, emb_bytes)
                    if not bio_success:
                        cloud_error = self.cloud._last_error or "Failed to upload biometric vector to Supabase"
            except Exception as e:
                cloud_error = str(e)
                logger.error(f"Cloud upload error: {e}")

        # 4. Also cache in local device SQLite database if available
        local_db_synced = False
        if self.device_db:
            try:
                self.device_db.sync_roster_cache(
                    [{"student_id": sid, "name": name, "class_name": cname, "bus_id": bus_id, "is_active": True}],
                    {sid: emb_bytes}
                )
                local_db_synced = True
            except Exception as e:
                logger.warning(f"Local device_db cache warning: {e}")

        if cloud_success and bio_success:
            logger.info(f"Successfully registered student {name} ({sid}) with 512-D ArcFace biometrics!")
            self._set_cors_headers(200)
            self.wfile.write(json.dumps({
                "success": true,
                "student_id": sid,
                "name": name,
                "class_name": cname,
                "bus_id": bus_id,
                "biometrics_verified": True,
                "embedding_dimension": 512,
                "cloud_synced": True,
                "local_db_synced": local_db_synced,
                "message": f"Student '{name}' registered with 512-D biometric face vector! Ready for camera attendance."
            }).encode("utf-8"))
        else:
            self._set_cors_headers(502 if cloud_error else 400)
            self.wfile.write(json.dumps({
                "success": False,
                "student_id": sid,
                "error": cloud_error or "Biometric upload failed",
                "biometrics_extracted": True
            }).encode("utf-8"))

    def _handle_generate_biometrics(self, body: Dict[str, Any]) -> None:
        """Generate and upload biometrics for an already existing student."""
        sid = str(body.get("student_id", "")).strip()
        photo_data = body.get("photo")

        if not sid or not photo_data:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"success": False, "error": "student_id and photo are required"}).encode("utf-8"))
            return

        frame = self._decode_photo_to_cv2(photo_data)
        if frame is None or frame.size == 0:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"success": False, "error": "Invalid photo"}).encode("utf-8"))
            return

        faces = self.recognizer.extract_faces(frame) if self.recognizer else []
        if len(faces) != 1:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({
                "success": False,
                "error": f"Expected exactly 1 face, detected {len(faces)}"
            }).encode("utf-8"))
            return

        emb_bytes = np.asarray(faces[0].embedding, dtype=np.float32).tobytes()
        ok_bio = self.cloud.upload_biometrics(sid, emb_bytes) if self.cloud else False

        if ok_bio:
            if self.device_db:
                self.device_db.update_biometrics(sid, emb_bytes)
            self._set_cors_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "student_id": sid,
                "message": "Face biometric vector generated and uploaded successfully!"
            }).encode("utf-8"))
        else:
            self._set_cors_headers(502)
            self.wfile.write(json.dumps({
                "success": False,
                "error": self.cloud._last_error if self.cloud else "Cloud client not configured"
            }).encode("utf-8"))


def run_bridge_server(port: int = PORT) -> None:
    """Initialize models and run the threaded HTTP bridge."""
    print("=" * 60)
    print("   FLEETPASS BIOMETRIC BRIDGE SERVER (ArcFace Engine)")
    print("=" * 60)
    print(f"Loading InsightFace buffalo_sc neural network...")

    try:
        BiometricBridgeHandler.recognizer = FaceRecognizer(model_name="buffalo_sc")
        print("InsightFace ArcFace model loaded successfully.")
    except Exception as e:
        print(f"Error loading FaceRecognizer: {e}")
        sys.exit(1)

    BiometricBridgeHandler.cloud = FleetCloudClient()
    if BiometricBridgeHandler.cloud.is_configured():
        print(f"Connected to Supabase cloud: {BiometricBridgeHandler.cloud.url}")
    else:
        print("Supabase cloud client not configured or in offline mode.")

    # Local SQLite database cache
    db_path = os.path.join(_PROJECT_ROOT, "fleet_system", "device_app", "data", "device.db")
    if os.path.exists(db_path):
        BiometricBridgeHandler.device_db = DeviceDatabase(db_path=db_path)
        print(f"Connected to local device attendance database: {db_path}")

    server_address = ("0.0.0.0", port)
    httpd = ThreadedHTTPServer(server_address, BiometricBridgeHandler)

    print("-" * 60)
    print(f"Biometric Bridge active and listening on port {port}:")
    print(f" - Localhost  : http://localhost:{port}/api/status")
    print(f" - Mobile LAN  : http://<YOUR_PC_IP>:{port}/api/status")
    print("Ready to process face embeddings for Web, Mobile, and Desktop apps.")
    print("Press Ctrl+C to terminate.")
    print("=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Biometric Bridge...")
        httpd.server_close()
        print("Biometric Bridge stopped cleanly.")


if __name__ == "__main__":
    run_bridge_server()
