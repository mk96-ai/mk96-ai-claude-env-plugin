"""Three-way comparison of one item: this machine, the repository and the last sync."""

from enum import Enum


class Status(Enum):
    UNCHANGED = "unchanged"
    ADDED_HERE = "added here"
    ADDED_ELSEWHERE = "added elsewhere"
    CHANGED_HERE = "changed here"
    CHANGED_ELSEWHERE = "changed elsewhere"
    REMOVED_HERE = "removed here"
    REMOVED_ELSEWHERE = "removed elsewhere"
    CONFLICT = "conflict"


def classify(
    local: str | None, repo: str | None, base: str | None, is_first_sync: bool
) -> Status:
    """Classify an item from its content hashes (None means the item is absent).

    `base` is the hash recorded at the last sync of this machine. On the first
    sync there is no base, and absences never count as removals: the first
    sync only adds, and differing items are conflicts so the user chooses
    (a machine that switches repository must not lose its own versions).
    """
    if local == repo:
        return Status.UNCHANGED
    if is_first_sync:
        if repo is None:
            return Status.ADDED_HERE
        if local is None:
            return Status.ADDED_ELSEWHERE
        return Status.CONFLICT
    if local == base:
        if base is None:
            return Status.ADDED_ELSEWHERE
        return Status.REMOVED_ELSEWHERE if repo is None else Status.CHANGED_ELSEWHERE
    if repo == base:
        if base is None:
            return Status.ADDED_HERE
        return Status.REMOVED_HERE if local is None else Status.CHANGED_HERE
    return Status.CONFLICT
