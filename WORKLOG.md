# Worklog agent · v1.15 (part of the Sonelo Solution DevKit v4.0)

Installed and updated through the kit: `python repo_setup.py install` does the machine setup, `/repo-setup` or `apply` puts it in a repo. The rest of this file is the reference.

Drop this `.worklog/` folder into any repo you want reporting. From then on, every Claude Code session in that repo reports the repo's commits, sessions and token usage into one central pot, and the pot's reports are rebuilt from everything that's reporting, plus the machine-level picture: time at the desk, editor time per repo, and when the machine was unlocked.

## Install, once per repo

From the repo root:

```
python .worklog/worklog_agent.py install
```

That's the whole thing. Defaults:

- **Pot:** `C:\Users\AccountA\Worklog`. Created if it doesn't exist, remembered in `~/.claude/worklog.json` for every repo after.
- **Project name:** the repo's folder name, so `nurture-loop-tek` reports as `nurture-loop-tek`.

- **Post-commit hook:** on, so a plain `git commit` outside a Claude Code session still reports. `--no-git-hook` to skip.
- **Presence tasks:** registered the first time any repo is installed on the machine, then left alone (`install` checks they exist and skips). `--no-presence` to skip.

Both names can be overridden when you want to: `install --project Knecta` makes this repo report under Knecta (install a second repo with the same name and they share one line), and `--pot "D:/Reports/Worklog"` moves the pot for all repos. Restart any Claude Code session already open in that repo so it picks up the hooks.

Or let Claude Code do it. Unzip into the repo root, open Claude Code there and say:

> Read .worklog/README.md and install the worklog agent for this repo.

### Once per machine

**Auto-install.** Run `install --auto` from any one repo. It registers a user-level Claude Code hook (in `~/.claude/settings.json`) that runs at the start of every session, anywhere: if the folder is a git repo with no agent, it drops one in and installs it; if the repo's copy is older than the one in `<pot>/bin/`, it replaces it and re-installs; otherwise it exits in under a tenth of a second. From then on, new and cloned repos report as soon as you open Claude Code in them, and updating the agent means updating any one repo and running `install` there, because that refreshes `bin/` and every other repo upgrades itself the next time you open it. To keep a repo out, put an empty file called `.noworklog` in its root. `uninstall --auto` removes the hook.

