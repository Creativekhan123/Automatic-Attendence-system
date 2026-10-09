"""Automatic School Bus Attendance System - Main Application Entry Point.

Fleet Attendance Suite V4.2 (2026)
Launch the unified desktop application with one command:
    python app.py
or:
    python dashboard.py
"""
import sys
import os
import multiprocessing
from src.config import DEFAULT_DB_PATH


def main() -> None:
    # Required for frozen Windows executables using multiprocessing
    multiprocessing.freeze_support()

    # When frozen, set cwd to the exe's directory so relative paths work
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(exe_dir)

    # If executed with arguments to run the attendance camera engine:
    # e.g.: AttendanceSystem.exe --run-attendance --bus-id BUS01 --camera-index 0
    if len(sys.argv) > 1 and sys.argv[1] == "--run-attendance":
        # Remove the internal flag so main.py's argparse sees the real args
        sys.argv.pop(1)
        import main as attendance_main
        attendance_main.main()
        return

    from dashboard import run_dashboard
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    run_dashboard(db_path=db_path)


if __name__ == "__main__":
    main()
