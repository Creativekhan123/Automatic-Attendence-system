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
from tkinter import messagebox, filedialog, simpledialog
from PIL import Image
import cv2
import numpy as np

# Ensure root path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CURRENT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fleet_system.shared.cloud_client import FleetCloudClient, save_cloud_credentials
from fleet_system.device_app.local_db import DeviceDatabase

# Set CustomTkinter theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class TabViewCompat:
    """Compatibility adapter enabling legacy self.tabs.set() callers to switch pages cleanly."""
    def __init__(self, app: "AttendanceManagerApp") -> None:
        self.app = app

    def set(self, tab_name: str) -> None:
        self.app.set_tab(tab_name)


class AttendanceManagerApp(ctk.CTk):
    """Main desktop manager window with modern enterprise collapsible sidebar layout."""

    EXPANDED_WIDTH = 220
    COLLAPSED_WIDTH = 68

    PAGE_METADATA = {
        "live_attendance": (
            "Live Attendance",
            "Monitor today's student boarding activity across your fleet."
        ),
        "student_directory": (
            "Student Directory & Bus Assignment",
            "Manage student rosters, bus assignments, and biometric status."
        ),
        "bus_management": (
            "Bus Fleet Management",
            "View and manage fleet school buses, driver routes, and assignments."
        ),
        "register_student": (
            "Register Student (Live Camera)",
            "Enroll new student biometric face profile via camera."
        ),
        "reports": (
            "Reports & CSV Export",
            "Generate and download official school bus attendance logs in CSV format."
        ),
        "cloud_settings": (
            "Cloud Configuration & Settings",
            "Manage central Supabase connection credentials and endpoints."
        ),
        "settings": (
            "Cloud Configuration & Settings",
            "Manage central Supabase connection credentials and endpoints."
        ),
    }

    def __init__(self) -> None:
        super().__init__()
        self.title("Fleet Attendance Manager — Enterprise School Bus Cloud Workstation")
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

        # Sidebar & Navigation State
        self.is_sidebar_collapsed: bool = False
        self.current_page_key: str = "live_attendance"
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        self.nav_icons: Dict[str, str] = {}
        self.nav_labels: Dict[str, str] = {}
        self.tabs = TabViewCompat(self)

        self._build_ui()
        self.show_page("live_attendance")
        self.refresh_all_data()

    def get_face_recognizer(self):
        """Lazy load FaceRecognizer once for fast in-app registration."""
        if self._recognizer is None:
            from src.face_recognizer import FaceRecognizer
            self._recognizer = FaceRecognizer(model_name="buffalo_sc")
        return self._recognizer

    def _on_theme_changed(self, mode_str: str) -> None:
        """Toggle between Dark and Light appearance modes."""
        mode = "Dark" if "Dark" in mode_str else "Light"
        ctk.set_appearance_mode(mode)
        self._update_nav_styles()

    def _build_ui(self) -> None:
        """Create header, collapsible sidebar navigation, and main content area."""
        # =====================================================================
        # 1. TOP HEADER BAR
        # =====================================================================
        header = ctk.CTkFrame(
            self,
            height=60,
            corner_radius=0,
            fg_color=("#ffffff", "#11131a"),
            border_width=1,
            border_color=("#e2e8f0", "#1e2433")
        )
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Left Branding: Bus Icon, Title & Subtitle
        brand_frame = ctk.CTkFrame(header, fg_color="transparent")
        brand_frame.pack(side="left", padx=18, pady=8)

        title_lbl = ctk.CTkLabel(
            brand_frame,
            text="🚌 FLEET ATTENDANCE MANAGER",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=("#0284c7", "#38bdf8")
        )
        title_lbl.pack(anchor="w")

        sub_lbl = ctk.CTkLabel(
            brand_frame,
            text="Enterprise School Bus Cloud Workstation",
            font=ctk.CTkFont(size=11),
            text_color=("#64748b", "#94a3b8")
        )
        sub_lbl.pack(anchor="w")

        # Right Header Controls
        header_right = ctk.CTkFrame(header, fg_color="transparent")
        header_right.pack(side="right", padx=16, pady=10)

        # Theme Switcher Segmented Button
        self.theme_btn = ctk.CTkSegmentedButton(
            header_right,
            values=["🌙 Dark", "☀️ Light"],
            command=self._on_theme_changed,
            width=120,
            height=30
        )
        self.theme_btn.set("🌙 Dark")
        self.theme_btn.pack(side="right", padx=(8, 0))

        # Quick Settings Button
        settings_btn = ctk.CTkButton(
            header_right,
            text="⚙️ Settings",
            width=90,
            height=30,
            fg_color=("#e2e8f0", "#1e293b"),
            text_color=("#0f172a", "#f8fafc"),
            hover_color=("#cbd5e1", "#334155"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self.show_page("cloud_settings")
        )
        settings_btn.pack(side="right", padx=8)

        self.status_lbl = ctk.CTkLabel(
            header_right,
            text="● Connecting...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24"
        )
        self.status_lbl.pack(side="right", padx=12)

        # =====================================================================
        # 2. BODY CONTAINER (SIDEBAR + MAIN CONTENT AREA)
        # =====================================================================
        self.body_container = ctk.CTkFrame(self, fg_color="transparent")
        self.body_container.pack(fill="both", expand=True)

        # Left Sidebar Frame
        self.sidebar = ctk.CTkFrame(
            self.body_container,
            width=self.EXPANDED_WIDTH,
            corner_radius=0,
            fg_color=("#f8fafc", "#11131a"),
            border_width=1,
            border_color=("#e2e8f0", "#1e2433")
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Main Content Area Frame (Right)
        self.content_area = ctk.CTkFrame(
            self.body_container,
            corner_radius=0,
            fg_color=("#f1f5f9", "#0b0c10")
        )
        self.content_area.pack(side="right", fill="both", expand=True)

        # =====================================================================
        # 3. SIDEBAR NAVIGATION ITEMS
        # =====================================================================
        # WORKSPACE Section Header
        self.workspace_lbl = ctk.CTkLabel(
            self.sidebar,
            text="WORKSPACE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#64748b", "#64748b"),
            anchor="w"
        )
        self.workspace_lbl.pack(fill="x", padx=16, pady=(16, 6))

        self.nav_items_config = [
            ("live_attendance", "⊞", "Live Attendance", "WORKSPACE"),
            ("student_directory", "👥", "Student Directory", "WORKSPACE"),
            ("bus_management", "🚌", "Bus Management", "WORKSPACE"),
            ("register_student", "👤+", "Register Student", "WORKSPACE"),
            ("reports", "📊", "Reports & Export", "WORKSPACE"),
            ("cloud_settings", "☁️", "Cloud Settings", "SYSTEM"),
            ("settings", "⚙️", "Settings", "SYSTEM"),
        ]

        # Add WORKSPACE buttons
        for key, icon, label, group in self.nav_items_config:
            if group == "WORKSPACE":
                self.nav_icons[key] = icon
                self.nav_labels[key] = label
                btn = ctk.CTkButton(
                    self.sidebar,
                    text=f"  {icon}  {label}",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    height=38,
                    corner_radius=8,
                    anchor="w",
                    command=lambda k=key: self.show_page(k)
                )
                btn.pack(fill="x", padx=10, pady=2)
                self.nav_buttons[key] = btn

        # SYSTEM Section Header
        self.system_lbl = ctk.CTkLabel(
            self.sidebar,
            text="SYSTEM",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#64748b", "#64748b"),
            anchor="w"
        )
        self.system_lbl.pack(fill="x", padx=16, pady=(16, 6))

        # Add SYSTEM buttons
        for key, icon, label, group in self.nav_items_config:
            if group == "SYSTEM":
                self.nav_icons[key] = icon
                self.nav_labels[key] = label
                btn = ctk.CTkButton(
                    self.sidebar,
                    text=f"  {icon}  {label}",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    height=38,
                    corner_radius=8,
                    anchor="w",
                    command=lambda k=key: self.show_page(k)
                )
                btn.pack(fill="x", padx=10, pady=2)
                self.nav_buttons[key] = btn

        # Spacer to push Collapse button to bottom
        sidebar_spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        sidebar_spacer.pack(fill="both", expand=True)

        # Divider line
        div_frame = ctk.CTkFrame(self.sidebar, height=1, fg_color=("#e2e8f0", "#1e2433"))
        div_frame.pack(fill="x", padx=12, pady=(4, 6))

        # Bottom Collapse/Expand Sidebar Button
        self.collapse_btn = ctk.CTkButton(
            self.sidebar,
            text="  ◧  Collapse sidebar",
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            text_color=("#64748b", "#94a3b8"),
            hover_color=("#e2e8f0", "#1e293b"),
            height=36,
            corner_radius=8,
            anchor="w",
            command=self.toggle_sidebar
        )
        self.collapse_btn.pack(fill="x", padx=10, pady=(0, 12))

        # =====================================================================
        # 4. MAIN CONTENT AREA HEADER & PAGES CONTAINER
        # =====================================================================
        self.page_header_frame = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.page_header_frame.pack(fill="x", padx=20, pady=(14, 4))

        self.page_title_lbl = ctk.CTkLabel(
            self.page_header_frame,
            text="Live Attendance",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=("#0f172a", "#f8fafc"),
            anchor="w"
        )
        self.page_title_lbl.pack(anchor="w")

        self.page_subtitle_lbl = ctk.CTkLabel(
            self.page_header_frame,
            text="Monitor today's student boarding activity across your fleet.",
            font=ctk.CTkFont(size=12),
            text_color=("#64748b", "#94a3b8"),
            anchor="w"
        )
        self.page_subtitle_lbl.pack(anchor="w", pady=(2, 0))

        # Container holding all page frames
        self.pages_container = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.pages_container.pack(fill="both", expand=True, padx=14, pady=(2, 10))

        # Individual Page Frames
        self.tab_attendance = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.tab_students = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.tab_register = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.tab_reports = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.tab_settings = ctk.CTkFrame(self.pages_container, fg_color="transparent")

        # Build each page's content inside its respective frame
        self._build_attendance_tab()
        self._build_students_tab()
        self._build_register_tab()
        self._build_reports_tab()
        self._build_settings_tab()

    # =========================================================================
    # SIDEBAR TOGGLING & NAVIGATION ROUTING
    # =========================================================================

    def toggle_sidebar(self) -> None:
        """Collapse or expand the vertical left sidebar."""
        self.is_sidebar_collapsed = not self.is_sidebar_collapsed
        self._update_sidebar_view()

    def _update_sidebar_view(self) -> None:
        """Update sidebar widget appearances between expanded and collapsed modes."""
        if self.is_sidebar_collapsed:
            self.sidebar.configure(width=self.COLLAPSED_WIDTH)
            self.workspace_lbl.configure(text="")
            self.system_lbl.configure(text="")
            for key, btn in self.nav_buttons.items():
                icon = self.nav_icons[key]
                btn.configure(text=icon, anchor="center")
            self.collapse_btn.configure(text="◨", anchor="center")
        else:
            self.sidebar.configure(width=self.EXPANDED_WIDTH)
            self.workspace_lbl.configure(text="WORKSPACE")
            self.system_lbl.configure(text="SYSTEM")
            for key, btn in self.nav_buttons.items():
                icon = self.nav_icons[key]
                label = self.nav_labels[key]
                btn.configure(text=f"  {icon}  {label}", anchor="w")
            self.collapse_btn.configure(text="  ◧  Collapse sidebar", anchor="w")
        self._update_nav_styles()

    def _update_nav_styles(self) -> None:
        """Apply active highlight styling to selected sidebar item and reset others."""
        for key, btn in self.nav_buttons.items():
            is_active = (key == self.current_page_key) or (key == "settings" and self.current_page_key == "cloud_settings")
            if is_active:
                btn.configure(
                    fg_color=("#e0f2fe", "#1e293b"),
                    border_width=1,
                    border_color=("#0284c7", "#38bdf8"),
                    text_color=("#0284c7", "#38bdf8"),
                    hover_color=("#bae6fd", "#334155")
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    border_width=0,
                    text_color=("#475569", "#94a3b8"),
                    hover_color=("#e2e8f0", "#1c1f2b")
                )

    def show_page(self, page_key: str) -> None:
        """Navigate to requested page by key and update sidebar state."""
        if page_key in ("cloud_settings", "settings"):
            target_frame = self.tab_settings
            actual_key = "cloud_settings"
        elif page_key == "bus_management":
            target_frame = self.tab_students
            actual_key = "bus_management"
        elif page_key == "student_directory":
            target_frame = self.tab_students
            actual_key = "student_directory"
        elif page_key == "register_student":
            target_frame = self.tab_register
            actual_key = "register_student"
        elif page_key == "reports":
            target_frame = self.tab_reports
            actual_key = "reports"
        else:
            target_frame = self.tab_attendance
            actual_key = "live_attendance"

        # Stop camera if switching away from registration page
        if actual_key != "register_student" and getattr(self, "_cam_running", False):
            self.stop_registration_camera()

        # Hide all pages and show target page
        for p in (self.tab_attendance, self.tab_students, self.tab_register, self.tab_reports, self.tab_settings):
            p.pack_forget()

        target_frame.pack(fill="both", expand=True)
        self.current_page_key = actual_key

        # Update page title & subtitle in header
        title, sub = self.PAGE_METADATA.get(actual_key, ("Fleet Attendance Manager", ""))
        self.page_title_lbl.configure(text=title)
        self.page_subtitle_lbl.configure(text=sub)

        # Update sidebar active highlights
        self._update_nav_styles()

    def set_tab(self, tab_name: str) -> None:
        """Fuzzy page router for backward compatibility with self.tabs.set() calls."""
        name = tab_name.lower()
        if "attend" in name:
            self.show_page("live_attendance")
        elif "register" in name or "camera" in name:
            self.show_page("register_student")
        elif "student" in name or "directory" in name:
            self.show_page("student_directory")
        elif "bus" in name:
            self.show_page("bus_management")
        elif "report" in name or "csv" in name or "export" in name:
            self.show_page("reports")
        elif "cloud" in name or "setting" in name:
            self.show_page("cloud_settings")
        else:
            self.show_page("live_attendance")

    # =========================================================================
    # TAB 1: ATTENDANCE VIEW
    # =========================================================================

    def _create_kpi_card(self, parent, row: int, col: int, title: str, initial_val: str, accent_color: str):
        card = ctk.CTkFrame(parent, fg_color=("#ffffff", "#1c1f2b"), corner_radius=10, border_width=1, border_color=("#e2e8f0", "#2d3748"))
        card.grid(row=row, column=col, padx=6, pady=4, sticky="nsew")
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=("#64748b", "#94a3b8")).pack(anchor="w", padx=14, pady=(10, 2))
        val_lbl = ctk.CTkLabel(card, text=initial_val, font=ctk.CTkFont(size=24, weight="bold"), text_color=accent_color)
        val_lbl.pack(anchor="w", padx=14, pady=(0, 10))
        return val_lbl

    def _build_attendance_tab(self) -> None:
        # KPI Summary Cards (2x2 grid matching dashboard screenshot)
        kpi_frame = ctk.CTkFrame(self.tab_attendance, fg_color="transparent")
        kpi_frame.pack(fill="x", padx=10, pady=(2, 6))
        kpi_frame.grid_columnconfigure((0, 1), weight=1)

        self.kpi_card_total = self._create_kpi_card(kpi_frame, 0, 0, "Total Students", "0", "#38bdf8")
        self.kpi_card_present = self._create_kpi_card(kpi_frame, 0, 1, "Present Today", "0", "#10b981")
        self.kpi_card_absent = self._create_kpi_card(kpi_frame, 1, 0, "Pending / Unmarked", "0", "#f59e0b")
        self.kpi_card_buses = self._create_kpi_card(kpi_frame, 1, 1, "Active Fleet Buses", "0", "#a78bfa")

        # Recent Attendance Card Container
        att_card = ctk.CTkFrame(self.tab_attendance, fg_color=("#ffffff", "#161822"), corner_radius=10, border_width=1, border_color=("#e2e8f0", "#2d3748"))
        att_card.pack(fill="both", expand=True, padx=10, pady=(4, 6))

        # Recent Attendance Header & Filters Bar
        top_ctrl = ctk.CTkFrame(att_card, fg_color="transparent")
        top_ctrl.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            top_ctrl,
            text="Recent Attendance",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        ).pack(side="left")

        filter_box = ctk.CTkFrame(top_ctrl, fg_color="transparent")
        filter_box.pack(side="right")

        ctk.CTkLabel(filter_box, text="Bus:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(8, 4))
        self.bus_filter_var = ctk.StringVar(value="All Buses")
        self.bus_combo = ctk.CTkComboBox(
            filter_box,
            variable=self.bus_filter_var,
            values=["All Buses"],
            width=120,
            height=28,
            command=lambda _: self.apply_attendance_filters()
        )
        self.bus_combo.pack(side="left", padx=4)

        ctk.CTkLabel(filter_box, text="Date:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(10, 4))
        self.date_entry = ctk.CTkEntry(filter_box, width=105, height=28)
        self.date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.date_entry.pack(side="left", padx=4)

        refresh_btn = ctk.CTkButton(
            filter_box,
            text="🔄 Refresh",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=95,
            height=28,
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=self.refresh_all_data
        )
        refresh_btn.pack(side="left", padx=(8, 0))

        # Attendance Table (Scrollable) inside att_card
        self.att_scroll = ctk.CTkScrollableFrame(att_card, fg_color="transparent")
        self.att_scroll.pack(fill="both", expand=True, padx=10, pady=(4, 10))

    def render_attendance_table(self, records: List[Dict[str, Any]]) -> None:
        for widget in self.att_scroll.winfo_children():
            widget.destroy()

        # Header Row
        hdr_frame = ctk.CTkFrame(self.att_scroll, fg_color=("#e2e8f0", "#242938"), height=36, corner_radius=6)
        hdr_frame.pack(fill="x", pady=2)
        cols = [("Time", 90), ("Date", 100), ("Student ID", 100), ("Student Name", 180), ("Bus ID", 100), ("Status", 90)]
        for col_name, w in cols:
            lbl = ctk.CTkLabel(hdr_frame, text=col_name, width=w, font=ctk.CTkFont(weight="bold"))
            lbl.pack(side="left", padx=5, pady=5)

        if not records:
            empty_lbl = ctk.CTkLabel(self.att_scroll, text="No attendance records found for selected filter.", text_color=("#64748b", "#94a3b8"))
            empty_lbl.pack(pady=40)
            return

        # Map student_id -> student_name for fast lookup
        student_name_map = {str(s.get("student_id", "")).strip(): s.get("name", "") for s in self.students}

        for r in records:
            row_frame = ctk.CTkFrame(self.att_scroll, fg_color=("#f8fafc", "#1c1f2b"), height=34, corner_radius=6)
            row_frame.pack(fill="x", pady=2)

            sid = str(r.get("student_id", "")).strip()
            sname = student_name_map.get(sid, "--")

            ctk.CTkLabel(row_frame, text=r.get("attendance_time", ""), width=90).pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=r.get("attendance_date", ""), width=100).pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=sid, width=100, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=sname, width=180, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=r.get("bus_id", ""), width=100).pack(side="left", padx=5)

            status_text = r.get("status", "Present")
            status_badge = ctk.CTkLabel(
                row_frame,
                text=status_text,
                width=80,
                height=24,
                corner_radius=12,
                fg_color=("#dcfce7", "#064e3b") if status_text == "Present" else ("#fef3c7", "#78350f"),
                text_color=("#15803d", "#34d399") if status_text == "Present" else ("#b45309", "#fbbf24"),
                font=ctk.CTkFont(size=11, weight="bold")
            )
            status_badge.pack(side="left", padx=10)

    # =========================================================================
    # TAB 2: STUDENT DIRECTORY & BUS ASSIGNMENT
    # =========================================================================

    def _build_students_tab(self) -> None:
        ctrl = ctk.CTkFrame(self.tab_students, fg_color=("#ffffff", "#1c1f2b"), corner_radius=10, border_width=1, border_color=("#e2e8f0", "#2d3748"))
        ctrl.pack(fill="x", padx=10, pady=(6, 8))

        goto_register_btn = ctk.CTkButton(
            ctrl,
            text="➕ Register New Student",
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(weight="bold"),
            command=self.switch_to_register_tab
        )
        goto_register_btn.pack(side="left", padx=15, pady=10)

        ctk.CTkLabel(ctrl, text="Filter Bus:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(15, 5))
        self.stu_bus_filter_var = ctk.StringVar(value="All Buses")
        self.stu_bus_combo = ctk.CTkComboBox(
            ctrl,
            variable=self.stu_bus_filter_var,
            values=["All Buses"],
            width=120,
            command=lambda _: self.render_students_table()
        )
        self.stu_bus_combo.pack(side="left", padx=5)

        add_bus_btn = ctk.CTkButton(
            ctrl,
            text="🚌 Add Bus",
            width=90,
            fg_color=("#e2e8f0", "#334155"),
            text_color=("#0f172a", "#f8fafc"),
            hover_color=("#cbd5e1", "#475569"),
            font=ctk.CTkFont(weight="bold"),
            command=self.prompt_add_new_bus
        )
        add_bus_btn.pack(side="left", padx=5)

        ctk.CTkLabel(ctrl, text="Search:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(15, 5))
        self.search_entry = ctk.CTkEntry(ctrl, placeholder_text="ID or Name...", width=160)
        self.search_entry.pack(side="left", padx=5)
        self.search_entry.bind("<KeyRelease>", lambda _: self.render_students_table())

        self.students_scroll = ctk.CTkScrollableFrame(self.tab_students, fg_color=("#ffffff", "#161822"), corner_radius=10, border_width=1, border_color=("#e2e8f0", "#2d3748"))
        self.students_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def switch_to_register_tab(self) -> None:
        self.show_page("register_student")
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
        hdr = ctk.CTkFrame(self.students_scroll, fg_color=("#e2e8f0", "#242938"), height=35, corner_radius=6)
        hdr.pack(fill="x", pady=2)
        cols = [("ID", 80), ("Full Name", 190), ("Class", 90), ("Assigned Bus", 150), ("Status", 90), ("Actions", 130)]
        for cname, w in cols:
            ctk.CTkLabel(hdr, text=cname, width=w, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5, pady=5)

        if not filtered:
            ctk.CTkLabel(self.students_scroll, text="No registered students found.", text_color=("#64748b", "#94a3b8")).pack(pady=40)
            return

        for s in filtered:
            sid = str(s.get("student_id", "")).strip()
            sname = str(s.get("name", "")).strip()
            cur_bus = str(s.get("bus_id", "")).strip()

            if not sid:
                continue

            row = ctk.CTkFrame(self.students_scroll, fg_color=("#f8fafc", "#1c1f2b"), height=38, corner_radius=6)
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

    def prompt_add_new_bus(self) -> None:
        """Prompt manager to manually register a new bus in Supabase cloud."""
        new_bus = simpledialog.askstring("Add School Bus", "Enter New Bus ID (e.g. Bus02, Bus03):", parent=self)
        if new_bus and new_bus.strip():
            clean_b = new_bus.strip()
            self.status_lbl.configure(text=f"Registering {clean_b} to Supabase...", text_color="#fbbf24")
            def _async_add():
                ok = self.cloud.ensure_bus(clean_b)
                if ok:
                    self.after(0, lambda: messagebox.showinfo("Bus Registered", f"Bus '{clean_b}' registered successfully in Supabase!"))
                    self.refresh_all_data()
                else:
                    self.after(0, lambda: messagebox.showerror("Cloud Error", f"Failed to register bus: {self.cloud._last_error}"))
            threading.Thread(target=_async_add, daemon=True).start()

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
        container = ctk.CTkFrame(self.tab_register, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Left Column: Student Details Form
        left_form = ctk.CTkFrame(container, fg_color=("#ffffff", "#1c1f2b"), width=360, corner_radius=10, border_width=1, border_color=("#e2e8f0", "#2d3748"))
        left_form.pack(side="left", fill="y", padx=(0, 10), pady=0)
        left_form.pack_propagate(False)

        ctk.CTkLabel(
            left_form,
            text="Student Details",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=("#0284c7", "#38bdf8")
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

        ctk.CTkLabel(left_form, text="Assign Bus ID (Select or Type):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(6, 2))
        self.reg_bus_var = ctk.StringVar(value="Bus01")
        self.reg_bus_menu = ctk.CTkComboBox(left_form, variable=self.reg_bus_var, values=["Bus01"], height=35)
        self.reg_bus_menu.pack(fill="x", padx=20, pady=(0, 20))

        # Instructions card
        info_box = ctk.CTkFrame(left_form, fg_color=("#f1f5f9", "#161822"), corner_radius=8)
        info_box.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkLabel(
            info_box,
            text="📌 Instructions:\n• Stand in front of camera\n• Ensure exactly 1 face is visible\n• Box turns Green when ready\n• Click 'Capture & Register'",
            justify="left",
            text_color=("#64748b", "#94a3b8")
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
        right_cam = ctk.CTkFrame(container, fg_color=("#ffffff", "#1c1f2b"), corner_radius=10, border_width=1, border_color=("#e2e8f0", "#2d3748"))
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
        self.show_page("student_directory")

    # =========================================================================
    # TAB 4: REPORTS & CSV EXPORT
    # =========================================================================

    def _build_reports_tab(self) -> None:
        frame = ctk.CTkFrame(self.tab_reports, fg_color=("#ffffff", "#1c1f2b"), corner_radius=10, border_width=1, border_color=("#e2e8f0", "#2d3748"))
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
        date_val = self.date_entry.get().strip() if hasattr(self, "date_entry") else datetime.now().strftime("%Y-%m-%d")
        bus_val = None if (not hasattr(self, "bus_filter_var") or self.bus_filter_var.get() == "All Buses") else self.bus_filter_var.get()
        threading.Thread(target=self._async_fetch_all, args=(date_val, bus_val), daemon=True).start()

    def _async_fetch_all(self, date_val: str, bus_val: Optional[str]) -> None:
        buses = self.cloud.get_buses()
        students = self.cloud.get_students(active_only=False)
        records = self.cloud.get_attendance(date_str=date_val, bus_id=bus_val)

        self.buses = buses
        self.students = students
        self.attendance_records = records

        try:
            self.after(0, self._update_ui_after_fetch)
        except Exception:
            pass

    def _update_ui_after_fetch(self) -> None:
        # Discover all unique bus IDs from buses table + students + attendance records
        distinct_buses = set(b["bus_id"] for b in self.buses if b.get("bus_id"))
        for s in self.students:
            if s.get("bus_id"):
                distinct_buses.add(str(s["bus_id"]).strip())
        for r in self.attendance_records:
            if r.get("bus_id"):
                distinct_buses.add(str(r["bus_id"]).strip())

        sorted_buses = sorted(list(distinct_buses))
        if not sorted_buses:
            sorted_buses = ["Bus01"]

        bus_names = ["All Buses"] + sorted_buses

        # Update filter dropdowns
        self.bus_combo.configure(values=bus_names)
        self.stu_bus_combo.configure(values=bus_names)

        # Update bus options in registration form
        self.reg_bus_menu.configure(values=sorted_buses)

        # Update KPI Cards
        total_active_students = len([s for s in self.students if s.get("is_active", True)])
        present_count = len([r for r in self.attendance_records if r.get("status") == "Present"])
        unmarked_count = max(0, total_active_students - present_count)

        self.kpi_card_total.configure(text=str(total_active_students))
        self.kpi_card_present.configure(text=str(present_count))
        self.kpi_card_absent.configure(text=str(unmarked_count))
        self.kpi_card_buses.configure(text=str(len(sorted_buses)))

        self.status_lbl.configure(
            text=f"✔ Connected | {time.strftime('%H:%M:%S')}",
            text_color="#10b981"
        )
        self.render_attendance_table(self.attendance_records)
        self.render_students_table()

    def apply_attendance_filters(self) -> None:
        self.refresh_all_data()

    # =========================================================================
    # TAB 5: CLOUD SETTINGS & CREDENTIALS MANAGEMENT
    # =========================================================================

    def _build_settings_tab(self) -> None:
        scroll = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=15)

        card = ctk.CTkFrame(scroll, fg_color=("#ffffff", "#1c1f2b"), corner_radius=12, border_width=1, border_color=("#e2e8f0", "#2d3748"))
        card.pack(fill="x", padx=40, pady=10)

        # Title
        ctk.CTkLabel(
            card,
            text="⚙️ Supabase Cloud Database Configuration",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=("#0284c7", "#38bdf8")
        ).pack(anchor="w", padx=25, pady=(20, 5))

        ctk.CTkLabel(
            card,
            text="Manage central cloud connectivity, API keys, and server endpoints. Changes persist locally in .env.",
            font=ctk.CTkFont(size=12),
            text_color=("#64748b", "#94a3b8")
        ).pack(anchor="w", padx=25, pady=(0, 20))

        # Project URL
        ctk.CTkLabel(card, text="Supabase Project URL:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=25, pady=(5, 2))
        cur_url, cur_key = self.cloud.get_current_credentials()
        self.cfg_url_entry = ctk.CTkEntry(card, height=38, placeholder_text="https://your-project.supabase.co")
        self.cfg_url_entry.insert(0, cur_url)
        self.cfg_url_entry.pack(fill="x", padx=25, pady=(0, 15))

        # API Key with Show/Hide toggle
        key_hdr = ctk.CTkFrame(card, fg_color="transparent")
        key_hdr.pack(fill="x", padx=25, pady=(5, 2))
        ctk.CTkLabel(key_hdr, text="Supabase API Key (Publishable / Anon / Service):", font=ctk.CTkFont(weight="bold")).pack(side="left")

        self.key_visible = False
        self.show_hide_btn = ctk.CTkButton(
            key_hdr,
            text="👁️ Show Key",
            width=90,
            height=26,
            fg_color=("#e2e8f0", "#334155"),
            text_color=("#0f172a", "#f8fafc"),
            hover_color=("#cbd5e1", "#475569"),
            command=self._toggle_key_visibility
        )
        self.show_hide_btn.pack(side="right")

        self.cfg_key_entry = ctk.CTkEntry(card, height=38, show="•", placeholder_text="sb_publishable_...")
        self.cfg_key_entry.insert(0, cur_key)
        self.cfg_key_entry.pack(fill="x", padx=25, pady=(0, 15))

        # Connection status feedback box
        self.cfg_status_box = ctk.CTkLabel(
            card,
            text="Status: Connected (Ready)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#10b981"
        )
        self.cfg_status_box.pack(anchor="w", padx=25, pady=(0, 15))

        # Action Buttons
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=25, pady=(5, 25))

        test_btn = ctk.CTkButton(
            btn_row,
            text="🧪 Test Connection",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=40,
            width=160,
            command=self.test_cloud_settings
        )
        test_btn.pack(side="left", padx=(0, 10))

        save_btn = ctk.CTkButton(
            btn_row,
            text="💾 Save & Apply",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=40,
            width=160,
            command=self.save_cloud_settings
        )
        save_btn.pack(side="left", padx=10)

        reset_btn = ctk.CTkButton(
            btn_row,
            text="🔄 Restore Defaults",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#64748b",
            hover_color="#475569",
            height=40,
            width=160,
            command=self.restore_default_settings
        )
        reset_btn.pack(side="right")

    def _toggle_key_visibility(self) -> None:
        if self.key_visible:
            self.cfg_key_entry.configure(show="•")
            self.show_hide_btn.configure(text="👁️ Show Key")
            self.key_visible = False
        else:
            self.cfg_key_entry.configure(show="")
            self.show_hide_btn.configure(text="🙈 Hide Key")
            self.key_visible = True

    def test_cloud_settings(self) -> None:
        url = self.cfg_url_entry.get().strip().rstrip("/")
        key = self.cfg_key_entry.get().strip()
        if not url or not key:
            messagebox.showwarning("Incomplete", "Please provide both Supabase URL and API Key.")
            return

        self.cfg_status_box.configure(text="Testing connection...", text_color="#fbbf24")

        def _test():
            from fleet_system.shared.cloud_client import FleetCloudClient
            temp_client = FleetCloudClient(url=url, key=key)
            ok, msg = temp_client.test_connection()
            if ok:
                self.after(0, lambda: self.cfg_status_box.configure(text="✅ Connection Successful (200 OK)", text_color="#10b981"))
                self.after(0, lambda: messagebox.showinfo("Connection OK", "Successfully connected to Supabase cloud!"))
            else:
                self.after(0, lambda: self.cfg_status_box.configure(text=f"❌ Connection Failed: {msg[:40]}...", text_color="#ef4444"))
                self.after(0, lambda: messagebox.showerror("Connection Failed", f"Could not connect to Supabase:\n\n{msg}"))

        threading.Thread(target=_test, daemon=True).start()

    def save_cloud_settings(self) -> None:
        url = self.cfg_url_entry.get().strip().rstrip("/")
        key = self.cfg_key_entry.get().strip()
        if not url or not key:
            messagebox.showwarning("Incomplete", "Please provide both Supabase URL and API Key.")
            return

        confirm = messagebox.askyesno(
            "Confirm Save",
            f"Are you sure you want to save and switch to this Supabase project?\n\nURL: {url}\n\nThis will reconfigure the application and reload all buses, students, and attendance."
        )
        if not confirm:
            return

        ok = save_cloud_credentials(url, key)
        self.cloud.reconfigure(url, key)
        if ok:
            messagebox.showinfo("Saved", "Cloud credentials saved to .env and applied successfully!")
        else:
            messagebox.showwarning("Partial Save", "Credentials applied in memory, but could not write to .env file.")

        self.refresh_all_data()

    def restore_default_settings(self) -> None:
        confirm = messagebox.askyesno(
            "Restore Defaults",
            "Are you sure you want to restore the built-in factory default Supabase credentials?"
        )
        if not confirm:
            return

        url, key = self.cloud.reset_to_defaults()
        self.cfg_url_entry.delete(0, "end")
        self.cfg_url_entry.insert(0, url)
        self.cfg_key_entry.delete(0, "end")
        self.cfg_key_entry.insert(0, key)
        self.cfg_status_box.configure(text="Status: Factory Defaults Restored", text_color="#38bdf8")
        messagebox.showinfo("Restored", "Factory default credentials have been restored!")
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
