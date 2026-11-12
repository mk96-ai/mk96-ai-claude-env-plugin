import unittest

from mk96env_core.summary import Direction, ItemResult, Outcome, Report, render


def report(direction, results, **extra):
    return Report(direction=direction, remote="owner/repo", results=results, **extra)


class RenderTest(unittest.TestCase):
    def test_export_summary_lists_each_group_with_symbols_and_the_pushed_commit(self):
        text = render(report(
            Direction.EXPORT,
            [
                ItemResult("CLAUDE.md", Outcome.UPDATED),
                ItemResult("commands/git_new.md", Outcome.ADDED),
                ItemResult("commands/git_old.md", Outcome.REMOVED),
                ItemResult("commands/git_log.md", Outcome.UNCHANGED),
                ItemResult("settings/model", Outcome.UPDATED, detail='"sonnet" → "opus"'),
            ],
            pushed_commit="a1b2c3d",
        ))
        lines = text.splitlines()
        self.assertEqual(lines[0], "mk96-env export → owner/repo")
        self.assertIn("  CLAUDE.md        ✎ 1 updated", lines)
        self.assertIn("  commands         + 1 added   − 1 removed   = 1 unchanged", lines)
        self.assertIn("  skills           = none", lines)
        self.assertIn("  settings         ✎ 1 updated", lines)
        self.assertIn('    settings: ✎ model ("sonnet" → "opus")', lines)
        self.assertIn("  ✔ pushed (a1b2c3d)", lines)

    def test_rules_and_hooks_have_their_own_groups(self):
        text = render(report(
            Direction.EXPORT,
            [
                ItemResult("rules/java.md", Outcome.ADDED),
                ItemResult("hooks/git-guard", Outcome.ADDED),
            ],
        ))
        lines = text.splitlines()
        self.assertIn("  rules            + 1 added", lines)
        self.assertIn("  hooks            + 1 added", lines)

    def test_items_changed_on_the_other_side_are_shown_as_pending(self):
        text = render(report(
            Direction.IMPORT,
            [ItemResult("commands/mine.md", Outcome.PENDING)],
        ))
        self.assertIn("  commands         ! 1 pending export", text.splitlines())

    def test_import_that_touched_plugins_asks_for_a_restart(self):
        text = render(report(
            Direction.IMPORT,
            [ItemResult("plugins/tool@market", Outcome.ADDED)],
        ))
        self.assertIn("restart Claude Code", text)

    def test_long_detail_lists_are_shortened(self):
        results = [ItemResult(f"commands/c{index}.md", Outcome.ADDED) for index in range(48)]
        text = render(report(Direction.IMPORT, results))
        detail = next(line for line in text.splitlines() if line.startswith("    commands:"))
        self.assertTrue(detail.endswith("… +42 more"), detail)

    def test_failures_and_backups_are_reported(self):
        text = render(report(
            Direction.IMPORT,
            [ItemResult("plugins/tool@market", Outcome.FAILED, detail="network down")],
            backup_folder="/home/me/.claude/backups/mk96-env/20261112-101010",
        ))
        self.assertIn("  plugins          ✗ 1 failed", text.splitlines())
        self.assertIn("    plugins: ✗ tool@market (network down)", text.splitlines())
        self.assertIn("  backups: /home/me/.claude/backups/mk96-env/20261112-101010", text.splitlines())


if __name__ == "__main__":
    unittest.main()
