# Install & setup — details

The [README](../README.md) covers the two install paths and the one-command repo
setup at a glance. This page holds the depth: every Claude Code install variant,
how updates reach you per path, the stale-install gotcha (matters most for
routines), keeping an interactive install current, and the `SessionStart` routing
hook.

## Skulto (any `SKILL.md` agent)

[Skulto](https://github.com/asteroid-belt/skulto) is a cross-platform skill
manager that syncs `SKILL.md` skills to Claude Code, Cursor, Windsurf, Copilot, and
25+ other agent tools. Because every lens is a standard `SKILL.md`, this is the
recommended install for anything other than (or in addition to) a Claude Code
plugin:

```bash
brew install asteroid-belt/tap/skulto
skulto add brandondees/code-quality-atlas        # register the repo and sync it
skulto install brandondees/code-quality-atlas -y # install all skills (drop -y to pick interactively)
```

Skulto installs are snapshots — run `skulto pull` (or `skulto update`, which adds a
security re-scan and change report) to refresh to the latest merged commit. To pin
a project's skill set for teammates, `skulto save` writes the current installs to a
`skulto.json` manifest that `skulto sync` reproduces.

## Claude Code (plugin)

In an interactive Claude Code session (terminal CLI, desktop app, or IDE
extension):

```text
/plugin marketplace add brandondees/code-quality-atlas
/plugin install code-quality-atlas@code-quality-atlas
```

Or from a plain shell, non-interactively (add `--scope project` to scope to one
repo):

```bash
claude plugin marketplace add brandondees/code-quality-atlas
claude plugin install code-quality-atlas@code-quality-atlas
```

Or per-repo via settings — commit this to a project's `.claude/settings.json` and
anyone who trusts the folder gets the suite, **including Claude Code web sessions**
(which don't expose the interactive `/plugin` command):

```json
{
  "extraKnownMarketplaces": {
    "code-quality-atlas": {
      "source": { "source": "github", "repo": "brandondees/code-quality-atlas" }
    }
  },
  "enabledPlugins": {
    "code-quality-atlas@code-quality-atlas": true
  }
}
```

> **Note:** if installing from a private copy/fork of this repo, the installing
> machine needs git credentials that can read it (`gh` auth or SSH keys; web
> sessions clone with your GitHub credentials).

## How updates reach you

All 35 skills load with provenance intact, and updates ship with every merged
commit (commit-SHA versioning — no version bumps). Which install path you used
decides how those updates arrive:

- **Settings-based installs** (the `.claude/settings.json` snippet above, including
  web sessions) install fresh at session start — every new session already has the
  latest merged commit, nothing to do.
- **Interactive installs** (`/plugin install` on CLI/desktop/IDE) cache the plugin
  and do **not** auto-refresh by default. Either pull manually with
  `/plugin marketplace update code-quality-atlas`, or enable auto-update once
  (`/plugin` → **Marketplaces** → `code-quality-atlas` → **Enable auto-update**).

> **Stale-install gotcha (esp. for routines).** An interactive cached install with
> auto-update *off* stays pinned to whatever commit it was installed at and can
> silently run a months-old copy — the tell is a session reporting that
> `commands/atlas-review-pr.md` or `REVIEW.md` is *"not in the repo or its
> history."* For any repo a routine reviews, prefer the **settings-based install**
> (always fresh per session) or **enable auto-update**.

## Keeping an interactive install current (opt-in)

If you stay on an interactive install and don't want to enable auto-update,
[`../tooling/keep-plugin-current.sh`](../tooling/keep-plugin-current.sh) refreshes
the marketplace clone and re-pins **every** scope (user + each project) to the
latest commit. It reads the scopes from `~/.claude/plugins/installed_plugins.json`,
so new projects are picked up automatically. A Claude restart still applies the
staged update — the script only stages it for the next session.

```bash
tooling/keep-plugin-current.sh                       # this plugin, all scopes
tooling/keep-plugin-current.sh --user-only           # skip project scopes
tooling/keep-plugin-current.sh other@some-marketplace # any plugin
```

To self-heal every session, add a throttled (once-a-day) `SessionStart` hook to
your **personal** `~/.claude/settings.json` (not committed to any repo),
backgrounded so it never blocks startup:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "lf=\"$HOME/.claude/.keep-plugin-current-last\"; ts=$(date +%s); { [ -f \"$lf\" ] && [ $((ts-$(cat \"$lf\"))) -lt 86400 ]; } && exit 0; echo \"$ts\" > \"$lf\"; nohup bash /abs/path/to/code-quality-atlas/tooling/keep-plugin-current.sh >/dev/null 2>&1 &",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The leading timestamp guard runs the updater at most once a day, so most session
starts exit immediately without a git fetch. Drop the guard to run it every
session.

## Automatic routing (SessionStart hook)

For Claude Code, the plugin ships a `SessionStart` hook
([`../hooks/hooks.json`](../hooks/hooks.json) → [`../hooks/route.sh`](../hooks/route.sh))
so the suite is used as designed without you having to name a skill first. On each
session it injects one line of routing guidance into context.

This exists because, with 33+ skills, individual skill **descriptions** can be
dropped from the model's skill listing (budgeted to ~1% of context, not re-injected
after `/compact`), which makes the lenses easy to overlook on a plain "review this"
request; the hook's `additionalContext` is injected verbatim before the first
prompt, so it's reliable where the listing isn't. The hook is **side-effect-free** —
it only prints to stdout and writes nothing to your repo.

The hook is a per-session *nudge* that works even before a repo is wired; the
committed routing block from `/atlas-init` is the durable, deterministic override.
The two pair together.

> **Cold-first-session caveat.** The hook can only fire once the plugin itself is
> loaded. On the very first session right after install — while a marketplace plugin
> is still being fetched and indexed — both the skill listing *and* this hook may
> arrive after your first message. Every subsequent session, the plugin is cached
> and the hook fires at startup as intended. If a first session misses it, just
> re-send your request or invoke `choosing-review-lenses` directly.
