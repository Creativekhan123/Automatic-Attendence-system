import os
import sys
import csv
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk
import customtkinter as ctk

from src.database import Database
from src.camera import Camera
from src.attendance import AttendanceEngine
from src.face_recognizer import FaceRecognizer
from src.config import (
    DEFAULT_BUS_ID,
    DEFAULT_DB_PATH,
    DEFAULT_SIMILARITY_THRESHOLD,
    REQUIRED_CONFIRMATIONS,
    CONFIRMATION_WINDOW_SECONDS,
    NOTIFICATION_DURATION_SECONDS
)

# Set initial appearance mode to Dark by default
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Design System Palette (Supporting dynamic Light and Dark modes)
# CustomTkinter widgets accept (light_color, dark_color) tuples and switch automatically!
PALETTE: Dict[str, Tuple[str, str]] = {
    "bg_main": ("#f1f5f9", "#0f1117"),          # Page background
    "bg_sidebar": ("#ffffff", "#161822"),       # Sidebar background
    "bg_card": ("#ffffff", "#1c1f2b"),          # Card container
    "border": ("#e2e8f0", "#282c3c"),           # Card & frame border
    "text_primary": ("#0f172a", "#f9fafb"),     # High contrast primary text
    "text_secondary": ("#64748b", "#9ca3af"),   # Muted neutral text
    "text_tertiary": ("#94a3b8", "#6b7280"),    # Low-contrast subtitle text
    "accent_blue": ("#2563eb", "#3b82f6"),      # Modern blue
    "accent_blue_hover": ("#1d4ed8", "#2563eb"),# Blue hover
    "success_green": ("#059669", "#10b981"),    # Emerald green
    "danger_red": ("#dc2626", "#ef4444"),       # Crimson red
    "warning_amber": ("#d97706", "#f59e0b"),    # Amber warning
    "btn_neutral": ("#e2e8f0", "#232736"),      # Neutral button
    "btn_neutral_hover": ("#cbd5e1", "#2e3346"),# Neutral button hover
    "table_bg": ("#ffffff", "#141620"),         # Table background
    "table_heading": ("#f8fafc", "#1c1f2d"),    # Table header background
    "table_selected": ("#dbeafe", "#283046")    # Table selected row highlight
}


def get_color(color_spec: Any) -> str:
    """Extract single hex color string matching current mode for standard Tk / ttk widgets."""
    if isinstance(color_spec, (tuple, list)):
        return color_spec[0] if ctk.get_appearance_mode() == "Light" else color_spec[1]
    return str(color_spec)


# =============================================================================
# MODAL DIALOGS
# =============================================================================

