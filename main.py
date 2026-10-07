import argparse
import sys
import time
from datetime import datetime
import cv2

from src.camera import Camera
from src.face_recognizer import FaceRecognizer
from src.database import Database
from src.attendance import AttendanceEngine
from src.config import (
    DEFAULT_BUS_ID,
    DEFAULT_DB_PATH,
    DEFAULT_SIMILARITY_THRESHOLD,
    REQUIRED_CONFIRMATIONS,
    CONFIRMATION_WINDOW_SECONDS,
    NOTIFICATION_DURATION_SECONDS
)


def print_attendance_summary(engine: AttendanceEngine) -> None:
    """Print a clean summary of today's attendance session to the console."""
    summary = engine.get_attendance_summary()
    print("\n========================================================")
    print(f"       TODAY'S ATTENDANCE SUMMARY ({summary['date']})     ")
    print(f"       Bus ID: {summary['bus_id']}                       ")
    print("========================================================")
    print(f"Registered Students : {summary['total_registered']}")
    print(f"Marked Present      : {summary['total_present']}")
    print(f"Not Yet Present     : {summary['not_yet_present_count']}")
    print("--------------------------------------------------------")
    print(f"{'Student ID':<12} | {'Name':<18} | {'Time':<8} | {'Status'}")
    print("--------------------------------------------------------")
    if summary["present_records"]:
        for r in summary["present_records"]:
            print(f"{r['student_id']:<12} | {r['name']:<18} | {r['attendance_time']:<8} | {r['status']}")
    else:
        print("No students marked present yet.")
    print("========================================================\n")


