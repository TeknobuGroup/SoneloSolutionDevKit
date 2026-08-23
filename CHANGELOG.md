# Changelog

## [Unreleased]

### Added
- Worklog 1.14: the dashboard's Agents card and the weekly report group agent usage by project (project totals with agents beneath, share bars), agents display friendly persona names with raw agent IDs on hover — built-in map overridable via `"agent_names"` in `~/.claude/worklog.json` (malformed config ignored safely). New stdlib unit-test suite wired into .githooks/checks alongside py_compile. History renders with the new names.
- Teknobu standards kit v3.2: CLAUDE.md project instructions, .teknobu.json configuration, git hooks for commit format and branch protection, GitHub workflows and PR template, documentation structure, and .gitignore rules for standard artifacts.

## 4.0
- Renamed: the kit is now the **Sonelo Solution DevKit** (repo `TeknobuGroup/SoneloSolutionDevKit`). Machine home moves to `~/.claude/sonelo` with automatic migration; old markers, `.teknobu.json` and `TEKNOBU_*` escape hatches remain recognised. New escape hatches: `SONELO_SKIP`, `SONELO_ALLOW_MAIN`, `SONELO_SKIP_HOOKS`. Presets: `sonelo` (alias of `teknobu`).
- Worklog 1.13: the pot defaults to `~/Worklog` on every machine (configured pots unchanged).
