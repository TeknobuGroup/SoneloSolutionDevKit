# ARCHITECTURE - teknobu-kit

## Services and hosting
Sonelo Solution DevKit: a Python toolkit (two files, standard library only, Windows first). Installed into `~/.claude/sonelo/` per machine. Installs CLIs (gh, Supabase, Vercel) and agent pipeline. No hosted service; runs locally in Claude Code sessions. `repo_setup.py` creates repos on Vercel and Supabase; `worklog_agent.py` tracks sessions, commits, agents, time and tokens across all Claude repos.

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

## Change pipeline
Event-driven: `.claude/hooks/pipeline-state.sh` derives the changed set, reviewable subset, and due reviewers (code always; design on tsx/jsx/css/tailwind; security on supabase/functions/auth paths); computes a content signature ("sig") of the filtered diff. `stop-gate.sh` requires a fresh verdict covering every due reviewer with matching sig (count-based valve: at most two blocks per sig, second demands disclosure). `session-brief.sh` states outstanding debt at session open. Verdicts and sig stored in `.claude/state/<branch>/review.json`, not committed. Releases cut by `.github/workflows/release.yml` on every main merge. SessionStart nudge offers `update` (daily throttled, 3s timeout, silent offline) and `refresh` per target repo — both require consent, never auto-applied.

## Environments
- Local: dev machine, `~/.claude/sonelo/` config, Python + CLIs
- Prelive (configured branch, default `staging`): separate Supabase project/branch and Vercel preview URL
- Production (`main`): protected branch, separate Supabase project, Vercel production domain, manual PR merges only
