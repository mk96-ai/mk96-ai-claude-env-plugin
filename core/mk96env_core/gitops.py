"""Git operations on the sync clone (the working copy only this tool touches)."""

import subprocess
from pathlib import Path

ENV_FOLDER = "env"


class GitError(Exception):
    """A git command failed or the clone is not in a state the tool can sync from."""


class PushRejected(GitError):
    """The remote moved on while this run was preparing its commit."""


class Git:
    def __init__(self, clone_dir: Path):
        self.clone_dir = clone_dir

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *args], cwd=self.clone_dir, capture_output=True,
            encoding="utf-8", errors="replace",
        )
        if check and result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result

    def _output(self, *args: str) -> str:
        return self._git(*args).stdout.strip()

    def ensure_ready(self) -> None:
        """Refuse to sync from a clone with local work: it must mirror its remote branch."""
        if self._git("var", "GIT_COMMITTER_IDENT", check=False).returncode != 0:
            raise GitError(
                "git has no user identity; set it with `git config --global user.name` "
                "and `git config --global user.email` (or locally in the sync clone)"
            )
        branch = self._output("rev-parse", "--abbrev-ref", "HEAD")
        default = self._git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
        if default.returncode == 0 and default.stdout.strip() != f"origin/{branch}":
            raise GitError(
                f"the sync clone {self.clone_dir} is on branch '{branch}', "
                f"not on the default branch ({default.stdout.strip()})"
            )
        if self._output("status", "--porcelain"):
            raise GitError(f"the sync clone {self.clone_dir} has uncommitted changes")
        self._git("fetch", "-q")
        if int(self._output("rev-list", "--count", "@{u}..HEAD")):
            raise GitError(f"the sync clone {self.clone_dir} has local commits that were not pushed")

    def pull(self) -> None:
        self._git("pull", "-q", "--ff-only")

    def head(self) -> str:
        return self._output("rev-parse", "--short", "HEAD")

    def remote_url(self) -> str:
        return self._output("remote", "get-url", "origin")

    def remote_label(self) -> str:
        return self.remote_url().removeprefix("https://github.com/").removesuffix(".git")

    def discard_env_changes(self) -> None:
        """Undo what this run wrote under env/, so the clone is clean for the next run."""
        self._git("reset", "-q", "--", ENV_FOLDER)
        self._git("checkout", "-q", "--", ENV_FOLDER, check=False)
        untracked = self._output("ls-files", "--others", "--exclude-standard", "--", ENV_FOLDER)
        for relative_path in untracked.splitlines():
            (self.clone_dir / relative_path).unlink(missing_ok=True)

    def commit_and_push(self, message: str) -> str | None:
        """Commit everything under env/ and push it; return the commit, or None if nothing changed."""
        self._git("add", "-A", ENV_FOLDER)
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return None
        commit = self._git("commit", "-q", "-m", message, check=False)
        if commit.returncode != 0:
            self.discard_env_changes()
            raise GitError(f"git commit failed: {(commit.stderr or commit.stdout).strip()}")
        push = self._git("push", "-q", check=False)
        if push.returncode != 0:
            raise PushRejected(f"git push was rejected: {push.stderr.strip()}")
        return self.head()

    def reset_to_upstream(self) -> None:
        """Drop the tool's own unpushed commit; its content is rebuilt from ~/.claude on retry."""
        self._git("reset", "-q", "--keep", "@{u}")
