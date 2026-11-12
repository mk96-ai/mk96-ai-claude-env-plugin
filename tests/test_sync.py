"""End-to-end runs of import/export between two simulated machines and a real git remote."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from mk96env_core.cli import Context, ExitCode, execute

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class Machine:
    """A simulated computer: its own ~/.claude, ~/.config and plugin CLI."""

    def __init__(self, root: Path, remote: Path):
        self.claude_home = root / ".claude"
        self.claude_home.mkdir(parents=True)
        self.clone = root / "sync-clone"
        git("clone", "-q", str(remote), str(self.clone), cwd=root)
        self.context = Context(
            claude_home=self.claude_home, config_dir=root / ".config" / "mk96-env", runner=self.fake_claude
        )
        self.context.config_dir.mkdir(parents=True)
        (self.context.config_dir / "repo-path").write_text(str(self.clone))

    def fake_claude(self, args):
        """Simulate `claude plugin install|uninstall|enable|disable` by editing settings."""
        settings = self.settings()
        plugins = settings.setdefault("enabledPlugins", {})
        action, target = args[2], args[-1]
        if action in ("install", "enable"):
            plugins[target] = True
        elif action == "disable":
            plugins[target] = False
        elif action == "uninstall":
            plugins.pop(target, None)
        self.write_settings(settings)
        return subprocess.CompletedProcess(args, 0, "", "")

    def settings(self):
        path = self.claude_home / "settings.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def write_settings(self, settings):
        (self.claude_home / "settings.json").write_text(json.dumps(settings))

    def write(self, relative, text):
        path = self.claude_home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def read(self, relative):
        return (self.claude_home / relative).read_text()

    def run(self, command, resolutions=None):
        return execute(command, self.context, resolutions or {})


class SyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved_environ = dict(os.environ)
        os.environ.update(GIT_IDENTITY)
        self.remote = self.root / "remote.git"
        git("init", "-q", "--bare", "-b", "main", str(self.remote), cwd=self.root)
        seed = self.root / "seed"
        git("clone", "-q", str(self.remote), str(seed), cwd=self.root)
        (seed / "README.md").write_text("tool")
        git("add", ".", cwd=seed)
        git("commit", "-q", "-m", "init", cwd=seed)
        git("push", "-q", "origin", "main", cwd=seed)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_environ)
        self._tmp.cleanup()

    def machine(self, name):
        return Machine(self.root / name, self.remote)

    def remote_head(self):
        return git("rev-parse", "main", cwd=self.remote)

    def home_with_environment(self):
        home = self.machine("home")
        home.write("CLAUDE.md", "# rules\n")
        home.write("commands/git_commit.md", "commit\n")
        home.write_settings({"model": "opus", "enabledPlugins": {"tool@market": True}, "hooks": {"Stop": []}})
        self.assertEqual(home.run("export").exit_code, ExitCode.OK)
        return home

    def test_environment_exported_at_home_is_imported_at_work(self):
        self.home_with_environment()
        work = self.machine("work")
        work.write_settings({"statusLine": {"command": "other app"}})

        result = work.run("import")

        self.assertEqual(result.exit_code, ExitCode.OK, result.output)
        self.assertEqual(work.read("CLAUDE.md"), "# rules\n")
        self.assertEqual(work.read("commands/git_commit.md"), "commit\n")
        self.assertEqual(
            work.settings(),
            {"statusLine": {"command": "other app"}, "model": "opus", "enabledPlugins": {"tool@market": True}},
        )
        self.assertIn("mk96-env import", result.output)

    def test_fresh_machine_cannot_export_over_a_stored_environment(self):
        self.home_with_environment()
        before = self.remote_head()
        fresh = self.machine("fresh")

        result = fresh.run("export")

        self.assertEqual(result.exit_code, ExitCode.BLOCKED)
        self.assertIn("import", result.output)
        self.assertEqual(self.remote_head(), before)

    def test_first_import_keeps_local_only_items(self):
        self.home_with_environment()
        work = self.machine("work")
        work.write("commands/work_only.md", "mine\n")

        result = work.run("import")

        self.assertEqual(work.read("commands/work_only.md"), "mine\n")
        self.assertIn("pending export", result.output)

    def test_first_import_asks_before_overwriting_a_differing_local_item(self):
        self.home_with_environment()
        work = self.machine("work")
        work.write("CLAUDE.md", "# work rules\n")

        result = work.run("import")

        self.assertEqual(result.exit_code, ExitCode.CONFLICTS)
        self.assertEqual(work.read("CLAUDE.md"), "# work rules\n")

    def test_removal_at_home_propagates_to_work(self):
        home = self.home_with_environment()
        work = self.machine("work")
        work.run("import")

        (home.claude_home / "commands" / "git_commit.md").unlink()
        self.assertEqual(home.run("export").exit_code, ExitCode.OK)
        work.run("import")

        self.assertFalse((work.claude_home / "commands" / "git_commit.md").exists())

    def test_conflict_is_reported_then_resolved_with_the_chosen_version(self):
        home = self.home_with_environment()
        work = self.machine("work")
        work.run("import")
        home.write("CLAUDE.md", "# home rules\n")
        home.run("export")
        work.write("CLAUDE.md", "# work rules\n")

        pending = work.run("import")
        self.assertEqual(pending.exit_code, ExitCode.CONFLICTS)
        conflicts = json.loads(pending.output)["conflicts"]
        self.assertEqual([conflict["key"] for conflict in conflicts], ["CLAUDE.md"])
        self.assertEqual(work.read("CLAUDE.md"), "# work rules\n")

        resolved = work.run("import", {"CLAUDE.md": "repo"})
        self.assertEqual(resolved.exit_code, ExitCode.OK, resolved.output)
        self.assertEqual(work.read("CLAUDE.md"), "# home rules\n")
        backups = list((work.claude_home / "backups" / "mk96-env").rglob("CLAUDE.md"))
        self.assertEqual([path.read_text() for path in backups], ["# work rules\n"])

    def test_keeping_this_machines_version_on_import_exports_it_next(self):
        home = self.home_with_environment()
        work = self.machine("work")
        work.run("import")
        home.write("CLAUDE.md", "# home rules\n")
        home.run("export")
        work.write("CLAUDE.md", "# work rules\n")

        work.run("import", {"CLAUDE.md": "local"})
        work.run("export")
        home.run("import")

        self.assertEqual(home.read("CLAUDE.md"), "# work rules\n")

    def test_secret_blocks_the_export_and_nothing_is_pushed(self):
        home = self.home_with_environment()
        before = self.remote_head()
        home.write("commands/deploy.md", "TOKEN=ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8\n")

        result = home.run("export")

        self.assertEqual(result.exit_code, ExitCode.BLOCKED)
        self.assertIn("commands/deploy.md", result.output)
        self.assertEqual(self.remote_head(), before)
        self.assertFalse((home.clone / "env" / "commands" / "deploy.md").exists())

    def test_second_claude_profile_sharing_the_config_folder_cannot_empty_the_repository(self):
        home = self.home_with_environment()
        before = self.remote_head()
        empty_profile = self.root / "home" / ".claude-other"
        empty_profile.mkdir()
        home.context.claude_home = empty_profile

        result = home.run("export")

        self.assertEqual(result.exit_code, ExitCode.BLOCKED)
        self.assertEqual(self.remote_head(), before)

    def test_item_restored_after_a_shared_removal_is_exported_again(self):
        home = self.home_with_environment()
        work = self.machine("work")
        work.run("import")
        (home.claude_home / "commands" / "git_commit.md").unlink()
        home.run("export")
        (work.claude_home / "commands" / "git_commit.md").unlink()
        work.run("import")

        work.write("commands/git_commit.md", "commit\n")
        work.run("export")
        home.run("import")

        self.assertEqual(home.read("commands/git_commit.md"), "commit\n")

    def test_failed_commit_leaves_the_sync_clone_usable(self):
        home = self.home_with_environment()
        hook = home.clone / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        home.write("CLAUDE.md", "# changed\n")

        self.assertEqual(home.run("export").exit_code, ExitCode.ERROR)
        hook.unlink()
        result = home.run("export")

        self.assertEqual(result.exit_code, ExitCode.OK, result.output)
        self.assertIn("pushed", result.output)

    def test_missing_configuration_is_reported(self):
        work = self.machine("work")
        (work.context.config_dir / "repo-path").unlink()
        self.assertEqual(work.run("import").exit_code, ExitCode.NOT_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
