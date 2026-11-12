"""Result of a sync run and its schematic text summary."""

from dataclasses import dataclass, field
from enum import Enum


class Direction(Enum):
    IMPORT = "import"
    EXPORT = "export"


class Outcome(Enum):
    ADDED = "added"
    UPDATED = "updated"
    REMOVED = "removed"
    UNCHANGED = "unchanged"
    PENDING = "pending"
    SKIPPED = "conflict skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ItemResult:
    key: str
    outcome: Outcome
    detail: str = ""


@dataclass
class Report:
    direction: Direction
    remote: str
    results: list[ItemResult]
    pushed_commit: str | None = None
    synced_commit: str | None = None
    backup_folder: str | None = None
    notes: list[str] = field(default_factory=list)


GROUPS = (
    "CLAUDE.md", "rules", "commands", "skills", "agents", "hooks",
    "mods", "marketplaces", "plugins", "settings",
)
# Groups whose changes only take effect after Claude Code restarts.
RESTART_GROUPS = ("mods", "marketplaces", "plugins", "settings")
SYMBOLS = {
    Outcome.ADDED: "+",
    Outcome.UPDATED: "✎",
    Outcome.REMOVED: "−",
    Outcome.PENDING: "!",
    Outcome.SKIPPED: "!",
    Outcome.FAILED: "✗",
    Outcome.UNCHANGED: "=",
}
CHANGES = (Outcome.ADDED, Outcome.UPDATED, Outcome.REMOVED)
LABEL_WIDTH = 16
PART_SEPARATOR = "   "
MAX_DETAIL_ENTRIES = 6


def _group_of(key: str) -> str:
    return key.split("/", 1)[0]


def _name_of(key: str) -> str:
    return key.split("/", 1)[-1]


def _outcome_label(outcome: Outcome, direction: Direction) -> str:
    if outcome is Outcome.PENDING:
        other = Direction.EXPORT if direction is Direction.IMPORT else Direction.IMPORT
        return f"pending {other.value}"
    return outcome.value


def _group_line(group: str, results: list[ItemResult], direction: Direction) -> str:
    label = group.ljust(LABEL_WIDTH)
    if not results:
        return f"  {label} = none"
    parts = []
    for outcome in SYMBOLS:
        count = sum(1 for result in results if result.outcome is outcome)
        if count:
            parts.append(f"{SYMBOLS[outcome]} {count} {_outcome_label(outcome, direction)}")
    return f"  {label} {PART_SEPARATOR.join(parts)}"


def _detail_line(group: str, results: list[ItemResult]) -> str | None:
    entries = []
    for result in results:
        if result.outcome is Outcome.UNCHANGED:
            continue
        entry = f"{SYMBOLS[result.outcome]} {_name_of(result.key)}"
        entries.append(f"{entry} ({result.detail})" if result.detail else entry)
    if not entries:
        return None
    hidden = len(entries) - MAX_DETAIL_ENTRIES
    shown = ", ".join(entries[:MAX_DETAIL_ENTRIES])
    return f"    {group}: {shown}" + (f", … +{hidden} more" if hidden > 0 else "")


def _needs_restart(report: Report) -> bool:
    return report.direction is Direction.IMPORT and any(
        _group_of(result.key) in RESTART_GROUPS and result.outcome in CHANGES
        for result in report.results
    )


def render(report: Report) -> str:
    arrow = "→" if report.direction is Direction.EXPORT else "←"
    lines = [f"mk96-env {report.direction.value} {arrow} {report.remote}"]
    grouped = {group: [] for group in GROUPS}
    for result in report.results:
        grouped[_group_of(result.key)].append(result)

    lines += [_group_line(group, results, report.direction) for group, results in grouped.items()]
    details = [_detail_line(group, results) for group, results in grouped.items()]
    lines += [line for line in details if line]

    if report.pushed_commit:
        lines.append(f"  ✔ pushed ({report.pushed_commit})")
    elif report.synced_commit:
        lines.append(f"  ✔ in sync with {report.synced_commit}")
    if report.backup_folder:
        lines.append(f"  backups: {report.backup_folder}")
    if _needs_restart(report):
        lines.append("  ↻ restart Claude Code to apply plugin, mod and settings changes")
    lines += [f"  • {note}" for note in report.notes]
    return "\n".join(lines)
