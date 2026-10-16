"""Attendance Manager Application - Administrative Workstation.

Built with CustomTkinter:
- Authenticated view of Central Supabase Attendance across all buses.
- Live filtering by Date, Bus ID, Student, and Status.
- In-Window Embedded Student Registration with Live Webcam Preview (Exactly like legacy dashboard).
- Student Directory with instant Bus Reassignment and Permanent Delete (deletes from local & Supabase).
- Export official Attendance reports to CSV.
- Real-time cloud sync status indicator.
"""
import os
import sys
import time
import csv
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any
import customtkinter as ctk
from tkinter import messagebox, filedialog
from PIL import Image
import cv2
import numpy as np

# Ensure root path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CURRENT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fleet_system.shared.cloud_client import FleetCloudClient
from fleet_system.device_app.local_db import DeviceDatabase

# Set CustomTkinter theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AttendanceManagerApp(ctk.CTk):
    """Main desktop manager window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Fleet Attendance Manager — Administrative Suite")
        self.geometry("1180x760")
        self.minsize(1050, 680)

        self.cloud = FleetCloudClient()
        self.local_device_db = DeviceDatabase("fleet_system/device_app/data/device.db")

        # Cache data
        self.buses: List[Dict[str, Any]] = []
        self.students: List[Dict[str, Any]] = []
        self.attendance_records: List[Dict[str, Any]] = []

        # Shared FaceRecognizer instance
        self._recognizer = None

        self._build_ui()
        self.refresh_all_data()

    def get_face_recognizer(self):
        """Lazy load FaceRecognizer once for fast in-app registration."""
        if self._recognizer is None:
            from src.face_recognizer import FaceRecognizer
            self._recognizer = FaceRecognizer(model_name="buffalo_sc")
        return self._recognizer

    def _build_ui(self) -> None:
        """Create tabbed navigation and layout."""
        # Top Header Bar
        header = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color="#161822")
        header.pack(fill="x", side="top")

        title_lbl = ctk.CTkLabel(
            header,
            text="🚌 FLEET ATTENDANCE MANAGER",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#38bdf8"
        )
        title_lbl.pack(side="left", padx=20, pady=15)

        self.status_lbl = ctk.CTkLabel(
            header,
            text="Connecting to Supabase...",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8"
        )
        self.status_lbl.pack(side="right", padx=20)

        # Main Tabview
        self.tabs = ctk.CTkTabview(self, fg_color="#0f1117")
        self.tabs.pack(fill="both", expand=True, padx=15, pady=10)

        self.tab_attendance = self.tabs.add("📋 Live Attendance")
        self.tab_students = self.tabs.add("👥 Student Directory & Bus Assign")
        self.tab_register = self.tabs.add("➕ Register Student (Live Camera)")
        self.tab_reports = self.tabs.add("📊 Reports & CSV Export")

        self._build_attendance_tab()
        self._build_students_tab()
        self._build_register_tab()
        self._build_reports_tab()

    # =========================================================================
    # TAB 1: ATTENDANCE VIEW
    # =========================================================================

    def _build_attendance_tab(self) -> None:
        top_ctrl = ctk.CTkFrame(self.tab_attendance, fg_color="#1c1f2b", corner_radius=8)
        top_ctrl.pack(fill="x", padx=10, pady=10)

        # Filters
        ctk.CTkLabel(top_ctrl, text="Bus Filter:").pack(side="left", padx=(15, 5), pady=10)
        self.bus_filter_var = ctk.StringVar(value="All Buses")
        self.bus_combo = ctk.CTkComboBox(
            top_ctrl,
            variable=self.bus_filter_var,
            values=["All Buses"],
            command=lambda _: self.apply_attendance_filters()
        )
        self.bus_combo.pack(side="left", padx=5)

        ctk.CTkLabel(top_ctrl, text="Date:").pack(side="left", padx=(15, 5))
        self.date_entry = ctk.CTkEntry(top_ctrl, width=110)
        self.date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.date_entry.pack(side="left", padx=5)

        refresh_btn = ctk.CTkButton(
            top_ctrl,
            text="🔄 Refresh",
            width=90,
            command=self.refresh_all_data
        )
        refresh_btn.pack(side="left", padx=15)

        # Summary KPIs
        self.kpi_lbl = ctk.CTkLabel(
            top_ctrl,
            text="Total Present: 0",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#10b981"
        )
        self.kpi_lbl.pack(side="right", padx=20)

        # Attendance Table (Scrollable)
        self.att_scroll = ctk.CTkScrollableFrame(self.tab_attendance, fg_color="#161822")
        self.att_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def render_attendance_table(self, records: List[Dict[str, Any]]) -> None:
        for widget in self.att_scroll.winfo_children():
            widget.destroy()

        # Header Row
        hdr_frame = ctk.CTkFrame(self.att_scroll, fg_color="#242938", height=35)
        hdr_frame.pack(fill="x", pady=2)
        cols = [("Time", 90), ("Date", 100), ("Student ID", 90), ("Student Name", 160), ("Bus ID", 90), ("Device", 120), ("Status", 80)]
        for col_name, w in cols:
            lbl = ctk.CTkLabel(hdr_frame, text=col_name, width=w, font=ctk.CTkFont(weight="bold"))
            lbl.pack(side="left", padx=5, pady=5)

        if not records:
            empty_lbl = ctk.CTkLabel(self.att_scroll, text="No attendance records found for selected filter.", text_color="#64748b")
            empty_lbl.pack(pady=40)
            self.kpi_lbl.configure(text="Total Present: 0")
            return

        # Map student_id -> student_name for fast lookup
        student_name_map = {str(s.get("student_id", "")).strip(): s.get("name", "") for s in self.students}

        present_count = 0
        for r in records:
            if r.get("status") == "Present":
                present_count += 1
            row_frame = ctk.CTkFrame(self.att_scroll, fg_color="#1c1f2b", height=32)
            row_frame.pack(fill="x", pady=2)

            sid = str(r.get("student_id", "")).strip()
            sname = student_name_map.get(sid, "--")

            ctk.CTkLabel(row_frame, text=r.get("attendance_time", ""), width=90).pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=r.get("attendance_date", ""), width=100).pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=sid, width=90, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=sname, width=160, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=r.get("bus_id", ""), width=90).pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=r.get("device_id", "--"), width=120, text_color="#94a3b8").pack(side="left", padx=5)
            status_lbl = ctk.CTkLabel(row_frame, text=r.get("status", "Present"), width=80, text_color="#10b981")
            status_lbl.pack(side="left", padx=5)

        self.kpi_lbl.configure(text=f"Total Present: {present_count}")

    # =========================================================================
    # TAB 2: STUDENT DIRECTORY & BUS ASSIGNMENT
    # =========================================================================

    def _build_students_tab(self) -> None:
        ctrl = ctk.CTkFrame(self.tab_students, fg_color="#1c1f2b", corner_radius=8)
        ctrl.pack(fill="x", padx=10, pady=10)

        goto_register_btn = ctk.CTkButton(
            ctrl,
            text="➕ Register New Student",
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(weight="bold"),
            command=self.switch_to_register_tab
        )
        goto_register_btn.pack(side="left", padx=15, pady=10)

        ctk.CTkLabel(ctrl, text="Filter Bus:").pack(side="left", padx=(20, 5))
        self.stu_bus_filter_var = ctk.StringVar(value="All Buses")
        self.stu_bus_combo = ctk.CTkComboBox(
            ctrl,
            variable=self.stu_bus_filter_var,
            values=["All Buses"],
            width=130,
            command=lambda _: self.render_students_table()
        )
        self.stu_bus_combo.pack(side="left", padx=5)

        ctk.CTkLabel(ctrl, text="Search:").pack(side="left", padx=(15, 5))
        self.search_entry = ctk.CTkEntry(ctrl, placeholder_text="ID or Name...", width=160)
        self.search_entry.pack(side="left", padx=5)
        self.search_entry.bind("<KeyRelease>", lambda _: self.render_students_table())

        self.students_scroll = ctk.CTkScrollableFrame(self.tab_students, fg_color="#161822")
        self.students_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def switch_to_register_tab(self) -> None:
        self.tabs.set("➕ Register Student (Live Camera)")
        self.start_registration_camera()

    def render_students_table(self) -> None:
        for widget in self.students_scroll.winfo_children():
            widget.destroy()

        query = self.search_entry.get().strip().lower()
        selected_bus = self.stu_bus_filter_var.get()

        # Filter students by active status, search query, and selected bus
        filtered = []
        for s in self.students:
            if not s.get("is_active", True):
                continue
            if selected_bus != "All Buses" and str(s.get("bus_id", "")).strip() != selected_bus:
                continue
            if query and query not in s.get("student_id", "").lower() and query not in s.get("name", "").lower():
                continue
            filtered.append(s)

        # Table Header
        hdr = ctk.CTkFrame(self.students_scroll, fg_color="#242938", height=35)
        hdr.pack(fill="x", pady=2)
        cols = [("ID", 80), ("Full Name", 190), ("Class", 90), ("Assigned Bus", 150), ("Status", 90), ("Actions", 130)]
        for cname, w in cols:
            ctk.CTkLabel(hdr, text=cname, width=w, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5, pady=5)

        if not filtered:
            ctk.CTkLabel(self.students_scroll, text="No registered students found.", text_color="#64748b").pack(pady=40)
            return

        for s in filtered:
            sid = str(s.get("student_id", "")).strip()
            sname = str(s.get("name", "")).strip()
            cur_bus = str(s.get("bus_id", "")).strip()

            if not sid:
                continue

            row = ctk.CTkFrame(self.students_scroll, fg_color="#1c1f2b", height=38)
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(row, text=sid, width=80, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=sname, width=190, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(row, text=str(s.get("class_name", "--")), width=90).pack(side="left", padx=5)

            # Bus Reassign Dropdown directly inline
            bus_var = ctk.StringVar(value=cur_bus)
            bus_menu = ctk.CTkOptionMenu(
                row,
                variable=bus_var,
                values=[b["bus_id"] for b in self.buses] or [cur_bus],
                width=150,
                command=lambda new_b, stu_id=sid: self.reassign_bus(stu_id, new_b)
            )
            bus_menu.pack(side="left", padx=5)

            ctk.CTkLabel(row, text="Active", width=90, text_color="#10b981").pack(side="left", padx=5)

            # Permanent DELETE Button
            del_btn = ctk.CTkButton(
                row,
                text="🗑️ Delete",
                width=110,
                fg_color="#b91c1c",
                hover_color="#991b1b",
                font=ctk.CTkFont(weight="bold"),
                command=lambda stu_id=sid, stu_name=sname: self.delete_student_permanently(stu_id, stu_name)
            )
            del_btn.pack(side="left", padx=5)

    def reassign_bus(self, student_id: str, new_bus_id: str) -> None:
        """Update student bus assignment in cloud."""
        threading.Thread(target=self._async_reassign_bus, args=(student_id, new_bus_id), daemon=True).start()

    def _async_reassign_bus(self, student_id: str, new_bus_id: str) -> None:
        ok = self.cloud.update_student_bus(student_id, new_bus_id)
        if ok:
            self.refresh_all_data()

    def delete_student_permanently(self, student_id: str, student_name: str) -> None:
        """Delete student from both local SQLite database and Supabase cloud."""
        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to permanently delete student:\n\n'{student_name}' (ID: {student_id})?\n\nThis will remove their profile and face data from the local database and Supabase."
        )
        if not confirm:
            return

        self.status_lbl.configure(text=f"Deleting student {student_id}...", text_color="#fbbf24")
        threading.Thread(target=self._async_delete_student, args=(student_id,), daemon=True).start()

    def _async_delete_student(self, student_id: str) -> None:
        # 1. Delete from Supabase cloud (purges biometric embedding & marks inactive or drops row)
        ok_cloud = self.cloud.delete_student(student_id)
        # 2. Delete from local database
        self.local_device_db.delete_student(student_id)

        self.after(0, lambda: self._on_delete_completed(student_id, ok_cloud))

    def _on_delete_completed(self, student_id: str, ok_cloud: bool) -> None:
        if ok_cloud:
            messagebox.showinfo("Deleted", f"Student {student_id} was successfully deleted from Database & Supabase.")
        else:
            messagebox.showwarning("Notice", f"Student {student_id} was deleted locally, but cloud reported: {self.cloud._last_error}")
        self.refresh_all_data()

    # =========================================================================
    # TAB 3: IN-WINDOW LIVE CAMERA REGISTRATION
    # =========================================================================

    def _build_register_tab(self) -> None:
        """Build registration UI with embedded camera view on right and student form on left."""
        container = ctk.CTkFrame(self.tab_register, fg_color="#0f1117")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Left Column: Student Details Form
        left_form = ctk.CTkFrame(container, fg_color="#1c1f2b", width=360, corner_radius=10)
        left_form.pack(side="left", fill="y", padx=(0, 10), pady=0)
        left_form.pack_propagate(False)

        ctk.CTkLabel(
            left_form,
            text="Student Details",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#38bdf8"
        ).pack(anchor="w", padx=20, pady=(18, 12))

        ctk.CTkLabel(left_form, text="Student ID:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(6, 2))
        self.reg_id_entry = ctk.CTkEntry(left_form, placeholder_text="e.g. STU101", height=35)
        self.reg_id_entry.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(left_form, text="Full Name:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(6, 2))
        self.reg_name_entry = ctk.CTkEntry(left_form, placeholder_text="e.g. Alex Johnson", height=35)
        self.reg_name_entry.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(left_form, text="Class / Grade:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(6, 2))
        self.reg_class_entry = ctk.CTkEntry(left_form, placeholder_text="e.g. 5A", height=35)
        self.reg_class_entry.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(left_form, text="Assign Bus ID:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(6, 2))
        self.reg_bus_var = ctk.StringVar(value="Bus01")
        self.reg_bus_menu = ctk.CTkOptionMenu(left_form, variable=self.reg_bus_var, values=["Bus01"], height=35)
        self.reg_bus_menu.pack(fill="x", padx=20, pady=(0, 20))

        # Instructions card
        info_box = ctk.CTkFrame(left_form, fg_color="#161822", corner_radius=8)
        info_box.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkLabel(
            info_box,
            text="📌 Instructions:\n• Stand in front of camera\n• Ensure exactly 1 face is visible\n• Box turns Green when ready\n• Click 'Capture & Register'",
            justify="left",
            text_color="#94a3b8"
        ).pack(padx=12, pady=12)

        self.reg_save_btn = ctk.CTkButton(
            left_form,
            text="📸 Capture Face & Register",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=44,
            command=self.capture_and_register_student
        )
        self.reg_save_btn.pack(fill="x", padx=20, pady=(0, 10))

        # Right Column: Embedded Camera Feed
        right_cam = ctk.CTkFrame(container, fg_color="#1c1f2b", corner_radius=10)
        right_cam.pack(side="right", fill="both", expand=True)

        cam_hdr = ctk.CTkFrame(right_cam, fg_color="transparent")
        cam_hdr.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(
            cam_hdr,
            text="Live Face Scanner",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        # Camera Index Selector
        cam_ctrl_frame = ctk.CTkFrame(cam_hdr, fg_color="transparent")
        cam_ctrl_frame.pack(side="right")

        ctk.CTkLabel(cam_ctrl_frame, text="Cam Index:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 5))
        self.cam_index_var = ctk.StringVar(value="0")
        self.cam_index_menu = ctk.CTkOptionMenu(
            cam_ctrl_frame,
            variable=self.cam_index_var,
            values=["0", "1", "2", "3"],
            width=65,
            command=self._on_cam_index_changed
        )
        self.cam_index_menu.pack(side="left", padx=(0, 10))

        self.cam_toggle_btn = ctk.CTkButton(
            cam_ctrl_frame,
            text="▶️ Start Camera",
            width=120,
            command=self.toggle_camera
        )
        self.cam_toggle_btn.pack(side="left")

        # Camera status banner
        self.cam_status_lbl = ctk.CTkLabel(
            right_cam,
            text="Camera stopped. Click 'Start Camera' to begin.",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94a3b8"
        )
        self.cam_status_lbl.pack(pady=5)

        # Video frame display label
        self.video_display_lbl = ctk.CTkLabel(
            right_cam,
            text="",
            fg_color="#090a0f",
            corner_radius=8
        )
        self.video_display_lbl.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        # Camera state variables
        self._cam_running = False
        self._cam_thread: Optional[threading.Thread] = None
        self._cam_lock = threading.Lock()
        self._latest_camera_frame = None
        self._latest_faces = []
        self._latest_face_ready = False

    def _on_cam_index_changed(self, new_idx: str) -> None:
        """Switch camera if camera is currently running."""
        if self._cam_running:
            self.stop_registration_camera()
            self.after(200, self.start_registration_camera)

    def toggle_camera(self) -> None:
        if self._cam_running:
            self.stop_registration_camera()
        else:
            self.start_registration_camera()

    def start_registration_camera(self) -> None:
        if self._cam_running:
            return
        self._cam_running = True
        self.cam_toggle_btn.configure(text="⏹️ Stop Camera", fg_color="#b91c1c", hover_color="#991b1b")
        self.cam_status_lbl.configure(text="Starting camera & loading models...", text_color="#38bdf8")

        self._cam_thread = threading.Thread(target=self._camera_stream_loop, daemon=True)
        self._cam_thread.start()
        self.after(35, self._update_camera_display)

    def stop_registration_camera(self) -> None:
        self._cam_running = False
        self.cam_toggle_btn.configure(text="▶️ Start Camera", fg_color="#0284c7", hover_color="#0369a1")
        self.cam_status_lbl.configure(text="Camera stopped.", text_color="#94a3b8")
        self.video_display_lbl.configure(image="", text="Camera Offline")

    def _camera_stream_loop(self) -> None:
        from src.camera import Camera
        idx = int(self.cam_index_var.get()) if self.cam_index_var.get().isdigit() else 0
        cam = Camera(camera_index=idx)
        if not cam.start():
            with self._cam_lock:
                self.cam_status_lbl.configure(text=f"Error: Could not open camera (index {idx}).", text_color="#ef4444")
            self._cam_running = False
            return

        recognizer = self.get_face_recognizer()

        while self._cam_running:
            ret, frame = cam.read_frame()
            if not ret or frame is None:
                time.sleep(0.04)
                continue

            display_frame = frame.copy()
            faces = recognizer.extract_faces(frame)
            num_faces = len(faces)

            if num_faces == 1:
                face = faces[0]
                box = face.bbox.astype(int)
                cv2.rectangle(display_frame, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
                cv2.putText(display_frame, "READY TO CAPTURE", (box[0], max(box[1] - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                status_txt = "READY: Exactly 1 face detected. Click 'Capture Face & Register'."
                ready = True
            elif num_faces == 0:
                status_txt = "Looking for student face... Please look directly at camera."
                ready = False
            else:
                for f in faces:
                    box = f.bbox.astype(int)
                    cv2.rectangle(display_frame, (box[0], box[1]), (box[2], box[3]), (0, 0, 255), 2)
                status_txt = f"WARNING: {num_faces} faces detected. ONLY 1 face allowed!"
                ready = False

            with self._cam_lock:
                self._latest_camera_frame = display_frame
                self._latest_faces = faces
                self._latest_face_ready = ready
                self._latest_status_txt = status_txt

            time.sleep(0.03)

        cam.release()

    def _update_camera_display(self) -> None:
        if not self._cam_running:
            return

        frame = None
        status = ""
        ready = False
        with self._cam_lock:
            if self._latest_camera_frame is not None:
                frame = self._latest_camera_frame.copy()
            status = getattr(self, "_latest_status_txt", "")
            ready = self._latest_face_ready

        if status:
            col = "#10b981" if ready else ("#ef4444" if "WARNING" in status else "#f59e0b")
            self.cam_status_lbl.configure(text=status, text_color=col)

        if frame is not None:
            try:
                # Resize to fit video preview
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                disp_w = 640
                disp_h = int(h * (disp_w / w))
                resized = cv2.resize(rgb, (disp_w, disp_h))
                pil_img = Image.fromarray(resized)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(disp_w, disp_h))
                self.video_display_lbl.configure(image=ctk_img, text="")
                self._current_cam_image = ctk_img
            except Exception:
                pass

        if self._cam_running:
            self.after(35, self._update_camera_display)

    def capture_and_register_student(self) -> None:
        """Capture currently detected face and upload to Supabase & local DB."""
        sid = self.reg_id_entry.get().strip()
        name = self.reg_name_entry.get().strip()
        cname = self.reg_class_entry.get().strip()
        bus_id = self.reg_bus_var.get().strip()

        if not sid or not name or not cname or not bus_id:
            messagebox.showwarning("Missing Fields", "Please enter Student ID, Name, Class, and Bus ID.")
            return

        with self._cam_lock:
            faces = list(self._latest_faces)
            ready = self._latest_face_ready

        if not ready or len(faces) != 1:
            messagebox.showwarning("No Face", "Please start camera and ensure exactly 1 student face is highlighted in Green.")
            return

        # Extract 512-D embedding
        emb = faces[0].embedding
        arr = np.asarray(emb, dtype=np.float32)
        emb_bytes = arr.tobytes()

        self.reg_save_btn.configure(state="disabled", text="Saving to Cloud...")
        threading.Thread(target=self._async_save_student, args=(sid, name, cname, bus_id, emb_bytes), daemon=True).start()

    def _async_save_student(self, sid: str, name: str, cname: str, bus_id: str, emb_bytes: bytes) -> None:
        # 1. Upload to Supabase
        ok_stu = self.cloud.upsert_student(sid, name, cname, bus_id, is_active=True)
        if not ok_stu:
            self.after(0, lambda: messagebox.showerror("Cloud Error", f"Failed to save student profile: {self.cloud._last_error}"))
            self.after(0, lambda: self.reg_save_btn.configure(state="normal", text="📸 Capture Face & Register"))
            return

        ok_bio = self.cloud.upload_biometrics(sid, emb_bytes)
        if not ok_bio:
            self.after(0, lambda: messagebox.showerror("Biometrics Error", f"Failed to upload face biometric vector: {self.cloud._last_error}"))
            self.after(0, lambda: self.reg_save_btn.configure(state="normal", text="📸 Capture Face & Register"))
            return

        # 2. Also register into local device db cache
        self.local_device_db.sync_roster_cache(
            [{"student_id": sid, "name": name, "class_name": cname, "bus_id": bus_id, "is_active": True}],
            {sid: emb_bytes}
        )

        self.after(0, lambda: self._on_register_success(sid, name, bus_id))

    def _on_register_success(self, sid: str, name: str, bus_id: str) -> None:
        self.reg_save_btn.configure(state="normal", text="📸 Capture Face & Register")
        messagebox.showinfo("Success", f"Student '{name}' ({sid}) successfully registered and assigned to {bus_id}!")
        # Clear fields
        self.reg_id_entry.delete(0, "end")
        self.reg_name_entry.delete(0, "end")
        self.reg_class_entry.delete(0, "end")

        # Refresh directory and switch to students tab
        self.refresh_all_data()
        self.tabs.set("👥 Student Directory & Bus Assign")

    # =========================================================================
    # TAB 4: REPORTS & CSV EXPORT
    # =========================================================================

    def _build_reports_tab(self) -> None:
        frame = ctk.CTkFrame(self.tab_reports, fg_color="#1c1f2b", corner_radius=8)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="Export Attendance Logs to CSV",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(30, 10))

        ctk.CTkLabel(
            frame,
            text="Exports filtered cloud attendance data to an official Excel/CSV report.",
            text_color="#94a3b8"
        ).pack(pady=5)

        export_btn = ctk.CTkButton(
            frame,
            text="💾 Download CSV Report",
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=45,
            width=220,
            command=self.export_csv
        )
        export_btn.pack(pady=30)

    def export_csv(self) -> None:
        if not self.attendance_records:
            messagebox.showwarning("Empty", "No attendance records available to export.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile=f"attendance_report_{datetime.now().strftime('%Y%m%d')}.csv"
        )
        if not file_path:
            return

        try:
            student_name_map = {str(s.get("student_id", "")).strip(): s.get("name", "") for s in self.students}
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Event ID", "Student ID", "Student Name", "Attendance Date", "Attendance Time", "Bus ID", "Status", "Device ID"])
                for r in self.attendance_records:
                    sid = str(r.get("student_id", "")).strip()
                    writer.writerow([
                        r.get("event_id", ""),
                        sid,
                        student_name_map.get(sid, "--"),
                        r.get("attendance_date", ""),
                        r.get("attendance_time", ""),
                        r.get("bus_id", ""),
                        r.get("status", "Present"),
                        r.get("device_id", "")
                    ])
            messagebox.showinfo("Success", f"Report saved successfully to:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save CSV: {e}")

    # =========================================================================
    # DATA REFRESHING
    # =========================================================================

    def refresh_all_data(self) -> None:
        self.status_lbl.configure(text="Syncing with Supabase...", text_color="#fbbf24")
        threading.Thread(target=self._async_fetch_all, daemon=True).start()

    def _async_fetch_all(self) -> None:
        buses = self.cloud.get_buses()
        students = self.cloud.get_students(active_only=False)
        date_val = self.date_entry.get().strip()
        bus_val = None if self.bus_filter_var.get() == "All Buses" else self.bus_filter_var.get()
        records = self.cloud.get_attendance(date_str=date_val, bus_id=bus_val)

        self.buses = buses
        self.students = students
        self.attendance_records = records

        self.after(0, self._update_ui_after_fetch)

    def _update_ui_after_fetch(self) -> None:
        # Update bus dropdown options
        bus_names = ["All Buses"] + [b["bus_id"] for b in self.buses]
        self.bus_combo.configure(values=bus_names)
        self.stu_bus_combo.configure(values=bus_names)

        # Update bus options in registration form
        clean_bus_ids = [b["bus_id"] for b in self.buses] or ["Bus01"]
        self.reg_bus_menu.configure(values=clean_bus_ids)

        self.status_lbl.configure(
            text=f"Connected to Cloud | Last sync: {time.strftime('%H:%M:%S')}",
            text_color="#10b981"
        )
        self.render_attendance_table(self.attendance_records)
        self.render_students_table()

    def apply_attendance_filters(self) -> None:
        self.refresh_all_data()

    def destroy(self) -> None:
        """Cleanly stop camera on window close."""
        self._cam_running = False
        super().destroy()


def main() -> None:
    app = AttendanceManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
