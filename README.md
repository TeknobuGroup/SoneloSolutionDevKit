# Sonelo Solution DevKit

Kit v4.0 · worklog v1.15. Sonelo is the developer platform brand of Teknobu Group. Repo standards, a complete agent pipeline, infrastructure creation and a work log for Claude Code projects. One Python file each, standard library only, Windows first.

## Install (once per machine)

Needs Python 3, git, Node.js (for the Vercel CLI and the type-check hook) and Claude Code.

```
git clone https://github.com/TeknobuGroup/SoneloSolutionDevKit
cd SoneloSolutionDevKit
python repo_setup.py install          # or double-click install.cmd on Windows, ./install.sh on Mac/Linux
```

Or without cloning - one line, PowerShell:

```
iwr https://raw.githubusercontent.com/TeknobuGroup/SoneloSolutionDevKit/main/repo_setup.py -OutFile "$env:TEMP\repo_setup.py"; python "$env:TEMP\repo_setup.py" install
```

Mac/Linux:

```
curl -fsSL https://raw.githubusercontent.com/TeknobuGroup/SoneloSolutionDevKit/main/repo_setup.py -o /tmp/repo_setup.py && python3 /tmp/repo_setup.py install
```

The lone file fetches the worklog from the same repository during install.

Or download the zip from the releases page and run the same from the unzipped folder. It asks four things the first time:

- **Full setup or worklog only.** Worklog only installs nothing but the work log: per-repo hooks, a dashboard, a morning page.
- **GitHub organisation** for new repos.
- **The branch you work on** (default `staging`). It gets its own URL and database; `main` is production and moves only by pull request.
- **Database strategy.** `separate` (a `<name>-<branch>` project and a `<name>` project) or `branching` (one project plus a persistent Supabase branch; Pro plan).

Everything else lives in `~/.claude/sonelo/config.json`: Vercel team, domain pattern, Supabase organisation and region, default stack, brand defaults for the design contract. `install --preset sonelo` applies Teknobu Group's own values (`--preset teknobu` still works); `install --set key=value` changes one.

The install also downloads `gh` and the Supabase CLI into its own folder, installs the Vercel CLI with npm, and runs the three browser logins. `repo_setup.py doctor` shows what's present, never the values.

## Use

In Claude Code, in any repo or empty folder: `/repo-setup`. It asks whether this is an existing repo, a new project or a Lovable migration, asks everything else in one message with your defaults, confirms, then runs to the end. `/new-repo` skips the first question.

`/landing` opens the repo's landing page in the browser: the pipeline at a glance, every command with a copy button, every agent with what it does, the repo's standards state, the environment URLs and Supabase projects (never keys), the documents, and links into the worklog.

## What you get

**A complete pipeline, built in.** Ten agents: impact-analyst (before), code-reviewer, security-reviewer and design-reviewer (read-only, in parallel), test-writer (the only writer, tests only; failing test first for every bug), test-runner, qa-runner (Playwright against the work-branch URL), uat-writer, changelog-scribe and docs-maintainer (Haiku). Three commands: `/post-change` (review → fix loop, two rounds max → tests → verdict → docs), `/design-pass` (design-led polish within the contract, nothing that touches logic), `/pr` (UAT document required, becomes the PR body). Three Claude Code hooks: typecheck and lint after every edit, migrations append-only, and a Stop gate that holds the session until the changelog entry, regenerated types and a clear review verdict exist. CI gates mirror it on every PR: changelog, UAT document, types. The lead is the session you type into; the agents are its specialists. A starter folder of your own overrides any file; `apply --update-pipeline` refreshes the built-ins with backups.

**Branches and hooks.** Conventional commit messages. Secrets, `.env` files and files over 5 MB can't be committed. Pushes to `main` and force-pushes refused. Typecheck, lint and tests before every push, and again in CI with a secrets scan. `main` protected on GitHub with the CI and gates checks required.

**Databases and hosting.** Supabase projects or branches created with their keys in git-ignored env files and the deploy secrets set on GitHub; migrations and edge functions deploy per branch. Vercel project created from the repo with the branch domain bound, DNS checked, env pushed per environment. Vite apps get the SPA rewrite.

**Lovable migrations.** Detected from the code; `MIGRATION.md` lists the ordered steps with counts.

**Worklog.** Every repo reports to one folder: commits, Claude Code sessions, time, tokens, and from v1.12 a breakdown per agent (runs, time, tokens for each subagent, plus the slash commands and tools used), a dashboard, a morning page once a day. See `WORKLOG.md`.

## Escape hatches

`SONELO_SKIP=1` in front of a git command disables the hooks once. `SONELO_ALLOW_MAIN=1` allows one direct push. (The older `TEKNOBU_*` names still work.) `.nokit` in a repo silences the session-start nudge; `.noworklog` opts a repo out of the work log.

## Update

`python ~/.claude/sonelo/repo_setup.py update` fetches the latest release and installs it; your config is kept. From a clone, `git pull` then `install` does the same. Repos pick up the new worklog as you open them; `apply --update-pipeline` in a repo refreshes its agents, commands and hooks with backups.

Windows is the first-class platform (installer, Credential Manager, scheduled presence stamps). The kit and the pipeline also run on Mac and Linux; the presence stamps don't.

## Before you rely on it

This creates billable resources on your Supabase and Vercel accounts and reads your Claude Code transcripts (and, with ActivityWatch, window titles) for the work log, all on your own machine. Read what a command will do before you run it on a client's account. MIT licence, no warranty.

## Upgrading from teknobu-kit v3

Run `install` once; it migrates `~/.claude/teknobu` (config, pipeline, CLIs) to `~/.claude/sonelo` and leaves the old folder untouched. Repos keep every file they have - the kit recognises its earlier `teknobu-kit` markers as its own - and `apply --update-pipeline` refreshes them under the new name. `.teknobu.json` keeps its filename, and the old `TEKNOBU_*` escape hatches keep working.
