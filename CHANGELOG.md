# Changelog

## 3.2
- `/landing`: a generated page per repo (pipeline, commands, agents, state, environments, documents, worklog).
- `update` command: fetch and install the latest GitHub release; `install.sh` for Mac and Linux.
- Worklog 1.12: per-agent runs, time and tokens; slash commands and tools; per-project breakdown.

## 3.1
- Complete built-in pipeline: ten agents, `/post-change`, `/design-pass`, `/pr`, three Claude Code hooks, CI gates, managed CLAUDE.md section; `apply --update-pipeline`.

## 3.0
- Config instead of constants (`config.json`, presets, `--set`); `separate` or `branching` database strategy; `full` or `worklog` install mode; MIT licence.

## 2.0
- Install downloads `gh` and the Supabase CLI, installs the Vercel CLI, runs logins; `doctor`; design-reviewer and per-repo design contract; Lovable migration checklist; SPA rewrite; fixes from the first two live setups.
