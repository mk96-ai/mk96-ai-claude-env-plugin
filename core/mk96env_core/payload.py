"""Content of a synced item as a mapping of relative path to bytes.

A single file uses the key SINGLE_FILE; a directory uses its relative POSIX paths.
"""

import hashlib
import os
from pathlib import Path

Payload = dict[str, bytes]

SINGLE_FILE = ""
# Never part of an item: nested repositories and caches differ on every machine.
IGNORED_NAMES = frozenset({".git", "__pycache__"})
IGNORED_SUFFIXES = (".pyc",)
SHEBANG = b"#!"
EXECUTABLE_BITS = 0o111


def normalize(data: bytes) -> bytes:
    """Return text with LF line endings so Windows and Linux copies compare equal.

    Binary content (not valid UTF-8) is returned untouched.
    """
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return data.replace(b"\r\n", b"\n")


def payload_hash(payload: Payload) -> str:
    """Stable sha256 of a payload, independent of line endings and path order."""
    digest = hashlib.sha256()
    for relative_path in sorted(payload):
        digest.update(relative_path.encode("utf-8") + b"\0")
        digest.update(normalize(payload[relative_path]) + b"\0")
    return digest.hexdigest()


def read_file(path: Path) -> Payload | None:
    return {SINGLE_FILE: normalize(path.read_bytes())} if path.is_file() else None


def write_file(path: Path, payload: Payload) -> None:
    _write_with_mode(path, payload[SINGLE_FILE])


def _is_excluded(relative_path: str, excluded: tuple[str, ...]) -> bool:
    parts = relative_path.split("/")
    if IGNORED_NAMES.intersection(parts) or relative_path.endswith(IGNORED_SUFFIXES):
        return True
    return any(
        relative_path == prefix or relative_path.startswith(prefix + "/")
        for prefix in excluded
    )


def _tree_files(root: Path, excluded: tuple[str, ...]) -> dict[str, Path]:
    files = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        if path.is_file() and not _is_excluded(relative_path, excluded):
            files[relative_path] = path
    return files


def read_tree(root: Path, excluded: tuple[str, ...] = ()) -> Payload:
    """Read every file under root, skipping the excluded relative folders."""
    return {
        relative_path: normalize(path.read_bytes())
        for relative_path, path in _tree_files(root, excluded).items()
    }


def _write_with_mode(target: Path, data: bytes) -> None:
    # The payload carries no file modes: keep the existing mode, and make new
    # scripts (shebang) executable so skills' helper scripts keep working.
    is_new = not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if is_new and data.startswith(SHEBANG) and os.name != "nt":
        target.chmod(target.stat().st_mode | EXECUTABLE_BITS)


def _remove_empty_folders(root: Path) -> None:
    for folder in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()


def write_tree(root: Path, payload: Payload, excluded: tuple[str, ...] = ()) -> None:
    """Make the files of root match the payload, leaving excluded and ignored paths untouched."""
    if root.exists():
        for relative_path, path in _tree_files(root, excluded).items():
            if relative_path not in payload:
                path.unlink()
        _remove_empty_folders(root)
    for relative_path, data in payload.items():
        _write_with_mode(root / relative_path, data)
