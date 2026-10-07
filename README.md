# Automatic School Bus Attendance System - Part 3 (V3)

**Part 3: Automatic Attendance Engine**

This stage implements an automated attendance decision engine on top of face recognition. When a registered student is consistently identified across a sliding confirmation time window, the system creates an attendance record in a local SQLite database with duplicate prevention.

---

## What V3 Adds

1. **Recognition Confirmation (Anti-False-Positive)**:
   - Does **not** record attendance on a single transient frame.
   - Requires $N$ consistent observations within a sliding time window (default: **3 consistent observations within 2.0 seconds**).
   - If candidate recognition is intermittent, noisy, or switches identities, confirmation resets or expires automatically.
2. **Strict Duplicate Prevention**:
   - Each student is marked **Present at most once** per date and bus session (`UNIQUE(student_id, attendance_date, bus_id)`).
   - Subsequent frames tag the student as `ALREADY PRESENT` and generate zero database writes.
3. **Session & Persistence Support**:
   - Uses real local system date (`YYYY-MM-DD`) and time (`HH:MM:SS`).
   - If the application is closed and restarted, existing records for today's session are automatically re-indexed from the database.
4. **Independent Multi-Student Tracking**:
   - Multiple students appearing simultaneously in the camera feed are tracked and confirmed independently.
   - `UNKNOWN` persons are completely ignored by the attendance engine.
5. **Session Summary & Visual Toasts**:
   - High-contrast visual banners in the camera stream for "ATTENDANCE MARKED".
   - Bounding boxes reflect state: **Yellow** (`CONFIRMING (x/3)`), **Green** (`PRESENT` / `ALREADY PRESENT`), **Red** (`UNKNOWN`).
   - Pressing **`S`** in the camera window prints today's complete attendance summary table in the terminal.

---

## Architecture Flow

```text
camera.py (Frame Capture)
       ↓
face_recognizer.py (InsightFace ArcFace Embedding & Identity Match)
       ↓
attendance.py (Multi-Frame Confirmation & Session Deduplication)
       ↓
database.py (SQLite Storage with Uniqueness Constraints)
```

---

## Configuration Settings (`src/config.py`)

All parameters are centrally managed in `src/config.py` and can also be overridden via command-line arguments:

| Setting | Default Value | Description |
| :--- | :--- | :--- |
| `DEFAULT_BUS_ID` | `"BUS01"` | Identifier of the bus conducting attendance |
| `DEFAULT_DB_PATH` | `"data/attendance.db"` | SQLite database file location |
| `REQUIRED_CONFIRMATIONS` | `3` | Consecutive observations needed to confirm attendance |
| `CONFIRMATION_WINDOW_SECONDS` | `2.0` | Time window (seconds) within which confirmations must occur |
| `DEFAULT_SIMILARITY_THRESHOLD` | `0.50` | ArcFace cosine similarity cutoff |
| `NOTIFICATION_DURATION_SECONDS`| `3.0` | Duration (seconds) of on-screen visual banners |

---

## Database Architecture (`data/attendance.db`)

Managed by `src/database.py`:

```sql
-- Students Table (from V2)
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    bus_id TEXT NOT NULL,
    face_embedding BLOB NOT NULL,
    created_at TEXT NOT NULL
);

-- Attendance Table (added in V3)
CREATE TABLE IF NOT EXISTS attendance (
    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    attendance_date TEXT NOT NULL,
    attendance_time TEXT NOT NULL,
    bus_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    UNIQUE (student_id, attendance_date, bus_id)
);
```

---

## How to Run the System

### 1. Register Students
Before running attendance, register one or more students:
```powershell
python register_student.py
```

### 2. Start Live Attendance
Run the attendance engine with the default bus ID (`BUS01`):
```powershell
python main.py
```

#### Custom Bus ID or Camera:
```powershell
python main.py --bus-id BUS-02 --camera-index 1
```

#### Custom Confirmation Parameters:
```powershell
python main.py --confirmations 4 --window 2.5 --threshold 0.55
```

---

## Controls

