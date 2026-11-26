from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_llm_vtuber.announcement_routes import init_announcement_routes
from open_llm_vtuber.announcements import AnnouncementStore


class AnnouncementStoreTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = AnnouncementStore(Path(tmp_dir) / "missing.yaml")
            self.assertEqual(store.list_active(), [])

    def test_loads_filters_and_sorts_announcements(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "announcements.yaml"
            file_path.write_text(
                """
announcements:
  - id: "old-info"
    title: "Older info"
    content: "Body 1"
    level: "info"
    updated_at: "2026-11-20T10:00:00Z"
  - id: "new-info"
    title: "Newer info"
    content: "Body 2"
    level: "warning"
    updated_at: "2026-11-25T10:00:00+08:00"
  - id: "pinned-old"
    title: "Pinned announcement"
    content: "Pinned body"
    level: "important"
    pinned: true
    popup: true
    updated_at: "2026-11-18T00:00:00Z"
  - id: "disabled-item"
    title: "Disabled"
    content: "Hidden"
    enabled: false
  - id: "future-item"
    title: "Future"
    content: "Not yet"
    starts_at: "2026-12-01T00:00:00Z"
  - id: "expired-item"
    title: "Expired"
    content: "Gone"
    ends_at: "2026-11-26T00:00:00Z"
""",
                encoding="utf-8",
            )

            store = AnnouncementStore(file_path)
            now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
            active = store.list_active(now=now)

            self.assertEqual(
                [item["id"] for item in active],
                ["pinned-old", "new-info", "old-info"],
            )
            self.assertTrue(active[0]["pinned"])
            self.assertTrue(active[0]["popup"])
            self.assertEqual(active[0]["level"], "important")
            self.assertEqual(active[1]["level"], "warning")

    def test_hot_reloads_and_keeps_last_good_on_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "announcements.yaml"
            file_path.write_text(
                """
announcements:
  - id: "v1"
    title: "First"
    content: "Hello"
""",
                encoding="utf-8",
            )

            store = AnnouncementStore(file_path)
            self.assertEqual([item["id"] for item in store.list_active()], ["v1"])

            stat = file_path.stat()
            file_path.write_text(
                """
announcements:
  - id: "v2"
    title: "Second"
    content: "Updated content"
""",
                encoding="utf-8",
            )
            os.utime(file_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            self.assertEqual([item["id"] for item in store.list_active()], ["v2"])

            stat2 = file_path.stat()
            file_path.write_text("announcements: [unclosed", encoding="utf-8")
            os.utime(
                file_path, ns=(stat2.st_atime_ns, stat2.st_mtime_ns + 1_000_000_000)
            )
            self.assertEqual([item["id"] for item in store.list_active()], ["v2"])

            file_path.unlink()
            self.assertEqual(store.list_active(), [])

    def test_skips_invalid_entries_and_handles_yaml_coercions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "announcements.yaml"
            file_path.write_text(
                """
announcements:
  - "not-a-dict"
  - id: ""
    title: "No id"
    content: "Ignored"
  - id: "missing-content"
    title: "No content"
  - id: 20261126
    title: "Numeric id"
    content: "Valid body"
    level: "unknown-level"
    starts_at: 2026-11-26
    updated_at: "2026-11-26T08:00:00Z"
  - id: "20261126"
    title: "Duplicate id"
    content: "Should be skipped"
""",
                encoding="utf-8",
            )

            store = AnnouncementStore(file_path)
            now = datetime(2026, 11, 26, 23, 59, tzinfo=timezone.utc)
            active = store.list_active(now=now)

            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["id"], "20261126")
            self.assertEqual(active[0]["title"], "Numeric id")
            self.assertEqual(active[0]["level"], "info")
            self.assertIsNotNone(active[0]["starts_at"])

    def test_announcement_http_route(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "announcements.yaml"
            file_path.write_text(
                f"""
announcements:
  - id: "http-check"
    title: "Maintenance"
    content: "**Notice** at {int(time.time())}"
    level: "warning"
    popup: true
""",
                encoding="utf-8",
            )

            app = FastAPI()
            app.include_router(init_announcement_routes(AnnouncementStore(file_path)))
            client = TestClient(app)

            response = client.get("/api/announcements")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            payload = response.json()
            self.assertEqual(len(payload["announcements"]), 1)
            self.assertEqual(payload["announcements"][0]["id"], "http-check")
            self.assertTrue(payload["announcements"][0]["popup"])


if __name__ == "__main__":
    unittest.main()
