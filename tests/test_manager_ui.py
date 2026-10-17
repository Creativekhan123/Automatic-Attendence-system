"""Unit test suite for AttendanceManagerApp sidebar navigation, theme toggling, and collapse."""
import os
import sys
import unittest

# Ensure root
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class TestManagerUINavigation(unittest.TestCase):

    def setUp(self):
        from fleet_system.manager_app.main import AttendanceManagerApp
        self.app = AttendanceManagerApp()
        self.app.update()

    def tearDown(self):
        if hasattr(self, "app") and self.app:
            self.app.destroy()

    def test_sidebar_pages_navigation(self):
        pages = [
            "live_attendance",
            "student_directory",
            "bus_management",
            "register_student",
            "reports",
            "cloud_settings",
            "settings"
        ]
        for p in pages:
            self.app.show_page(p)
            self.app.update()
            expected = "cloud_settings" if p == "settings" else p
            self.assertEqual(self.app.current_page_key, expected)

    def test_legacy_tabs_backward_compatibility(self):
        legacy_tabs = [
            ("📋 Live Attendance", "live_attendance"),
            ("👥 Student Directory & Bus Assign", "student_directory"),
            ("➕ Register Student (Live Camera)", "register_student"),
            ("📊 Reports & CSV Export", "reports"),
            ("⚙️ Cloud Settings", "cloud_settings"),
        ]
        for tab_label, expected_key in legacy_tabs:
            self.app.tabs.set(tab_label)
            self.app.update()
            self.assertEqual(self.app.current_page_key, expected_key)

    def test_sidebar_collapse_and_expand(self):
        self.assertFalse(self.app.is_sidebar_collapsed)
        self.app.toggle_sidebar()
        self.app.update()
        self.assertTrue(self.app.is_sidebar_collapsed)
        self.assertEqual(self.app.sidebar.cget("width"), self.app.COLLAPSED_WIDTH)

        self.app.toggle_sidebar()
        self.app.update()
        self.assertFalse(self.app.is_sidebar_collapsed)
        self.assertEqual(self.app.sidebar.cget("width"), self.app.EXPANDED_WIDTH)

    def test_dark_and_light_theme_toggle(self):
        self.app._on_theme_changed("☀️ Light")
        self.app.update()
        self.app._on_theme_changed("🌙 Dark")
        self.app.update()


if __name__ == "__main__":
    unittest.main()