- **`S`**: Display today's real-time attendance summary table in the terminal.
- **`Q`**: Exit cleanly and print final session attendance summary.
- **`Ctrl+C`**: Keyboard interrupt exit.

---

## Attendance Calculation & Absentee Policy

- **Present**: Explicitly recorded when a registered student is confirmed.
- **Not Yet Present**: Computed dynamically as:
  $$\text{Not Yet Present} = \text{Total Registered Students} - \text{Total Marked Present}$$
- Students are **never** permanently recorded as `Absent` in the database until an administrative session is formally closed (reserved for future parts).

---

---

## Attendance Management & Testing Tool (`manage_attendance.py`)

For rapid development and iterative testing, run the management utility:
```powershell
python manage_attendance.py
```

### Menu Options:
1. **View today's attendance**: Displays today's marked students (`Present: X / Total`) and lists registered students who are **Not Yet Present**.
2. **Clear today's attendance for current bus**: Prompts for `YES` confirmation and deletes attendance rows for today and `DEFAULT_BUS_ID`. Student registrations and biometrics are unaffected.
3. **Clear ALL attendance records**: Prompts for `DELETE ALL` confirmation and removes all attendance history across all dates and buses. Student profiles and face embeddings are completely preserved.
4. **Exit**: Exits cleanly.

---

---

## School Attendance Dashboard (`dashboard.py`) - V4.1 Modern Suite

A modern, professional 2026 administration desktop application built with **CustomTkinter** for monitoring bus attendance in real time, managing students, modifying fleet bus assignments, reviewing historical sessions, and exporting official reports.

```powershell
python dashboard.py
```

### V4.1 Features & Design System:

1. **Modern 2026 Dark-First Aesthetic**:
   - **Default Dark Mode**: Automatically launches in dark mode without requiring manual selection.
   - **Maximized Startup**: Opens fully maximized on desktop with standard title bar and window controls preserved.
   - **Sleek Neutral Palette**: Dark slate background (`#0f1117`), sidebar (`#161822`), subtle bordered cards (`#1c1f2b`), crisp light typography (`#f9fafb`), and restrained functional accents (emerald green for Present, coral red for Not Present, clean blue for primary actions).

2. **Accurate Fleet Bus Roster Logic**:
   - **Total Assigned**: Strictly calculates registered students assigned to the selected bus (`students.bus_id == selected_bus`).
   - **Present**: Number of assigned students verified on that bus for the selected date.
   - **Not Present**: `Total Assigned - Present` (pending boarding).
   - **Attendance Rate**: `(Present / Total Assigned) * 100` (safe `0.0%` fallback if no students assigned).
   - **Full Roster Display**: Displays all students assigned to the bus with real-time presence indicators. If an unassigned student boards, they are flagged as `PRESENT (Unassigned)` to alert staff to a fleet allocation discrepancy.

3. **Student Directory & Bus Assignment (`👥 Student Directory`)**:
   - **`[ ✏️ Edit Student ]`**: Update student name, grade/class, and assigned bus. **Changing bus assignment does not affect facial embeddings and preserves historical attendance on original buses**.
   - **`[ + Register Student ]`**: Spawns the dedicated biometric camera registration console (`register_student.py`).
   - **`[ 🔍 View Details ]`**: Profile modal with attendance audit logs.
   - **`[ 🗑️ Delete Student ]`**: Removes biometric registration while preserving historical attendance.
   - **Live Search**: Instant multi-field filtering by ID, Name, Class, or Bus.

4. **Attendance History (`🕒 Attendance History`)**:
   - Historical audit logs filtered by Bus and Date (`YYYY-MM-DD`).

5. **Reports & CSV Export (`📁 Reports & Export`)**:
   - Live roster preview and standardized CSV report export (`Student ID,Name,Class,Bus ID,Date,Status,Time`) with duplicate overwrite warnings.

---

## Known Limitations

- Requires frontal or moderate 3/4 face angles for detection.
- Extreme low light or heavy backlight may degrade camera detection.
- Anti-spoofing and liveness detection are not yet implemented (scheduled for later parts).


