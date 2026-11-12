---
name: export
description: Store this machine's Claude Code environment (CLAUDE.md, rules, commands, skills, agents, hooks, mods, plugins, preferences and deny rules) in the user's environment repository and push it. Run only when the user invokes /mk96-env:export.
disable-model-invocation: true
---

# Export this machine's environment

Everything is done by the script; never copy or edit files in `~/.claude` or in the sync clone by hand.

`MK96ENV` = `python3 "<base directory of this skill>/../../core/mk96env.py"` (the base directory is shown at the top of these instructions). If `python3` is not found, use `python`. Requires Python 3.10+ and git with push access to the environment repository.

Running this skill is the user's request to commit and push: the only question is where (step 0), never whether.

## Flow

0. Run `$MK96ENV where`. On exit 0 ask one question: "Export to <repository> (clone at <clone>)?" with the options "Yes" and "Change". On "Change" ask whether the environment is a **remote repository** (then ask its URL and the folder to clone it into, any name) or a **local folder** that is already a clone (then ask its path), run `$MK96ENV setup --clone <path> [--url <url>]` and continue. On exit 2 go straight to step 1. The location is remembered for next time.
1. Run `$MK96ENV export` and act on its exit code.
2. **Exit 0** — show the output exactly as printed, inside a code block, and nothing else. Items marked `pending import` changed on another machine: suggest `/mk96-env:import` in one sentence.
3. **Exit 2 (no sync clone on this machine)** — ask whether the environment is a remote repository or a local folder that is already a clone. Local folder: ask its path. Remote repository: ask where to clone it, offering the suggested location from the output, and the URL of the user's **environment repository** (never this plugin's repository). Run `$MK96ENV setup --clone <path> [--url <url>]` and, if it succeeds, go back to step 1. The tool refuses to sync while that clone has local changes or is on another branch.
4. **Exit 3 (conflicts)** — the output is JSON: `{"conflicts": [{"key", "exists_here", "exists_in_repository", "diff"}]}`. These items changed both on this machine and in the repository since the last sync. For each one, show its key and diff, then ask: "Keep this machine's version", "Keep the repository's version" or "Skip for now" (several conflicts can go in one AskUserQuestion call, at most 4 per call). Then rerun with every answer: `$MK96ENV export --resolve <key>=local|repo|skip ...`.
5. **Exit 4 (blocked)** — show the message. If it lists possible secrets, tell the user which files and lines to clean (never repeat the masked values in full) and stop; never bypass the check. If this machine has never imported, suggest `/mk96-env:import` first.
6. **Exit 1 (error)** — show the error, explain the likely cause (for example the push was rejected twice, or the sync clone has local changes), and stop. Never fix the sync clone with `git reset`, `git clean` or force operations.

## Rules

- Everything is synced; never ask the user to pick items.
- Commits are made only by the script, with no AI attribution lines.
