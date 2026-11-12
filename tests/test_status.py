import os
import tempfile
import unittest
from pathlib import Path

from mk96env_core.payload import payload_hash, read_tree, write_tree
from mk96env_core.status import Status, classify

A, B, C = "hash-a", "hash-b", "hash-c"


class ClassifyWithStateTest(unittest.TestCase):
    def check(self, local, repo, base, expected):
        self.assertEqual(classify(local, repo, base, is_first_sync=False), expected)

    def test_same_everywhere_is_unchanged(self):
        self.check(A, A, A, Status.UNCHANGED)

    def test_local_edit_is_changed_here(self):
        self.check(B, A, A, Status.CHANGED_HERE)

    def test_repo_edit_is_changed_elsewhere(self):
        self.check(A, B, A, Status.CHANGED_ELSEWHERE)

    def test_both_edited_differently_is_conflict(self):
        self.check(B, C, A, Status.CONFLICT)

    def test_both_edited_identically_is_unchanged(self):
        self.check(B, B, A, Status.UNCHANGED)

    def test_local_removal_is_removed_here(self):
        self.check(None, A, A, Status.REMOVED_HERE)

    def test_repo_removal_is_removed_elsewhere(self):
        self.check(A, None, A, Status.REMOVED_ELSEWHERE)

    def test_new_local_item_is_added_here(self):
        self.check(A, None, None, Status.ADDED_HERE)

    def test_new_repo_item_is_added_elsewhere(self):
        self.check(None, A, None, Status.ADDED_ELSEWHERE)

    def test_new_on_both_sides_with_different_content_is_conflict(self):
        self.check(A, B, None, Status.CONFLICT)

    def test_removed_here_but_modified_elsewhere_is_conflict(self):
        self.check(None, B, A, Status.CONFLICT)

    def test_modified_here_but_removed_elsewhere_is_conflict(self):
        self.check(B, None, A, Status.CONFLICT)


class ClassifyFirstSyncTest(unittest.TestCase):
    """Without a state file nothing may be removed or overwritten: the first sync only adds."""

    def check(self, local, repo, expected):
        self.assertEqual(classify(local, repo, None, is_first_sync=True), expected)

    def test_local_only_item_is_kept_as_added_here(self):
        self.check(A, None, Status.ADDED_HERE)

    def test_repo_only_item_is_added_elsewhere(self):
        self.check(None, A, Status.ADDED_ELSEWHERE)

    def test_differing_item_is_a_conflict_so_nothing_is_overwritten(self):
        self.check(A, B, Status.CONFLICT)


class PayloadTest(unittest.TestCase):
    def test_line_endings_do_not_change_the_hash(self):
        self.assertEqual(
            payload_hash({"": b"one\r\ntwo\r\n"}), payload_hash({"": b"one\ntwo\n"})
        )

    def test_tree_round_trip_skips_excluded_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "mod")
            (source / ".claude-plugin" / "types").mkdir(parents=True)
            (source / ".claude-plugin" / "plugin.json").write_text("{}")
            (source / ".claude-plugin" / "types" / "index.d.ts").write_text("x")
            payload = read_tree(source, excluded=(".claude-plugin/types",))
            self.assertEqual(set(payload), {".claude-plugin/plugin.json"})

            target = Path(tmp, "copy")
            write_tree(target, payload)
            self.assertEqual(read_tree(target), payload)

    def test_nested_git_repositories_and_python_caches_are_never_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp, "skill")
            (skill / ".git").mkdir(parents=True)
            (skill / ".git" / "HEAD").write_text("ref")
            (skill / "__pycache__").mkdir()
            (skill / "__pycache__" / "x.pyc").write_bytes(b"\0")
            (skill / "helper.pyc").write_bytes(b"\0")
            (skill / "SKILL.md").write_text("x")
            self.assertEqual(set(read_tree(skill)), {"SKILL.md"})

    def test_updating_a_tree_keeps_excluded_folders_and_drops_stale_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp, "mod")
            (mod / "node_modules").mkdir(parents=True)
            (mod / "node_modules" / "lib.js").write_text("lib")
            (mod / "stale.txt").write_text("old")

            write_tree(mod, {"hooks.json": b"{}"}, excluded=("node_modules",))

            self.assertTrue((mod / "node_modules" / "lib.js").exists())
            self.assertFalse((mod / "stale.txt").exists())
            self.assertEqual((mod / "hooks.json").read_text(), "{}")

    @unittest.skipIf(os.name == "nt", "no executable bit on Windows")
    def test_scripts_stay_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp, "skill")
            write_tree(skill, {"scripts/run.sh": b"#!/bin/sh\necho hi\n", "SKILL.md": b"x"})
            self.assertTrue(os.access(skill / "scripts" / "run.sh", os.X_OK))
            self.assertFalse(os.access(skill / "SKILL.md", os.X_OK))


if __name__ == "__main__":
    unittest.main()
