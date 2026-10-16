"""Shared Supabase Cloud API Client for Fleet Attendance System.

Provides high-performance, resilient REST operations for:
- Bus fleet management
- Student profile registration & metadata
- Secure 512-D ArcFace biometric feature vector transmission (protected with fleet sync token)
- Attendance query and idempotent cloud upload
"""
import os
import re
import json
import logging
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import requests
from dotenv import load_dotenv

# Automatically load environment variables from project root .env
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CURRENT_DIR))
_env_path = os.path.join(_PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)
else:
    load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
FLEET_SYNC_TOKEN = os.environ.get("FLEET_SYNC_TOKEN", "PROTOTYPE_FLEET_SYNC_SECRET").strip()
SYNC_HTTP_TIMEOUT = float(os.environ.get("SYNC_HTTP_TIMEOUT", "15.0"))

logger = logging.getLogger(__name__)


class FleetCloudClient:
    """Resilient REST client for Supabase interactions with token-protected biometrics."""

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        fleet_token: Optional[str] = None,
        timeout: float = SYNC_HTTP_TIMEOUT
    ) -> None:
        self.url = (url or SUPABASE_URL).strip().rstrip("/")
        self.key = (key or SUPABASE_KEY).strip()
        self.fleet_token = fleet_token or FLEET_SYNC_TOKEN
        self.timeout = timeout
        self.session = requests.Session()
        self._last_error: Optional[str] = None

    def _get_headers(self, with_token: bool = False, prefer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json"
        }
        if with_token and self.fleet_token:
            headers["x-fleet-sync-token"] = self.fleet_token
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def is_configured(self) -> bool:
        """Check if cloud credentials are provided."""
        return bool(self.url and self.key and not self.url.startswith("https://your-project"))

    def test_connection(self) -> Tuple[bool, str]:
        """Test live connection to Supabase REST API."""
        if not self.is_configured():
            return False, "Supabase credentials are missing or set to placeholder in .env"
        try:
            resp = self.session.get(
                f"{self.url}/rest/v1/buses?select=bus_id&limit=1",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            if resp.status_code in (200, 206):
                return True, "Successfully connected to Supabase cloud."
            return False, f"Supabase responded with HTTP {resp.status_code}: {resp.text}"
        except Exception as e:
            self._last_error = str(e)
            return False, f"Connection failed: {e}"

    # =========================================================================
    # BUS OPERATIONS
    # =========================================================================

    def get_buses(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Fetch all buses."""
        if not self.is_configured():
            return []
        try:
            params = "select=*"
            if active_only:
                params += "&is_active=eq.true"
            params += "&order=bus_id.asc"
            resp = self.session.get(
                f"{self.url}/rest/v1/buses?{params}",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            if resp.status_code == 200:
                return resp.json()
            logger.error(f"Failed to fetch buses: HTTP {resp.status_code} {resp.text}")
            return []
        except Exception as e:
            logger.error(f"Error fetching buses: {e}")
            self._last_error = str(e)
            return []

    def ensure_bus(self, bus_id: str, bus_name: Optional[str] = None) -> bool:
        """Ensure a bus exists in cloud. Does not overwrite if already existing."""
        if not self.is_configured() or not bus_id:
            return False
        clean_id = bus_id.strip()
        try:
            # Check existence first
            check = self.session.get(
                f"{self.url}/rest/v1/buses?bus_id=eq.{clean_id}&select=bus_id",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            if check.status_code == 200 and len(check.json()) > 0:
                return True
            # Insert new
            payload = {
                "bus_id": clean_id,
                "bus_name": (bus_name.strip() if bus_name else f"Bus {clean_id}"),
                "is_active": True
            }
            resp = self.session.post(
                f"{self.url}/rest/v1/buses",
                headers=self._get_headers(prefer="return=minimal"),
                json=payload,
                timeout=self.timeout
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.error(f"Error ensuring bus {bus_id}: {e}")
            self._last_error = str(e)
            return False

    # =========================================================================
    # STUDENT OPERATIONS
    # =========================================================================

    def get_students(self, bus_id: Optional[str] = None, active_only: bool = True) -> List[Dict[str, Any]]:
        """Fetch student profiles. Filter by bus_id if specified."""
        if not self.is_configured():
            return []
        try:
            params = "select=*"
            if active_only:
                params += "&is_active=eq.true"
            if bus_id:
                params += f"&bus_id=eq.{bus_id.strip()}"
            params += "&order=student_id.asc"
            resp = self.session.get(
                f"{self.url}/rest/v1/students?{params}",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            if resp.status_code == 200:
                return resp.json()
            logger.error(f"Failed to fetch students: HTTP {resp.status_code} {resp.text}")
            return []
        except Exception as e:
            logger.error(f"Error fetching students: {e}")
            self._last_error = str(e)
            return []

    def upsert_student(
        self,
        student_id: str,
        name: str,
        class_name: str,
        bus_id: str,
        is_active: bool = True
    ) -> bool:
        """Upsert student profile in Supabase cloud."""
        if not self.is_configured() or not student_id:
            return False
        try:
            # Ensure bus exists
            self.ensure_bus(bus_id)
            payload = {
                "student_id": student_id.strip(),
                "name": name.strip(),
                "class_name": class_name.strip(),
                "bus_id": bus_id.strip(),
                "is_active": is_active
            }
            resp = self.session.post(
                f"{self.url}/rest/v1/students",
                headers=self._get_headers(prefer="resolution=merge-duplicates"),
                json=payload,
                timeout=self.timeout
            )
            if resp.status_code in (200, 201):
                return True
            self._last_error = f"HTTP {resp.status_code}: {resp.text}"
            logger.error(f"Failed to upsert student {student_id}: {self._last_error}")
            return False
        except Exception as e:
            logger.error(f"Error upserting student: {e}")
            self._last_error = str(e)
            return False

    def update_student_status(self, student_id: str, is_active: bool) -> bool:
        """Deactivate or activate student (Soft Delete)."""
        if not self.is_configured() or not student_id:
            return False
        try:
            resp = self.session.patch(
                f"{self.url}/rest/v1/students?student_id=eq.{student_id.strip()}",
                headers=self._get_headers(prefer="return=minimal"),
                json={"is_active": is_active},
                timeout=self.timeout
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Error updating status for {student_id}: {e}")
            self._last_error = str(e)
            return False

    def update_student_bus(self, student_id: str, new_bus_id: str) -> bool:
        """Reassign student to a new bus."""
        if not self.is_configured() or not student_id:
            return False
        try:
            self.ensure_bus(new_bus_id)
            resp = self.session.patch(
                f"{self.url}/rest/v1/students?student_id=eq.{student_id.strip()}",
                headers=self._get_headers(prefer="return=minimal"),
                json={"bus_id": new_bus_id.strip()},
                timeout=self.timeout
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Error reassigning bus for {student_id}: {e}")
            self._last_error = str(e)
            return False

    def delete_student(self, student_id: str) -> bool:
        """Permanently remove student: deletes biometric vector and marks inactive/purged."""
        if not self.is_configured() or not student_id:
            return False
        clean_id = student_id.strip()
        try:
            # 1. Purge biometrics in student_biometrics (zero-out or delete)
            import numpy as np
            zero_bytes = np.zeros(512, dtype=np.float32).tobytes()
            self.session.post(
                f"{self.url}/rest/v1/student_biometrics",
                headers=self._get_headers(with_token=True, prefer="resolution=merge-duplicates"),
                json={
                    "student_id": clean_id,
                    "embedding": "\\x" + zero_bytes.hex(),
                    "dimension": 512,
                    "model_name": "deleted"
                },
                timeout=self.timeout
            )
            # 2. Try hard delete on student row
            del_resp = self.session.delete(
                f"{self.url}/rest/v1/students?student_id=eq.{clean_id}",
                headers=self._get_headers(prefer="return=minimal"),
                timeout=self.timeout
            )
            if del_resp.status_code in (200, 204):
                return True

            # If hard delete is blocked by RLS/FK, mark is_active=false
            patch_resp = self.session.patch(
                f"{self.url}/rest/v1/students?student_id=eq.{clean_id}",
                headers=self._get_headers(prefer="return=minimal"),
                json={"is_active": False},
                timeout=self.timeout
            )
            return patch_resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Error deleting student {clean_id}: {e}")
            self._last_error = str(e)
            return False


    # =========================================================================
    # BIOMETRICS OPERATIONS (Protected with x-fleet-sync-token)
    # =========================================================================

    def upload_biometrics(
        self,
        student_id: str,
        embedding_bytes: bytes,
        model_name: str = "buffalo_sc"
    ) -> bool:
        """Upload raw 2048-byte float32 ArcFace embedding as hex string."""
        if not self.is_configured() or not student_id or not embedding_bytes:
            return False
        try:
            hex_str = "\\x" + embedding_bytes.hex()
            payload = {
                "student_id": student_id.strip(),
                "embedding": hex_str,
                "dimension": 512,
                "model_name": model_name
            }
            resp = self.session.post(
                f"{self.url}/rest/v1/student_biometrics",
                headers=self._get_headers(with_token=True, prefer="resolution=merge-duplicates"),
                json=payload,
                timeout=self.timeout
            )
            if resp.status_code in (200, 201):
                return True
            self._last_error = f"HTTP {resp.status_code}: {resp.text}"
            logger.error(f"Failed to upload biometrics: {self._last_error}")
            return False
        except Exception as e:
            logger.error(f"Error uploading biometrics: {e}")
            self._last_error = str(e)
            return False

    def get_biometrics_for_students(self, student_ids: List[str]) -> Dict[str, bytes]:
        """Fetch face embeddings for a list of student IDs. Returns {student_id: raw_bytes}."""
        if not self.is_configured() or not student_ids:
            return {}
        try:
            # Query in batches or in operator
            id_list_str = ",".join(s.strip() for s in student_ids)
            resp = self.session.get(
                f"{self.url}/rest/v1/student_biometrics?student_id=in.({id_list_str})&select=student_id,embedding",
                headers=self._get_headers(with_token=True),
                timeout=self.timeout
            )
            if resp.status_code != 200:
                logger.error(f"Failed to download biometrics: HTTP {resp.status_code} {resp.text}")
                return {}

            result: Dict[str, bytes] = {}
            for row in resp.json():
                sid = row.get("student_id")
                raw_emb = row.get("embedding")
                if not sid or not raw_emb:
                    continue
                if isinstance(raw_emb, str):
                    if raw_emb.startswith("\\x"):
                        raw_emb = raw_emb[2:]
                    result[sid] = bytes.fromhex(raw_emb)
                elif isinstance(raw_emb, bytes):
                    result[sid] = raw_emb
            return result
        except Exception as e:
            logger.error(f"Error fetching biometrics: {e}")
            self._last_error = str(e)
            return {}

    # =========================================================================
    # ATTENDANCE OPERATIONS
    # =========================================================================

    def upload_attendance_batch(self, records: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        """Upload attendance records with idempotent conflict handling.
        
        Returns:
            Tuple of (successful_event_ids, failed_event_ids)
        """
        if not self.is_configured() or not records:
            return [], []

        allowed = {
            "event_id", "student_id", "bus_id", "attendance_date",
            "attendance_time", "status", "device_id"
        }
        clean_records = []
        for r in records:
            item = {k: v for k, v in r.items() if k in allowed}
            # Enforce title-cased status
            if "status" in item:
                item["status"] = str(item["status"]).capitalize()
            clean_records.append(item)

        try:
            resp = self.session.post(
                f"{self.url}/rest/v1/attendance",
                headers=self._get_headers(prefer="resolution=merge-duplicates"),
                json=clean_records,
                timeout=self.timeout
            )
            if resp.status_code in (200, 201):
                return [r["event_id"] for r in clean_records if "event_id" in r], []
            
            logger.error(f"Batch attendance upload failed: HTTP {resp.status_code} {resp.text}")
            self._last_error = f"HTTP {resp.status_code}: {resp.text}"
            # Fall back to single record uploads
            return self._upload_attendance_individual(clean_records)
        except Exception as e:
            logger.error(f"Network error in batch attendance upload: {e}")
            self._last_error = str(e)
            return [], [r["event_id"] for r in clean_records if "event_id" in r]

    def _upload_attendance_individual(self, records: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        """Individual upload fallback to isolate any faulty row."""
        success = []
        failed = []
        for r in records:
            eid = r.get("event_id")
            try:
                resp = self.session.post(
                    f"{self.url}/rest/v1/attendance",
                    headers=self._get_headers(prefer="resolution=merge-duplicates"),
                    json=r,
                    timeout=self.timeout
                )
                if resp.status_code in (200, 201):
                    if eid:
                        success.append(eid)
                elif resp.status_code == 409 or "23505" in resp.text:
                    # Already exists in cloud -> treat as synced
                    if eid:
                        success.append(eid)
                else:
                    if eid:
                        failed.append(eid)
            except Exception:
                if eid:
                    failed.append(eid)
        return success, failed

    def get_attendance(
        self,
        date_str: Optional[str] = None,
        bus_id: Optional[str] = None,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Query attendance history with optional filters."""
        if not self.is_configured():
            return []
        try:
            params = "select=*&order=attendance_date.desc,attendance_time.desc"
            if date_str:
                params += f"&attendance_date=eq.{date_str.strip()}"
            if bus_id:
                params += f"&bus_id=eq.{bus_id.strip()}"
            if limit:
                params += f"&limit={limit}"

            resp = self.session.get(
                f"{self.url}/rest/v1/attendance?{params}",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            if resp.status_code == 200:
                return resp.json()
            logger.error(f"Failed to query attendance: HTTP {resp.status_code} {resp.text}")
            return []
        except Exception as e:
            logger.error(f"Error querying attendance: {e}")
            self._last_error = str(e)
            return []