**Desk time and editor time.** Install [ActivityWatch](https://activitywatch.net) (free, local, runs in the tray; nothing leaves the machine). The agent reads it on `http://localhost:5600` and the desk-time and editor-time columns appear from the next run. Without it those columns are simply absent. `--aw-url ""` on install disables the lookup.

**Logon / lock / unlock stamps.** Handled by `install` itself: the first install on a machine registers three Task Scheduler tasks (`Worklog presence logon / lock / unlock`) that append a timestamp to `<pot>/presence/` whenever you log on, lock or unlock. No admin rights, no window flashes (they run under `pythonw.exe` from a copy of the agent kept at `<pot>/bin/`). Boot, shutdown, sleep and wake are read from the Windows System event log automatically, so days bracket correctly even without a lock. `uninstall --presence` removes the tasks; the next `install` in any repo puts them back unless you pass `--no-presence`.

## What install does

- Registers SessionStart, Stop and SessionEnd hooks in `.claude/settings.local.json`, which is personal and not committed. `--shared` writes them to `.claude/settings.json` instead, so every clone reports.
- Adds `.worklog/` and `.claude/settings.local.json` to this clone's local git excludes (`.git/info/exclude`), so client repos stay clean. `--shared` skips that.
- Appends one line to `.git/hooks/post-commit` (created if absent, existing hooks kept), so every commit reports too.
- Keeps a copy of the agent at `<pot>/bin/worklog_agent.py` and, on Windows, registers the presence tasks if they aren't there yet.
- Runs a first collection and renders the pot, then prints what it found.

## What happens after

It runs on events, not a clock: when a Claude Code session starts or ends in an installed repo, after each response (at most every three minutes), on every commit, and whenever you log on, lock or unlock the machine (that last one refreshes desk time and presence and re-renders, so the dashboard is current when you sit down). Every hook call returns in about a tenth of a second, does the real work in a detached process, and prints nothing into the session. The work: collect this repo's last 28 days of commits and Claude Code sessions into `<pot>/slices/Knecta__nurture-loop-tek.json`, refresh the machine slice (ActivityWatch and presence, at most every ten minutes), then re-render the pot from all slices:

```
C:\Users\AccountA\Worklog\
  dashboard.html                      interactive view of all of it — double-click to open
  morning.html                        yesterday and where you left off; pops up once a day
  latest-week.md                      this week so far, as Markdown
  latest-14-days.md                   the last two weeks, rolling
  latest.md                           yesterday
  weekly/worklog-2026-W34-to-date.md  this week, rebuilt on every run
  weekly/worklog-2026-W33.md + .csv   each completed week in the window, final
  weekly/worklog-2026-W32.md + .csv
  slices/                             one JSON per reporting repo, plus _machine__<host>.json
  presence/                           the logon/lock/unlock stamps
  bin/                                the machine copy of the agent
```

### The morning page

The first time the agent runs on a given day after 05:00, whether that's your first unlock, logon or Claude Code session, it renders `morning.html` and opens it in a frameless browser app window (Chrome or Edge; the default browser otherwise): yesterday's projects with commits, Claude Code time, what each session was working on and any uncommitted files, the day's desk and unlocked facts, this week so far, and a button to the dashboard. Once a day, then it stays out of the way. `worklog_agent.py brief` opens it any time; `install --no-brief` turns the pop-up off; `brief_after` in `~/.claude/worklog.json` moves the earliest time. It reads only the pot, so calendar and inbox stay with the Cowork morning brief.

### The dashboard

`dashboard.html` is a single self-contained file, rebuilt on every run with the data embedded, so it opens by double-click with no server and nothing leaves the machine. Refresh the page after a run to see new data. It has presets for this week, last week, 14 and 28 days, with arrows to step back through the window, and clicking a project focuses every section on it.

- **Days** — one row per day on a 24-hour track: Claude Code sessions as bars, commits as ticks (coloured by project), the machine's unlocked periods in light blue, with desk, editor, Claude and commit figures at the end of each row.
- **Projects** — commits, sessions, Claude Code and editor time, a proportional bar, estimated cost once prices are set, and an **uncommitted** badge.
- **At a glance** — the project × day grid, shaded by Claude plus editor time.
- **Claude Code usage** — tokens per project with a share bar (input, cache read, output) and models.
- **Weeks** — hours per week by project, stacked, from the archived weekly CSVs plus the current week to date, so the trend keeps growing past the 28-day window.
- **Log** — commits and sessions per project per day, newest first.

The Markdown reports carry the same data for reading in a plain editor or feeding to Claude. Each report has:

- **Summary** — commits, Claude Code sessions, estimated active time and days touched, per project.
- **At a glance** — project × day grid, `2c · 1h 05m` (commits, active Claude Code time).
- **Editor time** — project × day grid of VS Code time while you were at the keyboard, matched to repos by window title. Needs ActivityWatch.
- **Days** — one row per day: at desk (ActivityWatch), unlocked span and total (presence), first and last trace (earliest and latest commit or Claude Code event), Claude Code active, editor time, commits. Columns whose source isn't running are left out. The yesterday report shows the same as a single **Day:** line.
- **Claude Code usage** — input, cache-read and output tokens per project with the models used. Add prices to `~/.claude/worklog.json` and an estimated cost column appears:

  ```json
  "currency": "£",
  "prices": {"sonnet-4-6": {"in": 3, "cache_create": 3.75, "cache_read": 0.3, "out": 15},
             "opus-4-8":   {"in": 15, "cache_create": 18.75, "cache_read": 1.5, "out": 75}}
  ```

  Keys are matched as substrings of the model name; values are per million tokens. Fill them from the current price list; the agent ships with none.
- **Per project** — repos, branches, an **uncommitted** flag with the file count, then per day, commits and sessions in time order.

Stop hooks are throttled to one collection every three minutes; the Windows event log is read at most hourly.

## Commands

```
python .worklog/worklog_agent.py status            # config, hooks, last slice, ActivityWatch, presence
python .worklog/worklog_agent.py run --sync        # collect + render now, in the foreground
python .worklog/worklog_agent.py render            # rebuild the pot from the slices already there
python .worklog/worklog_agent.py refresh           # pull desk time and presence, re-render (what lock/unlock trigger)
python .worklog/worklog_agent.py brief             # render and open the morning page now
python .worklog/worklog_agent.py setup             # machine-level only (pot, auto hook, presence); what the Teknobu kit calls
python .worklog/worklog_agent.py uninstall         # remove this repo's hooks (slice and folder stay)
python .worklog/worklog_agent.py uninstall --presence   # also remove the Task Scheduler tasks
python .worklog/worklog_agent.py uninstall --auto       # also remove the user-level auto-install hook
python .worklog/worklog_agent.py stamp lock        # what the tasks call; you won't need it
```

## Notes

- History is included from the first run: each slice reaches back 28 days (`--window-days` to change), so the two weeks before you installed are in the reports straight away. ActivityWatch data is likewise pulled back 28 days on the first run (as far as it has been installed), then each run refreshes from the day of the previous refresh, so a quiet weekend doesn't lose Friday evening. A repo reports whenever Claude Code runs in it or you commit, and a quiet repo catches up the next time it does.
- How the time columns differ: *Claude Code active* on a day row (and the dashboard's top card) is wall-clock time with any session active; the per-project *Claude Code* figure is effort, summed over that project's sessions, so with several Claude Code windows open in parallel the project figures add up to more than the day. Both use gaps between transcript events capped at `idle_minutes` (15). *Editor* is the VS Code window in front while keyboard or mouse were active; *at desk* is all keyboard/mouse activity in any app; *unlocked* is between a logon/unlock stamp and lock/sleep/shutdown, so it only exists from the day the presence tasks were registered (boot and wake events from the event log don't count on their own, because Windows wakes itself for updates). None is a billable figure; together they show the shape of the day.
- Session folders are matched case-insensitively, because VS Code's terminal reports `c:\` where other launches say `C:\`, and Claude Code keeps those as separate folders. An old slice for the same repo under a previous project name is removed when the repo next reports.
- Editor time is attributed by the folder name in the VS Code title bar (`file - folder - Visual Studio Code`), so it lines up with the repo name or the project label. Cursor and Windsurf are matched too. A custom `window.title` setting without the folder will leave it unattributed.
- If the pot isn't reachable at the time (say it's later moved onto a synced or network drive), the run is logged and skipped; the next one catches up. If ActivityWatch isn't running, cached days are kept and the error is noted in `status`.
- Updating the agent: with auto-install on, replace `worklog_agent.py` in any one repo and run `install` there; `bin/` is refreshed and every other repo upgrades itself — at its next session start, and since v1.15 also mid-session (each hook run adopts a newer `bin/` copy for the next run, so always-on machines with long-lived sessions catch up within minutes). Without auto-install, replace the file in each repo and run `install` in each. `status` shows the version.
- What's new after an upgrade (v1.15): the session-start message says what changed, the dashboard header shows "worklog vX · new: ..." for 7 days after a version first renders, and the morning page carries the same line for 3 days (first-render date kept in `<pot>/.whats-new.json`).
- Windows: Claude Code runs hooks through Git Bash (from Git for Windows, which you already have). The installer writes the full path of the Python it was run with, so PATH differences between shells don't matter.
- Every run logs to `.worklog/agent.log` in the repo; the scheduled tasks log to `<pot>/bin/agent.log`.

## Agents (since v1.12, grouped by project since v1.14)

The dashboard's **Agents** card and the weekly report's *Agents and commands* section show, for the sessions in range, agent usage grouped by project: each project with its totals, then each subagent under it with how many times it ran, how long it ran, and the tokens it consumed, attributed from the Task calls in the session transcript and the subagent transcripts under it. Agents appear under friendly display names (e.g. code-reviewer as "Stephen - Tech Nerd"); the raw ids stay in the data, and `"agent_names": {"code-reviewer": "..."}` in `~/.claude/worklog.json` overrides any of them. Below the table: the slash commands used (`/post-change` x3) and the tools Claude called most. Sessions collected before v1.12 show no agent data.
