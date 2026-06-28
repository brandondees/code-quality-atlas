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

### Collapsed form (4 entrypoints)

The same marketplace also offers a **collapsed** plugin —
`code-quality-atlas-collapsed` — that installs the suite as **4 entrypoint
skills** (`reviewing-a-change`, `auditing-a-repository`, `reviewing-a-decision`,
`reviewing-an-artifact`) instead of 35, bundling each shape's lenses and loading
them on demand. The collapsed **form** is the one to reach for on
**cloud / account-skill / context-budget-constrained** surfaces; the standalone
form keeps the richest top-level discoverability. Install **one form, not both**.

The `/plugin install` below is the **local CLI / desktop / IDE** path (like the
standalone plugin, it does **not** load in web/cloud — see the callout below). For
the collapsed form **in cloud**, enable it as account skills or vendor it with the
`--collapsed` flag, per [`distribution.md`](distribution.md) (*Two forms*).

```text
/plugin install code-quality-atlas-collapsed@code-quality-atlas
```

Or per-repo via settings — commit this to a project's `.claude/settings.json`,
which installs the plugin for **local CLI / desktop / IDE** sessions that trust
the folder (it avoids the interactive `/plugin` command):

> **Does not work in Claude Code web/cloud.** `enabledPlugins` /
> `extraKnownMarketplaces` is a CLI-local mechanism — the cloud runtime does not
> run the plugin-install step, so committing this snippet has **no effect** in
> web sessions or routines (the
> [routines docs](https://code.claude.com/docs/en/routines) list "skills
> committed to the cloned repository" and connectors as what loads; plugins are
> not included). For the suite in cloud, see [`distribution.md`](distribution.md):
> enable it as **account skills on claude.ai** (repo-independent, loads in cloud
> automatically) and/or **vendor `.claude/skills/`** into the repo.

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

For the **collapsed** form instead, keep the same `extraKnownMarketplaces` block
(one marketplace serves both) and swap the `enabledPlugins` key to
`"code-quality-atlas-collapsed@code-quality-atlas": true` — enable one form, not
both.

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

The same mechanics apply to the **collapsed** plugin
(`code-quality-atlas-collapsed`): the settings snippet below installs and refreshes
it per session on local CLI, and an interactive `/plugin install` caches it until you
update or enable auto-update. Both plugins share the one marketplace, so
`/plugin marketplace update code-quality-atlas` (and `keep-plugin-current.sh`)
refresh whichever form you installed. In **cloud**, neither plugin loads — refresh
the collapsed form by re-enabling its account skills or re-running
`vendor-skills.sh --collapsed` and committing, exactly as for the standalone form.

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

> **Replace `/abs/path/to/code-quality-atlas/`** in the command below with the
> absolute path to your code-quality-atlas clone — for example,
> `$HOME/code/code-quality-atlas/`. It is a placeholder, not a real path: left
> as-is, the backgrounded command fails silently (`No such file or directory`,
> swallowed by `>/dev/null 2>&1 &`) and the updater never runs.

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

**How the wiring loads.** The hook needs no `hooks` key in
[`../.claude-plugin/plugin.json`](../.claude-plugin/plugin.json): Claude Code
**auto-discovers** a plugin's hook config at the conventional path `hooks/hooks.json`
under the plugin root, so the omission is intentional, not a missing registration
([plugins reference](https://code.claude.com/docs/en/plugins-reference) — *File
locations*). The hook command runs `"${CLAUDE_PLUGIN_ROOT}/hooks/route.sh"`;
`CLAUDE_PLUGIN_ROOT` is a **Claude-Code-provided** environment variable set to the
plugin's install directory for the duration of hook (and command) execution — it is
not something you configure, and it is quoted so the path survives spaces. Outside a
Claude Code plugin install (e.g. a `SKILL.md`-only Skulto install), there is no
plugin runtime, so this hook does not apply — the committed `/atlas-init` routing
block is the portable fallback.

The hook is a per-session *nudge* that works even before a repo is wired; the
committed routing block from `/atlas-init` is the durable, deterministic override.
The two pair together.

> **Cold-first-session caveat.** The hook can only fire once the plugin itself is
> loaded. On the very first session right after install — while a marketplace plugin
> is still being fetched and indexed — both the skill listing *and* this hook may
> arrive after your first message. Every subsequent session, the plugin is cached
> and the hook fires at startup as intended. If a first session misses it, just
> re-send your request or invoke `choosing-review-lenses` directly.
