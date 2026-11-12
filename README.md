# mk96-ai-claude-env-plugin

Claude Code plugin (`mk96-env`) that makes a Claude Code environment portable. This repository holds only the tool; the environment itself lives in its own **environment repository** (an `env/` folder), for example [mk96-ai/mk96-ai-claude-env](https://github.com/mk96-ai/mk96-ai-claude-env), and is kept in sync across machines in both directions.

| Command | What it does |
|---|---|
| `/mk96-env:import` | Brings the stored environment into this machine's `~/.claude` |
| `/mk96-env:export` | Stores this machine's environment in the environment repository and pushes it |

Both always sync **everything** and end with a short summary:

```
mk96-env export → mk96-ai/mk96-ai-claude-env
  CLAUDE.md        ✎ 1 updated
  rules            = 7 unchanged
  commands         + 2 added   − 1 removed   = 47 unchanged
  skills           = none
  agents           = none
  hooks            = 1 unchanged
  mods             = 1 unchanged
  marketplaces     = 2 unchanged
  plugins          = 8 unchanged
  settings         ✎ 1 updated
    CLAUDE.md: ✎ CLAUDE.md
    commands: + git_tag.md, + git_rebase.md, − git_old.md
    settings: ✎ model ("sonnet" → "opus")
  ✔ pushed (a1b2c3d)
```

## Install

```
claude plugin marketplace add mk96-ai/mk96-ai-claude-env-plugin
claude plugin install mk96-env@mk96-ai-claude-env-plugin
```

Then run `/mk96-env:import`. The first time, it asks for your environment repository and where to keep its **sync clone** (default `~/.mk96-env/repo`, or an existing clone such as one in your projects folder); the tool pulls and pushes there and nowhere else, and refuses to sync while that clone has local changes or is on another branch. The location is remembered, and every import and export first asks whether to keep using it or change it (another remote repository or local folder).

Requirements: Python 3.10+ and git with a user identity (`user.name`, `user.email`). To export, git needs push access to the environment repository (for GitHub, `gh auth login` and `gh auth setup-git` are enough). `/mk96-env:export` only runs when you type it, since it pushes without asking.

## Use your own environment

1. Create a repository for your environment (public or private), empty, or fork [mk96-ai/mk96-ai-claude-env](https://github.com/mk96-ai/mk96-ai-claude-env) to start from that environment.
2. Install the plugin as above; there is no need to fork the plugin.
3. Run `/mk96-env:import` (starting from a fork) or `/mk96-env:export` (starting empty) and give your repository's URL when asked.

The environment repository only needs an `env/` folder; the tool creates it on the first export.

## What is synced

| Item | On the machine | In the repository |
|---|---|---|
| Global instructions | `~/.claude/CLAUDE.md` | `env/CLAUDE.md` |
| Personal rules | `~/.claude/rules/*.md` | `env/rules/` |
| Personal commands | `~/.claude/commands/*.md` | `env/commands/` |
| Personal skills | `~/.claude/skills/<name>/` | `env/skills/` |
| Personal agents | `~/.claude/agents/*.md` | `env/agents/` |
| Hook scripts | `~/.claude/hooks/<name>/` | `env/hooks/` |
| Mods (local plugins) | `~/.claude/mods/<name>/`, loaded through `CLAUDE_CODE_PLUGIN_DIRS` | `env/mods/` |
| Marketplaces | `~/.claude/plugins/known_marketplaces.json` (GitHub, git and URL sources) | `env/plugins.json` |
| Plugins and their enabled state | `enabledPlugins` in `settings.json` | `env/plugins.json` |
| Preferences | `model`, `autoMemoryEnabled` in `settings.json` | `env/settings.json` |
| Deny rules | `permissions.deny` in `settings.json` | `env/settings.json` |
| Own hooks | `hooks` entries in `settings.json` whose command runs a script from `$HOME/.claude/hooks/` or `~/.claude/hooks/` | `env/settings.json` |

Plugins are installed from their own marketplaces, never copied. Only the keys above are changed in `settings.json`; everything else in it is left as it is. Inside skills and mods, nested `.git` folders, `__pycache__` and `*.pyc` are ignored, and so are a mod's generated `.claude-plugin/types/` and `node_modules/` (they stay untouched on each machine).

Own hooks replace only the own hooks on the other machine; hooks of other tools are never exported nor touched. A hook that points to `~/.claude/hooks/` through an absolute path (`/home/me/...`) is treated as machine-specific and left out. Hook scripts with a `#!` line stay executable.

**Not synced:** hooks of other tools, `permissions.allow` and `permissions.ask` (usually machine-specific), status line, themes and keybindings (usually owned by other apps), `skipDangerousModePermissionPrompt` and other safety settings (each person should choose them), account skills in `~/.claude/skills/synced/` (Claude Code downloads them for whoever logs in), local-directory marketplaces, credentials, history and sessions.

## How sync works

- Each machine remembers, in `~/.config/mk96-env/state/` (one file per Claude folder and repository), what every item looked like at its last sync. Comparing that with this machine and the repository tells, per item, whether it changed here, elsewhere, or in both places.
- `import` applies what changed elsewhere; `export` stores what changed here. Items changed on the other side are shown as pending.
- An item changed in both places is a **conflict**: the only time the tool asks a question (keep this machine's version, the repository's, or skip).
- Removals propagate, except on a machine's first sync with a repository, which only adds and treats any item that differs on both sides as a conflict (nothing local is overwritten without asking).
- `export` is blocked on a machine that has never imported while the repository already holds an environment, so a fresh machine cannot wipe it.
- Before overwriting or deleting anything local, a copy goes to `~/.claude/backups/mk96-env/<timestamp>/`.
- `export` stops and pushes nothing if an item looks like it contains a secret (tokens, private keys, password assignments).
- `import` also updates the plugin itself from its marketplace.

## Layout

```
.claude-plugin/        plugin.json, marketplace.json
skills/import/         /mk96-env:import
skills/export/         /mk96-env:export
core/mk96env.py        entry point: import | export | where | setup --clone PATH [--url URL]
core/mk96env_core/     sync engine (standard library only)
  payload.py           item content, hashing, line-ending normalization
  status.py            three-way comparison of one item
  sides.py             this machine (~/.claude) and the repository (env/)
  backup.py            copies taken before local overwrites
  secrets.py           credential detection before export
  state.py             per-machine record of the last sync
  sync.py              the engine: compare, apply, new state, conflicts
  gitops.py            git operations on the sync clone
  summary.py           result model and text summary
  config.py            paths and the plugin's own installation
  cli.py               commands and exit codes used by the skills
tests/                 unittest suite
```

## Development

```
PYTHONPATH=core python3 -m unittest discover -s tests
claude --plugin-dir .        # try the plugin without installing it
```

Known limitations:
- The list separator of `CLAUDE_CODE_PLUGIN_DIRS` on Windows is assumed to be `;` (like `PATH`); not yet verified on Windows.
- Only top-level `*.md` files of `commands/`, `agents/` and `rules/` are synced; files in subfolders (namespaced commands) are not.