class EditStudentDialog(ctk.CTkToplevel):
    """Modern modal dialog allowing administrators to update student profile and bus assignment."""

    def __init__(
        self,
        parent: ctk.CTk,
        student: Dict[str, Any],
        db: Database,
        on_saved_callback: Any
    ) -> None:
        super().__init__(parent)
        self.student = student
        self.db = db
        self.on_saved_callback = on_saved_callback

        self.title(f"Edit Student — {student['name']}")
        self.geometry("480x420")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.configure(fg_color=PALETTE["bg_main"])
        self._build_ui()

    def _build_ui(self) -> None:
        # Header card
        header = ctk.CTkFrame(self, fg_color=PALETTE["bg_card"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        header.pack(fill="x", padx=20, pady=(18, 12))

        ctk.CTkLabel(
            header,
            text="Edit Student Profile",
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=16, pady=(12, 2))

        ctk.CTkLabel(
            header,
            text=f"Student ID: {self.student['student_id']} (Permanent ID)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # Form fields frame
        form = ctk.CTkFrame(self, fg_color=PALETTE["bg_card"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        form.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        # Name
        ctk.CTkLabel(form, text="Full Name", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(anchor="w", padx=16, pady=(12, 2))
        self.name_entry = ctk.CTkEntry(form, height=34, fg_color=PALETTE["bg_sidebar"], border_color=PALETTE["border"], text_color=PALETTE["text_primary"])
        self.name_entry.insert(0, self.student.get("name", ""))
        self.name_entry.pack(fill="x", padx=16, pady=(0, 8))

        # Class
        ctk.CTkLabel(form, text="Class / Grade", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(anchor="w", padx=16, pady=(2, 2))
        self.class_entry = ctk.CTkEntry(form, height=34, fg_color=PALETTE["bg_sidebar"], border_color=PALETTE["border"], text_color=PALETTE["text_primary"])
        self.class_entry.insert(0, self.student.get("class_name", ""))
        self.class_entry.pack(fill="x", padx=16, pady=(0, 8))

        # Assigned Bus
        ctk.CTkLabel(form, text="Assigned Bus", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(anchor="w", padx=16, pady=(2, 2))
        bus_options = self.db.get_distinct_bus_ids()
        curr_bus = self.student.get("bus_id", DEFAULT_BUS_ID)
        if curr_bus and curr_bus not in bus_options:
            bus_options.append(curr_bus)
        bus_options = sorted(list(set(bus_options)))

        bus_row = ctk.CTkFrame(form, fg_color="transparent")
        bus_row.pack(fill="x", padx=16, pady=(0, 14))

        self.bus_menu = ctk.CTkOptionMenu(
            bus_row,
            values=bus_options,
            command=self._on_bus_dropdown_selected,
            height=34,
            width=150,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"]
        )
        self.bus_menu.set(curr_bus)
        self.bus_menu.pack(side="left", padx=(0, 8))

        self.custom_bus_entry = ctk.CTkEntry(
            bus_row,
            placeholder_text="Or type new Bus ID...",
            height=34,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"]
        )
        self.custom_bus_entry.pack(side="left", fill="x", expand=True)

        # Buttons frame
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=100,
            height=36,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=self.destroy
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame,
            text="Save Changes",
            width=130,
            height=36,
            fg_color=PALETTE["accent_blue"],
            hover_color=PALETTE["accent_blue_hover"],
            text_color="#ffffff",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_save
        ).pack(side="right")

    def _on_bus_dropdown_selected(self, val: str) -> None:
        self.custom_bus_entry.delete(0, tk.END)

    def _on_save(self) -> None:
        new_name = self.name_entry.get().strip()
        new_class = self.class_entry.get().strip()
        custom_bus = self.custom_bus_entry.get().strip()
        new_bus = custom_bus if custom_bus else self.bus_menu.get().strip()

        if not new_name:
            messagebox.showerror("Validation Error", "Student name cannot be empty.", parent=self)
            return
        if not new_class:
            messagebox.showerror("Validation Error", "Class / Grade cannot be empty.", parent=self)
            return
        if not new_bus:
            messagebox.showerror("Validation Error", "Assigned Bus cannot be empty.", parent=self)
            return

        success = self.db.update_student(
            student_id=self.student["student_id"],
            name=new_name,
            class_name=new_class,
            bus_id=new_bus
        )

        if success:
            messagebox.showinfo("Success", f"Profile for '{new_name}' updated successfully.", parent=self)
            if self.on_saved_callback:
                self.on_saved_callback()
            self.destroy()
        else:
            messagebox.showerror("Update Error", "Failed to update student profile in database.", parent=self)


class StudentDetailsDialog(ctk.CTkToplevel):
    """Detailed modal view showing complete profile and attendance history for a student."""

    def __init__(self, parent: ctk.CTk, student: Dict[str, Any], db: Database) -> None:
        super().__init__(parent)
        self.student = student
        self.db = db

        self.title(f"Student Details — {student['name']} ({student['student_id']})")
        self.geometry("620x520")
        self.minsize(580, 460)
        self.transient(parent)
        self.grab_set()

        self.configure(fg_color=PALETTE["bg_main"])
        self._build_ui()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header Profile Card
        header = ctk.CTkFrame(self, fg_color=PALETTE["bg_card"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=20, pady=(18, 12), sticky="ew")

        # Top row: Name and ID
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            title_row,
            text=self.student["name"],
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text=f"ID: {self.student['student_id']}",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=PALETTE["btn_neutral"],
            text_color=PALETTE["text_secondary"],
            corner_radius=6,
            padx=10,
            pady=4
        ).pack(side="right")

        # Info Badges
        info_row = ctk.CTkFrame(header, fg_color="transparent")
        info_row.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(info_row, text=f"Class: {self.student.get('class_name', '--')}", font=ctk.CTkFont(size=13), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(0, 18))
        ctk.CTkLabel(info_row, text=f"Bus: {self.student.get('bus_id', '--')}", font=ctk.CTkFont(size=13, weight="bold"), text_color=PALETTE["accent_blue"]).pack(side="left")

        created_str = self.student.get("created_at", "--")
        if "T" in created_str:
            created_str = created_str.replace("T", " ").split(".")[0]
        meta_lbl = ctk.CTkLabel(
            header,
            text=f"Biometrics Registered: {created_str}",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=PALETTE["text_tertiary"]
        )
        meta_lbl.pack(anchor="w", padx=16, pady=(0, 12))

        # History Title Bar
        history_records = self.db.get_student_attendance_history(self.student["student_id"])
        history_bar = ctk.CTkFrame(self, fg_color="transparent")
        history_bar.grid(row=1, column=0, padx=20, pady=(6, 4), sticky="ew")

        ctk.CTkLabel(
            history_bar,
            text="Historical Attendance Log",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(side="left")

        ctk.CTkLabel(
            history_bar,
            text=f"Total: {len(history_records)} recorded sessions",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=PALETTE["text_secondary"]
        ).pack(side="right")

        # History Treeview container
        table_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=PALETTE["table_bg"], border_width=1, border_color=PALETTE["border"])
        table_frame.grid(row=2, column=0, padx=20, pady=5, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            table_frame,
            columns=("date", "time", "bus", "status"),
            show="headings",
            selectmode="browse"
        )
        tree.heading("date", text="Date", anchor="center")
        tree.heading("time", text="Time", anchor="center")
        tree.heading("bus", text="Bus", anchor="center")
        tree.heading("status", text="Status", anchor="center")

        tree.column("date", width=120, anchor="center")
        tree.column("time", width=110, anchor="center")
        tree.column("bus", width=110, anchor="center")
        tree.column("status", width=110, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 5), pady=5)

        for rec in history_records:
            tree.insert("", "end", values=(
                rec["attendance_date"],
                rec["attendance_time"],
                rec["bus_id"],
                rec["status"]
            ))

        # Close
        close_btn = ctk.CTkButton(
            self,
            text="Close",
            width=90,
            height=34,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=self.destroy
        )
        close_btn.grid(row=3, column=0, padx=20, pady=(10, 16), sticky="e")


class CameraSettingsDialog(ctk.CTkToplevel):
    """Modal dialog allowing administrator to select Bus ID and Camera Device before starting attendance."""

    def __init__(self, parent: ctk.CTk, default_bus: str = DEFAULT_BUS_ID, default_cam: int = 0) -> None:
        super().__init__(parent)
        self.confirmed = False
        self.bus_id = default_bus
        self.camera_index = default_cam
        self.parent = parent
        self.db: Database = parent.db

        self.title("Configure Attendance Session")
        self.geometry("450x360")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.configure(fg_color=PALETTE["bg_main"])
        self._build_ui(default_bus, default_cam)

    def _build_ui(self, default_bus: str, default_cam: int) -> None:
        header = ctk.CTkFrame(self, fg_color=PALETTE["bg_card"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        header.pack(fill="x", padx=20, pady=(18, 12))

        ctk.CTkLabel(
            header,
            text="🎥 Start Attendance Session",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=16, pady=(12, 2))

        ctk.CTkLabel(
            header,
            text="Configure target bus route and camera index before starting",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=16, pady=(0, 12))

        form = ctk.CTkFrame(self, fg_color=PALETTE["bg_card"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        form.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        ctk.CTkLabel(form, text="Select Bus Route:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(anchor="w", padx=16, pady=(12, 4))

        buses = self.db.get_distinct_bus_ids()
        if default_bus not in buses:
            buses.append(default_bus)
        buses = sorted(list(set(buses)))

        bus_row = ctk.CTkFrame(form, fg_color="transparent")
        bus_row.pack(fill="x", padx=16, pady=(0, 10))

        self.bus_menu = ctk.CTkOptionMenu(
            bus_row,
            values=buses,
            width=150,
            height=34,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"]
        )
        self.bus_menu.set(default_bus if default_bus in buses else buses[0])
        self.bus_menu.pack(side="left", padx=(0, 8))

        self.custom_bus_entry = ctk.CTkEntry(
            bus_row,
            placeholder_text="Or type custom bus...",
            height=34,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"]
        )
        self.custom_bus_entry.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(form, text="Camera Device Index:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(anchor="w", padx=16, pady=(4, 4))

        self.cam_entry = ctk.CTkEntry(
            form,
            height=34,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"]
        )
        self.cam_entry.insert(0, str(default_cam))
        self.cam_entry.pack(fill="x", padx=16, pady=(0, 14))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=100,
            height=36,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=self._on_cancel
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame,
            text="🚀 Start Attendance",
            width=150,
            height=36,
            fg_color=PALETTE["success_green"],
            hover_color="#0d9268",
            text_color="#ffffff",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_confirm
        ).pack(side="right")

    def _on_confirm(self) -> None:
        custom_bus = self.custom_bus_entry.get().strip()
        self.bus_id = custom_bus if custom_bus else self.bus_menu.get().strip()
        try:
            self.camera_index = int(self.cam_entry.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Input", "Camera Index must be an integer (e.g. 0).", parent=self)
            return
        if not self.bus_id:
            messagebox.showerror("Invalid Input", "Bus ID cannot be empty.", parent=self)
            return
        self.confirmed = True
        self.destroy()

    def _on_cancel(self) -> None:
        self.confirmed = False
        self.destroy()


class RegistrationCameraDialog(ctk.CTkToplevel):
    """Modern modal dialog for capturing a student's face embedding via live webcam."""

    def __init__(
        self,
        parent: ctk.CTk,
        student_id: str,
        name: str,
        class_name: str,
        bus_id: str,
        camera_index: int,
        db: Database
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.student_id = student_id
        self.name = name
        self.class_name = class_name
        self.bus_id = bus_id
        self.camera_index = camera_index
        self.db = db
        self.success = False

        self.title(f"Face Enrollment — {name} ({student_id})")
        self.geometry("680x620")
        self.minsize(640, 580)
        self.transient(parent)
        self.grab_set()

        self.configure(fg_color=PALETTE["bg_main"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Threading & Camera State
        self._running = False
        self._camera = None
        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_faces = []
        self._latest_status = "Initializing face recognition camera..."
        self._latest_ready = False
        self._worker_thread: Optional[threading.Thread] = None

        self._build_ui()
        self._start_capture()

    def _build_ui(self) -> None:
        # Header Info Card
        header = ctk.CTkFrame(self, fg_color=PALETTE["bg_card"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        header.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            header,
            text=f"Enroll Face: {self.name}",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=16, pady=(10, 2))

        ctk.CTkLabel(
            header,
            text=f"ID: {self.student_id}  |  Class: {self.class_name}  |  Assigned Bus: {self.bus_id}",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # Preview Container
        preview_container = ctk.CTkFrame(self, fg_color=PALETTE["bg_card"], corner_radius=10, border_width=1, border_color=PALETTE["border"])
        preview_container.pack(fill="both", expand=True, padx=16, pady=4)

        # Camera Display Label
        self.preview_lbl = ctk.CTkLabel(
            preview_container,
            text="Connecting to webcam...",
            font=ctk.CTkFont(size=14),
            text_color=PALETTE["text_secondary"]
        )
        self.preview_lbl.pack(fill="both", expand=True, padx=10, pady=10)

        # Status Bar inside preview container
        self.status_lbl = ctk.CTkLabel(
            preview_container,
            text=self._latest_status,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=PALETTE["warning_amber"]
        )
        self.status_lbl.pack(pady=(0, 8))

        # Action Buttons Frame
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(8, 14))

        self.cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=100,
            height=38,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=self._on_close
        )
        self.cancel_btn.pack(side="left")

        # Fallback button to import photo if webcam is unavailable
        self.file_btn = ctk.CTkButton(
            btn_frame,
            text="📁 Select Photo File",
            width=140,
            height=38,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_secondary"],
            command=self._on_select_photo_file
        )
        self.file_btn.pack(side="left", padx=8)

        self.capture_btn = ctk.CTkButton(
            btn_frame,
            text="📸 Capture Face & Register",
            width=200,
            height=38,
            fg_color=PALETTE["success_green"],
            hover_color="#0d9268",
            text_color="#ffffff",
            font=ctk.CTkFont(weight="bold"),
            state="disabled",
            command=self._on_capture
        )
        self.capture_btn.pack(side="right")

        # Keyboard shortcut: Spacebar captures face
        self.bind("<space>", lambda e: self._on_capture() if self._latest_ready else None)

    def _start_capture(self) -> None:
        self._running = True
        self._worker_thread = threading.Thread(target=self._camera_worker, daemon=True)
        self._worker_thread.start()
        self.after(40, self._update_gui_preview)

    def _camera_worker(self) -> None:
        from src.camera import Camera
        from src.face_recognizer import FaceRecognizer

        try:
            if hasattr(self.parent, "get_face_recognizer"):
                recognizer = self.parent.get_face_recognizer()
            else:
                recognizer = FaceRecognizer()
        except Exception as e:
            with self._lock:
                self._latest_status = f"Error loading face recognition engine: {e}"
            return

        try:
            camera = Camera(camera_index=self.camera_index)
            if not camera.start():
                with self._lock:
                    self._latest_status = f"Webcam unavailable at index {self.camera_index}. Check device or choose 'Select Photo File'."
                return
            self._camera = camera
        except Exception as e:
            with self._lock:
                self._latest_status = f"Camera initialization error: {e}"
            return

        while self._running:
            ret, frame = camera.read_frame()
            if not ret or frame is None:
                time.sleep(0.04)
                continue

            display_frame = frame.copy()
            faces = recognizer.extract_faces(frame)
            num_faces = len(faces)

            if num_faces == 1:
                face = faces[0]
                bbox = [int(v) for v in face.bbox]
                cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                cv2.putText(display_frame, "READY TO CAPTURE", (bbox[0], max(bbox[1] - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
                status_txt = "READY: Exactly 1 face detected. Click 'Capture Face' or press SPACE."
                ready = True
            elif num_faces == 0:
                status_txt = "Looking for student face... Please look directly at the camera."
                ready = False
            else:
                for f in faces:
                    bbox = [int(v) for v in f.bbox]
                    cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 0, 255), 2)
                status_txt = f"WARNING: {num_faces} faces detected. ONLY 1 face allowed!"
                ready = False

            with self._lock:
                self._latest_frame = display_frame
                self._latest_faces = faces
                self._latest_ready = ready
                self._latest_status = status_txt

            time.sleep(0.03)

        if self._camera:
            self._camera.release()
            self._camera = None

    def _update_gui_preview(self) -> None:
        if not self._running:
            return

        with self._lock:
            frame = self._latest_frame
            status = self._latest_status
            ready = self._latest_ready

        color_key = "success_green" if ready else ("danger_red" if "WARNING" in status or "unavailable" in status or "Error" in status else "warning_amber")
        self.status_lbl.configure(text=status, text_color=PALETTE[color_key])
        self.capture_btn.configure(state="normal" if ready else "disabled")

        if frame is not None:
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(540, 405))
                self.preview_lbl.configure(image=ctk_img, text="")
                self.preview_lbl.image = ctk_img
            except Exception:
                pass

        if self._running:
            self.after(35, self._update_gui_preview)

    def _on_capture(self) -> None:
        with self._lock:
            faces = list(self._latest_faces)

        if len(faces) != 1:
            messagebox.showwarning("Face Required", "Exactly 1 face must be visible to capture.", parent=self)
            return

        embedding = faces[0].embedding
        ok = self.db.register_student(
            student_id=self.student_id,
            name=self.name,
            class_name=self.class_name,
            bus_id=self.bus_id,
            face_embedding=embedding
        )
        if ok:
            self.success = True
            messagebox.showinfo(
                "Enrollment Successful",
                f"Student '{self.name}' ({self.student_id}) enrolled successfully!\nAssigned to: {self.bus_id}",
                parent=self
            )
            self._on_close()
        else:
            messagebox.showerror("Save Failed", "Failed to save student record to database.", parent=self)

    def _on_select_photo_file(self) -> None:
        """Allow administrator to select a photo file if camera is offline."""
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Select Student Photo for Biometric Enrollment",
            filetypes=[("Image files", "*.jpg;*.jpeg;*.png"), ("All files", "*.*")]
        )
        if not file_path:
            return

        try:
            from src.face_recognizer import FaceRecognizer
            if hasattr(self.parent, "get_face_recognizer"):
                recognizer = self.parent.get_face_recognizer()
            else:
                recognizer = FaceRecognizer()

            img = cv2.imread(file_path)
            if img is None:
                messagebox.showerror("File Error", "Could not read the selected image file.", parent=self)
                return

            faces = recognizer.extract_faces(img)
            if len(faces) == 0:
                messagebox.showwarning("No Face", "No human face was detected in this photo. Please choose a clearer photo.", parent=self)
                return
            if len(faces) > 1:
                messagebox.showwarning("Multiple Faces", f"{len(faces)} faces were detected. Only 1 student face is allowed.", parent=self)
                return

            embedding = faces[0].embedding
            ok = self.db.register_student(
                student_id=self.student_id,
                name=self.name,
                class_name=self.class_name,
                bus_id=self.bus_id,
                face_embedding=embedding
            )
            if ok:
                self.success = True
                messagebox.showinfo(
                    "Enrollment Successful",
                    f"Student '{self.name}' ({self.student_id}) enrolled successfully from photo file!\nAssigned to: {self.bus_id}",
                    parent=self
                )
                self._on_close()
            else:
                messagebox.showerror("Save Failed", "Failed to save student to database.", parent=self)
        except Exception as e:
            messagebox.showerror("Enrollment Error", f"Failed to extract biometrics from image:\n{e}", parent=self)

    def _on_close(self) -> None:
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)
        if self._camera:
            try:
                self._camera.release()
            except Exception:
                pass
            self._camera = None
        self.destroy()


# =============================================================================
# MAIN APPLICATION: ATTENDANCE DASHBOARD
# =============================================================================

class AttendanceDashboard(ctk.CTk):
    """Modern 2026 School Bus Attendance Administration Dashboard."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        super().__init__()

        self.db = Database(db_path=db_path)
        self.db_path = db_path
        self.title("School Bus Attendance System — Administration Suite")
        self.minsize(980, 640)

        # 1. Startup: Dark mode by default
        ctk.set_appearance_mode("Dark")

        # 2. Startup: Open maximized on desktop with titlebar intact
        try:
            self.state("zoomed")
        except Exception:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

        self.configure(fg_color=PALETTE["bg_main"])

        # State Variables
        self.selected_date = datetime.now().strftime("%Y-%m-%d")
        self.selected_bus = "ALL BUSES"
        self.current_view = "dashboard"

        # Background Camera / Attendance Engine process tracking
        self._camera_process: Optional[subprocess.Popen] = None
        self._camera_monitor_thread: Optional[threading.Thread] = None
        self.camera_index: int = 0
        self.active_bus_id: str = DEFAULT_BUS_ID
        self._face_recognizer = None

        # Embedded Camera & Attendance Engine state
        self._camera_device: Optional[Camera] = None
        self._camera_thread: Optional[threading.Thread] = None
        self._camera_running: bool = False
        self._active_camera_mode: Optional[str] = None  # "attendance" or "registration"
        self._camera_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_camera_error: Optional[str] = None
        self._need_live_refresh: bool = False

        # Registration Biometric State
        self._latest_reg_faces: List[Any] = []
        self._latest_reg_ready: bool = False
        self._latest_reg_status: str = "Initializing camera..."
        self._reg_captured_embedding: Optional[np.ndarray] = None

        # Auto-refresh timer
        self.auto_refresh_enabled = True
        self.auto_refresh_ms = 5000
        self._refresh_job: Optional[str] = None

        self._configure_treeview_styles()
        self._build_main_layout()

        # Show initial dashboard view
        self._show_view("dashboard")
        self._schedule_auto_refresh()

    def get_face_recognizer(self):
        """Cache single FaceRecognizer instance to make subsequent enrollments fast."""
        if self._face_recognizer is None:
            from src.face_recognizer import FaceRecognizer
            self._face_recognizer = FaceRecognizer()
        return self._face_recognizer

    def _configure_treeview_styles(self) -> None:
        """Apply a sleek table style matching the current Light / Dark mode."""
        style = ttk.Style()
        style.theme_use("clam")

        tbl_bg = get_color(PALETTE["table_bg"])
        tbl_fg = get_color(PALETTE["text_primary"])
        hdr_bg = get_color(PALETTE["table_heading"])
        hdr_fg = get_color(PALETTE["text_secondary"])
        sel_bg = get_color(PALETTE["table_selected"])

        style.configure(
            "Treeview",
            background=tbl_bg,
            foreground=tbl_fg,
            fieldbackground=tbl_bg,
            rowheight=34,
            font=("Segoe UI", 10),
            borderwidth=0
        )
        style.configure(
            "Treeview.Heading",
            background=hdr_bg,
            foreground=hdr_fg,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padding=6
        )
        style.map(
            "Treeview",
            background=[("selected", sel_bg)],
            foreground=[("selected", tbl_fg)]
        )

    def _update_treeview_tags(self) -> None:
        """Update tag colors for treeviews when appearance mode changes."""
        present_color = get_color(PALETTE["success_green"])
        not_present_color = get_color(PALETTE["danger_red"])
        unassigned_color = get_color(PALETTE["warning_amber"])

        for tree_attr in ["dash_tree", "live_tree", "hist_tree", "rep_tree", "students_tree"]:
            tree = getattr(self, tree_attr, None)
            if tree is not None:
                try:
                    tree.tag_configure("present", foreground=present_color, font=("Segoe UI", 10, "bold"))
                    tree.tag_configure("not_present", foreground=not_present_color, font=("Segoe UI", 10))
                    tree.tag_configure("unassigned", foreground=unassigned_color, font=("Segoe UI", 10, "bold"))
                except Exception:
                    pass

    def _build_main_layout(self) -> None:
        """Create a clean two-column layout: Sidebar on left, View Container on right."""
        self.grid_columnconfigure(0, weight=0)  # Sidebar fixed width
        self.grid_columnconfigure(1, weight=1)  # Content expands
        self.grid_rowconfigure(0, weight=1)

        # ==================== SIDEBAR ====================
        sidebar = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=PALETTE["bg_sidebar"], border_width=0)
        sidebar.grid(row=0, column=0, sticky="nsew")

        # Brand / App Title
        brand_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand_frame.grid(row=0, column=0, padx=18, pady=(20, 16), sticky="ew")

        ctk.CTkLabel(
            brand_frame,
            text="🚌 AUTOBUS",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w")

        ctk.CTkLabel(
            brand_frame,
            text="Fleet Attendance Suite 2026",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=PALETTE["text_tertiary"]
        ).pack(anchor="w", pady=(1, 0))

        # Navigation Items
        self.nav_btns = {}
        nav_items = [
            ("dashboard", "📊  Dashboard"),
            ("live", "🎥  Live Attendance"),
            ("students", "👥  Students"),
            ("history", "🕒  Attendance History"),
            ("reports", "📁  Reports"),
            ("register", "📷  Register Student"),
            ("settings", "⚙️  Settings"),
        ]

        for idx, (view_id, title) in enumerate(nav_items, start=1):
            btn = ctk.CTkButton(
                sidebar,
                text=title,
                height=40,
                corner_radius=8,
                anchor="w",
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                fg_color="transparent",
                text_color=PALETTE["text_secondary"],
                hover_color=PALETTE["btn_neutral"],
                command=lambda v=view_id: self._show_view(v)
            )
            btn.grid(row=idx, column=0, padx=12, pady=3, sticky="ew")
            self.nav_btns[view_id] = btn

        # Separator line
        cam_sep = ctk.CTkFrame(sidebar, fg_color=PALETTE["border"], height=1, corner_radius=0)
        cam_sep.grid(row=8, column=0, padx=16, pady=(10, 8), sticky="ew")

        # Camera Status Indicator
        self.cam_status_lbl = ctk.CTkLabel(
            sidebar,
            text="● Camera Stopped",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=PALETTE["text_tertiary"]
        )
        self.cam_status_lbl.grid(row=9, column=0, padx=18, pady=(0, 4), sticky="w")

        # Quick Action: Start Attendance Camera
        self.start_cam_btn = ctk.CTkButton(
            sidebar,
            text="🎥  Start Camera",
            height=36,
            corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=PALETTE["success_green"],
            hover_color="#0d9268",
            text_color="#ffffff",
            command=self._on_sidebar_start_camera
        )
        self.start_cam_btn.grid(row=10, column=0, padx=12, pady=(0, 4), sticky="ew")

        # Quick Action: Stop Attendance Camera
        self.stop_cam_btn = ctk.CTkButton(
            sidebar,
            text="🛑  Stop Camera",
            height=36,
            corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=PALETTE["danger_red"],
            hover_color="#c23737",
            text_color="#ffffff",
            state="disabled",
            command=self._on_sidebar_stop_camera
        )
        self.stop_cam_btn.grid(row=11, column=0, padx=12, pady=(0, 10), sticky="ew")

        # Footer Frame
        footer_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer_frame.grid(row=12, column=0, padx=16, pady=(10, 16), sticky="ew")

        ctk.CTkLabel(
            footer_frame,
            text="THEME MODE",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=PALETTE["text_tertiary"]
        ).pack(anchor="w", pady=(0, 4))

        self.appearance_menu = ctk.CTkOptionMenu(
            footer_frame,
            values=["Dark", "Light"],
            command=self._on_change_appearance,
            height=30,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"]
        )
        self.appearance_menu.set(ctk.get_appearance_mode())
        self.appearance_menu.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            footer_frame,
            text="v4.2 — Local Engine",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=PALETTE["text_tertiary"]
        ).pack(anchor="w")

        # ==================== MAIN VIEW CONTAINER ====================
        self.view_container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.view_container.grid(row=0, column=1, sticky="nsew")
        self.view_container.grid_columnconfigure(0, weight=1)
        self.view_container.grid_rowconfigure(0, weight=1)

        # Initialize All 7 Application Views
        self.views = {
            "dashboard": self._create_dashboard_view(),
            "live": self._create_live_view(),
            "students": self._create_students_view(),
            "history": self._create_history_view(),
            "reports": self._create_reports_view(),
            "register": self._create_register_view(),
            "settings": self._create_settings_view(),
        }

    def _show_view(self, view_name: str) -> None:
        """Switch active view in the container."""
        # Stop any active embedded camera when leaving a camera-enabled view
        if self.current_view in ("live", "register") and self.current_view != view_name:
            self._stop_embedded_camera()

        for v in self.views.values():
            v.grid_forget()

        if view_name in self.views:
            self.views[view_name].grid(row=0, column=0, sticky="nsew")
            self.current_view = view_name

        for name, btn in self.nav_btns.items():
            if name == view_name:
                btn.configure(fg_color=PALETTE["accent_blue"], text_color="#ffffff")
            else:
                btn.configure(fg_color="transparent", text_color=PALETTE["text_secondary"])

        # Auto-start camera when entering Attendance or Registration; refresh other views
        if view_name == "dashboard":
            self.refresh_dashboard_data()
        elif view_name == "live":
            self.refresh_live_view_data()
            self._start_live_attendance_camera()
        elif view_name == "students":
            self.refresh_students_data()
        elif view_name == "history":
            self.refresh_history_data()
        elif view_name == "reports":
            self.refresh_reports_preview()
        elif view_name == "register":
            self._start_registration_camera()
        elif view_name == "settings":
            self.refresh_settings_data()

    def _on_change_appearance(self, mode: str) -> None:
        """Handle theme switch between Light and Dark mode."""
        ctk.set_appearance_mode(mode)
        self.appearance_menu.set(mode)
        if hasattr(self, "settings_theme_menu"):
            self.settings_theme_menu.set(mode)

        self._configure_treeview_styles()
        self._update_treeview_tags()

        # Re-apply active view styling
        self._show_view(self.current_view)

    # =========================================================================
    # EMBEDDED CAMERA & ATTENDANCE ENGINE LIFECYCLE CONTROLS
    # =========================================================================

    def _stop_embedded_camera(self) -> None:
        """Safely stop and release any active camera worker thread and device."""
        self._camera_running = False
        if self._camera_thread is not None and self._camera_thread.is_alive():
            if threading.current_thread() != self._camera_thread:
                self._camera_thread.join(timeout=1.2)
        self._camera_thread = None

        if self._camera_device is not None:
            try:
                self._camera_device.release()
            except Exception:
                pass
            self._camera_device = None

        with self._camera_lock:
            self._latest_frame = None
            self._latest_camera_error = None

        self._active_camera_mode = None
        self._reset_camera_ui()

    def _reset_camera_ui(self) -> None:
        """Reset camera button and label states to stopped."""
        try:
            self.start_cam_btn.configure(state="normal", fg_color=PALETTE["success_green"])
            self.stop_cam_btn.configure(state="disabled")
            self.cam_status_lbl.configure(text="● Camera Stopped", text_color=PALETTE["text_tertiary"])
            if hasattr(self, "live_status_badge"):
                self.live_status_badge.configure(text="● STOPPED", text_color=PALETTE["text_tertiary"])
                self.live_start_btn.configure(state="normal")
                self.live_stop_btn.configure(state="disabled")
            if hasattr(self, "live_cam_lbl"):
                self.live_cam_lbl.configure(image="", text="Camera stopped.\nClick 'Start Attendance' to resume.")
            if hasattr(self, "reg_cam_preview_lbl") and self.current_view != "register":
                self.reg_cam_preview_lbl.configure(image="", text="Camera stopped.")
        except Exception:
            pass

    def _on_sidebar_start_camera(self) -> None:
        """Sidebar button: navigate to Live Attendance view and activate camera."""
        if self.current_view != "live":
            self._show_view("live")
        else:
            self._start_live_attendance_camera()

    def _on_sidebar_stop_camera(self) -> None:
        """Sidebar button: stop any running camera session."""
        self._stop_embedded_camera()

    # ------------------ LIVE ATTENDANCE CAMERA ------------------
    def _start_live_attendance_camera(self) -> None:
        """Start the embedded attendance camera feed inside the main window."""
        if self._camera_running and self._active_camera_mode == "attendance":
            return

        self._stop_embedded_camera()

        try:
            cam_idx = int(self.live_cam_entry.get().strip())
        except (ValueError, AttributeError):
            cam_idx = self.camera_index

        self.camera_index = cam_idx
        self.active_bus_id = self.live_bus_menu.get().strip() if hasattr(self, "live_bus_menu") else DEFAULT_BUS_ID

        self._camera_running = True
        self._active_camera_mode = "attendance"
        self._latest_camera_error = None

        # Update UI States
        self.start_cam_btn.configure(state="disabled", fg_color="#5a6478")
        self.stop_cam_btn.configure(state="normal")
        self.cam_status_lbl.configure(
            text=f"● Camera Running\n  Bus: {self.active_bus_id}",
            text_color=PALETTE["success_green"]
        )
        if hasattr(self, "live_status_badge"):
            self.live_status_badge.configure(text="● RUNNING", text_color=PALETTE["success_green"])
            self.live_start_btn.configure(state="disabled")
            self.live_stop_btn.configure(state="normal")
        if hasattr(self, "live_cam_lbl"):
            self.live_cam_lbl.configure(image="", text="Starting camera stream...", text_color=PALETTE["text_secondary"])

        self._camera_thread = threading.Thread(target=self._live_attendance_worker, daemon=True)
        self._camera_thread.start()
        self.after(35, self._update_live_camera_preview)

    def _live_attendance_worker(self) -> None:
        """Worker thread running webcam capture and real-time attendance recognition."""
        cam = Camera(camera_index=self.camera_index)
        if not cam.start():
            with self._camera_lock:
                self._latest_camera_error = "Camera could not be opened. Please check the camera connection."
                self._camera_running = False
            return

        self._camera_device = cam

        try:
            recognizer = self.get_face_recognizer()
        except Exception as e:
            with self._camera_lock:
                self._latest_camera_error = f"Error loading face recognition engine: {e}"
                self._camera_running = False
            cam.release()
            return

        attendance_engine = AttendanceEngine(
            db=self.db,
            bus_id=self.active_bus_id,
            required_confirmations=REQUIRED_CONFIRMATIONS,
            confirmation_window_seconds=CONFIRMATION_WINDOW_SECONDS
        )

        registered_students = self.db.get_all_students()
        last_db_refresh = time.time()
        recent_notification = None

        while self._camera_running and self._active_camera_mode == "attendance":
            # Sync target bus if user changed dropdown while camera runs
            if hasattr(self, "live_bus_menu"):
                current_bus = self.live_bus_menu.get().strip()
                if current_bus and current_bus != attendance_engine.bus_id:
                    attendance_engine.bus_id = current_bus
                    attendance_engine._refresh_marked_cache()
                    self.active_bus_id = current_bus

            now = time.time()
            if now - last_db_refresh > 5.0:
                registered_students = self.db.get_all_students()
                last_db_refresh = now

            ret, frame = cam.read_frame()
            if not ret or frame is None:
                time.sleep(0.04)
                continue

            faces = recognizer.extract_faces(frame)
            num_faces = len(faces)

            for face in faces:
                bbox = [int(v) for v in face.bbox]
                x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

                _, matched_student, score = recognizer.identify_face(
                    face.embedding,
                    registered_students
                )

                if matched_student is not None:
                    status, count, newly_marked = attendance_engine.process_recognition(matched_student)
                    student_name = matched_student["name"]
                    student_id = matched_student["student_id"]

                    if newly_marked:
                        self._need_live_refresh = True
                        recent_notification = (
                            f"ATTENDANCE MARKED: {student_name} ({student_id})",
                            time.time() + NOTIFICATION_DURATION_SECONDS,
                            False
                        )

                    if status in ("PRESENT", "ALREADY PRESENT"):
                        box_color = (0, 255, 0)
                        label_line1 = f"{student_name} ({student_id})"
                        label_line2 = "ALREADY PRESENT" if status == "ALREADY PRESENT" else "PRESENT"
                    elif status == "CONFIRMING":
                        box_color = (0, 255, 255)
                        label_line1 = f"{student_name} ({student_id})"
                        label_line2 = f"CONFIRMING ({count}/{REQUIRED_CONFIRMATIONS})"
                    else:
                        box_color = (0, 0, 255)
                        label_line1 = f"{student_name} ({student_id})"
                        label_line2 = "ERROR SAVING ATTENDANCE"
                        recent_notification = (
                            "Unable to save attendance. Database error.",
                            time.time() + NOTIFICATION_DURATION_SECONDS,
                            True
                        )
                else:
                    box_color = (0, 0, 255)
                    label_line1 = "UNKNOWN"
                    label_line2 = ""

                # Draw face bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

                # Draw text badge
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

            # Draw temporary toast banner if active
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
            top_bar_text = f"Bus: {self.active_bus_id} | Faces: {num_faces} | Present: {summary['total_present']}/{summary['total_registered']}"
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

            with self._camera_lock:
                self._latest_frame = frame

            time.sleep(0.03)

        if cam:
            cam.release()

    def _update_live_camera_preview(self) -> None:
        """GUI event-loop callback to refresh the live attendance video frame."""
        if self._active_camera_mode != "attendance":
            return

        with self._camera_lock:
            err = self._latest_camera_error
            frame = self._latest_frame

        if err:
            self.live_cam_lbl.configure(
                image="",
                text=err,
                text_color=PALETTE["danger_red"]
            )
            if hasattr(self, "live_status_badge"):
                self.live_status_badge.configure(text="● ERROR", text_color=PALETTE["danger_red"])
            self.start_cam_btn.configure(state="normal")
            self.stop_cam_btn.configure(state="disabled")
            return

        if frame is not None:
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(580, 435))
                self.live_cam_lbl.configure(image=ctk_img, text="")
                self.live_cam_lbl.image = ctk_img
            except Exception:
                pass

        if self._need_live_refresh:
            self._need_live_refresh = False
            self.refresh_live_view_data()

        if self._camera_running and self._active_camera_mode == "attendance":
            self.after(35, self._update_live_camera_preview)

    # ------------------ REGISTRATION CAMERA ------------------
    def _start_registration_camera(self) -> None:
        """Start the embedded registration camera feed inside the main window."""
        if self._camera_running and self._active_camera_mode == "registration":
            return

        self._stop_embedded_camera()

        try:
            cam_idx = int(self.reg_cam_entry.get().strip())
        except (ValueError, AttributeError):
            cam_idx = 0

        self.camera_index = cam_idx
        self._camera_running = True
        self._active_camera_mode = "registration"
        self._latest_camera_error = None
        self._latest_reg_ready = False
        self._latest_reg_status = "Connecting to webcam..."

        if hasattr(self, "reg_cam_preview_lbl"):
            self.reg_cam_preview_lbl.configure(image="", text="Starting camera preview...", text_color=PALETTE["text_secondary"])
        if hasattr(self, "reg_cam_status_lbl"):
            self.reg_cam_status_lbl.configure(text=self._latest_reg_status, text_color=PALETTE["warning_amber"])

        self._camera_thread = threading.Thread(target=self._registration_camera_worker, daemon=True)
        self._camera_thread.start()
        self.after(35, self._update_registration_camera_preview)

    def _registration_camera_worker(self) -> None:
        """Background worker thread capturing frames and detecting faces for enrollment."""
        cam = Camera(camera_index=self.camera_index)
        if not cam.start():
            with self._camera_lock:
                self._latest_camera_error = "Camera could not be opened. Please check the camera connection."
                self._latest_reg_status = "Camera could not be opened. Please check the camera connection."
                self._camera_running = False
            return

        self._camera_device = cam

        try:
            recognizer = self.get_face_recognizer()
        except Exception as e:
            with self._camera_lock:
                self._latest_camera_error = f"Error loading face recognition engine: {e}"
                self._latest_reg_status = f"Error loading face recognition engine: {e}"
                self._camera_running = False
            cam.release()
            return

        while self._camera_running and self._active_camera_mode == "registration":
            ret, frame = cam.read_frame()
            if not ret or frame is None:
                time.sleep(0.04)
                continue

            display_frame = frame.copy()
            faces = recognizer.extract_faces(frame)
            num_faces = len(faces)

            if num_faces == 1:
                face = faces[0]
                bbox = [int(v) for v in face.bbox]
                cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                cv2.putText(display_frame, "READY TO CAPTURE", (bbox[0], max(bbox[1] - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
                status_txt = "READY: Exactly 1 face detected. Click 'Capture Face' or press SPACE."
                ready = True
            elif num_faces == 0:
                status_txt = "Looking for student face... Please look directly at the camera."
                ready = False
            else:
                for f in faces:
                    bbox = [int(v) for v in f.bbox]
                    cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 0, 255), 2)
                status_txt = f"WARNING: {num_faces} faces detected. ONLY 1 face allowed!"
                ready = False

            with self._camera_lock:
                self._latest_frame = display_frame
                self._latest_reg_faces = faces
                self._latest_reg_ready = ready
                self._latest_reg_status = status_txt

            time.sleep(0.03)

        if cam:
            cam.release()

    def _update_registration_camera_preview(self) -> None:
        """GUI event-loop callback to refresh the registration preview."""
        if self._active_camera_mode != "registration":
            return

        with self._camera_lock:
            err = self._latest_camera_error
            frame = self._latest_frame
            status = self._latest_reg_status
            ready = self._latest_reg_ready

        if err:
            self.reg_cam_preview_lbl.configure(image="", text=err, text_color=PALETTE["danger_red"])
            self.reg_cam_status_lbl.configure(text=err, text_color=PALETTE["danger_red"])
            return

        color_key = "success_green" if ready else ("danger_red" if "WARNING" in status or "Error" in status else "warning_amber")
        self.reg_cam_status_lbl.configure(text=status, text_color=PALETTE[color_key])

        if frame is not None:
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(520, 390))
                self.reg_cam_preview_lbl.configure(image=ctk_img, text="")
                self.reg_cam_preview_lbl.image = ctk_img
            except Exception:
                pass

        if self._camera_running and self._active_camera_mode == "registration":
            self.after(35, self._update_registration_camera_preview)

    # =========================================================================
    # VIEW 1: DASHBOARD (OVERALL & BUS ATTENDANCE)
    # =========================================================================

    def _create_dashboard_view(self) -> ctk.CTkFrame:
        """Build the Live Monitoring Dashboard view."""
        frame = ctk.CTkFrame(self.view_container, fg_color=PALETTE["bg_main"])
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(4, weight=1)

        # Header Frame
        header = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=22, pady=(18, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Attendance Dashboard",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).grid(row=0, column=0, padx=20, pady=(12, 1), sticky="w")

        ctk.CTkLabel(
            header,
            text="Real-time facial verification, bus route metrics, and overall school attendance",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=PALETTE["text_secondary"]
        ).grid(row=1, column=0, padx=20, pady=(0, 12), sticky="w")

        meta = ctk.CTkFrame(header, fg_color="transparent")
        meta.grid(row=0, column=1, rowspan=2, padx=20, pady=10, sticky="e")

        self.dash_bus_badge = ctk.CTkLabel(
            meta,
            text=f"Bus: {self.selected_bus}",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=PALETTE["btn_neutral"],
            text_color=PALETTE["text_primary"],
            corner_radius=6,
            padx=12,
            pady=6
        )
        self.dash_bus_badge.pack(side="left", padx=4)

        self.dash_date_badge = ctk.CTkLabel(
            meta,
            text=datetime.now().strftime("%d %b %Y"),
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=PALETTE["btn_neutral"],
            text_color=PALETTE["text_primary"],
            corner_radius=6,
            padx=12,
            pady=6
        )
        self.dash_date_badge.pack(side="left", padx=4)

        # Filter & Control Bar
        controls = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        controls.grid(row=1, column=0, padx=22, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(controls, text="View Bus:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(16, 6), pady=10)

        self.dash_bus_menu = ctk.CTkOptionMenu(
            controls,
            values=["ALL BUSES", "BUS01"],
            command=self._on_dash_bus_selected,
            width=140,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.dash_bus_menu.set(self.selected_bus)
        self.dash_bus_menu.pack(side="left", padx=(0, 16), pady=10)

        ctk.CTkLabel(controls, text="Date:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(6, 6), pady=10)

        self.dash_date_entry = ctk.CTkEntry(
            controls,
            width=115,
            height=32,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(size=12)
        )
        self.dash_date_entry.insert(0, self.selected_date)
        self.dash_date_entry.pack(side="left", padx=(0, 8), pady=10)

        ctk.CTkButton(
            controls,
            text="Apply Date",
            width=90,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_primary"],
            command=self._on_dash_apply_date
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            controls,
            text="Today",
            width=65,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_secondary"],
            command=self._on_dash_today
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            controls,
            text="🔄 Refresh",
            width=85,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_secondary"],
            command=self.refresh_dashboard_data
        ).pack(side="left", padx=4, pady=10)

        self.dash_status_indicator = ctk.CTkLabel(
            controls,
            text="Synced with local SQLite",
            font=ctk.CTkFont(size=12),
            text_color=PALETTE["text_tertiary"]
        )
        self.dash_status_indicator.pack(side="right", padx=16, pady=10)

        # KPI Summary Cards Frame (Selected View metrics)
        cards_frame = ctk.CTkFrame(frame, fg_color="transparent")
        cards_frame.grid(row=2, column=0, padx=22, pady=(0, 8), sticky="ew")
        for i in range(4):
            cards_frame.grid_columnconfigure(i, weight=1)

        self.card_total = self._create_modern_card(cards_frame, 0, "ROSTER SIZE", "0", "Students on roster", PALETTE["text_primary"])
        self.card_present = self._create_modern_card(cards_frame, 1, "PRESENT", "0", "Boarded & verified", PALETTE["success_green"])
        self.card_not_present = self._create_modern_card(cards_frame, 2, "NOT PRESENT", "0", "Pending boarding", PALETTE["danger_red"])
        self.card_percent = self._create_modern_card(cards_frame, 3, "ATTENDANCE RATE", "0.0%", "Of assigned roster", PALETTE["accent_blue"])

        # Overall Fleet vs Bus Comparison Banner
        self.fleet_banner = ctk.CTkFrame(frame, corner_radius=8, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        self.fleet_banner.grid(row=3, column=0, padx=22, pady=(0, 10), sticky="ew")

        self.fleet_summary_lbl = ctk.CTkLabel(
            self.fleet_banner,
            text="🏫 OVERALL FLEET ATTENDANCE: Total: 0 | Present: 0 | Not Present: 0 | Rate: 0.0%",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=PALETTE["text_secondary"]
        )
        self.fleet_summary_lbl.pack(padx=16, pady=8, anchor="w")

        # Table Container
        table_container = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["table_bg"], border_width=1, border_color=PALETTE["border"])
        table_container.grid(row=4, column=0, padx=22, pady=(0, 18), sticky="nsew")
        table_container.grid_columnconfigure(0, weight=1)
        table_container.grid_rowconfigure(0, weight=1)

        columns = ("student_id", "name", "class", "bus", "status", "time")
        self.dash_tree = ttk.Treeview(
            table_container,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        self.dash_tree.heading("student_id", text="Student ID", anchor="center")
        self.dash_tree.heading("name", text="Student Name", anchor="w")
        self.dash_tree.heading("class", text="Class", anchor="center")
        self.dash_tree.heading("bus", text="Assigned Bus", anchor="center")
        self.dash_tree.heading("status", text="Status", anchor="center")
        self.dash_tree.heading("time", text="Boarding Time", anchor="center")

        self.dash_tree.column("student_id", width=120, anchor="center")
        self.dash_tree.column("name", width=220, anchor="w")
        self.dash_tree.column("class", width=90, anchor="center")
        self.dash_tree.column("bus", width=110, anchor="center")
        self.dash_tree.column("status", width=140, anchor="center")
        self.dash_tree.column("time", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.dash_tree.yview)
        self.dash_tree.configure(yscrollcommand=scrollbar.set)
        self.dash_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)

        self._update_treeview_tags()
        return frame

    def _create_modern_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        title: str,
        value: str,
        subtitle: str,
        accent_color: Tuple[str, str]
    ) -> Dict[str, Any]:
        """Build KPI metric card."""
        card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color=PALETTE["bg_card"],
            border_width=1,
            border_color=PALETTE["border"]
        )
        card.grid(row=0, column=col, padx=4, sticky="nsew")

        title_lbl = ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=PALETTE["text_tertiary"]
        )
        title_lbl.pack(anchor="w", padx=16, pady=(12, 2))

        val_lbl = ctk.CTkLabel(
            card,
            text=value,
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=accent_color
        )
        val_lbl.pack(anchor="w", padx=16, pady=(0, 2))

        sub_lbl = ctk.CTkLabel(
            card,
            text=subtitle,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=PALETTE["text_secondary"]
        )
        sub_lbl.pack(anchor="w", padx=16, pady=(0, 12))

        return {"frame": card, "title_lbl": title_lbl, "val_lbl": val_lbl, "sub_lbl": sub_lbl}

    def _on_dash_bus_selected(self, bus_id: str) -> None:
        self.selected_bus = bus_id
        self.refresh_dashboard_data()

    def _on_dash_apply_date(self) -> None:
        val = self.dash_date_entry.get().strip()
        try:
            datetime.strptime(val, "%Y-%m-%d")
            self.selected_date = val
            self.refresh_dashboard_data()
        except ValueError:
            messagebox.showerror("Invalid Date", "Date must be formatted as YYYY-MM-DD.")

    def _on_dash_today(self) -> None:
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.selected_date = today_str
        self.dash_date_entry.delete(0, tk.END)
        self.dash_date_entry.insert(0, today_str)
        self.refresh_dashboard_data()

    def refresh_dashboard_data(self) -> None:
        """Query SQLite and reload Live Dashboard metrics and table with correct bus & overall math."""
        # 1. Update available buses dropdown
        distinct_buses = self.db.get_distinct_bus_ids()
        bus_options = ["ALL BUSES"] + [b for b in distinct_buses if b != "ALL BUSES"]
        if self.dash_bus_menu.cget("values") != bus_options:
            self.dash_bus_menu.configure(values=bus_options)
        self.dash_bus_menu.set(self.selected_bus)

        # 2. Get all registered students
        all_students = self.db.get_all_students()
        total_registered_all = len(all_students)

        # 3. Get all attendance records for selected date
        all_date_attendance = self.db.get_attendance_for_date(self.selected_date, bus_id=None)

        # Overall unique present students on selected date
        overall_present_ids = {r["student_id"] for r in all_date_attendance if r.get("status") == "Present"}
        overall_present_count = len(overall_present_ids)
        overall_not_present_count = max(total_registered_all - overall_present_count, 0)
        overall_pct = (overall_present_count / total_registered_all * 100.0) if total_registered_all > 0 else 0.0

        # Update Fleet Comparison Banner
        self.fleet_summary_lbl.configure(
            text=f"🏫 OVERALL FLEET ATTENDANCE ({self.selected_date}):  Total: {total_registered_all}  |  "
                 f"Present: {overall_present_count}  |  Not Present: {overall_not_present_count}  |  "
                 f"Rate: {overall_pct:.1f}%"
        )

        is_all_buses = (self.selected_bus in ("ALL BUSES", "All Buses"))

        if is_all_buses:
            total_students = total_registered_all
            present_count = overall_present_count
            not_present_count = overall_not_present_count
            percentage = overall_pct

            self.dash_bus_badge.configure(text="Fleet: ALL BUSES")
            self.card_total["val_lbl"].configure(text=str(total_students))
            self.card_total["sub_lbl"].configure(text="Total fleet roster")

            self.card_present["val_lbl"].configure(text=str(present_count))
            self.card_present["sub_lbl"].configure(text="Boarded across all buses")

            self.card_not_present["val_lbl"].configure(text=str(not_present_count))
            self.card_not_present["sub_lbl"].configure(text="Not yet boarded")

            self.card_percent["val_lbl"].configure(text=f"{percentage:.1f}%")
            self.card_percent["sub_lbl"].configure(text="Overall fleet rate")

            for item in self.dash_tree.get_children():
                self.dash_tree.delete(item)

            att_by_id = {r["student_id"]: r for r in all_date_attendance if r.get("status") == "Present"}

            for s in all_students:
                s_id = s["student_id"]
                if s_id in att_by_id:
                    rec = att_by_id[s_id]
                    self.dash_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), rec.get("bus_id", s.get("bus_id", "--")), "PRESENT", rec.get("attendance_time", "--")),
                        tags=("present",)
                    )

            for s in all_students:
                s_id = s["student_id"]
                if s_id not in att_by_id:
                    self.dash_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), s.get("bus_id", "--"), "NOT PRESENT", "--"),
                        tags=("not_present",)
                    )
        else:
            bus_students = [s for s in all_students if s.get("bus_id") == self.selected_bus]
            total_students = len(bus_students)
            bus_student_ids = {s["student_id"] for s in bus_students}

            bus_attendance = [r for r in all_date_attendance if r.get("bus_id") == self.selected_bus]
            present_assigned = [r for r in bus_attendance if r["student_id"] in bus_student_ids and r.get("status") == "Present"]
            present_count = len(present_assigned)
            not_present_count = max(total_students - present_count, 0)
            percentage = (present_count / total_students * 100.0) if total_students > 0 else 0.0

            unassigned_boardings = [r for r in bus_attendance if r["student_id"] not in bus_student_ids and r.get("status") == "Present"]

            self.dash_bus_badge.configure(text=f"Bus: {self.selected_bus}")
            self.card_total["val_lbl"].configure(text=str(total_students))
            self.card_total["sub_lbl"].configure(text=f"Assigned to {self.selected_bus} (Fleet: {total_registered_all})")

            self.card_present["val_lbl"].configure(text=str(present_count))
            self.card_present["sub_lbl"].configure(text=f"Boarded this bus (Fleet: {overall_present_count})")

            self.card_not_present["val_lbl"].configure(text=str(not_present_count))
            self.card_not_present["sub_lbl"].configure(text=f"Pending (Fleet: {overall_not_present_count})")

            self.card_percent["val_lbl"].configure(text=f"{percentage:.1f}%")
            self.card_percent["sub_lbl"].configure(text=f"Bus rate (Fleet: {overall_pct:.1f}%)")

            for item in self.dash_tree.get_children():
                self.dash_tree.delete(item)

            att_by_id = {r["student_id"]: r for r in present_assigned}

            for s in bus_students:
                s_id = s["student_id"]
                if s_id in att_by_id:
                    rec = att_by_id[s_id]
                    self.dash_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), s.get("bus_id", self.selected_bus), "PRESENT", rec.get("attendance_time", "--")),
                        tags=("present",)
                    )

            for s in bus_students:
                s_id = s["student_id"]
                if s_id not in att_by_id:
                    self.dash_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), s.get("bus_id", self.selected_bus), "NOT PRESENT", "--"),
                        tags=("not_present",)
                    )

            for unassigned in unassigned_boardings:
                u_id = unassigned["student_id"]
                self.dash_tree.insert(
                    "", "end",
                    values=(u_id, unassigned.get("name", u_id), unassigned.get("class_name", "--"), f"Wrong Bus ({self.selected_bus})", "PRESENT (Unassigned)", unassigned.get("attendance_time", "--")),
                    tags=("unassigned",)
                )

        now_time = datetime.now().strftime("%H:%M:%S")
        self.dash_status_indicator.configure(text=f"Synced at {now_time}")

    # =========================================================================
    # VIEW 2: LIVE ATTENDANCE (CAMERA ENGINE CONTROL)
    # =========================================================================

    def _create_live_view(self) -> ctk.CTkFrame:
        """Build the dedicated Live Attendance session view with embedded camera feed."""
        frame = ctk.CTkFrame(self.view_container, fg_color=PALETTE["bg_main"])
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # 1. Header
        header = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=22, pady=(18, 10), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Live Attendance Session",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=20, pady=(12, 1))

        ctk.CTkLabel(
            header,
            text="Embedded on-bus facial recognition camera and real-time boarding attendance",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # 2. Main Content: Split Camera (Left) & Attendance Info / Boarding Log (Right)
        content_frame = ctk.CTkFrame(frame, fg_color="transparent")
        content_frame.grid(row=1, column=0, padx=22, pady=0, sticky="nsew")
        content_frame.grid_columnconfigure(0, weight=3)
        content_frame.grid_columnconfigure(1, weight=2)
        content_frame.grid_rowconfigure(0, weight=1)

        # ---- LEFT PANEL: Embedded Camera Feed ----
        cam_card = ctk.CTkFrame(content_frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        cam_card.grid(row=0, column=0, padx=(0, 12), pady=0, sticky="nsew")
        cam_card.grid_columnconfigure(0, weight=1)
        cam_card.grid_rowconfigure(1, weight=1)

        cam_hdr = ctk.CTkFrame(cam_card, fg_color="transparent")
        cam_hdr.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="ew")

        ctk.CTkLabel(
            cam_hdr,
            text="📹 Live Camera Feed",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(side="left")

        self.live_status_badge = ctk.CTkLabel(
            cam_hdr,
            text="● STOPPED",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=PALETTE["text_tertiary"]
        )
        self.live_status_badge.pack(side="right")

        # Camera Display Label
        self.live_cam_lbl = ctk.CTkLabel(
            cam_card,
            text="Camera stopped.\nClick 'Start Attendance' to begin.",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=PALETTE["text_secondary"],
            fg_color=PALETTE["table_bg"],
            corner_radius=8
        )
        self.live_cam_lbl.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")

        # ---- RIGHT PANEL: Attendance Info & Recent Boarding Log ----
        info_card = ctk.CTkFrame(content_frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        info_card.grid(row=0, column=1, padx=(0, 0), pady=0, sticky="nsew")
        info_card.grid_columnconfigure(0, weight=1)
        info_card.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            info_card,
            text="Attendance Session Info",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")

        # Settings row inside right card
        settings_row = ctk.CTkFrame(info_card, fg_color="transparent")
        settings_row.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(settings_row, text="Bus:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(0, 4))
        self.live_bus_menu = ctk.CTkOptionMenu(
            settings_row,
            values=["BUS01"],
            width=110,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=self._on_live_bus_selected
        )
        self.live_bus_menu.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(settings_row, text="Cam:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(0, 4))
        self.live_cam_entry = ctk.CTkEntry(
            settings_row,
            width=50,
            height=32,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"]
        )
        self.live_cam_entry.insert(0, str(self.camera_index))
        self.live_cam_entry.pack(side="left")

        # Present Stats Banner
        self.live_stats_lbl = ctk.CTkLabel(
            info_card,
            text="Present on BUS01: 0 / 0 (0.0%)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=PALETTE["accent_blue"]
        )
        self.live_stats_lbl.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="w")

        # Boarding Log Table Header
        ctk.CTkLabel(
            info_card,
            text="Today's Boarding Activity Log",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).grid(row=3, column=0, padx=16, pady=(4, 4), sticky="w")

        # Table Container
        table_container = ctk.CTkFrame(info_card, corner_radius=8, fg_color=PALETTE["table_bg"], border_width=1, border_color=PALETTE["border"])
        table_container.grid(row=4, column=0, padx=14, pady=(0, 14), sticky="nsew")
        table_container.grid_columnconfigure(0, weight=1)
        table_container.grid_rowconfigure(0, weight=1)

        columns = ("student_id", "name", "class", "bus", "time", "status")
        self.live_tree = ttk.Treeview(
            table_container,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        self.live_tree.heading("student_id", text="Student ID", anchor="center")
        self.live_tree.heading("name", text="Name", anchor="w")
        self.live_tree.heading("class", text="Class", anchor="center")
        self.live_tree.heading("bus", text="Bus", anchor="center")
        self.live_tree.heading("time", text="Time", anchor="center")
        self.live_tree.heading("status", text="Status", anchor="center")

        self.live_tree.column("student_id", width=90, anchor="center")
        self.live_tree.column("name", width=140, anchor="w")
        self.live_tree.column("class", width=60, anchor="center")
        self.live_tree.column("bus", width=75, anchor="center")
        self.live_tree.column("time", width=80, anchor="center")
        self.live_tree.column("status", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.live_tree.yview)
        self.live_tree.configure(yscrollcommand=scrollbar.set)
        self.live_tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)

        # 3. Bottom Controls Row
        btn_bar = ctk.CTkFrame(frame, fg_color="transparent")
        btn_bar.grid(row=2, column=0, padx=22, pady=(12, 16), sticky="ew")

        self.live_start_btn = ctk.CTkButton(
            btn_bar,
            text="🎥 Start Attendance",
            width=180,
            height=40,
            fg_color=PALETTE["success_green"],
            hover_color="#0d9268",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#ffffff",
            command=self._start_live_attendance_camera
        )
        self.live_start_btn.pack(side="left", padx=(0, 10))

        self.live_stop_btn = ctk.CTkButton(
            btn_bar,
            text="🛑 Stop Attendance",
            width=170,
            height=40,
            fg_color=PALETTE["danger_red"],
            hover_color="#c23737",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#ffffff",
            state="disabled",
            command=self._stop_embedded_camera
        )
        self.live_stop_btn.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_bar,
            text="⬅ Back to Dashboard",
            width=160,
            height=40,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=13),
            command=lambda: self._show_view("dashboard")
        ).pack(side="right")

        return frame

    def _on_live_bus_selected(self, bus_id: str) -> None:
        self.active_bus_id = bus_id
        self.refresh_live_view_data()

    def refresh_live_view_data(self) -> None:
        """Update live attendance board metrics and recent boarding logs."""
        buses = self.db.get_distinct_bus_ids()
        if self.live_bus_menu.cget("values") != buses:
            self.live_bus_menu.configure(values=buses)
        if self.active_bus_id in buses:
            self.live_bus_menu.set(self.active_bus_id)

        target_bus = self.live_bus_menu.get().strip()
        today_str = datetime.now().strftime("%Y-%m-%d")

        bus_students = self.db.get_students_by_bus(bus_id=target_bus)
        total_assigned = len(bus_students)

        today_records = self.db.get_attendance_for_date(today_str, bus_id=target_bus)
        present_count = len([r for r in today_records if r.get("status") == "Present"])
        pct = (present_count / total_assigned * 100.0) if total_assigned > 0 else 0.0

        self.live_stats_lbl.configure(
            text=f"Present on {target_bus}: {present_count} / {total_assigned} ({pct:.1f}%)"
        )

        for item in self.live_tree.get_children():
            self.live_tree.delete(item)

        for r in reversed(today_records):
            self.live_tree.insert(
                "", "end",
                values=(
                    r["student_id"],
                    r["name"],
                    r.get("class_name", "--"),
                    r["bus_id"],
                    r.get("attendance_time", "--"),
                    r.get("status", "Present")
                ),
                tags=("present",)
            )

    # =========================================================================
    # VIEW 3: STUDENTS (DIRECTORY & BIOMETRIC ENROLLMENTS)
    # =========================================================================

    def _create_students_view(self) -> ctk.CTkFrame:
        """Build the Student Management view."""
        frame = ctk.CTkFrame(self.view_container, fg_color=PALETTE["bg_main"])
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # Header Frame
        header = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=22, pady=(18, 12), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Student Directory & Fleet Assignments",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=20, pady=(12, 1))

        ctk.CTkLabel(
            header,
            text="Manage student profiles, bus allocations, and biometric enrollments",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # Toolbar Frame
        actions_bar = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        actions_bar.grid(row=1, column=0, padx=22, pady=4, sticky="ew")

        # Action Buttons
        ctk.CTkButton(
            actions_bar,
            text="+ Register Student",
            width=140,
            height=34,
            fg_color=PALETTE["accent_blue"],
            hover_color=PALETTE["accent_blue_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff",
            command=self._on_launch_registration
        ).pack(side="left", padx=(14, 6), pady=10)

        ctk.CTkButton(
            actions_bar,
            text="✏️ Edit Student",
            width=110,
            height=34,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_primary"],
            command=self._on_edit_student
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            actions_bar,
            text="🔍 View Details",
            width=110,
            height=34,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_primary"],
            command=self._on_view_student_details
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            actions_bar,
            text="🗑️ Delete",
            width=85,
            height=34,
            fg_color=PALETTE["danger_red"],
            hover_color="#dc2626",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff",
            command=self._on_delete_student
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            actions_bar,
            text="🔄 Refresh",
            width=85,
            height=34,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_secondary"],
            command=self.refresh_students_data
        ).pack(side="left", padx=4, pady=10)

        # Search box on right
        self.student_search_entry = ctk.CTkEntry(
            actions_bar,
            placeholder_text="Search ID, Name, Bus...",
            width=200,
            height=34,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(size=12)
        )
        self.student_search_entry.pack(side="right", padx=14, pady=10)
        self.student_search_entry.bind("<KeyRelease>", lambda e: self.refresh_students_data())

        # Students Table
        table_container = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["table_bg"], border_width=1, border_color=PALETTE["border"])
        table_container.grid(row=2, column=0, padx=22, pady=(10, 18), sticky="nsew")
        table_container.grid_columnconfigure(0, weight=1)
        table_container.grid_rowconfigure(0, weight=1)

        columns = ("student_id", "name", "class", "bus", "attendance_count", "registered_on")
        self.students_tree = ttk.Treeview(
            table_container,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        self.students_tree.heading("student_id", text="Student ID", anchor="center")
        self.students_tree.heading("name", text="Full Name", anchor="w")
        self.students_tree.heading("class", text="Class / Grade", anchor="center")
        self.students_tree.heading("bus", text="Assigned Bus", anchor="center")
        self.students_tree.heading("attendance_count", text="Total Sessions", anchor="center")
        self.students_tree.heading("registered_on", text="Enrollment Date", anchor="center")

        self.students_tree.column("student_id", width=120, anchor="center")
        self.students_tree.column("name", width=220, anchor="w")
        self.students_tree.column("class", width=100, anchor="center")
        self.students_tree.column("bus", width=110, anchor="center")
        self.students_tree.column("attendance_count", width=110, anchor="center")
        self.students_tree.column("registered_on", width=160, anchor="center")

        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.students_tree.yview)
        self.students_tree.configure(yscrollcommand=scrollbar.set)
        self.students_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)

        return frame

    def _get_selected_student_id(self) -> Optional[str]:
        selected = self.students_tree.selection()
        if not selected:
            return None
        values = self.students_tree.item(selected[0], "values")
        return str(values[0]) if values else None

    def _on_edit_student(self) -> None:
        stu_id = self._get_selected_student_id()
        if not stu_id:
            messagebox.showinfo("Selection Required", "Please select a student from the table to edit.")
            return

        student = self.db.get_student_by_id(stu_id)
        if not student:
            messagebox.showerror("Error", f"Student {stu_id} not found in database.")
            return

        EditStudentDialog(
            parent=self,
            student=student,
            db=self.db,
            on_saved_callback=lambda: (self.refresh_students_data(), self.refresh_dashboard_data())
        )

    def _on_view_student_details(self) -> None:
        stu_id = self._get_selected_student_id()
        if not stu_id:
            messagebox.showinfo("Selection Required", "Please select a student from the table first.")
            return

        student = self.db.get_student_by_id(stu_id)
        if not student:
            messagebox.showerror("Error", f"Student {stu_id} not found in database.")
            return

        StudentDetailsDialog(self, student, self.db)

    def _on_delete_student(self) -> None:
        stu_id = self._get_selected_student_id()
        if not stu_id:
            messagebox.showinfo("Selection Required", "Please select a student to delete.")
            return

        student = self.db.get_student_by_id(stu_id)
        if not student:
            messagebox.showerror("Error", f"Student {stu_id} not found.")
            return

        name = student["name"]
        att_count = self.db.get_student_attendance_count(stu_id)

        if att_count > 0:
            msg = (
                f"Student '{name}' (ID: {stu_id}) has {att_count} historical attendance records.\n\n"
                f"Deleting this student removes their profile and facial biometric embedding.\n\n"
                f"Historical attendance records will be PRESERVED in the audit log.\n\n"
                f"Do you want to proceed?"
            )
        else:
            msg = f"Are you sure you want to delete student '{name}' (ID: {stu_id})?"

        confirm = messagebox.askyesno("Confirm Deletion", msg, icon="warning")
        if confirm:
            ok = self.db.delete_student(stu_id)
            if ok:
                messagebox.showinfo("Student Deleted", f"Student '{name}' ({stu_id}) was removed.")
                self.refresh_students_data()
                self.refresh_dashboard_data()
            else:
                messagebox.showerror("Delete Error", f"Failed to delete student {stu_id}.")

    def _on_launch_registration(self) -> None:
        """Switch to in-application registration view (no terminal needed!)."""
        self._show_view("register")

    def refresh_students_data(self) -> None:
        """Reload student directory table, applying search filter."""
        students = self.db.get_all_students()
        search_query = self.student_search_entry.get().strip().lower()

        for item in self.students_tree.get_children():
            self.students_tree.delete(item)

        for s in students:
            s_id = s["student_id"]
            name = s["name"]
            bus = s.get("bus_id", "")
            class_name = s.get("class_name", "")

            if search_query:
                combined = f"{s_id} {name} {bus} {class_name}".lower()
                if search_query not in combined:
                    continue

            att_cnt = self.db.get_student_attendance_count(s_id)
            created = s.get("created_at", "--")
            if "T" in created:
                created = created.replace("T", " ").split(".")[0]

            self.students_tree.insert(
                "", "end",
                values=(s_id, name, class_name, bus, att_cnt, created)
            )

    # =========================================================================
    # VIEW 4: ATTENDANCE HISTORY
    # =========================================================================

    def _create_history_view(self) -> ctk.CTkFrame:
        """Build the Historical Attendance view."""
        frame = ctk.CTkFrame(self.view_container, fg_color=PALETTE["bg_main"])
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # Header Frame
        header = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=22, pady=(18, 12), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Attendance History & Audit Logs",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=20, pady=(12, 1))

        ctk.CTkLabel(
            header,
            text="Inspect historical attendance records across dates and buses",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # Filter Bar
        filters = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        filters.grid(row=1, column=0, padx=22, pady=4, sticky="ew")

        ctk.CTkLabel(filters, text="Bus:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(16, 6), pady=10)

        self.hist_bus_menu = ctk.CTkOptionMenu(
            filters,
            values=["ALL BUSES", "BUS01"],
            width=130,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.hist_bus_menu.set(self.selected_bus)
        self.hist_bus_menu.pack(side="left", padx=(0, 16), pady=10)

        ctk.CTkLabel(filters, text="Date:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(6, 6), pady=10)

        self.hist_date_entry = ctk.CTkEntry(
            filters,
            width=115,
            height=32,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(size=12)
        )
        self.hist_date_entry.insert(0, self.selected_date)
        self.hist_date_entry.pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkButton(
            filters,
            text="Search / Filter",
            width=110,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_primary"],
            command=self.refresh_history_data
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            filters,
            text="Today",
            width=65,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_secondary"],
            command=self._on_hist_today
        ).pack(side="left", padx=4, pady=10)

        # Summary indicator
        self.hist_summary_lbl = ctk.CTkLabel(
            filters,
            text="Present: 0 / 0 (0.0%)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=PALETTE["text_primary"]
        )
        self.hist_summary_lbl.pack(side="right", padx=20, pady=10)

        # Table Container
        table_container = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["table_bg"], border_width=1, border_color=PALETTE["border"])
        table_container.grid(row=2, column=0, padx=22, pady=(10, 18), sticky="nsew")
        table_container.grid_columnconfigure(0, weight=1)
        table_container.grid_rowconfigure(0, weight=1)

        columns = ("student_id", "name", "class", "bus", "status", "time")
        self.hist_tree = ttk.Treeview(
            table_container,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        self.hist_tree.heading("student_id", text="Student ID", anchor="center")
        self.hist_tree.heading("name", text="Name", anchor="w")
        self.hist_tree.heading("class", text="Class", anchor="center")
        self.hist_tree.heading("bus", text="Bus", anchor="center")
        self.hist_tree.heading("status", text="Status", anchor="center")
        self.hist_tree.heading("time", text="Boarding Time", anchor="center")

        self.hist_tree.column("student_id", width=120, anchor="center")
        self.hist_tree.column("name", width=220, anchor="w")
        self.hist_tree.column("class", width=90, anchor="center")
        self.hist_tree.column("bus", width=110, anchor="center")
        self.hist_tree.column("status", width=130, anchor="center")
        self.hist_tree.column("time", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=scrollbar.set)
        self.hist_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)

        return frame

    def _on_hist_today(self) -> None:
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.hist_date_entry.delete(0, tk.END)
        self.hist_date_entry.insert(0, today_str)
        self.refresh_history_data()

    def refresh_history_data(self) -> None:
        """Query historical records for selected bus and date."""
        distinct_buses = self.db.get_distinct_bus_ids()
        bus_options = ["ALL BUSES"] + [b for b in distinct_buses if b != "ALL BUSES"]
        if self.hist_bus_menu.cget("values") != bus_options:
            self.hist_bus_menu.configure(values=bus_options)

        selected_bus = self.hist_bus_menu.get().strip()
        date_str = self.hist_date_entry.get().strip()

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Invalid Date", "Please enter a valid date in format YYYY-MM-DD.")
            return

        is_all = (selected_bus in ("ALL BUSES", "All Buses"))

        if is_all:
            all_students = self.db.get_all_students()
            total_students = len(all_students)
            records = self.db.get_attendance_for_date(attendance_date=date_str, bus_id=None)
            present_records = [r for r in records if r.get("status") == "Present"]
            present_count = len({r["student_id"] for r in present_records})
            pct = (present_count / total_students * 100.0) if total_students > 0 else 0.0

            self.hist_summary_lbl.configure(text=f"Present (All Buses): {present_count} / {total_students} ({pct:.1f}%)")

            for item in self.hist_tree.get_children():
                self.hist_tree.delete(item)

            att_by_id = {r["student_id"]: r for r in present_records}

            for s in all_students:
                s_id = s["student_id"]
                if s_id in att_by_id:
                    rec = att_by_id[s_id]
                    self.hist_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), rec.get("bus_id", s.get("bus_id", "--")), "PRESENT", rec.get("attendance_time", "--")),
                        tags=("present",)
                    )

            for s in all_students:
                s_id = s["student_id"]
                if s_id not in att_by_id:
                    self.hist_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), s.get("bus_id", "--"), "NOT PRESENT", "--"),
                        tags=("not_present",)
                    )
        else:
            bus_students = self.db.get_students_by_bus(bus_id=selected_bus)
            total_students = len(bus_students)
            records = self.db.get_attendance_for_date(attendance_date=date_str, bus_id=selected_bus)
            bus_student_ids = {s["student_id"] for s in bus_students}
            present_records = [r for r in records if r["student_id"] in bus_student_ids and r.get("status") == "Present"]
            present_count = len(present_records)
            pct = (present_count / total_students * 100.0) if total_students > 0 else 0.0

            self.hist_summary_lbl.configure(text=f"Present on {selected_bus}: {present_count} / {total_students} ({pct:.1f}%)")

            for item in self.hist_tree.get_children():
                self.hist_tree.delete(item)

            att_by_id = {r["student_id"]: r for r in present_records}

            for s in bus_students:
                s_id = s["student_id"]
                if s_id in att_by_id:
                    rec = att_by_id[s_id]
                    self.hist_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), selected_bus, "PRESENT", rec.get("attendance_time", "--")),
                        tags=("present",)
                    )

            for s in bus_students:
                s_id = s["student_id"]
                if s_id not in att_by_id:
                    self.hist_tree.insert(
                        "", "end",
                        values=(s_id, s["name"], s.get("class_name", "--"), selected_bus, "NOT PRESENT", "--"),
                        tags=("not_present",)
                    )

    # =========================================================================
    # VIEW 5: REPORTS & CSV EXPORT
    # =========================================================================

    def _create_reports_view(self) -> ctk.CTkFrame:
        """Build the Report Generator and CSV Export view."""
        frame = ctk.CTkFrame(self.view_container, fg_color=PALETTE["bg_main"])
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # Header Frame
        header = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=22, pady=(18, 12), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Attendance Reports & CSV Export",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=20, pady=(12, 1))

        ctk.CTkLabel(
            header,
            text="Generate compliant CSV reports for administrative archival and school analytics",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # Controls Bar
        controls = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        controls.grid(row=1, column=0, padx=22, pady=4, sticky="ew")

        ctk.CTkLabel(controls, text="Bus:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(16, 6), pady=10)

        self.rep_bus_menu = ctk.CTkOptionMenu(
            controls,
            values=["ALL BUSES", "BUS01"],
            width=130,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=lambda b: self.refresh_reports_preview(),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.rep_bus_menu.set(self.selected_bus)
        self.rep_bus_menu.pack(side="left", padx=(0, 16), pady=10)

        ctk.CTkLabel(controls, text="Date:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(6, 6), pady=10)

        self.rep_date_entry = ctk.CTkEntry(
            controls,
            width=115,
            height=32,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(size=12)
        )
        self.rep_date_entry.insert(0, self.selected_date)
        self.rep_date_entry.pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkButton(
            controls,
            text="Preview",
            width=80,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_primary"],
            command=self.refresh_reports_preview
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            controls,
            text="Today",
            width=65,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_secondary"],
            command=self._on_rep_today
        ).pack(side="left", padx=4, pady=10)

        # Export Button
        ctk.CTkButton(
            controls,
            text="📥 Export CSV",
            width=130,
            height=34,
            fg_color=PALETTE["accent_blue"],
            hover_color=PALETTE["accent_blue_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff",
            command=self._on_export_csv
        ).pack(side="right", padx=16, pady=10)

        self.rep_status_lbl = ctk.CTkLabel(
            controls,
            text="Ready to export",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE["text_secondary"]
        )
        self.rep_status_lbl.pack(side="right", padx=12, pady=10)

        # Preview Table Container
        table_container = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["table_bg"], border_width=1, border_color=PALETTE["border"])
        table_container.grid(row=2, column=0, padx=22, pady=(10, 18), sticky="nsew")
        table_container.grid_columnconfigure(0, weight=1)
        table_container.grid_rowconfigure(0, weight=1)

        columns = ("student_id", "name", "class", "bus", "date", "status", "time")
        self.rep_tree = ttk.Treeview(
            table_container,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        self.rep_tree.heading("student_id", text="Student ID", anchor="center")
        self.rep_tree.heading("name", text="Name", anchor="w")
        self.rep_tree.heading("class", text="Class", anchor="center")
        self.rep_tree.heading("bus", text="Bus ID", anchor="center")
        self.rep_tree.heading("date", text="Date", anchor="center")
        self.rep_tree.heading("status", text="Status", anchor="center")
        self.rep_tree.heading("time", text="Boarding Time", anchor="center")

        self.rep_tree.column("student_id", width=110, anchor="center")
        self.rep_tree.column("name", width=200, anchor="w")
        self.rep_tree.column("class", width=80, anchor="center")
        self.rep_tree.column("bus", width=90, anchor="center")
        self.rep_tree.column("date", width=110, anchor="center")
        self.rep_tree.column("status", width=110, anchor="center")
        self.rep_tree.column("time", width=110, anchor="center")

        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.rep_tree.yview)
        self.rep_tree.configure(yscrollcommand=scrollbar.set)
        self.rep_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)

        return frame

    def _on_rep_today(self) -> None:
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.rep_date_entry.delete(0, tk.END)
        self.rep_date_entry.insert(0, today_str)
        self.refresh_reports_preview()

    def _get_report_data(self) -> List[Dict[str, str]]:
        """Compute the full attendance roster for selected date and bus (or ALL BUSES)."""
        bus_id = self.rep_bus_menu.get().strip()
        date_str = self.rep_date_entry.get().strip()

        is_all = (bus_id in ("ALL BUSES", "All Buses"))

        if is_all:
            students = self.db.get_all_students()
            records = self.db.get_attendance_for_date(attendance_date=date_str, bus_id=None)
        else:
            students = self.db.get_students_by_bus(bus_id=bus_id)
            records = self.db.get_attendance_for_date(attendance_date=date_str, bus_id=bus_id)

        present_map = {r["student_id"]: r for r in records if r.get("status") == "Present"}

        result = []
        for s in students:
            s_id = s["student_id"]
            assigned_bus = s.get("bus_id", bus_id)
            if s_id in present_map:
                rec = present_map[s_id]
                result.append({
                    "student_id": s_id,
                    "name": s["name"],
                    "class_name": s.get("class_name", "--"),
                    "bus_id": rec.get("bus_id", assigned_bus),
                    "date": date_str,
                    "status": "Present",
                    "time": rec.get("attendance_time", "--")
                })
            else:
                result.append({
                    "student_id": s_id,
                    "name": s["name"],
                    "class_name": s.get("class_name", "--"),
                    "bus_id": assigned_bus,
                    "date": date_str,
                    "status": "Not Present",
                    "time": "--"
                })

        return result

    def refresh_reports_preview(self) -> None:
        """Update report preview treeview with current date/bus."""
        distinct_buses = self.db.get_distinct_bus_ids()
        bus_options = ["ALL BUSES"] + [b for b in distinct_buses if b != "ALL BUSES"]
        if self.rep_bus_menu.cget("values") != bus_options:
            self.rep_bus_menu.configure(values=bus_options)

        date_str = self.rep_date_entry.get().strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Invalid Date", "Please enter date in format YYYY-MM-DD.")
            return

        for item in self.rep_tree.get_children():
            self.rep_tree.delete(item)

        data = self._get_report_data()
        present_count = 0
        for row in data:
            tag = "present" if row["status"] == "Present" else "not_present"
            if row["status"] == "Present":
                present_count += 1
            self.rep_tree.insert(
                "",
                "end",
                values=(
                    row["student_id"],
                    row["name"],
                    row["class_name"],
                    row["bus_id"],
                    row["date"],
                    row["status"],
                    row["time"]
                ),
                tags=(tag,)
            )

        self.rep_status_lbl.configure(text=f"Total: {len(data)} | Present: {present_count}")

    def _on_export_csv(self) -> None:
        """Export current report to CSV with file dialog, overwrite confirmation, and validation."""
        bus_id = self.rep_bus_menu.get().strip()
        date_str = self.rep_date_entry.get().strip()

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Invalid Date", "Please enter a valid date in YYYY-MM-DD format.")
            return

        report_rows = self._get_report_data()
        if not report_rows:
            messagebox.showwarning("No Data", f"No student records found for {bus_id}.")
            return

        is_all = (bus_id in ("ALL BUSES", "All Buses"))
        bus_filename_part = "ALL_BUSES" if is_all else bus_id
        default_filename = f"attendance_{bus_filename_part}_{date_str}.csv"

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_filename,
            title="Save Attendance CSV Report"
        )

        if not file_path:
            return

        if os.path.exists(file_path):
            overwrite = messagebox.askyesno(
                "Overwrite File?",
                f"The file '{os.path.basename(file_path)}' already exists.\nDo you want to replace it?"
            )
            if not overwrite:
                return

        try:
            with open(file_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Student ID", "Name", "Class", "Bus ID", "Date", "Status", "Time"])
                for r in report_rows:
                    writer.writerow([
                        r["student_id"],
                        r["name"],
                        r["class_name"],
                        r["bus_id"],
                        r["date"],
                        r["status"],
                        r["time"]
                    ])

            messagebox.showinfo(
                "Export Successful",
                f"Attendance report successfully exported!\n\n"
                f"File: {os.path.basename(file_path)}\n"
                f"Total Records: {len(report_rows)}"
            )
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to write CSV file:\n{e}")

    # =========================================================================
    # VIEW 6: REGISTER STUDENT (GUI ENROLLMENT WIZARD)
    # =========================================================================

    def _create_register_view(self) -> ctk.CTkFrame:
        """Build the student registration view with embedded camera and form fields."""
        frame = ctk.CTkFrame(self.view_container, fg_color=PALETTE["bg_main"])
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # 1. Header
        header = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=22, pady=(18, 10), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Register Student",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=20, pady=(12, 1))

        ctk.CTkLabel(
            header,
            text="Live face capture and biometric student registration into the attendance database",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # 2. Main Content: Split Camera (Left) & Student Details Form (Right)
        content_frame = ctk.CTkFrame(frame, fg_color="transparent")
        content_frame.grid(row=1, column=0, padx=22, pady=0, sticky="nsew")
        content_frame.grid_columnconfigure(0, weight=3)
        content_frame.grid_columnconfigure(1, weight=2)
        content_frame.grid_rowconfigure(0, weight=1)

        # ---- LEFT PANEL: Embedded Camera Feed & Detection Status ----
        cam_card = ctk.CTkFrame(content_frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        cam_card.grid(row=0, column=0, padx=(0, 12), pady=0, sticky="nsew")
        cam_card.grid_columnconfigure(0, weight=1)
        cam_card.grid_rowconfigure(1, weight=1)

        cam_hdr = ctk.CTkFrame(cam_card, fg_color="transparent")
        cam_hdr.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="ew")

        ctk.CTkLabel(
            cam_hdr,
            text="📷 Live Registration Camera",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(side="left")

        # Camera Display Label
        self.reg_cam_preview_lbl = ctk.CTkLabel(
            cam_card,
            text="Connecting to webcam...",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=PALETTE["text_secondary"],
            fg_color=PALETTE["table_bg"],
            corner_radius=8
        )
        self.reg_cam_preview_lbl.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="nsew")

        # Camera status label below preview
        self.reg_cam_status_lbl = ctk.CTkLabel(
            cam_card,
            text="Initializing camera...",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=PALETTE["warning_amber"]
        )
        self.reg_cam_status_lbl.grid(row=2, column=0, padx=14, pady=(0, 8), sticky="ew")

        # Fallback & camera index row
        cam_tools_row = ctk.CTkFrame(cam_card, fg_color="transparent")
        cam_tools_row.grid(row=3, column=0, padx=14, pady=(0, 14), sticky="ew")

        ctk.CTkButton(
            cam_tools_row,
            text="📁 Select Photo File",
            width=150,
            height=32,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=self._on_select_photo_file
        ).pack(side="left")

        ctk.CTkLabel(cam_tools_row, text="Camera Index:", font=ctk.CTkFont(size=12), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(16, 6))
        self.reg_cam_entry = ctk.CTkEntry(
            cam_tools_row,
            width=50,
            height=32,
            fg_color=PALETTE["bg_sidebar"],
            border_color=PALETTE["border"],
            text_color=PALETTE["text_primary"]
        )
        self.reg_cam_entry.insert(0, "0")
        self.reg_cam_entry.pack(side="left")

        # ---- RIGHT PANEL: Student Details Form & Action ----
        form_card = ctk.CTkFrame(content_frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        form_card.grid(row=0, column=1, padx=(0, 0), pady=0, sticky="nsew")
        form_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            form_card,
            text="Student Details",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=18, pady=(14, 10))

        # Form fields
        form_inner = ctk.CTkFrame(form_card, fg_color="transparent")
        form_inner.pack(fill="x", padx=18, pady=0)
        form_inner.grid_columnconfigure(0, weight=1)

        # Student ID
        ctk.CTkLabel(form_inner, text="Student ID *", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.reg_id_entry = ctk.CTkEntry(
            form_inner, height=36, placeholder_text="e.g. STU001",
            fg_color=PALETTE["bg_sidebar"], border_color=PALETTE["border"], text_color=PALETTE["text_primary"]
        )
        self.reg_id_entry.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        # Full Name
        ctk.CTkLabel(form_inner, text="Full Name *", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.reg_name_entry = ctk.CTkEntry(
            form_inner, height=36, placeholder_text="e.g. Alex Johnson",
            fg_color=PALETTE["bg_sidebar"], border_color=PALETTE["border"], text_color=PALETTE["text_primary"]
        )
        self.reg_name_entry.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        # Class / Grade
        ctk.CTkLabel(form_inner, text="Class / Grade *", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).grid(row=4, column=0, sticky="w", pady=(0, 2))
        self.reg_class_entry = ctk.CTkEntry(
            form_inner, height=36, placeholder_text="e.g. 5A",
            fg_color=PALETTE["bg_sidebar"], border_color=PALETTE["border"], text_color=PALETTE["text_primary"]
        )
        self.reg_class_entry.grid(row=5, column=0, sticky="ew", pady=(0, 8))

        # Assigned Bus
        ctk.CTkLabel(form_inner, text="Assigned Bus *", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).grid(row=6, column=0, sticky="w", pady=(0, 2))
        bus_row = ctk.CTkFrame(form_inner, fg_color="transparent")
        bus_row.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        bus_row.grid_columnconfigure(0, weight=1)

        existing_buses = self.db.get_distinct_bus_ids() or [DEFAULT_BUS_ID]
        self.reg_bus_menu = ctk.CTkOptionMenu(
            bus_row,
            values=sorted(set(existing_buses)),
            height=36,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"]
        )
        self.reg_bus_menu.set(existing_buses[0] if existing_buses else DEFAULT_BUS_ID)
        self.reg_bus_menu.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.reg_bus_custom_entry = ctk.CTkEntry(
            bus_row, height=36, placeholder_text="Or new bus...",
            width=110,
            fg_color=PALETTE["bg_sidebar"], border_color=PALETTE["border"], text_color=PALETTE["text_primary"]
        )
        self.reg_bus_custom_entry.grid(row=0, column=1, sticky="ew")

        # Capture status badge card
        status_box = ctk.CTkFrame(form_card, fg_color=PALETTE["bg_sidebar"], corner_radius=8, border_width=1, border_color=PALETTE["border"])
        status_box.pack(fill="x", padx=18, pady=(4, 10))

        self.reg_capture_status_lbl = ctk.CTkLabel(
            status_box,
            text="⚪ Face not captured yet.\nAlign face in camera and click 'Capture Face'.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=PALETTE["text_secondary"],
            justify="center"
        )
        self.reg_capture_status_lbl.pack(padx=10, pady=8)

        # Action Buttons inside form card
        btn_box = ctk.CTkFrame(form_card, fg_color="transparent")
        btn_box.pack(fill="x", padx=18, pady=(0, 14))

        self.reg_capture_btn = ctk.CTkButton(
            btn_box,
            text="📸 Capture Face",
            height=38,
            corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=PALETTE["accent_blue"],
            hover_color=PALETTE["accent_blue_hover"],
            text_color="#ffffff",
            command=self._on_reg_capture_face
        )
        self.reg_capture_btn.pack(fill="x", pady=(0, 6))

        self.reg_submit_btn = ctk.CTkButton(
            btn_box,
            text="💾 Register Student",
            height=38,
            corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=PALETTE["success_green"],
            hover_color="#0d9268",
            text_color="#ffffff",
            command=self._on_reg_save_student
        )
        self.reg_submit_btn.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            btn_box,
            text="🗑 Clear Form",
            height=32,
            corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_secondary"],
            command=self._on_reg_clear
        ).pack(fill="x")

        # 3. Bottom Row: Back Button
        bot_bar = ctk.CTkFrame(frame, fg_color="transparent")
        bot_bar.grid(row=2, column=0, padx=22, pady=(10, 16), sticky="ew")

        ctk.CTkButton(
            bot_bar,
            text="⬅ Back to Dashboard",
            width=160,
            height=38,
            corner_radius=8,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=13),
            command=lambda: self._show_view("dashboard")
        ).pack(side="left")

        return frame

    def _on_reg_capture_face(self) -> None:
        """Capture the current face embedding from the live camera stream."""
        with self._camera_lock:
            faces = list(self._latest_reg_faces)
            ready = self._latest_reg_ready

        if not ready or len(faces) != 1:
            messagebox.showwarning("Face Required", "Exactly 1 face must be visible in the camera to capture.", parent=self)
            return

        self._reg_captured_embedding = faces[0].embedding
        self.reg_capture_status_lbl.configure(
            text="✅ Biometric face template captured!\nReady to register student.",
            text_color=PALETTE["success_green"]
        )

    def _on_reg_save_student(self) -> None:
        """Validate student details form, verify biometrics, check duplicates, and register."""
        student_id = self.reg_id_entry.get().strip()
        name = self.reg_name_entry.get().strip()
        class_name = self.reg_class_entry.get().strip()
        custom_bus = self.reg_bus_custom_entry.get().strip()
        bus_id = custom_bus if custom_bus else self.reg_bus_menu.get().strip()

        if not student_id:
            messagebox.showerror("Missing Field", "Student ID is required.", parent=self)
            return
        if not name:
            messagebox.showerror("Missing Field", "Full Name is required.", parent=self)
            return
        if not class_name:
            messagebox.showerror("Missing Field", "Class / Grade is required.", parent=self)
            return
        if not bus_id:
            messagebox.showerror("Missing Field", "Assigned Bus is required.", parent=self)
            return

        # STRICT DUPLICATE CHECK: As required, reject duplicate ID and do not overwrite existing student!
        existing = self.db.get_student_by_id(student_id)
        if existing:
            messagebox.showerror(
                "Student ID Already Exists",
                f"Student ID '{student_id}' is already registered to '{existing['name']}' ({existing.get('class_name', '')}).\n\n"
                f"Registration rejected. Duplicate Student IDs are not permitted.\n"
                f"To update this student's profile, edit them in the Student Directory.",
                parent=self
            )
            return

        # Check embedding
        embedding = self._reg_captured_embedding
        if embedding is None:
            with self._camera_lock:
                if self._latest_reg_ready and len(self._latest_reg_faces) == 1:
                    embedding = self._latest_reg_faces[0].embedding

            if embedding is None:
                messagebox.showwarning(
                    "Face Capture Required",
                    "Please look at the camera and click 'Capture Face' before registering.",
                    parent=self
                )
                return

        ok = self.db.register_student(
            student_id=student_id,
            name=name,
            class_name=class_name,
            bus_id=bus_id,
            face_embedding=embedding
        )
        if ok:
            messagebox.showinfo(
                "Registration Successful",
                f"Student '{name}' ({student_id}) enrolled successfully!\nAssigned to: {bus_id}",
                parent=self
            )
            self._reg_captured_embedding = None
            self._on_reg_clear()
            self.refresh_students_data()
            self.refresh_dashboard_data()
        else:
            messagebox.showerror("Save Failed", "Failed to save student record to database.", parent=self)

    def _on_reg_clear(self) -> None:
        """Clear the registration form and reset biometric template state."""
        self.reg_id_entry.delete(0, tk.END)
        self.reg_name_entry.delete(0, tk.END)
        self.reg_class_entry.delete(0, tk.END)
        self.reg_bus_custom_entry.delete(0, tk.END)
        self._reg_captured_embedding = None
        if hasattr(self, "reg_capture_status_lbl"):
            self.reg_capture_status_lbl.configure(
                text="⚪ Face not captured yet.\nAlign face in camera and click 'Capture Face'.",
                text_color=PALETTE["text_secondary"]
            )

    def _on_select_photo_file(self) -> None:
        """Allow administrator to select a photo file if camera is offline."""
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Select Student Photo for Biometric Enrollment",
            filetypes=[("Image files", "*.jpg;*.jpeg;*.png"), ("All files", "*.*")]
        )
        if not file_path:
            return

        try:
            recognizer = self.get_face_recognizer()
            img = cv2.imread(file_path)
            if img is None:
                messagebox.showerror("Error", "Could not load image file.", parent=self)
                return

            faces = recognizer.extract_faces(img)
            if len(faces) == 0:
                messagebox.showerror("No Face Found", "No face was detected in the selected image.", parent=self)
                return
            if len(faces) > 1:
                messagebox.showerror("Multiple Faces", f"Found {len(faces)} faces. Exactly 1 face required.", parent=self)
                return

            self._reg_captured_embedding = faces[0].embedding
            self.reg_capture_status_lbl.configure(
                text=f"✅ Biometrics loaded from file:\n{os.path.basename(file_path)}",
                text_color=PALETTE["success_green"]
            )
            messagebox.showinfo("Face Extracted", "Face biometric template successfully extracted from photo file!", parent=self)
        except Exception as e:
            messagebox.showerror("Extraction Error", f"Failed to extract face template:\n{e}", parent=self)

    # =========================================================================
    # VIEW 7: SETTINGS & MAINTENANCE
    # =========================================================================

    def _create_settings_view(self) -> ctk.CTkFrame:
        """Build the System Settings & Maintenance view."""
        frame = ctk.CTkFrame(self.view_container, fg_color=PALETTE["bg_main"])
        frame.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        header.grid(row=0, column=0, padx=22, pady=(18, 12), sticky="ew")

        ctk.CTkLabel(
            header,
            text="Settings & System Maintenance",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=PALETTE["text_primary"]
        ).pack(anchor="w", padx=20, pady=(12, 1))

        ctk.CTkLabel(
            header,
            text="Configure application preferences, bus routes, and testing utilities",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # Settings Cards Container
        cards_outer = ctk.CTkFrame(frame, fg_color="transparent")
        cards_outer.grid(row=1, column=0, padx=22, pady=0, sticky="nsew")
        cards_outer.grid_columnconfigure(0, weight=1)
        cards_outer.grid_columnconfigure(1, weight=1)

        # Left Card: General & Appearance
        left_card = ctk.CTkFrame(cards_outer, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        left_card.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="nsew")

        ctk.CTkLabel(left_card, text="General & UI Preferences", font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color=PALETTE["text_primary"]).pack(anchor="w", padx=18, pady=(16, 12))

        # Appearance mode
        ctk.CTkLabel(left_card, text="Appearance Theme:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(anchor="w", padx=18, pady=(4, 2))
        self.settings_theme_menu = ctk.CTkOptionMenu(
            left_card,
            values=["Dark", "Light"],
            command=self._on_change_appearance,
            height=34,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"]
        )
        self.settings_theme_menu.set(ctk.get_appearance_mode())
        self.settings_theme_menu.pack(fill="x", padx=18, pady=(0, 14))

        # Default Bus ID
        ctk.CTkLabel(left_card, text="Default Active Bus Route:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(anchor="w", padx=18, pady=(4, 2))
        self.settings_bus_menu = ctk.CTkOptionMenu(
            left_card,
            values=["BUS01"],
            height=34,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"],
            command=self._on_settings_bus_changed
        )
        self.settings_bus_menu.pack(fill="x", padx=18, pady=(0, 14))

        # System Specs Card
        right_card = ctk.CTkFrame(cards_outer, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        right_card.grid(row=0, column=1, padx=(10, 0), pady=0, sticky="nsew")

        ctk.CTkLabel(right_card, text="Biometrics & System Specifications", font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color=PALETTE["text_primary"]).pack(anchor="w", padx=18, pady=(16, 12))

        specs = [
            ("Application Version", "Autobus Fleet Suite V4.2 (2026)"),
            ("Biometrics Engine", "InsightFace ArcFace 512D (buffalo_sc)"),
            ("Verification Cutoff", f"Cosine Similarity >= {DEFAULT_SIMILARITY_THRESHOLD:.2f}"),
            ("Confirmation Rule", f"{REQUIRED_CONFIRMATIONS} observations in {CONFIRMATION_WINDOW_SECONDS:.1f}s window"),
            ("Database Storage", f"Local SQLite: {self.db_path}"),
            ("Cloud Biometrics", "DISABLED (100% On-Device Private)"),
        ]

        for label, val in specs:
            row = ctk.CTkFrame(right_card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=3)
            ctk.CTkLabel(row, text=label + ":", font=ctk.CTkFont(size=11, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left")
            ctk.CTkLabel(row, text=val, font=ctk.CTkFont(size=11), text_color=PALETTE["text_primary"]).pack(side="right")

        # Developer / Testing Tools Card
        dev_card = ctk.CTkFrame(frame, corner_radius=10, fg_color=PALETTE["bg_card"], border_width=1, border_color=PALETTE["border"])
        dev_card.grid(row=2, column=0, padx=22, pady=(16, 18), sticky="ew")

        # Dev header with clear warning badge
        dev_hdr = ctk.CTkFrame(dev_card, fg_color="transparent")
        dev_hdr.pack(fill="x", padx=18, pady=(14, 6))

        ctk.CTkLabel(dev_hdr, text="Developer & Testing Utilities", font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color=PALETTE["text_primary"]).pack(side="left")

        ctk.CTkLabel(
            dev_hdr,
            text="⚠️ DEVELOPMENT / TESTING ONLY",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=PALETTE["danger_red"],
            text_color="#ffffff",
            corner_radius=6,
            padx=10,
            pady=4
        ).pack(side="right")

        ctk.CTkLabel(
            dev_card,
            text="Use these tools to reset test attendance during development. Student registrations and biometrics are never deleted.",
            font=ctk.CTkFont(size=12),
            text_color=PALETTE["text_secondary"]
        ).pack(anchor="w", padx=18, pady=(0, 10))

        dev_actions = ctk.CTkFrame(dev_card, fg_color="transparent")
        dev_actions.pack(fill="x", padx=18, pady=(0, 14))

        ctk.CTkLabel(dev_actions, text="Select Bus to Clear:", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text_secondary"]).pack(side="left", padx=(0, 8))

        self.dev_bus_menu = ctk.CTkOptionMenu(
            dev_actions,
            values=["BUS01"],
            width=120,
            height=34,
            fg_color=PALETTE["btn_neutral"],
            button_color=PALETTE["btn_neutral_hover"],
            text_color=PALETTE["text_primary"]
        )
        self.dev_bus_menu.pack(side="left", padx=(0, 16))

        ctk.CTkButton(
            dev_actions,
            text="🗑️ Clear Today's Attendance (Selected Bus)",
            height=34,
            fg_color=PALETTE["btn_neutral"],
            hover_color=PALETTE["danger_red"],
            text_color=PALETTE["text_primary"],
            font=ctk.CTkFont(weight="bold"),
            command=self._on_dev_clear_today_bus
        ).pack(side="left")

        return frame

    def _on_settings_bus_changed(self, bus_id: str) -> None:
        self.active_bus_id = bus_id

    def _on_dev_clear_today_bus(self) -> None:
        target_bus = self.dev_bus_menu.get().strip()
        today_str = datetime.now().strftime("%Y-%m-%d")

        confirm = messagebox.askyesno(
            "Confirm Clearing Today's Attendance",
            f"Are you sure you want to clear attendance for {target_bus} on {today_str}?\n\n"
            f"This is for development testing only.\n"
            f"Student profile registrations and face biometrics will NOT be deleted.",
            icon="warning"
        )
        if confirm:
            deleted = self.db.clear_today_attendance(bus_id=target_bus, attendance_date=today_str)
            messagebox.showinfo("Attendance Cleared", f"Cleared {deleted} attendance records for {target_bus}.")
            self.refresh_dashboard_data()
            self.refresh_live_view_data()
            self.refresh_history_data()

    def refresh_settings_data(self) -> None:
        buses = self.db.get_distinct_bus_ids()
        if hasattr(self, "settings_bus_menu"):
            self.settings_bus_menu.configure(values=buses)
            if self.active_bus_id in buses:
                self.settings_bus_menu.set(self.active_bus_id)
        if hasattr(self, "dev_bus_menu"):
            self.dev_bus_menu.configure(values=buses)
            if self.active_bus_id in buses:
                self.dev_bus_menu.set(self.active_bus_id)

    # =========================================================================
    # APPLICATION AUTO-REFRESH & TEARDOWN
    # =========================================================================

    def _schedule_auto_refresh(self) -> None:
        """Periodically refresh data in the active view."""
        if not self.auto_refresh_enabled:
            return

        try:
            if self.current_view == "dashboard":
                self.refresh_dashboard_data()
            elif self.current_view == "live":
                self.refresh_live_view_data()
        except Exception:
            pass

        self._refresh_job = self.after(self.auto_refresh_ms, self._schedule_auto_refresh)

    def destroy(self) -> None:
        """Clean up background processes and resources on application exit."""
        if self._refresh_job:
            try:
                self.after_cancel(self._refresh_job)
            except Exception:
                pass

        self._stop_embedded_camera()

        if self._camera_process is not None and self._camera_process.poll() is None:
            try:
                self._camera_process.terminate()
                self._camera_process.wait(timeout=2)
            except Exception:
                try:
                    self._camera_process.kill()
                except Exception:
                    pass

        super().destroy()


def run_dashboard(db_path: str = DEFAULT_DB_PATH) -> None:
    """Entry point to launch the attendance dashboard application."""
    app = AttendanceDashboard(db_path=db_path)
    app.mainloop()


if __name__ == "__main__":
    run_dashboard()
