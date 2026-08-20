"""WorkspaceManager — the project context coding mode runs on.

This file previously held 34 tests behind
``@unittest.skip("WorkspaceManager implementation mismatch")``. The skip
was accurate: they were written against a pre-refactor API
(``scan_files``, ``get_file_content``, ``generate_tree``,
``recent_files``, ``root_path``, and ``cache_file`` / ``ignore_patterns``
constructor kwargs) and every one of them raised AttributeError or
TypeError once the skip came off. Nothing else in the suite touched
WorkspaceManager, so a live module — instantiated by ``agent/core.py``
and ``agent/modes/coding.py`` — had no coverage at all.

These assert the API that exists, and pin the behaviours worth pinning
rather than porting the dead ones one for one.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from agent.workspace_manager import WorkspaceManager


class WorkspaceTestCase(unittest.TestCase):
    """Builds a small project tree under a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "main.py").write_text("import helper\n")
        (self.root / "helper.py").write_text("def help():\n    return 1\n")
        (self.root / "README.md").write_text("# Project\n")
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("x = 1\n")
        self.wm = WorkspaceManager(str(self.root))

    def tearDown(self):
        self._tmp.cleanup()


class TestScan(WorkspaceTestCase):

    def test_scan_returns_paths_relative_to_project_root(self):
        files = self.wm.scan()
        self.assertIn("main.py", files)
        self.assertIn(os.path.join("src", "app.py"), files)
        for f in files:
            self.assertFalse(os.path.isabs(f), f"{f} should be relative")

    def test_scan_excludes_noise_directories(self):
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "main.cpython-39.pyc").write_bytes(b"\x00")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "pkg.js").write_text("//")
        files = self.wm.scan(force_refresh=True)
        self.assertFalse([f for f in files if "__pycache__" in f])
        self.assertFalse([f for f in files if "node_modules" in f])

    def test_scan_excludes_binaries_by_pattern(self):
        (self.root / "blob.bin").write_bytes(b"\x00")
        (self.root / "lib.so").write_bytes(b"\x00")
        files = self.wm.scan(force_refresh=True)
        self.assertNotIn("blob.bin", files)
        self.assertNotIn("lib.so", files)

    def test_scan_keeps_files_the_exclude_list_does_not_name(self):
        """Selection is exclude-based, not include-based.

        ``_include_extensions`` is built in __init__ and then never read;
        scan() filters only through _exclude_patterns. So a .jpg or a
        .sqlite lands in the workspace while an extensionless Dockerfile
        also survives — which is why enabling that list as-is would be a
        regression, not a fix. Pinning the real contract here so the
        difference is visible if anyone wires the list up.
        """
        (self.root / "photo.jpg").write_bytes(b"\xff\xd8\xff")
        (self.root / "Dockerfile").write_text("FROM python\n")
        files = self.wm.scan(force_refresh=True)
        self.assertIn("photo.jpg", files)
        self.assertIn("Dockerfile", files)

    def test_scan_serves_from_cache_until_forced(self):
        first = self.wm.scan()
        (self.root / "late.py").write_text("y = 2\n")
        self.assertEqual(self.wm.scan(), first, "cache should hold for 5 minutes")
        self.assertIn("late.py", self.wm.scan(force_refresh=True))

    def test_scan_records_metadata_per_file(self):
        self.wm.scan()
        meta = self.wm.file_metadata["main.py"]
        self.assertEqual(meta["extension"], ".py")
        self.assertGreater(meta["size"], 0)
        self.assertTrue(os.path.isabs(meta["absolute_path"]))


class TestGetFiles(WorkspaceTestCase):

    def test_get_files_merges_path_with_metadata(self):
        entries = self.wm.get_files()
        by_path = {e["path"]: e for e in entries}
        self.assertIn("main.py", by_path)
        self.assertEqual(by_path["main.py"]["extension"], ".py")
        self.assertIn("size", by_path["main.py"])


class TestFindFile(WorkspaceTestCase):

    def test_find_file_matches_glob(self):
        self.assertIn("main.py", self.wm.find_file("*.py"))

    def test_find_file_falls_back_to_substring_when_no_glob_chars(self):
        self.assertIn("helper.py", self.wm.find_file("helper"))

    def test_find_file_substring_is_case_insensitive(self):
        self.assertIn("README.md", self.wm.find_file("readme"))

    def test_find_file_returns_empty_for_no_match(self):
        self.assertEqual(self.wm.find_file("nothing_like_this"), [])


