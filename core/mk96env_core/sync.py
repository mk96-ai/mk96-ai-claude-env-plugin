"""The sync engine: compare both sides item by item and apply what the direction allows."""

import difflib
from dataclasses import dataclass

from .payload import SINGLE_FILE, Payload, payload_hash
from .secrets import Finding, find_secrets
from .sides import CommandError, LocalSide, RepoSide
from .state import State
from .status import Status, classify
from .summary import GROUPS, Direction, ItemResult, Outcome

KEEP_LOCAL, KEEP_REPO, SKIP = "local", "repo", "skip"
RESOLUTIONS = (KEEP_LOCAL, KEEP_REPO, SKIP)
MAX_DIFF_LINES = 80
NEVER_IMPORTED_MESSAGE = (
    "This machine has never imported this environment, and the repository already holds one. "
    "Run import first so the stored environment is not overwritten."
)

HERE = {Status.ADDED_HERE, Status.CHANGED_HERE, Status.REMOVED_HERE}
ELSEWHERE = {Status.ADDED_ELSEWHERE, Status.CHANGED_ELSEWHERE, Status.REMOVED_ELSEWHERE}


class Blocked(Exception):
    """The sync must not run; nothing was changed."""


class SecretsFound(Blocked):
    def __init__(self, findings: list[Finding]):
        self.findings = findings
        lines = [f"  {f.key}{'/' + f.path if f.path else ''}:{f.line}  {f.masked}" for f in findings]
        super().__init__("Possible secrets found; nothing was exported:\n" + "\n".join(lines))


@dataclass
class Item:
    key: str
    local: Payload | None
    repo: Payload | None
    status: Status


@dataclass
class SyncOutcome:
    results: list[ItemResult]
    conflicts: list[Item]
    state_items: dict[str, str]


def _hash(payload: Payload | None) -> str | None:
    return None if payload is None else payload_hash(payload)


def _sort_key(key: str) -> tuple[int, str]:
    return GROUPS.index(key.split("/", 1)[0]), key


def _compare(local: LocalSide, repo: RepoSide, state: State | None) -> list[Item]:
    base = state.items if state else {}
    items = []
    for key in sorted(local.keys() | repo.keys(), key=_sort_key):
        local_payload, repo_payload = local.read(key), repo.read(key)
        status = classify(
            _hash(local_payload), _hash(repo_payload), base.get(key), is_first_sync=state is None
        )
        items.append(Item(key, local_payload, repo_payload, status))
    return items


def _target(item: Item, direction: Direction, resolution: str | None) -> str | None:
    """Which side receives the other side's version: 'local', 'repo' or None."""
    if item.status is Status.CONFLICT:
        if resolution == KEEP_REPO:
            return "local"
        if resolution == KEEP_LOCAL and direction is Direction.EXPORT:
            return "repo"
        return None
    if direction is Direction.IMPORT and item.status in ELSEWHERE:
        return "local"
    if direction is Direction.EXPORT and item.status in HERE:
        return "repo"
    return None


def _idle_outcome(item: Item, resolution: str | None) -> Outcome:
    if item.status is Status.UNCHANGED:
        return Outcome.UNCHANGED
    if item.status is Status.CONFLICT and resolution in (SKIP, None):
        return Outcome.SKIPPED
    return Outcome.PENDING


def _setting_value(payload: Payload | None) -> str:
    return "unset" if payload is None else payload[SINGLE_FILE].decode("utf-8")


def _settings_detail(key: str, before: Payload | None, after: Payload | None) -> str:
    if not key.startswith("settings/"):
        return ""
    return f"{_setting_value(before)} → {_setting_value(after)}"


def _apply(item: Item, target: str, local: LocalSide, repo: RepoSide) -> ItemResult:
    side, source, current = (
        (local, item.repo, item.local) if target == "local" else (repo, item.local, item.repo)
    )
    try:
        if source is None:
            side.delete(item.key)
        else:
            side.write(item.key, source)
    except (CommandError, OSError) as error:
        return ItemResult(item.key, Outcome.FAILED, str(error))
    if source is None:
        outcome = Outcome.REMOVED
    else:
        outcome = Outcome.ADDED if current is None else Outcome.UPDATED
    return ItemResult(item.key, outcome, _settings_detail(item.key, current, source))


def _new_state(
    items: list[Item], local: LocalSide, repo: RepoSide, state: State | None,
    direction: Direction, resolutions: dict[str, str],
) -> dict[str, str]:
    """Hashes both sides agree on; items still pending keep their previous base.

    Keys absent on both sides are dropped, so a later restore is seen as new.
    """
    old_items = state.items if state else {}
    new_items: dict[str, str] = {}
    for item in items:
        local_hash, repo_hash = _hash(local.read(item.key)), _hash(repo.read(item.key))
        kept_local_on_import = (
            direction is Direction.IMPORT
            and item.status is Status.CONFLICT
            and resolutions.get(item.key) == KEEP_LOCAL
        )
        if kept_local_on_import:
            # Recording the repository version as the base makes the next export
            # see this machine's version as "changed here" and push it.
            agreed = repo_hash
        elif local_hash == repo_hash:
            agreed = local_hash
        else:
            agreed = old_items.get(item.key)  # still pending on one side
        if agreed is not None:
            new_items[item.key] = agreed
    return new_items


def run_sync(
    direction: Direction, local: LocalSide, repo: RepoSide,
    state: State | None, resolutions: dict[str, str],
) -> SyncOutcome:
    """Sync every managed item in one direction.

    Raises Blocked (or SecretsFound) before changing anything when the run is
    not allowed. Returns unresolved conflicts without changing anything.
    """
    items = _compare(local, repo, state)
    if direction is Direction.EXPORT and state is None and repo.keys():
        raise Blocked(NEVER_IMPORTED_MESSAGE)

    unresolved = [
        item for item in items
        if item.status is Status.CONFLICT and resolutions.get(item.key) not in RESOLUTIONS
    ]
    if unresolved:
        return SyncOutcome(results=[], conflicts=unresolved, state_items={})

    targets = {item.key: _target(item, direction, resolutions.get(item.key)) for item in items}
    findings = [
        finding
        for item in items
        if targets[item.key] == "repo" and item.local is not None
        for finding in find_secrets(item.key, item.local)
    ]
    if findings:
        raise SecretsFound(findings)

    results = []
    for item in items:
        target = targets[item.key]
        if target is None:
            results.append(ItemResult(item.key, _idle_outcome(item, resolutions.get(item.key))))
        else:
            results.append(_apply(item, target, local, repo))
    state_items = _new_state(items, local, repo, state, direction, resolutions)
    return SyncOutcome(results=results, conflicts=[], state_items=state_items)


def describe_conflict(item: Item) -> dict:
    """A conflict as data the skill can show: the key and a diff from this machine to the repository."""
    local, repo = item.local or {}, item.repo or {}
    diff_lines: list[str] = []
    for path in sorted(set(local) | set(repo)):
        before = local.get(path, b"").decode("utf-8", errors="replace").splitlines()
        after = repo.get(path, b"").decode("utf-8", errors="replace").splitlines()
        name = path or item.key
        diff_lines += difflib.unified_diff(
            before, after, f"this machine/{name}", f"repository/{name}", lineterm=""
        )
    truncated = len(diff_lines) > MAX_DIFF_LINES
    return {
        "key": item.key,
        "exists_here": item.local is not None,
        "exists_in_repository": item.repo is not None,
        "diff": "\n".join(diff_lines[:MAX_DIFF_LINES]) + ("\n…" if truncated else ""),
    }
