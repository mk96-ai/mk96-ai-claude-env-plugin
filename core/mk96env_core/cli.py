"""Command line: `import`, `export`, `where` and `setup`, with exit codes the skills act on."""

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path

from . import config
from .backup import Backup
from .gitops import Git, GitError, PushRejected
from .sides import FormatError, LocalSide, RepoSide, Runner
from .state import State, load_state, save_state
from .summary import CHANGES, Direction, Report, render
from .sync import RESOLUTIONS, Blocked, describe_conflict, run_sync

BACKUP_TIMESTAMP = "%Y%m%d-%H%M%S"
PUSH_ATTEMPTS = 2


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1
    NOT_CONFIGURED = 2
    CONFLICTS = 3
    BLOCKED = 4


@dataclass
class Context:
    claude_home: Path
    config_dir: Path
    runner: Runner


@dataclass
class CommandResult:
    exit_code: ExitCode
    output: str


def run_external(args: list[str]) -> subprocess.CompletedProcess:
    # shutil.which resolves `claude.cmd` on Windows, where a bare name may not run.
    executable = shutil.which(args[0]) or args[0]
    return subprocess.run(
        [executable, *args[1:]], capture_output=True, encoding="utf-8", errors="replace"
    )


def _commit_message(report_results) -> str:
    counts: dict[str, int] = {}
    for result in report_results:
        if result.outcome in CHANGES:
            group = result.key.split("/", 1)[0]
            counts[group] = counts.get(group, 0) + 1
    return "export: " + ", ".join(f"{group} ({count})" for group, count in counts.items())


def _self_update(context: Context) -> list[str]:
    """Update this plugin from its marketplace; return notes for the summary."""
    installed = config.installed_plugin(context.claude_home)
    if installed is None:
        return []
    marketplace, version_before = installed
    for args in (
        ["claude", "plugin", "marketplace", "update", marketplace],
        ["claude", "plugin", "update", f"{config.PLUGIN_NAME}@{marketplace}"],
    ):
        result = context.runner(args)
        if result.returncode != 0:
            return [f"could not check for mk96-env updates: {result.stderr.strip()}"]
    version_after = (config.installed_plugin(context.claude_home) or ("", version_before))[1]
    if version_after != version_before:
        return [f"mk96-env updated {version_before} → {version_after} (restart Claude Code)"]
    return []


def _sync(direction: Direction, context: Context, git: Git, resolutions: dict[str, str]) -> CommandResult:
    backup_folder = context.claude_home / "backups" / "mk96-env" / datetime.now().strftime(BACKUP_TIMESTAMP)
    backup = Backup(backup_folder, context.claude_home)
    local = LocalSide(context.claude_home, context.runner, backup)
    repo = RepoSide(git.clone_dir / "env")
    state_path = config.state_path(context.config_dir, context.claude_home, git.remote_url())
    state = load_state(state_path)

    pushed = None
    for attempt in range(PUSH_ATTEMPTS):
        outcome = run_sync(direction, local, repo, state, resolutions)
        if outcome.conflicts:
            conflicts = [describe_conflict(item) for item in outcome.conflicts]
            return CommandResult(ExitCode.CONFLICTS, json.dumps({"conflicts": conflicts}, indent=2))
        if direction is Direction.IMPORT:
            break
        try:
            pushed = git.commit_and_push(_commit_message(outcome.results))
            break
        except PushRejected:
            if attempt == PUSH_ATTEMPTS - 1:
                git.reset_to_upstream()
                raise
            git.reset_to_upstream()
            git.pull()

    local.finish()
    save_state(state_path, State(items=outcome.state_items, commit=git.head()))
    notes = _self_update(context) if direction is Direction.IMPORT else []
    report = Report(
        direction=direction,
        remote=git.remote_label(),
        results=outcome.results,
        pushed_commit=pushed,
        synced_commit=git.head(),
        backup_folder=str(backup.folder) if backup.is_used else None,
        notes=notes,
    )
    return CommandResult(ExitCode.OK, render(report))


def execute(command: str, context: Context, resolutions: dict[str, str]) -> CommandResult:
    """Run `import` or `export`. Never raises for expected failures: they become exit codes."""
    clone = config.read_clone_path(context.config_dir)
    if clone is None:
        return _not_configured()
    git = Git(clone)
    try:
        git.ensure_ready()
        git.pull()
        return _sync(Direction(command), context, git, resolutions)
    except Blocked as error:
        return CommandResult(ExitCode.BLOCKED, str(error))
    except (GitError, FormatError) as error:
        return CommandResult(ExitCode.ERROR, str(error))


def _not_configured() -> CommandResult:
    return CommandResult(
        ExitCode.NOT_CONFIGURED,
        f"mk96-env has no sync clone on this machine yet. Suggested location: {config.DEFAULT_CLONE}",
    )


def where(context: Context) -> CommandResult:
    """Show the remembered sync clone and its repository, so the skills can confirm them."""
    clone = config.read_clone_path(context.config_dir)
    if clone is None:
        return _not_configured()
    try:
        repository = Git(clone).remote_label()
    except GitError as error:
        return CommandResult(ExitCode.ERROR, str(error))
    return CommandResult(ExitCode.OK, f"clone: {clone}\nrepository: {repository}")


def setup(context: Context, clone: Path, url: str | None) -> CommandResult:
    """Use an existing clone at `clone`, or clone the environment repository `url` there.

    The environment lives in its own repository, separate from the plugin's code.
    """
    if not (clone / ".git").exists():
        if url is None:
            return CommandResult(
                ExitCode.ERROR,
                f"{clone} is not a clone yet; pass --url with your environment repository.",
            )
        if clone.exists() and any(clone.iterdir()):
            return CommandResult(ExitCode.ERROR, f"{clone} exists and is not empty.")
        result = run_external(["git", "clone", "-q", url, str(clone)])
        if result.returncode != 0:
            return CommandResult(ExitCode.ERROR, f"git clone failed: {result.stderr.strip()}")
    config.write_clone_path(context.config_dir, clone)
    return CommandResult(ExitCode.OK, f"mk96-env will sync through {clone}")


def _parse_resolutions(values: list[str]) -> dict[str, str]:
    resolutions = {}
    for value in values:
        key, _, choice = value.rpartition("=")
        if not key or choice not in RESOLUTIONS:
            raise argparse.ArgumentTypeError(f"invalid --resolve {value!r}; use KEY=local|repo|skip")
        resolutions[key] = choice
    return resolutions


class _ArgumentParser(argparse.ArgumentParser):
    """argparse exits with 2 on bad arguments, which the skills read as NOT_CONFIGURED."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        sys.exit(ExitCode.ERROR)


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(prog="mk96env", description="Sync a Claude Code environment.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "export"):
        sub = commands.add_parser(name)
        sub.add_argument("--resolve", action="append", default=[], metavar="KEY=local|repo|skip")
    commands.add_parser("where")
    setup_parser = commands.add_parser("setup")
    setup_parser.add_argument("--clone", required=True, type=Path)
    setup_parser.add_argument("--url")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    context = Context(config.default_claude_home(), config.default_config_dir(), run_external)
    if args.command == "setup":
        result = setup(context, args.clone.expanduser().resolve(), args.url)
    elif args.command == "where":
        result = where(context)
    else:
        try:
            resolutions = _parse_resolutions(args.resolve)
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))
        result = execute(args.command, context, resolutions)
    print(result.output)
    return int(result.exit_code)
