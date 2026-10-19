"""Centralized Supabase Service Module for Automatic School Bus Attendance System.

Provides robust, thread-safe online operations for buses, students, biometrics,
and attendance records with proper error handling, retry awareness, and offline tolerance.
"""
import os
import re
import json
import logging
from typing import List, Dict, Optional, Tuple, Any, TYPE_CHECKING, cast
from datetime import datetime

if TYPE_CHECKING:
    from supabase import Client

try:
    from supabase import create_client, Client  # type: ignore
    _SUPABASE_AVAILABLE = True
except ImportError:
    create_client = None
    _SUPABASE_AVAILABLE = False

try:
    from supabase.lib.client_options import SyncClientOptions
except Exception:  # pragma: no cover - older/newer supabase builds
    SyncClientOptions = None

from src.config import (
    SUPABASE_URL,
    SUPABASE_KEY,
    DEFAULT_BUS_ID,
    DEVICE_ID,
    BIOMETRIC_CLOUD_SYNC,
    SYNC_HTTP_TIMEOUT,
    ID_CROSSWALK_PATH,
)

logger = logging.getLogger(__name__)


class IdCrosswalk:
    """Explicit local <-> cloud identifier mapping applied only at the sync boundary.

    Identifiers are always treated as strings so leading zeroes are preserved
    ('01' != '1'). Identifiers that are not listed map to themselves. Local IDs
    and embeddings are never rewritten.
    """

    def __init__(
        self,
        students: Optional[Dict[str, str]] = None,
        buses: Optional[Dict[str, str]] = None
    ) -> None:
        self.students: Dict[str, str] = {k: v for k, v in (students or {}).items()}
        self.buses: Dict[str, str] = {k: v for k, v in (buses or {}).items()}
        self._students_rev = {v: k for k, v in self.students.items()}
        self._buses_rev = {v: k for k, v in self.buses.items()}

    @classmethod
    def load(cls, path: Optional[str] = None) -> "IdCrosswalk":
        """Load the crosswalk JSON. A missing/invalid file yields an identity mapping."""
        path = path or ID_CROSSWALK_PATH
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(students=data.get("students"), buses=data.get("buses"))
        except FileNotFoundError:
            return cls()
        except Exception as e:
            logger.error(f"Could not read ID crosswalk '{path}': {e}. Using identity mapping.")
            return cls()

    def student_to_cloud(self, student_id: Any) -> str:
        sid = str(student_id).strip()
        return self.students.get(sid, sid)

    def bus_to_cloud(self, bus_id: Any) -> str:
        bid = str(bus_id).strip()
        if bid in self.buses:
            return self.buses[bid]
        # Case-insensitive fallback to prevent accidental duplicate buses (e.g. BUS01 vs Bus01)
        bid_lower = bid.lower()
        for k, v in self.buses.items():
            if k.lower() == bid_lower or v.lower() == bid_lower:
                return v
        return bid

    def student_to_local(self, cloud_student_id: Any) -> str:
        sid = str(cloud_student_id).strip()
        return self._students_rev.get(sid, sid)

    def bus_to_local(self, cloud_bus_id: Any) -> str:
        bid = str(cloud_bus_id).strip()
        return self._buses_rev.get(bid, bid)