def run(
    camera_index: int = 0,
    bus_id: str = DEFAULT_BUS_ID,
    db_path: str = DEFAULT_DB_PATH,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    required_confirmations: int = REQUIRED_CONFIRMATIONS,
    confirmation_window: float = CONFIRMATION_WINDOW_SECONDS
) -> None:
    """Run the live camera feed, student face recognition, and automatic attendance engine.

    Args:
        camera_index: Device index of the webcam to use.
        bus_id: Identifier for the bus performing attendance.
        db_path: Path to the SQLite database.
        similarity_threshold: Cosine similarity cutoff for identity verification.
        required_confirmations: Consecutive observations needed to confirm attendance.
        confirmation_window: Time window in seconds for confirmation observations.
    """
    print("==========================================================")
    print(" Bus Attendance System - Part 3: Automatic Attendance      ")
    print("==========================================================")
    print(f"Session Bus ID: {bus_id}")
    print(f"Database File : {db_path}")
    print(f"Confirmation  : {required_confirmations} matches in {confirmation_window}s window")

    # 1. Initialize local SQLite database
    db = Database(db_path=db_path)
    registered_students = db.get_all_students()
    print(f"Loaded {len(registered_students)} registered student(s).")
    if not registered_students:
        print("Note: No students registered yet. Run 'python register_student.py' to enroll students.")

    # 2. Initialize Attendance Engine
    attendance_engine = AttendanceEngine(
        db=db,
        bus_id=bus_id,
        required_confirmations=required_confirmations,
        confirmation_window_seconds=confirmation_window
    )

    # 3. Initialize Face Recognizer model (loaded ONCE)
    print("\nLoading ArcFace recognition model...")
    try:
        recognizer = FaceRecognizer(
            model_name="buffalo_sc",
            det_size=(640, 640),
            similarity_threshold=similarity_threshold
        )
        print("Recognition model initialized successfully.")
    except Exception as e:
        print(f"Error initializing face recognition model: {e}")
        sys.exit(1)

    # 4. Connect to Camera
    print(f"Connecting to camera index: {camera_index}...")
    camera = Camera(camera_index=camera_index)
    if not camera.start():
        print(f"Error: Unable to open camera at index {camera_index}.")
        print("Please check that your webcam is connected and not in use by another app.")
        sys.exit(1)

    print("Camera initialized successfully.")
    window_title = f"Bus Attendance - {bus_id} (Q: Exit, S: Summary)"
    print("\nControls:")
    print(" - Press 'Q' in the camera window to exit.")
    print(" - Press 'S' to display the current attendance summary in console.")
    print("Live attendance engine running...\n")

    # Temporary visual banner state: (message_text, expire_timestamp, is_error)
    recent_notification = None

    last_db_refresh = time.time()

    try:
        while True:
            # Sync registered students periodically (every 5 seconds)
            now = time.time()
            if now - last_db_refresh > 5.0:
                registered_students = db.get_all_students()
                last_db_refresh = now

            ret, frame = camera.read_frame()
            if not ret or frame is None:
                print("Error: Failed to read frame from camera. Camera may have been disconnected.")
                break

            # Detect faces and extract embeddings
            faces = recognizer.extract_faces(frame)
            num_faces = len(faces)

            # Process each detected face
            for face in faces:
                bbox = [int(v) for v in face.bbox]
                x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

                # Identify against registered students
                _, matched_student, score = recognizer.identify_face(
                    face.embedding,
                    registered_students
                )

                if matched_student is not None:
                    # Feed recognition result into Attendance Engine
                    status, count, newly_marked = attendance_engine.process_recognition(matched_student)

                    student_name = matched_student["name"]
                    student_id = matched_student["student_id"]

                    if newly_marked:
                        print(f"[ATTENDANCE MARKED] {student_name} ({student_id}) marked Present on {bus_id} at {datetime.now().strftime('%H:%M:%S')}")
                        recent_notification = (
                            f"ATTENDANCE MARKED: {student_name} ({student_id})",
                            time.time() + NOTIFICATION_DURATION_SECONDS,
                            False
                        )

                    if status in ("PRESENT", "ALREADY PRESENT"):
                        box_color = (0, 255, 0)      # Green
                        label_line1 = f"{student_name} ({student_id})"
                        label_line2 = "ALREADY PRESENT" if status == "ALREADY PRESENT" else "PRESENT"
                    elif status == "CONFIRMING":
                        box_color = (0, 255, 255)    # Yellow
                        label_line1 = f"{student_name} ({student_id})"
                        label_line2 = f"CONFIRMING ({count}/{required_confirmations})"
                    else:  # DB ERROR
                        box_color = (0, 0, 255)
                        label_line1 = f"{student_name} ({student_id})"
                        label_line2 = "ERROR SAVING ATTENDANCE"
                        recent_notification = (
                            "Unable to save attendance. Database error.",
                            time.time() + NOTIFICATION_DURATION_SECONDS,
                            True
                        )

                else:
                    # Unrecognized face
                    box_color = (0, 0, 255)          # Red
                    label_line1 = "UNKNOWN"
                    label_line2 = ""

                # Draw face bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

                # Draw multi-line text badge above bounding box
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.55
                thickness = 2
                (w1, h1), _ = cv2.getTextSize(label_line1, font, font_scale, thickness)
                (w2, h2), _ = cv2.getTextSize(label_line2, font, 0.45, 1) if label_line2 else ((0, 0), 0)

                badge_w = max(w1, w2) + 12
                badge_h = h1 + (h2 + 8 if label_line2 else 0) + 10
                badge_y1 = max(y1 - badge_h - 5, 5)
                badge_y2 = badge_y1 + badge_h

                cv2.rectangle(frame, (x1, badge_y1), (x1 + badge_w, badge_y2), (0, 0, 0), -1)
                cv2.putText(frame, label_line1, (x1 + 6, badge_y1 + h1 + 4), font, font_scale, box_color, thickness, cv2.LINE_AA)
                if label_line2:
                    cv2.putText(frame, label_line2, (x1 + 6, badge_y1 + h1 + h2 + 8), font, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

            # Draw temporary toast notification banner if active
            if recent_notification:
                notif_msg, notif_expire, is_err = recent_notification
                if time.time() <= notif_expire:
                    bg_color = (0, 0, 180) if is_err else (0, 140, 0)
                    cv2.rectangle(frame, (10, frame.shape[0] - 50), (frame.shape[1] - 10, frame.shape[0] - 10), bg_color, -1)
                    cv2.putText(
                        frame,
                        notif_msg,
                        (25, frame.shape[0] - 22),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA
                    )
                else:
                    recent_notification = None

            # Top status banner overlay
            summary = attendance_engine.get_attendance_summary()
            top_bar_text = f"Bus: {bus_id} | Faces: {num_faces} | Present: {summary['total_present']}/{summary['total_registered']}"
            cv2.rectangle(frame, (10, 10), (450, 48), (0, 0, 0), -1)
            cv2.putText(
                frame,
                top_bar_text,
                (20, 36),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (0, 255, 255),
                2,
                cv2.LINE_AA
            )

            # Display frame
            cv2.imshow(window_title, frame)

            # Key handling (1ms)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == ord('Q'):
                print("Exit signal received ('Q' pressed). Closing application...")
                break
            elif key == ord('s') or key == ord('S'):
                print_attendance_summary(attendance_engine)

    except KeyboardInterrupt:
        print("\nProcess interrupted by user (Ctrl+C). Closing application...")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        print("Camera released and all OpenCV windows closed cleanly.")
        # Print final attendance summary on exit
        print_attendance_summary(attendance_engine)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="School Bus Attendance System - Part 3: Automatic Attendance Engine"
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="Webcam device index to use (default: 0)"
    )
    parser.add_argument(
        "--bus-id",
        type=str,
        default=DEFAULT_BUS_ID,
        help=f"Bus identifier (default: {DEFAULT_BUS_ID})"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database file (default: {DEFAULT_DB_PATH})"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help=f"Cosine similarity threshold (default: {DEFAULT_SIMILARITY_THRESHOLD})"
    )
    parser.add_argument(
        "--confirmations",
        type=int,
        default=REQUIRED_CONFIRMATIONS,
        help=f"Required consecutive confirmations (default: {REQUIRED_CONFIRMATIONS})"
    )
    parser.add_argument(
        "--window",
        type=float,
        default=CONFIRMATION_WINDOW_SECONDS,
        help=f"Confirmation time window in seconds (default: {CONFIRMATION_WINDOW_SECONDS})"
    )
    args = parser.parse_args()

    run(
        camera_index=args.camera_index,
        bus_id=args.bus_id,
        db_path=args.db_path,
        similarity_threshold=args.threshold,
        required_confirmations=args.confirmations,
        confirmation_window=args.window
    )
