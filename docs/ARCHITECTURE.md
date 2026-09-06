# ARCHITECTURE - teknobu-kit

## Services and hosting
Sonelo Solution DevKit: a Python toolkit (three files, standard library only, Windows first). Installed into `~/.claude/sonelo/` per machine. Installs CLIs (gh, Supabase, Vercel) and agent pipeline. No hosted service; runs locally in Claude Code sessions. `repo_setup.py` creates repos on Vercel and Supabase; `worklog_agent.py` tracks sessions, commits, agents, time and tokens across all Claude repos; `diary_agent.py` turns one day of that into a privacy-tiered day-file and serves it over a local stdio MCP server.

## Data
No database in the kit itself. Created repos use Supabase with multi-tenant RLS policies per `.claude/rules/supabase.md`.

## Edge functions
None in the kit. Created repos' edge functions validate JWT + tenant membership.

## Frontend
None in the kit. Kit provides: `/repo-setup` Claude Code command, `/landing` page (pipeline commands, agents, standards, environment URLs, docs, worklog links), hooks for commit/push/type-check, and agent folder with reviewers, test-writer, changelog-scribe, docs-maintainer.

## Integrations
- GitHub: `gh` CLI, Conventional Commits hook, branch protection on main
- Supabase: Project/branch creation, migrations, secrets via env files
- Vercel: Project creation from repo, branch domain binding, per-environment secrets
- Claude Code: Session tracking for worklog

## Diary
`diary_agent.py` (v1.0) reads, never writes, the things the machine already records: the worklog pot (`load_slices`, `session_day_minutes` - imported from `worklog_agent.py`, never reimplemented), each repo's git log for the day, Claude Code transcripts under `~/.claude/projects`, ActivityWatch and presence stamps from the machine slices, and its own notes and images under `~/Diary/`. Output is one JSON day-file per date in `~/Diary/`.

Privacy is per repo and defaults closed: `.teknobu.json` -> `diary.tier` of `own` | `nickname` | `private`, absent or unreadable meaning `private` (hours only). A project is labelled by its `description` or `nickname`, never by the repo name, at any tier. Session summaries are produced locally from a digest of prompts and assistant prose - tool results are excluded by construction - so raw transcripts never leave the machine; they are cached per session id per day, stamped with the tier. Before any file is written, a leak check runs every string against the blocklist, the repo and person names in the day, and (below `own`) branch names and four shapes (URL, file path, commit subject, branch); a hit fails the collect naming the term and the field, and `--force` redacts instead and records what it redacted.

`diary serve` is a stdio JSON-RPC MCP server (protocol 2025-06-18) exposing `diary_day`, `diary_sessions`, `diary_note` and `diary_list`. It is thin by construction: every tool calls the same function the CLI calls, so there is one implementation of "what a day is". stdout carries protocol only; all human output goes to stderr. Reference: `DIARY.md`; decision: `docs/decisions/0011`.

## Change pipeline
Event-driven: `.claude/hooks/pipeline-state.sh` derives the changed set, reviewable subset, and due reviewers (code always; design on tsx/jsx/css/tailwind; security on supabase/functions/auth paths); computes a content signature ("sig") of the filtered diff. `stop-gate.sh` requires a fresh verdict covering every due reviewer with matching sig (count-based valve: at most two blocks per sig, second demands disclosure). `session-brief.sh` states outstanding debt at session open. Verdicts and sig stored in `.claude/state/<branch>/review.json`, not committed. Releases cut by `.github/workflows/release.yml` on every main merge. SessionStart nudge offers `update` (daily throttled, 3s timeout, silent offline) and `refresh` per target repo — both require consent, never auto-applied.

## Environments
- Local: dev machine, `~/.claude/sonelo/` config, Python + CLIs
- Prelive (configured branch, default `staging`): separate Supabase project/branch and Vercel preview URL
- Production (`main`): protected branch, separate Supabase project, Vercel production domain, manual PR merges only
