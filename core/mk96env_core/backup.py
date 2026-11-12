"""Copies of local files taken before the tool overwrites or deletes them."""

import shutil
from pathlib import Path


class Backup:
    """Saves files under one timestamped folder, keeping their path relative to ~/.claude."""

    def __init__(self, folder: Path, claude_home: Path):
        self.folder = folder
        self._claude_home = claude_home
        self._saved: set[Path] = set()

    @property
    def is_used(self) -> bool:
        return bool(self._saved)

    def save(self, path: Path) -> None:
        """Copy a file or directory once per run; later calls for the same path are ignored."""
        if path in self._saved or not path.exists():
            return
        target = self.folder / path.relative_to(self._claude_home)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
        self._saved.add(path)
