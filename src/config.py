"""Configuration constants for the Automatic School Bus Attendance System."""

# Default Bus ID identifier
DEFAULT_BUS_ID: str = "BUS01"

# Database storage path
DEFAULT_DB_PATH: str = "data/attendance.db"

# Recognition threshold (cosine similarity cutoff)
DEFAULT_SIMILARITY_THRESHOLD: float = 0.50

# Recognition confirmation settings:
# Number of consistent observations required before triggering attendance
REQUIRED_CONFIRMATIONS: int = 3

# Time window in seconds in which the confirmations must occur
CONFIRMATION_WINDOW_SECONDS: float = 2.0

# Temporary on-screen visual notification duration (in seconds)
NOTIFICATION_DURATION_SECONDS: float = 3.0