class SupabaseService:
    """Manages cloud communication with Supabase PostgreSQL."""

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        crosswalk: Optional[IdCrosswalk] = None
    ) -> None:
        """Initialize the Supabase client.

        Args:
            url: Optional Supabase project URL (defaults to SUPABASE_URL from config).
            key: Optional Supabase Anon Key (defaults to SUPABASE_KEY from config).
            crosswalk: Optional explicit local->cloud ID mapping (defaults to id_crosswalk.json).
        """
        self.url = (SUPABASE_URL if url is None else url).strip()
        self.key = (SUPABASE_KEY if key is None else key).strip()
        self.client: Optional[Client] = None
        self._last_error: Optional[str] = None
        self.crosswalk: IdCrosswalk = crosswalk if crosswalk is not None else IdCrosswalk.load()
        self.biometric_sync_enabled: bool = BIOMETRIC_CLOUD_SYNC
        # Per-record outcome of the most recent attendance upload:
        # {event_id: (state, detail)} where state is ok | conflict | rejected | network
        self.last_upload_results: Dict[str, Tuple[str, Optional[str]]] = {}

        if not _SUPABASE_AVAILABLE:
            self._last_error = "supabase package not installed. Run 'pip install supabase'."
            return

        if self.is_configured():
            try:
                options = None
                if SyncClientOptions is not None:
                    try:
                        options = SyncClientOptions(postgrest_client_timeout=SYNC_HTTP_TIMEOUT)
                    except Exception:
                        options = None
                if create_client is not None:
                    if options is not None:
                        self.client = create_client(self.url, self.key, options)
                    else:
                        self.client = create_client(self.url, self.key)
                else:
                    self.client = None
            except Exception as e:
                self._last_error = f"Failed to initialize Supabase client: {e}"
                self.client = None

    def is_configured(self) -> bool:
        """Return True if both URL and Key are provided."""
        return bool(self.url and self.key and not self.url.startswith("https://your-project"))

    @staticmethod
    def _error_code(exc: Exception) -> Optional[str]:
        """Extract the PostgREST/PostgreSQL error code (e.g. '23505'), or None for network errors."""
        try:
            json_fn = getattr(exc, "json", None)
            if callable(json_fn):
                payload = json_fn()
                if isinstance(payload, dict) and payload.get("code"):
                    return str(payload["code"])
        except Exception:
            pass
        match = re.search(r"'code':\s*'([^']+)'", str(exc))
        return match.group(1) if match else None

    def test_connection(self) -> Tuple[bool, str]:
        """Test connection to Supabase and verify basic table access.

        Returns:
            Tuple of (success: bool, status_message: str).
        """
        if not _SUPABASE_AVAILABLE:
            return False, "Python supabase library is not installed."
        if not self.is_configured():
            return False, "Supabase credentials are not configured in .env."
        if self.client is None:
            return False, self._last_error or "Supabase client not initialized."

        try:
            # Query buses table lightly
            res = self.client.table("buses").select("bus_id").limit(1).execute()
            return True, "Successfully connected to Supabase cloud database."
        except Exception as e:
            err_msg = str(e)
            self._last_error = err_msg
            return False, f"Supabase connection failed: {err_msg}"

    # =========================================================================
    # BUS OPERATIONS
    # =========================================================================

    def get_all_buses(self) -> List[Dict[str, Any]]:
        """Fetch all buses from the central database."""
        if not self.client:
            return []
        try:
            res = self.client.table("buses").select("*").order("bus_id").execute()
            return [cast(Dict[str, Any], x) for x in res.data] if res.data else []
        except Exception as e:
            logger.error(f"Error fetching buses from Supabase: {e}")
            self._last_error = str(e)
            return []

    def bus_exists(self, cloud_bus_id: str) -> Optional[bool]:
        """Return True/False if the (already cloud-mapped) bus exists, None if unknown (error)."""
        if not self.client or not cloud_bus_id:
            return None
        clean_id = cloud_bus_id.strip()
        try:
            res = self.client.table("buses").select("bus_id").eq("bus_id", clean_id).limit(1).execute()
            return bool(res.data)
        except Exception as e:
            self._last_error = str(e)
            return None

    def upsert_bus(
        self,
        bus_id: str,
        bus_name: Optional[str] = None,
        is_active: bool = True
    ) -> bool:
        """Upsert a bus record into the cloud database (local bus ID is mapped via the crosswalk)."""
        if not self.client or not bus_id:
            return False
        try:
            cloud_bus_id = self.crosswalk.bus_to_cloud(bus_id)
            payload = {
                "bus_id": cloud_bus_id,
                "bus_name": bus_name.strip() if bus_name else f"Bus {cloud_bus_id}",
                "is_active": is_active,
            }
            self.client.table("buses").upsert(payload, on_conflict="bus_id").execute()
            return True
        except Exception as e:
            logger.error(f"Error upserting bus {bus_id}: {e}")
            self._last_error = str(e)
            return False

    def ensure_bus(self, bus_id: str, bus_name: Optional[str] = None) -> bool:
        """Create the bus only if it does not already exist. Never creates duplicate buses or overwrites existing."""
        if not self.client or not bus_id:
            return False
        cloud_bus_id = self.crosswalk.bus_to_cloud(bus_id)
        exists = self.bus_exists(cloud_bus_id)
        if exists is None:
            return False
        if exists:
            return True
        try:
            self.client.table("buses").insert({
                "bus_id": cloud_bus_id,
                "bus_name": bus_name.strip() if bus_name else f"Bus {cloud_bus_id}",
                "is_active": True,
            }).execute()  # plain insert: fails (23505) instead of overwriting an existing row
            return True
        except Exception as e:
            logger.error(f"Error creating bus {cloud_bus_id}: {e}")
            self._last_error = str(e)
            return False

    # =========================================================================
    # STUDENT OPERATIONS
    # =========================================================================

    def get_all_students(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Fetch student profiles from Supabase.

        Args:
            active_only: If True, only returns active students (is_active = TRUE).
        """
        if not self.client:
            return []
        try:
            query = self.client.table("students").select("*")
            if active_only:
                query = query.eq("is_active", True)
            res = query.order("student_id").execute()
            return [cast(Dict[str, Any], x) for x in res.data] if res.data else []
        except Exception as e:
            logger.error(f"Error fetching students from Supabase: {e}")
            self._last_error = str(e)
            return []

    def upsert_student(
        self,
        student_id: str,
        name: str,
        class_name: str,
        bus_id: str,
        is_active: bool = True,
        insert_only: bool = False
    ) -> bool:
        """Upsert a student profile into Supabase.

        Identifiers are mapped through the crosswalk. The assigned bus must already
        exist in the cloud (to satisfy the foreign key); it is never created
        implicitly, so a differently-cased duplicate bus can not appear.
        With insert_only=True an existing student row is never overwritten (the
        insert fails instead); used by the migration tool.
        """
        if not self.client or not student_id:
            return False
        try:
            cloud_bus_id = self.crosswalk.bus_to_cloud(bus_id)
            exists = self.bus_exists(cloud_bus_id)
            if not exists:
                self._last_error = (
                    f"Bus '{cloud_bus_id}' not found in cloud (or lookup failed); "
                    f"student {student_id} not uploaded."
                )
                logger.warning(self._last_error)
                return False

            payload = {
                "student_id": self.crosswalk.student_to_cloud(student_id),
                "name": name.strip(),
                "class_name": class_name.strip(),
                "bus_id": cloud_bus_id,
                "is_active": is_active,
            }
            if insert_only:
                self.client.table("students").insert(payload).execute()
            else:
                self.client.table("students").upsert(payload, on_conflict="student_id").execute()
            return True
        except Exception as e:
            logger.error(f"Error upserting student {student_id}: {e}")
            self._last_error = str(e)
            return False

    # =========================================================================
    # STUDENT BIOMETRICS (Dedicated Table)
    # =========================================================================

    def upload_student_biometrics(
        self,
        student_id: str,
        embedding_bytes: bytes,
        model_name: str = "buffalo_sc"
    ) -> bool:
        """Upload raw 512-D float32 ArcFace embedding vector to student_biometrics table.

        Stores embedding as hex-encoded string for clean PostgreSQL BYTEA transmission.
        Disabled unless BIOMETRIC_CLOUD_SYNC is explicitly enabled: face templates stay local.
        """
        if not self.biometric_sync_enabled:
            self._last_error = "Biometric cloud sync is disabled (BIOMETRIC_CLOUD_SYNC=false)."
            return False
        if not self.client or not student_id or not embedding_bytes:
            return False
        try:
            # PostgreSQL bytea accepts hex representation '\\x...'
            hex_str = "\\x" + embedding_bytes.hex()
            payload = {
                "student_id": self.crosswalk.student_to_cloud(student_id),
                "embedding": hex_str,
                "dimension": 512,
                "model_name": model_name,
            }
            self.client.table("student_biometrics").upsert(
                payload, on_conflict="student_id"
            ).execute()
            return True
        except Exception as e:
            logger.error(f"Error uploading biometrics for {student_id}: {e}")
            self._last_error = str(e)
            return False

    def get_all_biometrics(self) -> List[Dict[str, Any]]:
        """Fetch all biometric embeddings for local fleet caching (disabled unless enabled)."""
        if not self.biometric_sync_enabled or not self.client:
            return []
        try:
            res = self.client.table("student_biometrics").select("student_id, embedding, model_name").execute()
            records = []
            for row in (res.data or []):
                if not isinstance(row, dict):
                    continue
                raw_emb = row.get("embedding")
                if isinstance(raw_emb, str):
                    if raw_emb.startswith("\\x"):
                        raw_emb = raw_emb[2:]
                    byte_data = bytes.fromhex(raw_emb)
                elif isinstance(raw_emb, bytes):
                    byte_data = raw_emb
                else:
                    byte_data = None

                if byte_data:
                    records.append({
                        "student_id": self.crosswalk.student_to_local(str(row["student_id"])),
                        "embedding": byte_data,
                        "model_name": row.get("model_name", "buffalo_sc")
                    })
            return records
        except Exception as e:
            logger.error(f"Error fetching biometrics: {e}")
            self._last_error = str(e)
            return []

    # =========================================================================
    # ATTENDANCE OPERATIONS
    # =========================================================================

    def _to_cloud_attendance(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Map a local attendance record to the cloud schema (IDs, status casing, device_id)."""
        allowed = {
            "event_id", "student_id", "bus_id", "attendance_date",
            "attendance_time", "status", "device_id"
        }
        payload = {k: v for k, v in record.items() if k in allowed}
        if payload.get("student_id") is not None:
            payload["student_id"] = self.crosswalk.student_to_cloud(payload["student_id"])
        if payload.get("bus_id") is not None:
            payload["bus_id"] = self.crosswalk.bus_to_cloud(payload["bus_id"])
        if payload.get("status") is not None:
            payload["status"] = str(payload["status"]).strip().capitalize()
        device = payload.get("device_id")
        if device is not None and str(device).strip().lower() in ("", "null", "none"):
            payload["device_id"] = None
        return payload

    def _find_attendance_by_triple(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Look up the cloud row holding a (student_id, attendance_date, bus_id) combination."""
        if not self.client:
            return None
        try:
            res = (
                self.client.table("attendance")
                .select("event_id, student_id, attendance_date, attendance_time, bus_id, status")
                .eq("student_id", payload["student_id"])
                .eq("attendance_date", payload["attendance_date"])
                .eq("bus_id", payload["bus_id"])
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return cast(Dict[str, Any], rows[0]) if rows else None
        except Exception as e:
            self._last_error = str(e)
            return None

    def _upload_single_attendance(self, payload: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """Upsert one cloud-mapped record and classify the outcome."""
        if not self.client:
            return "network", "Supabase client not initialized"
        try:
            self.client.table("attendance").upsert(payload, on_conflict="event_id").execute()
            return "ok", None
        except Exception as e:
            msg = str(e)
            code = self._error_code(e)
            if code is None:
                return "network", msg
            if code == "23505":
                existing = self._find_attendance_by_triple(payload)
                if existing is not None:
                    if existing.get("event_id") == payload.get("event_id"):
                        return "ok", None
                    return "conflict", (
                        f"cloud row {existing.get('event_id')} already holds this "
                        f"student/date/bus combination"
                    )
                return "conflict", f"unique constraint violation (23505): {msg}"
            return "rejected", msg

    def upload_attendance_batch(
        self,
        records: List[Dict[str, Any]],
        verify: bool = False
    ) -> Tuple[int, List[str], Optional[str]]:
        """Idempotently upload a batch of attendance events to Supabase.

        Records use LOCAL identifiers and are mapped through the crosswalk. Buses and
        students are never created implicitly. If the batch is rejected by the server
        (foreign key, duplicate, ...) it is retried record-by-record so one bad record
        can not block the rest. Per-record outcomes are exposed in `last_upload_results`.

        Args:
            records: List of dictionaries matching the attendance table schema:
                     [{event_id, student_id, attendance_date, attendance_time, bus_id, status, device_id}, ...]
            verify: If True, read the uploaded rows back and only report rows found in the cloud.

        Returns:
            Tuple of (uploaded_count: int, uploaded_event_ids: List[str], error: Optional[str]).
            uploaded_event_ids only contains events confirmed in the cloud.
        """
        self.last_upload_results = {}
        if not self.client or not records:
            return 0, [], None

        payload = [self._to_cloud_attendance(r) for r in records if "event_id" in r]
        if not payload:
            return 0, [], None

        results: Dict[str, Tuple[str, Optional[str]]] = {}
        try:
            # Upsert with on_conflict="event_id" for idempotent retry safety
            self.client.table("attendance").upsert(
                payload, on_conflict="event_id"
            ).execute()
            for p in payload:
                results[p["event_id"]] = ("ok", None)
        except Exception as e:
            err_str = str(e)
            logger.error(f"Error uploading attendance batch: {err_str}")
            self._last_error = err_str
            if self._error_code(e) is None:
                # No server response: network problem. Nothing is confirmed.
                for p in payload:
                    results[p["event_id"]] = ("network", err_str)
            else:
                # Server rejected the batch: isolate the offending record(s).
                for p in payload:
                    results[p["event_id"]] = self._upload_single_attendance(p)

        ok_ids = [eid for eid, (state, _) in results.items() if state == "ok"]

        if verify and ok_ids:
            try:
                res = self.client.table("attendance").select("event_id").in_("event_id", ok_ids).execute()
                found = {
                    str(row["event_id"]) for row in (res.data or [])
                    if isinstance(row, dict) and "event_id" in row
                }
                for eid in ok_ids:
                    if eid not in found:
                        results[eid] = ("rejected", "not found on read-back verification")
                ok_ids = [eid for eid in ok_ids if eid in found]
            except Exception as e:
                for eid in ok_ids:
                    results[eid] = ("network", f"read-back verification failed: {e}")
                ok_ids = []

        self.last_upload_results = results
        failures = [(eid, st, d) for eid, (st, d) in results.items() if st != "ok"]
        err: Optional[str] = None
        if failures:
            err = "; ".join(f"{eid}: {st} ({d})" for eid, st, d in failures[:3])
            if len(failures) > 3:
                err += f"; ... {len(failures) - 3} more"
            self._last_error = err
        return len(ok_ids), ok_ids, err

    def get_attendance_for_date(
        self,
        attendance_date: str,
        bus_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve cloud attendance records for a specific date and optional bus."""
        if not self.client:
            return []
        try:
            query = self.client.table("attendance").select(
                "event_id, student_id, attendance_date, attendance_time, bus_id, status, device_id, created_at, students(name, class_name)"
            ).eq("attendance_date", attendance_date)

            if bus_id and bus_id not in ("ALL BUSES", "All Buses"):
                query = query.eq("bus_id", bus_id)

            res = query.order("attendance_time").execute()
            formatted = []
            for row in (res.data or []):
                if not isinstance(row, dict):
                    continue
                stu_raw = row.get("students")
                stu_info = stu_raw if isinstance(stu_raw, dict) else {}
                formatted.append({
                    "event_id": row.get("event_id"),
                    "student_id": row.get("student_id"),
                    "name": stu_info.get("name", f"Student {row.get('student_id')}"),
                    "class_name": stu_info.get("class_name", "--"),
                    "attendance_date": str(row.get("attendance_date")),
                    "attendance_time": str(row.get("attendance_time")),
                    "bus_id": row.get("bus_id"),
                    "status": row.get("status", "Present"),
                    "device_id": row.get("device_id"),
                    "created_at": str(row.get("created_at")),
                })
            return formatted
        except Exception as e:
            logger.error(f"Error retrieving attendance for date {attendance_date}: {e}")
            self._last_error = str(e)
            return []
