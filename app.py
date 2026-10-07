"""Automatic School Bus Attendance System - Main Application Entry Point.

Fleet Attendance Suite V4.2 (2026)
Launch the unified desktop application with one command:
    python app.py
or:
    python dashboard.py
"""
import sys
from dashboard import run_dashboard
from src.config import DEFAULT_DB_PATH

def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    run_dashboard(db_path=db_path)

if __name__ == "__main__":
    main()
