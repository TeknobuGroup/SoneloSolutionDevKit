# STATUS - teknobu-kit

## Now
- kit v4.3 shipped: PR #5 merged, release.yml cut v4.3 in 13s, this machine updated. Rollout outstanding per repo (see Next 1). Every shipped agent declares its model, the two heavyweight reviewers have a reading budget, and `refresh` is the narrow verb for taking a release. ADR-0004 records why.

## Done recently
- 2026-08-27: kit v4.2 → v4.3 — measured this machine's 28-day spend at $7,254, of which **74% is cache_read** (context re-reads: 98.1% of all token volume; output is 11%). Two causes, both configuration: the machine default was `opus[1m]`, so auto-compact never fired and sessions grew without limit; and seven of eleven agents declared no `model:`, inheriting Opus. Fixed both. Also fixed a silent bug the impact analysis surfaced: design-reviewer's carve-out in `design_files()` meant **no kit-wide frontmatter change had reached an existing repo** since that carve-out was written — it now ships from `BUILTIN_PIPELINE` like every other agent.
- 2026-08-27: machine config (not shipped) — `~/.claude/settings.json` model `opus[1m]` → `opus`; `~/.claude/worklog.json` `prices` filled for the current model line-up, so the worklog's cost column renders (it was written but dormant behind an empty `prices: {}`).
- 2026-08-25: v4.2 released and adopted here — first CI-cut release verified end to end (tag v4.2 + SoneloSolutionDevKit-v4.2.zip); `config.json` source pinned to TeknobuGroup/SoneloSolutionDevKit; Fortex nudge confirmed working, its pipeline block verified stock so the refresh is safe
- 2026-08-25: kit v4.1 → v4.2 (event-driven pipeline; dogfooding caught and fixed --update-pipeline wiping living docs; full pipeline 2 reviewers clear, findings fixed same round)
- 2026-08-24: kit v4.0 → v4.1 (new `worktree` command: new/list/clean; `/worktree` shipped to every repo via pipeline set; ADR-0002 records feature-branch-worktrees decision)
- 2026-08-24: worklog v1.15 → v1.16 (works in git worktrees; failing-test-first; 98 tests green, CI runs the suite)

## Blocked
- None

## Next
1. **Roll v4.3 out, one repo at a time.** This machine is on 4.3; other machines need `update` once. Then per repo:
   `refresh` for the 4.1/4.2 repos — **Fortex** (4.2), **MediaStack** (4.1), **flexiform-shutter-vercel** (4.1), **jbm-frontend-marvel** (4.1), and this repo. Fortex and Perfect both had live sessions on 2026-08-27, so refresh those when they are quiet.
   `apply` (not `refresh`) for the pre-pipeline repos — **ForeBalls** (3.2), **Lawre** (2.0), **hearta** (1.6): they lack the git hooks, CI and `.teknobu.json` stack keys that only `apply` writes, so a refresh would leave them half-upgraded.
   Not kit repos, leave or `/repo-setup` if wanted: HeyRobin, Knecta, PuppyParent, Sonelo CRM, Verloop.
2. **Starter folder cleaned (2026-08-27).** It held ten files that shadowed kit-owned ones on a *fresh* `apply` — six stale agents (that `test-runner` had a blanket `tools: Bash` instead of the narrow allowlist), plus a **pre-v4.2 `stop-gate.sh`**, so every new repo was getting the old Stop gate. Moved to `~/.claude/sonelo/pipeline-stale-20260827/`; verified a fresh apply now lays down all 11 current agents and the current gate. The starter keeps only what the kit does not own (CLAUDE.md, README-SETUP.md, doc templates, seed docs).
3. **Kit v4.4 — cost becomes visible (bytes, and the measurement).** The parked bundle-budget plan (`~/.claude/plans/refactored-brewing-pebble.md`, budget gate in `.teknobu.json` checked by pre-push + CI, test-runner treating a recurring warning as a finding). Plus the missing half of ADR-0004: the worklog collects per-model tokens but records no per-session **context high-water mark**, so "which session sat at 400k for three hours" still cannot be answered from the report. A PostToolUse context watchdog reading `transcript_path` is the mid-session counterpart — verify the hook payload carries it before planning.
4. Investigate pre-existing flexiform PermissionError (~/Worklog logs) and usage-table token bar min-width distortion.