class TestFileContext(WorkspaceTestCase):

    def test_get_file_context_reads_relative_path(self):
        self.assertIn("def help()", self.wm.get_file_context("helper.py"))

    def test_get_file_context_reads_absolute_path(self):
        abs_path = str(self.root / "helper.py")
        self.assertIn("def help()", self.wm.get_file_context(abs_path))

    def test_get_file_context_returns_none_for_missing_file(self):
        self.assertIsNone(self.wm.get_file_context("does_not_exist.py"))

    def test_get_file_context_returns_none_for_directory(self):
        self.assertIsNone(self.wm.get_file_context("src"))

    def test_get_file_context_truncates_and_says_so(self):
        (self.root / "long.py").write_text("\n".join(f"line{i}" for i in range(500)))
        out = self.wm.get_file_context("long.py", max_lines=10)
        self.assertIn("line0", out)
        self.assertNotIn("line400", out)
        self.assertIn("truncated", out)
        self.assertIn("500 lines", out)

    def test_reading_a_file_marks_it_recently_accessed(self):
        self.wm.get_file_context("helper.py")
        self.assertIn("helper.py", self.wm.get_recent_files())


class TestRecentFiles(WorkspaceTestCase):

    def test_recent_files_are_most_recent_first(self):
        self.wm.track_file_access("main.py")
        time.sleep(0.01)
        self.wm.track_file_access("helper.py")
        self.assertEqual(self.wm.get_recent_files()[0], "helper.py")

    def test_recent_files_honours_count(self):
        for name in ("main.py", "helper.py", "README.md"):
            self.wm.track_file_access(name)
            time.sleep(0.01)
        self.assertEqual(len(self.wm.get_recent_files(count=2)), 2)

    def test_track_file_access_normalises_absolute_paths(self):
        self.wm.track_file_access(str(self.root / "main.py"))
        self.assertIn("main.py", self.wm.get_recent_files())

    def test_track_file_access_keeps_only_the_last_twenty(self):
        for i in range(25):
            self.wm.track_file_access(f"f{i}.py")
        self.assertEqual(len(self.wm.recently_accessed), 20)
        self.assertNotIn("f0.py", [p for p, _ in self.wm.recently_accessed])

    def test_entries_older_than_a_day_are_dropped(self):
        self.wm.recently_accessed = [("stale.py", time.time() - 90000)]
        self.assertEqual(self.wm.get_recent_files(), [])

    def test_track_file_access_outside_project_is_ignored(self):
        outside = Path(self._tmp.name).parent / "elsewhere.py"
        self.wm.track_file_access(str(outside))
        self.assertNotIn("elsewhere.py", self.wm.get_recent_files())


class TestProjectStructure(WorkspaceTestCase):

    def test_structure_lists_files_and_directories(self):
        tree = self.wm.get_project_structure()
        self.assertIn("main.py", tree)
        self.assertIn("src", tree)
        self.assertIn("app.py", tree)

    def test_structure_collapses_paths_deeper_than_max_depth(self):
        deep = self.root / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "buried.py").write_text("z = 1\n")
        tree = self.wm.get_project_structure(max_depth=2)
        self.assertNotIn("buried.py", tree)
        self.assertIn("...", tree)

    def test_structure_reports_an_empty_project(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(
                WorkspaceManager(empty).get_project_structure(),
                "No files found in project.",
            )


class TestProjectRoot(unittest.TestCase):

    def test_defaults_to_cwd(self):
        self.assertEqual(WorkspaceManager().project_root, Path(os.getcwd()).resolve())

    def test_project_root_is_resolved(self):
        with tempfile.TemporaryDirectory() as d:
            unresolved = os.path.join(d, "sub", "..")
            os.makedirs(os.path.join(d, "sub"), exist_ok=True)
            self.assertEqual(
                WorkspaceManager(unresolved).project_root, Path(d).resolve()
            )


if __name__ == "__main__":
    unittest.main()
