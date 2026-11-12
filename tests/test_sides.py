import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from mk96env_core.backup import Backup
from mk96env_core.sides import FormatError, LocalSide, RepoSide


class FakeRunner:
    """Records `claude plugin ...` calls instead of running them."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")


class SidesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / ".claude"
        self.home.mkdir()
        self.backup = Backup(self.home / "backups" / "mk96-env" / "now", self.home)
        self.runner = FakeRunner()
        self.local = LocalSide(self.home, self.runner, self.backup)
        self.repo = RepoSide(self.root / "env")

    def tearDown(self):
        self._tmp.cleanup()

    def write_settings(self, settings):
        (self.home / "settings.json").write_text(json.dumps(settings))

    def read_settings(self):
        return json.loads((self.home / "settings.json").read_text())


class LocalSettingsTest(SidesTestCase):
    def test_writing_a_preference_keeps_every_unmanaged_key(self):
        original = {
            "model": "sonnet",
            "hooks": {"Stop": [{"hooks": [{"command": "orca"}]}]},
            "statusLine": {"type": "command", "command": "orca"},
            "env": {"OTHER": "1"},
        }
        self.write_settings(original)

        self.local.write("settings/model", {"": b'"opus"'})

        expected = dict(original, model="opus")
        self.assertEqual(self.read_settings(), expected)

    def test_settings_are_backed_up_before_the_first_change(self):
        self.write_settings({"model": "sonnet"})
        self.local.write("settings/model", {"": b'"opus"'})
        saved = self.backup.folder / "settings.json"
        self.assertEqual(json.loads(saved.read_text()), {"model": "sonnet"})

    def test_removing_a_preference_deletes_only_that_key(self):
        self.write_settings({"model": "opus", "theme": "dark"})
        self.local.delete("settings/model")
        self.assertEqual(self.read_settings(), {"theme": "dark"})

    def test_unmanaged_settings_are_never_listed(self):
        self.write_settings({"model": "opus", "skipDangerousModePermissionPrompt": True})
        self.assertEqual(self.local.keys(), {"settings/model"})


OWN_HOOK = {"type": "command", "command": '"$HOME/.claude/hooks/git-guard/git-guard.sh"'}
FOREIGN_HOOK = {"type": "command", "command": "orca-hook", "timeout": 10}


class LocalGuardrailsTest(SidesTestCase):
    """Deny rules and own hooks travel; everything machine-specific stays."""

    def test_only_deny_rules_are_exported(self):
        self.write_settings({"permissions": {
            "deny": ["Read(//**/.env)"], "allow": ["Bash(ls)"], "ask": ["Bash(rm *)"],
        }})
        self.assertEqual(self.local.keys(), {"settings/permissions.deny"})
        self.assertEqual(
            self.local.read("settings/permissions.deny"), {"": b'["Read(//**/.env)"]'}
        )

    def test_importing_deny_rules_keeps_allow_and_ask(self):
        self.write_settings({"permissions": {"deny": ["old"], "allow": ["Bash(ls)"]}})
        self.local.write("settings/permissions.deny", {"": b'["new"]'})
        self.assertEqual(
            self.read_settings()["permissions"], {"deny": ["new"], "allow": ["Bash(ls)"]}
        )

    def test_only_portable_own_hooks_are_exported(self):
        machine_bound = {"type": "command", "command": "/home/me/.claude/hooks/x/x.sh"}
        self.write_settings({"hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [FOREIGN_HOOK]},
                {"matcher": "Bash", "hooks": [OWN_HOOK]},
                {"matcher": "Edit", "hooks": [machine_bound]},
            ],
        }})

        exported = json.loads(self.local.read("settings/hooks")[""])

        self.assertIn("settings/hooks", self.local.keys())
        self.assertEqual(
            exported, [{"event": "PreToolUse", "matcher": "Bash", "hook": OWN_HOOK}]
        )

    def test_importing_hooks_replaces_own_ones_and_keeps_foreign_ones(self):
        stale = {"type": "command", "command": "~/.claude/hooks/old/old.sh"}
        self.write_settings({"hooks": {
            "PreToolUse": [{"matcher": "*", "hooks": [FOREIGN_HOOK]}],
            "Stop": [{"hooks": [stale]}],
        }})
        incoming = [{"event": "PreToolUse", "matcher": "Bash", "hook": OWN_HOOK}]

        self.local.write("settings/hooks", {"": json.dumps(incoming).encode()})

        self.assertEqual(self.read_settings()["hooks"], {"PreToolUse": [
            {"matcher": "*", "hooks": [FOREIGN_HOOK]},
            {"matcher": "Bash", "hooks": [OWN_HOOK]},
        ]})

    def test_removing_hooks_keeps_foreign_ones(self):
        self.write_settings({"hooks": {"PreToolUse": [
            {"matcher": "*", "hooks": [FOREIGN_HOOK]},
            {"matcher": "Bash", "hooks": [OWN_HOOK]},
        ]}})
        self.local.delete("settings/hooks")
        self.assertEqual(
            self.read_settings()["hooks"],
            {"PreToolUse": [{"matcher": "*", "hooks": [FOREIGN_HOOK]}]},
        )


class LocalFilesTest(SidesTestCase):
    def test_rules_and_hook_scripts_are_synced(self):
        (self.home / "rules").mkdir()
        (self.home / "rules" / "java.md").write_text("rule")
        (self.home / "hooks" / "git-guard").mkdir(parents=True)
        (self.home / "hooks" / "git-guard" / "git-guard.sh").write_text("#!/bin/sh\n")
        self.assertEqual(self.local.keys(), {"rules/java.md", "hooks/git-guard"})

    def test_overwriting_a_command_keeps_a_backup(self):
        command = self.home / "commands" / "git_commit.md"
        command.parent.mkdir()
        command.write_text("old")

        self.local.write("commands/git_commit.md", {"": b"new"})

        self.assertEqual(command.read_text(), "new")
        saved = self.backup.folder / "commands" / "git_commit.md"
        self.assertEqual(saved.read_text(), "old")

    def test_deleting_a_command_keeps_a_backup(self):
        command = self.home / "commands" / "old.md"
        command.parent.mkdir()
        command.write_text("bye")
        self.local.delete("commands/old.md")
        self.assertFalse(command.exists())
        self.assertTrue((self.backup.folder / "commands" / "old.md").exists())

    def test_account_skills_and_generated_mod_types_are_not_synced(self):
        (self.home / "skills" / "synced" / "pdf").mkdir(parents=True)
        (self.home / "skills" / "mine").mkdir()
        (self.home / "skills" / "mine" / "SKILL.md").write_text("x")
        types = self.home / "mods" / "panel" / ".claude-plugin" / "types"
        types.mkdir(parents=True)
        (types / "index.d.ts").write_text("x")
        (types.parent / "plugin.json").write_text("{}")

        self.assertEqual(self.local.keys(), {"skills/mine", "mods/panel"})
        self.assertEqual(
            set(self.local.read("mods/panel")), {".claude-plugin/plugin.json"}
        )


class LocalModsTest(SidesTestCase):
    def test_plugin_dirs_variable_points_to_this_machine_and_keeps_foreign_entries(self):
        foreign = str(self.root / "elsewhere" / "plugin")
        self.write_settings({"env": {"CLAUDE_CODE_PLUGIN_DIRS": foreign}})

        self.local.write("mods/panel", {".claude-plugin/plugin.json": b"{}"})
        self.local.finish()

        value = self.read_settings()["env"]["CLAUDE_CODE_PLUGIN_DIRS"]
        self.assertEqual(
            value.split(os.pathsep), [foreign, str(self.home / "mods" / "panel")]
        )

    def test_similarly_named_foreign_folders_are_kept(self):
        foreign = str(self.home / "mods-dev" / "experiment")
        self.write_settings({"env": {"CLAUDE_CODE_PLUGIN_DIRS": foreign}})
        self.local.write("mods/panel", {"plugin.json": b"{}"})
        self.local.finish()
        value = self.read_settings()["env"]["CLAUDE_CODE_PLUGIN_DIRS"]
        self.assertIn(foreign, value.split(os.pathsep))

    def test_removing_the_last_mod_removes_the_variable(self):
        mod = self.home / "mods" / "panel"
        mod.mkdir(parents=True)
        self.write_settings({"env": {"CLAUDE_CODE_PLUGIN_DIRS": str(mod)}})
        self.local.delete("mods/panel")
        self.local.finish()
        self.assertEqual(self.read_settings()["env"], {})


class LocalPluginsTest(SidesTestCase):
    def test_missing_plugin_is_installed(self):
        self.write_settings({})
        self.local.write("plugins/tool@market", {"": b'{"enabled": true}'})
        self.assertEqual(self.runner.calls, [["claude", "plugin", "install", "tool@market"]])

    def test_disabled_plugin_is_installed_then_disabled(self):
        self.write_settings({})
        self.local.write("plugins/tool@market", {"": b'{"enabled": false}'})
        self.assertEqual(
            self.runner.calls,
            [
                ["claude", "plugin", "install", "tool@market"],
                ["claude", "plugin", "disable", "tool@market"],
            ],
        )

    def test_installed_plugin_only_changes_its_enabled_state(self):
        self.write_settings({"enabledPlugins": {"tool@market": False}})
        self.local.write("plugins/tool@market", {"": b'{"enabled": true}'})
        self.assertEqual(self.runner.calls, [["claude", "plugin", "enable", "tool@market"]])

    def test_removed_plugin_is_uninstalled(self):
        self.write_settings({"enabledPlugins": {"tool@market": True}})
        self.local.delete("plugins/tool@market")
        self.assertEqual(self.runner.calls, [["claude", "plugin", "uninstall", "tool@market"]])

    def test_missing_marketplace_is_added_from_its_source(self):
        self.local.write(
            "marketplaces/market", {"": b'{"repo": "owner/repo", "source": "github"}'}
        )
        self.assertEqual(
            self.runner.calls, [["claude", "plugin", "marketplace", "add", "owner/repo"]]
        )

    def test_local_directory_marketplaces_are_not_portable(self):
        registry = self.home / "plugins" / "known_marketplaces.json"
        registry.parent.mkdir()
        registry.write_text(json.dumps({
            "remote": {"source": {"source": "github", "repo": "o/r"}},
            "mine": {"source": {"source": "directory", "path": "/home/me/dev"}},
        }))
        self.assertEqual(self.local.keys(), {"marketplaces/remote"})


class RepoSideTest(SidesTestCase):
    def test_items_round_trip_through_the_env_folder(self):
        items = {
            "CLAUDE.md": {"": b"rules"},
            "commands/git_commit.md": {"": b"commit"},
            "mods/panel": {"hooks/hooks.json": b"{}"},
            "plugins/tool@market": {"": b'{"enabled": true}'},
            "marketplaces/market": {"": b'{"repo": "o/r", "source": "github"}'},
            "settings/model": {"": b'"opus"'},
            "rules/java.md": {"": b"rule"},
            "hooks/git-guard": {"git-guard.sh": b"#!/bin/sh\n"},
            "settings/permissions.deny": {"": b'["Read(//**/.env)"]'},
        }
        for key, payload in items.items():
            self.repo.write(key, payload)

        self.assertEqual(self.repo.keys(), set(items))
        for key, payload in items.items():
            self.assertEqual(self.repo.read(key), payload)

    def test_newer_format_than_known_is_refused(self):
        env = self.root / "env"
        env.mkdir()
        (env / "plugins.json").write_text('{"format": 99, "plugins": {}}')
        with self.assertRaises(FormatError):
            self.repo.keys()


if __name__ == "__main__":
    unittest.main()
