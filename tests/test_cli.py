import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mk96env_core import config
from mk96env_core.cli import Context, ExitCode, main, setup, where


class ArgumentsTest(unittest.TestCase):
    def test_invalid_arguments_are_an_error_not_a_missing_configuration(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["import", "--resolve", "CLAUDE.md=mine"])
        self.assertEqual(raised.exception.code, ExitCode.ERROR)


class SetupTest(unittest.TestCase):
    """The environment lives in its own repository, never in the plugin's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.context = Context(self.root / ".claude", self.root / "config", runner=None)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_new_clone_needs_the_environment_repository_url(self):
        clone_ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("mk96env_core.cli.run_external", return_value=clone_ok) as run:
            result = setup(self.context, self.root / "env-clone", url=None)
        run.assert_not_called()
        self.assertEqual(result.exit_code, ExitCode.ERROR)
        self.assertIn("--url", result.output)
        self.assertIsNone(config.read_clone_path(self.context.config_dir))

    def test_an_existing_clone_is_used_without_url(self):
        clone = self.root / "env-clone"
        (clone / ".git").mkdir(parents=True)
        result = setup(self.context, clone, url=None)
        self.assertEqual(result.exit_code, ExitCode.OK)
        self.assertEqual(config.read_clone_path(self.context.config_dir), clone)


class WhereTest(unittest.TestCase):
    """Import and export confirm the remembered location before syncing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.context = Context(self.root / ".claude", self.root / "config", runner=None)

    def tearDown(self):
        self._tmp.cleanup()

    def test_without_a_remembered_clone_it_is_not_configured(self):
        result = where(self.context)
        self.assertEqual(result.exit_code, ExitCode.NOT_CONFIGURED)

    def test_shows_the_remembered_clone_and_its_repository(self):
        clone = self.root / "my-env"
        clone.mkdir()
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        subprocess.run(
            ["git", "-C", str(clone), "remote", "add", "origin", "https://github.com/me/my-env.git"],
            check=True,
        )
        config.write_clone_path(self.context.config_dir, clone)

        result = where(self.context)

        self.assertEqual(result.exit_code, ExitCode.OK)
        self.assertEqual(result.output, f"clone: {clone}\nrepository: me/my-env")


if __name__ == "__main__":
    unittest.main()
