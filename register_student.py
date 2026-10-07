import argparse
import sys
import cv2
import numpy as np

from src.camera import Camera
from src.face_recognizer import FaceRecognizer
from src.database import Database


def register_student_cli() -> None:
    """Command-line workflow to capture and register a student's face embedding."""
    parser = argparse.ArgumentParser(
        description="Register a student for the Automatic School Bus Attendance System"
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="Webcam device index to use (default: 0)"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/attendance.db",
        help="Path to SQLite database file (default: data/attendance.db)"
    )
    args = parser.parse_args()

    print("==================================================")
    print("      STUDENT REGISTRATION - V2                   ")
    print("==================================================")
    print("Please enter the student's details:")

    # 1. Ask for metadata
    while True:
        student_id = input("Student ID (e.g., STU001): ").strip()
        if student_id:
            break
        print("Student ID cannot be empty.")

    while True:
        name = input("Student Name (e.g., Alex Johnson): ").strip()
        if name:
            break
        print("Student Name cannot be empty.")

    while True:
        class_name = input("Class / Grade (e.g., 5A): ").strip()
        if class_name:
            break
        print("Class cannot be empty.")

    while True:
        bus_id = input("Bus ID (e.g., BUS-12): ").strip()
        if bus_id:
            break
        print("Bus ID cannot be empty.")

    # Check if student already exists in database
    db = Database(db_path=args.db_path)
    existing = db.get_student_by_id(student_id)
    if existing:
        print(f"\nWarning: Student ID '{student_id}' already registered for '{existing['name']}'.")
        overwrite = input("Do you want to update/overwrite their face embedding? (y/N): ").strip().lower()
        if overwrite not in ("y", "yes"):
            print("Registration cancelled.")
            return

    # 2. Initialize Face Recognizer model (loaded once)
    print("\nLoading face recognition model (InsightFace ArcFace)...")
    try:
        recognizer = FaceRecognizer()
        print("Recognition model loaded successfully.")
    except Exception as e:
        print(f"Error initializing face recognition model: {e}")
        sys.exit(1)

    # 3. Open webcam
    print(f"Connecting to camera index {args.camera_index}...")
    camera = Camera(camera_index=args.camera_index)
    if not camera.start():
        print(f"Error: Unable to open camera at index {args.camera_index}.")
        print("Please check that your webcam is connected.")
        sys.exit(1)

    window_title = f"Registering: {name} (Press SPACE to capture, Q to cancel)"
    print("\nStarting camera preview...")
    print("- Position the student facing the camera.")
    print("- Ensure EXACTLY ONE face is clearly visible.")
    print("- Press [SPACEBAR] to capture & register.")
    print("- Press [Q] to cancel.")

    captured_embedding = None

    try:
        while True:
            ret, frame = camera.read_frame()
            if not ret or frame is None:
                print("Error: Could not read frame from camera.")
                break

            # Work on a copy for visual display
            display_frame = frame.copy()
            faces = recognizer.extract_faces(frame)
            num_faces = len(faces)

            # Draw UI feedback
            if num_faces == 1:
                # Exactly 1 face: ready for capture (Green box)
                face = faces[0]
                bbox = [int(v) for v in face.bbox]
                cv2.rectangle(
                    display_frame,
                    (bbox[0], bbox[1]),
                    (bbox[2], bbox[3]),
                    (0, 255, 0),
                    2
                )
                status_text = "READY: Exactly 1 face detected. Press SPACE to capture."
                status_color = (0, 255, 0)
            elif num_faces == 0:
                status_text = "WARNING: No face detected. Look directly at camera."
                status_color = (0, 0, 255)
            else:
                # Multiple faces: not allowed for registration (Red boxes)
                for f in faces:
                    bbox = [int(v) for v in f.bbox]
                    cv2.rectangle(
                        display_frame,
                        (bbox[0], bbox[1]),
                        (bbox[2], bbox[3]),
                        (0, 0, 255),
                        2
                    )
                status_text = f"WARNING: {num_faces} faces detected. ONLY 1 face allowed!"
                status_color = (0, 0, 255)

            # Overlay banner
            cv2.rectangle(display_frame, (10, 10), (630, 75), (0, 0, 0), -1)
            cv2.putText(
                display_frame,
                f"Student: {name} | ID: {student_id}",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
                cv2.LINE_AA
            )
            cv2.putText(
                display_frame,
                status_text,
                (20, 62),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                status_color,
                1,
                cv2.LINE_AA
            )

            cv2.imshow(window_title, display_frame)
            key = cv2.waitKey(1) & 0xFF

            if key == 32:  # SPACEBAR pressed
                if num_faces == 1:
                    captured_embedding = faces[0].embedding
                    print(f"\nFace captured successfully for {name}!")
                    break
                elif num_faces == 0:
                    print("Cannot capture: No face visible in frame.")
                else:
                    print(f"Cannot capture: {num_faces} faces detected. Exactly 1 face must be present.")
            elif key == ord('q') or key == ord('Q'):
                print("\nRegistration cancelled by user.")
                break

    finally:
        camera.release()
        cv2.destroyAllWindows()

    # 4. Save to database if capture succeeded
    if captured_embedding is not None:
        print("Saving student details and face embedding to local database...")
        success = db.register_student(
            student_id=student_id,
            name=name,
            class_name=class_name,
            bus_id=bus_id,
            face_embedding=captured_embedding
        )
        if success:
            print("==================================================")
            print(f" SUCCESS: {name} ({student_id}) registered successfully!")
            print(f" Database: {args.db_path}")
            print("==================================================")
        else:
            print("Error: Failed to save student to database.")
    else:
        print("No student record was saved.")


if __name__ == "__main__":
    register_student_cli()
