"""Per-machine record of the last sync: the hash of every item and the repository commit."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .sides import FORMAT_VERSION, FormatError


@dataclass
class State:
    items: dict[str, str] = field(default_factory=dict)
    commit: str | None = None


def load_state(path: Path) -> State | None:
    """Return the saved state, or None when this machine has never synced."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format", FORMAT_VERSION) > FORMAT_VERSION:
        raise FormatError(f"{path} uses format {data['format']}; update the mk96-env plugin")
    return State(items=data.get("items", {}), commit=data.get("commit"))


def save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": FORMAT_VERSION, "commit": state.commit, "items": state.items}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
