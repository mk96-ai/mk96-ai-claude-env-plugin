"""Where things live on this machine, and how the plugin was installed."""

import hashlib
import json
import os
from pathlib import Path

PLUGIN_NAME = "mk96-env"
DEFAULT_CLONE = Path.home() / ".mk96-env" / "repo"


def default_claude_home() -> Path:
    """~/.claude, or the folder Claude Code was pointed at with CLAUDE_CONFIG_DIR."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured) if configured else Path.home() / ".claude"


def default_config_dir() -> Path:
    return Path.home() / ".config" / "mk96-env"


def state_path(config_dir: Path, claude_home: Path, remote_url: str) -> Path:
    """One state file per (Claude folder, repository) pair.

    A second Claude profile or a fork never reuses another pair's history, so
    it gets the first-sync protections instead of seeing everything as removed.
    """
    pair = f"{claude_home.resolve()}\n{remote_url}".encode("utf-8")
    return config_dir / "state" / f"{hashlib.sha256(pair).hexdigest()[:16]}.json"


def read_clone_path(config_dir: Path) -> Path | None:
    path_file = config_dir / "repo-path"
    if not path_file.is_file():
        return None
    clone = Path(path_file.read_text(encoding="utf-8").strip())
    return clone if (clone / ".git").exists() else None


def write_clone_path(config_dir: Path, clone: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "repo-path").write_text(str(clone) + "\n", encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def installed_plugin(claude_home: Path) -> tuple[str, str] | None:
    """Return (marketplace name, version) of this plugin's installation, if installed from one."""
    registry = _load(claude_home / "plugins" / "installed_plugins.json")
    for plugin_id, installs in registry.get("plugins", {}).items():
        name, _, marketplace = plugin_id.partition("@")
        if name == PLUGIN_NAME and installs:
            return marketplace, installs[0].get("version", "")
    return None
