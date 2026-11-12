"""The two places an environment lives: this machine (~/.claude) and the repository (env/).

Both sides expose the same operations on item keys:

    CLAUDE.md                 global instructions
    commands/<file>.md        personal slash commands
    agents/<file>.md          personal agents
    skills/<name>             personal skills (account skills in skills/synced are excluded)
    mods/<name>               local plugins loaded through CLAUDE_CODE_PLUGIN_DIRS
    marketplaces/<name>       plugin marketplaces, value = their source
    plugins/<plugin@market>   installed plugins, value = {"enabled": bool}
    rules/<file>.md           personal rules
    hooks/<name>              personal hook scripts
    settings/<key>            the managed preferences of settings.json, plus
                              settings/permissions.deny and settings/hooks (own hooks only)
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .backup import Backup
from .payload import SINGLE_FILE, Payload, read_file, read_tree, write_file, write_tree

Runner = Callable[[list[str]], subprocess.CompletedProcess]

FORMAT_VERSION = 1
MANAGED_SETTINGS = ("model", "autoMemoryEnabled")
DENY_SETTING = "permissions.deny"
HOOKS_SETTING = "hooks"
SYNCED_SETTINGS = (*MANAGED_SETTINGS, DENY_SETTING, HOOKS_SETTING)
# Own hooks run a script from ~/.claude/hooks through a portable path; hooks of other
# tools (or with this machine's absolute path) are never exported nor touched.
OWN_HOOK_COMMAND = re.compile(r'^"?(\$HOME|\$\{HOME\}|~)/\.claude/hooks/')
PLUGIN_DIRS_VARIABLE = "CLAUDE_CODE_PLUGIN_DIRS"
FILE_FOLDERS = ("commands", "agents", "rules")
TREE_FOLDERS = ("skills", "mods", "hooks")
ACCOUNT_SKILLS_FOLDER = "synced"
# Generated files that a mod rebuilds by itself on each machine.
MOD_EXCLUDED_PATHS = (".claude-plugin/types", "node_modules")
# Marketplace sources that work on any machine (a local directory does not).
PORTABLE_SOURCE_TYPES = ("github", "git", "url")


class FormatError(Exception):
    """The repository was written by a newer version of the tool."""


class CommandError(Exception):
    """A `claude plugin` command failed."""


def _json_payload(value) -> Payload:
    return {SINGLE_FILE: json.dumps(value, sort_keys=True).encode("utf-8")}


def _json_value(payload: Payload):
    return json.loads(payload[SINGLE_FILE])


def _split(key: str) -> tuple[str, str]:
    folder, _, name = key.partition("/")
    return folder, name


def _excluded_paths(folder: str) -> tuple[str, ...]:
    return MOD_EXCLUDED_PATHS if folder == "mods" else ()


def _is_own_hook(hook: dict) -> bool:
    return hook.get("type") == "command" and bool(OWN_HOOK_COMMAND.match(hook.get("command", "")))


def _own_hooks(hooks_config: dict) -> list[dict]:
    """Flatten the own hooks of settings.json into {event, matcher, hook} items."""
    return [
        {"event": event, "matcher": group.get("matcher"), "hook": hook}
        for event, groups in hooks_config.items()
        for group in groups
        for hook in group.get("hooks", [])
        if _is_own_hook(hook)
    ]


def _with_own_hooks(hooks_config: dict, own_hooks: list[dict]) -> dict:
    """Replace every own hook with own_hooks, keeping foreign hooks untouched."""
    merged: dict = {}
    for event, groups in hooks_config.items():
        kept_groups = []
        for group in groups:
            foreign = [hook for hook in group.get("hooks", []) if not _is_own_hook(hook)]
            if foreign:
                kept_groups.append({**group, "hooks": foreign})
        if kept_groups:
            merged[event] = kept_groups
    for item in own_hooks:
        group = {"hooks": [item["hook"]]}
        if item.get("matcher") is not None:
            group = {"matcher": item["matcher"], **group}
        merged.setdefault(item["event"], []).append(group)
    return merged


def _managed_settings(settings: dict) -> dict:
    """The parts of a full settings.json that are synced, by setting name."""
    managed = {key: settings[key] for key in MANAGED_SETTINGS if key in settings}
    deny = settings.get("permissions", {}).get("deny")
    if deny:
        managed[DENY_SETTING] = deny
    own_hooks = _own_hooks(settings.get("hooks", {}))
    if own_hooks:
        managed[HOOKS_SETTING] = own_hooks
    return managed


def _apply_setting(settings: dict, name: str, value) -> None:
    if name == DENY_SETTING:
        settings.setdefault("permissions", {})["deny"] = value
    elif name == HOOKS_SETTING:
        settings["hooks"] = _with_own_hooks(settings.get("hooks", {}), value)
    else:
        settings[name] = value


def _remove_setting(settings: dict, name: str) -> None:
    if name == DENY_SETTING:
        permissions = settings.get("permissions", {})
        permissions.pop("deny", None)
        if not permissions:
            settings.pop("permissions", None)
    elif name == HOOKS_SETTING:
        foreign_only = _with_own_hooks(settings.get("hooks", {}), [])
        if foreign_only:
            settings["hooks"] = foreign_only
        else:
            settings.pop("hooks", None)
    else:
        settings.pop(name, None)


def _list_files(root: Path, folder: str) -> set[str]:
    directory = root / folder
    if not directory.is_dir():
        return set()
    return {f"{folder}/{path.name}" for path in directory.glob("*.md") if path.is_file()}


def _list_trees(root: Path, folder: str, skipped: tuple[str, ...] = ()) -> set[str]:
    directory = root / folder
    if not directory.is_dir():
        return set()
    return {
        f"{folder}/{path.name}"
        for path in directory.iterdir()
        if path.is_dir() and path.name not in skipped
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class RepoSide:
    """The stored environment: the env/ folder of the working clone."""

    def __init__(self, env_dir: Path):
        self.env_dir = env_dir

    @property
    def _plugins_path(self) -> Path:
        return self.env_dir / "plugins.json"

    @property
    def _settings_path(self) -> Path:
        return self.env_dir / "settings.json"

    def _load_versioned(self, path: Path) -> dict:
        data = _load_json(path)
        if data.get("format", FORMAT_VERSION) > FORMAT_VERSION:
            raise FormatError(
                f"{path.name} uses format {data['format']}; update the mk96-env plugin"
            )
        return data

    def _plugins(self) -> dict:
        data = self._load_versioned(self._plugins_path)
        return {
            "marketplaces": data.get("marketplaces", {}),
            "plugins": data.get("plugins", {}),
        }

    def _settings(self) -> dict:
        data = self._load_versioned(self._settings_path)
        return {key: data[key] for key in SYNCED_SETTINGS if key in data}

    def keys(self) -> set[str]:
        keys: set[str] = set()
        if (self.env_dir / "CLAUDE.md").is_file():
            keys.add("CLAUDE.md")
        for folder in FILE_FOLDERS:
            keys |= _list_files(self.env_dir, folder)
        for folder in TREE_FOLDERS:
            keys |= _list_trees(self.env_dir, folder)
        plugins = self._plugins()
        keys |= {f"marketplaces/{name}" for name in plugins["marketplaces"]}
        keys |= {f"plugins/{plugin_id}" for plugin_id in plugins["plugins"]}
        keys |= {f"settings/{name}" for name in self._settings()}
        return keys

    def read(self, key: str) -> Payload | None:
        folder, name = _split(key)
        if key == "CLAUDE.md" or folder in FILE_FOLDERS:
            return read_file(self.env_dir / key)
        if folder in TREE_FOLDERS:
            path = self.env_dir / key
            return read_tree(path) if path.is_dir() else None
        if folder in ("marketplaces", "plugins"):
            entries = self._plugins()[folder]
            return _json_payload(entries[name]) if name in entries else None
        settings = self._settings()
        return _json_payload(settings[name]) if name in settings else None

    def write(self, key: str, payload: Payload) -> None:
        folder, name = _split(key)
        if key == "CLAUDE.md" or folder in FILE_FOLDERS:
            write_file(self.env_dir / key, payload)
        elif folder in TREE_FOLDERS:
            write_tree(self.env_dir / key, payload)
        elif folder in ("marketplaces", "plugins"):
            plugins = self._plugins()
            plugins[folder][name] = _json_value(payload)
            _save_json(self._plugins_path, {"format": FORMAT_VERSION, **plugins})
        else:
            settings = self._settings()
            settings[name] = _json_value(payload)
            _save_json(self._settings_path, {"format": FORMAT_VERSION, **settings})

    def delete(self, key: str) -> None:
        folder, name = _split(key)
        path = self.env_dir / key
        if key == "CLAUDE.md" or folder in FILE_FOLDERS:
            path.unlink(missing_ok=True)
        elif folder in TREE_FOLDERS:
            shutil.rmtree(path, ignore_errors=True)
        elif folder in ("marketplaces", "plugins"):
            plugins = self._plugins()
            plugins[folder].pop(name, None)
            _save_json(self._plugins_path, {"format": FORMAT_VERSION, **plugins})
        else:
            settings = self._settings()
            settings.pop(name, None)
            _save_json(self._settings_path, {"format": FORMAT_VERSION, **settings})


class LocalSide:
    """This machine's ~/.claude. Every overwrite or deletion is backed up first."""

    def __init__(self, claude_home: Path, runner: Runner, backup: Backup):
        self.claude_home = claude_home
        self._run = runner
        self._backup = backup

    @property
    def _settings_path(self) -> Path:
        return self.claude_home / "settings.json"

    @property
    def _mods_dir(self) -> Path:
        return self.claude_home / "mods"

    def _settings(self) -> dict:
        return _load_json(self._settings_path)

    def _save_settings(self, settings: dict) -> None:
        self._backup.save(self._settings_path)
        _save_json(self._settings_path, settings)

    def _marketplaces(self) -> dict:
        registry = _load_json(self.claude_home / "plugins" / "known_marketplaces.json")
        return {
            name: entry["source"]
            for name, entry in registry.items()
            if entry.get("source", {}).get("source") in PORTABLE_SOURCE_TYPES
        }

    def _plugins(self) -> dict:
        return self._settings().get("enabledPlugins", {})

    def _claude(self, *args: str) -> None:
        command = ["claude", "plugin", *args]
        result = self._run(command)
        if result.returncode != 0:
            raise CommandError(f"{' '.join(command)} failed: {result.stderr.strip()}")

    def keys(self) -> set[str]:
        keys: set[str] = set()
        if (self.claude_home / "CLAUDE.md").is_file():
            keys.add("CLAUDE.md")
        for folder in FILE_FOLDERS:
            keys |= _list_files(self.claude_home, folder)
        keys |= _list_trees(self.claude_home, "skills", skipped=(ACCOUNT_SKILLS_FOLDER,))
        keys |= _list_trees(self.claude_home, "mods")
        keys |= _list_trees(self.claude_home, "hooks")
        keys |= {f"marketplaces/{name}" for name in self._marketplaces()}
        keys |= {f"plugins/{plugin_id}" for plugin_id in self._plugins()}
        keys |= {f"settings/{name}" for name in _managed_settings(self._settings())}
        return keys

    def read(self, key: str) -> Payload | None:
        folder, name = _split(key)
        if key == "CLAUDE.md" or folder in FILE_FOLDERS:
            return read_file(self.claude_home / key)
        if folder in TREE_FOLDERS:
            path = self.claude_home / key
            return read_tree(path, _excluded_paths(folder)) if path.is_dir() else None
        if folder == "marketplaces":
            sources = self._marketplaces()
            return _json_payload(sources[name]) if name in sources else None
        if folder == "plugins":
            plugins = self._plugins()
            return _json_payload({"enabled": plugins[name]}) if name in plugins else None
        settings = _managed_settings(self._settings())
        return _json_payload(settings[name]) if name in settings else None

    def write(self, key: str, payload: Payload) -> None:
        folder, name = _split(key)
        path = self.claude_home / key
        if key == "CLAUDE.md" or folder in FILE_FOLDERS:
            self._backup.save(path)
            write_file(path, payload)
        elif folder in TREE_FOLDERS:
            self._backup.save(path)
            write_tree(path, payload, _excluded_paths(folder))
        elif folder == "marketplaces":
            self._write_marketplace(name, _json_value(payload))
        elif folder == "plugins":
            self._write_plugin(name, _json_value(payload)["enabled"])
        else:
            settings = self._settings()
            _apply_setting(settings, name, _json_value(payload))
            self._save_settings(settings)

    def delete(self, key: str) -> None:
        folder, name = _split(key)
        path = self.claude_home / key
        if key == "CLAUDE.md" or folder in FILE_FOLDERS:
            self._backup.save(path)
            path.unlink(missing_ok=True)
        elif folder in TREE_FOLDERS:
            self._backup.save(path)
            shutil.rmtree(path, ignore_errors=True)
        elif folder == "marketplaces":
            self._claude("marketplace", "remove", name)
        elif folder == "plugins":
            self._claude("uninstall", name)
        else:
            settings = self._settings()
            _remove_setting(settings, name)
            self._save_settings(settings)

    def _write_marketplace(self, name: str, source: dict) -> None:
        current = self._marketplaces().get(name)
        if current == source:
            return
        if current is not None:
            self._claude("marketplace", "remove", name)
        location = source.get("repo") if source["source"] == "github" else source.get("url")
        self._claude("marketplace", "add", location)

    def _write_plugin(self, plugin_id: str, is_enabled: bool) -> None:
        installed = self._plugins()
        if plugin_id not in installed:
            self._claude("install", plugin_id)
            if not is_enabled:
                self._claude("disable", plugin_id)
        elif installed[plugin_id] != is_enabled:
            self._claude("enable" if is_enabled else "disable", plugin_id)

    def finish(self) -> None:
        """Point CLAUDE_CODE_PLUGIN_DIRS at this machine's mods, keeping foreign entries."""
        settings = self._settings()
        env = settings.get("env", {})
        current = env.get(PLUGIN_DIRS_VARIABLE, "")
        foreign = [
            entry for entry in current.split(os.pathsep)
            if entry and Path(entry).parent != self._mods_dir
        ]
        mods = [str(path) for path in sorted(self._mods_dir.glob("*")) if path.is_dir()]
        # TODO(unverified): Claude Code's separator for this variable on Windows is
        # assumed to be os.pathsep, like PATH; confirm on a Windows machine.
        value = os.pathsep.join(foreign + mods)
        if value == current:
            return
        if value:
            env[PLUGIN_DIRS_VARIABLE] = value
        else:
            env.pop(PLUGIN_DIRS_VARIABLE, None)
        settings["env"] = env
        self._save_settings(settings)
