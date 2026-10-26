"""Configuration constants for the Automatic School Bus Attendance System."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Automatically load environment variables from .env in project root if present
# When frozen (PyInstaller), anchor to the executable directory so .env and data/attendance.db
# remain outside the extracted _internal folder and are not overwritten during updates.
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_env_path = os.path.join(_PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)
else:
    load_dotenv()

# Default Bus ID identifier
DEFAULT_BUS_ID: str = os.environ.get("DEFAULT_BUS_ID", "BUS01").strip()

# Hardware Device identifier (for Raspberry Pi 5 / bus computer audit trail)
DEVICE_ID: str = os.environ.get("DEVICE_ID", f"{DEFAULT_BUS_ID}_DEV_01").strip()

# Database storage path (Anchored to project root so working directory changes don't fracture the DB)
_env_db = os.environ.get("DATABASE_PATH", "").strip()
DEFAULT_DB_PATH: str = _env_db if _env_db else os.path.join(_PROJECT_ROOT, "data", "attendance.db")

# Supabase Cloud Configuration
_EMBEDDED_DEFAULT_URL = "https://iqxvzpcrzjkmninoofem.supabase.co"
_EMBEDDED_DEFAULT_KEY = "sb_publishable_1-EgL38pVxCRx9MDq0OtrQ_0E_z4LwB"

SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "").strip() or _EMBEDDED_DEFAULT_URL
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "").strip() or _EMBEDDED_DEFAULT_KEY

# Cloud Synchronization Settings
SYNC_INTERVAL_SECONDS: float = float(os.environ.get("SYNC_INTERVAL_SECONDS", "20.0"))
SYNC_BATCH_SIZE: int = int(os.environ.get("SYNC_BATCH_SIZE", "50"))
SYNC_MAX_RETRIES: int = int(os.environ.get("SYNC_MAX_RETRIES", "5"))


def _env_flag(name: str, default: bool) -> bool:
    """Parse a boolean environment flag (1/true/yes/on)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Safety gates (all default to the safest value; opt in explicitly via .env)
# Background upload of pending attendance only starts when SYNC_ENABLED is true.
SYNC_ENABLED: bool = _env_flag("SYNC_ENABLED", False)
# Downstream pulls of the cloud roster/buses into local SQLite are opt-in.
PULL_STUDENTS: bool = _env_flag("PULL_STUDENTS", False)
PULL_BUSES: bool = _env_flag("PULL_BUSES", False)
# Face embeddings stay local unless this is explicitly enabled.
BIOMETRIC_CLOUD_SYNC: bool = _env_flag("BIOMETRIC_CLOUD_SYNC", False)
# Network timeout (seconds) for Supabase REST calls, so a dead link cannot hang the worker.
SYNC_HTTP_TIMEOUT: float = float(os.environ.get("SYNC_HTTP_TIMEOUT", "15"))
def _resolve_crosswalk_path() -> str:
    env_val = os.environ.get("ID_CROSSWALK_PATH", "").strip()
    if env_val:
        return env_val
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            bundled = os.path.join(meipass, "id_crosswalk.json")
            if os.path.exists(bundled):
                return bundled
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, "id_crosswalk.json")
        if os.path.exists(exe_path):
            return exe_path
    return os.path.join(_PROJECT_ROOT, "id_crosswalk.json")


# Explicit local<->cloud identifier crosswalk (JSON). Optional.
ID_CROSSWALK_PATH: str = _resolve_crosswalk_path()

# Recognition threshold (cosine similarity cutoff)
DEFAULT_SIMILARITY_THRESHOLD: float = 0.50

# Recognition confirmation settings:
# Number of consistent observations required before triggering attendance
REQUIRED_CONFIRMATIONS: int = 3

# Time window in seconds in which the confirmations must occur
CONFIRMATION_WINDOW_SECONDS: float = 2.0

# Temporary on-screen visual notification duration (in seconds)
NOTIFICATION_DURATION_SECONDS: float = 3.0
