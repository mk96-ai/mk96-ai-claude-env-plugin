---
name: import
description: Bring the Claude Code environment stored in the user's environment repository into this machine (CLAUDE.md, rules, commands, skills, agents, hooks, mods, plugins, preferences and deny rules). Use when the user wants to import, pull, install, restore or sync their Claude environment or setup on this machine.
---

# Import the stored environment

Everything is done by the script; never copy or edit files in `~/.claude` or in the sync clone by hand.

`MK96ENV` = `python3 "<base directory of this skill>/../../core/mk96env.py"` (the base directory is shown at the top of these instructions). If `python3` is not found, use `python`. Requires Python 3.10+ and git.

## Flow

0. Run `$MK96ENV where`. On exit 0 ask one question: "Import from <repository> (clone at <clone>)?" with the options "Yes" and "Change". On "Change" ask whether the environment is a **remote repository** (then ask its URL and the folder to clone it into, any name) or a **local folder** that is already a clone (then ask its path), run `$MK96ENV setup --clone <path> [--url <url>]` and continue. On exit 2 go straight to step 1. The location is remembered for next time.
1. Run `$MK96ENV import` and act on its exit code.
2. **Exit 0** — show the output exactly as printed, inside a code block. Add nothing but, if it contains a `restart Claude Code` line, one short sentence reminding the user to restart.
3. **Exit 2 (no sync clone on this machine)** — ask whether the environment is a remote repository or a local folder that is already a clone. Local folder: ask its path. Remote repository: ask where to clone it, offering the suggested location from the output, and the URL of the user's **environment repository** (never this plugin's repository). Run `$MK96ENV setup --clone <path> [--url <url>]` and, if it succeeds, go back to step 1. The tool refuses to sync while that clone has local changes or is on another branch.
4. **Exit 3 (conflicts)** — the output is JSON: `{"conflicts": [{"key", "exists_here", "exists_in_repository", "diff"}]}`. These items changed both on this machine and in the repository since the last sync. For each one, show its key and diff, then ask: "Keep this machine's version", "Keep the repository's version" or "Skip for now" (several conflicts can go in one AskUserQuestion call, at most 4 per call). Then rerun with every answer: `$MK96ENV import --resolve <key>=local|repo|skip ...`. Keeping this machine's version means it will be uploaded on the next export.
5. **Exit 4 (blocked)** — show the message and explain it in one or two sentences. Do not retry or work around it.
6. **Exit 1 (error)** — show the error, explain the likely cause (for example the sync clone has local changes or is on another branch), and stop. Never fix the sync clone with `git reset`, `git clean` or force operations.

## Rules

- Everything is synced; never ask the user to pick items.
- Never commit or push from this skill.
