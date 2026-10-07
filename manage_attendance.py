import sys
from datetime import datetime
from src.database import Database
from src.config import DEFAULT_BUS_ID, DEFAULT_DB_PATH


def display_today_attendance(db: Database, bus_id: str) -> None:
    """Display today's attendance records and unpresent students for the configured bus."""
    today_date = datetime.now().strftime("%Y-%m-%d")
    today_records = db.get_attendance_for_date(attendance_date=today_date, bus_id=bus_id)
    all_students = db.get_all_students()
    not_yet_present = db.get_registered_students_not_present_today(bus_id=bus_id)

    total_registered = len(all_students)
    total_present = len(today_records)

    print("\n--------------------------------------------------")
    print("Today's Attendance")
    print(f"Date: {today_date}")
    print(f"Bus: {bus_id}")
    print("--------------------------------------------------")
    print(f"{'Student ID':<12} | {'Name':<18} | {'Time'}")
    print("--------------------------------------------------")

    if today_records:
        for r in today_records:
            print(f"{r['student_id']:<12} | {r['name']:<18} | {r['attendance_time']}")
    else:
        print("No attendance records found for today.")

    print("--------------------------------------------------")
    print(f"Present: {total_present} / {total_registered}")

    if not_yet_present:
        print("\nNot Yet Present:")
        for s in not_yet_present:
            print(f"* {s['student_id']} | {s['name']} ({s.get('class_name', '')})")
    elif total_registered > 0:
        print("\nAll registered students are marked Present!")
    else:
        print("\nNo students are currently registered in the system.")
    print("--------------------------------------------------\n")


def clear_today_attendance(db: Database, bus_id: str) -> None:
    """Prompt for confirmation and clear today's attendance for the current bus."""
    today_date = datetime.now().strftime("%Y-%m-%d")

    print("\nYou are about to clear today's attendance.\n")
    print(f"Date: {today_date}")
    print(f"Bus: {bus_id}\n")
    print("This will remove attendance records for this date and bus only.\n")

    confirm = input("Type YES to continue: ").strip()
    if confirm == "YES":
        rows_deleted = db.clear_today_attendance(bus_id=bus_id, attendance_date=today_date)
        print("\nToday's attendance has been cleared.")
        print(f"Records removed: {rows_deleted}")
        print("Student registrations were not affected.\n")
    else:
        print("\nOperation cancelled. No records were deleted.\n")


def clear_all_attendance(db: Database) -> None:
    """Prompt for strong confirmation and clear ALL attendance records."""
    print("\n========================================")
    print("WARNING!")
    print("========================================")
    print("This will permanently delete ALL attendance records.\n")
    print("Student registrations will NOT be deleted.\n")

    confirm = input("Type:\n\nDELETE ALL\n\nto continue: ").strip()
    if confirm == "DELETE ALL":
        rows_deleted = db.clear_all_attendance()
        print("\nAll attendance records have been cleared.")
        print(f"Total records removed: {rows_deleted}")
        print("Student registrations and embeddings remain intact.\n")
    else:
        print("\nOperation cancelled. No records were deleted.\n")


def main() -> None:
    """Run interactive menu loop for attendance management."""
    bus_id = DEFAULT_BUS_ID
    db = Database(db_path=DEFAULT_DB_PATH)

    while True:
        print("========================================")
        print("ATTENDANCE TEST / MANAGEMENT")
        print("========================================")
        print("1. View today's attendance")
        print("2. Clear today's attendance for current bus")
        print("3. Clear ALL attendance records")
        print("4. Exit")
        print("----------------------------------------")

        choice = input("Choose an option: ").strip()

        if choice == "1":
            display_today_attendance(db, bus_id)
        elif choice == "2":
            clear_today_attendance(db, bus_id)
        elif choice == "3":
            clear_all_attendance(db)
        elif choice == "4":
            print("Exiting attendance management. Goodbye!")
            sys.exit(0)
        else:
            print("\nInvalid choice. Please choose 1, 2, 3, or 4.\n")


if __name__ == "__main__":
    main()
