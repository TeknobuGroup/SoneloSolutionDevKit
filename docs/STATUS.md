# STATUS - teknobu-kit

## Now
- kit v4.2 on prelive heading to main (event-driven pipeline: pipeline-state/session-brief hooks, stop gate requires fresh sig-matched verdict, auto-release via CI + update-aware nudge; ADR-0003; 128 tests green, 30 new)

## Done recently
- 2026-08-25: kit v4.1 → v4.2 (event-driven pipeline; dogfooding caught and fixed --update-pipeline wiping living docs; full pipeline 2 reviewers clear, findings fixed same round)
- 2026-08-24: kit v4.0 → v4.1 (new `worktree` command: new/list/clean; `/worktree` shipped to every repo via pipeline set; ADR-0002 records feature-branch-worktrees decision)
- 2026-08-24: worklog v1.15 → v1.16 (works in git worktrees — hook install resolved via git rev-parse --git-path; failing-test-first; full pipeline 3 reviewers clear over 2 rounds, 98 tests green, CI runs the suite)
- 2026-08-24: worklog v1.14 → v1.15 (mid-session self-upgrade: atomic adoption of newer pot/bin copies, compile-checked; pot bin writes atomic; what's-new announcements; full pipeline 3-reviewer clear over 2 rounds, 75 tests green)
- 2026-08-24: all repos on this machine hand-upgraded to current (stale v1.11 session re-rendered old reports; v1.15 self-upgrade now prevents)
- 2026-08-24: PR #1 prelive → main merged (checks + gates green); fixed kit self-test workflow stale v3 paths, renamed job to `checks` for branch protection

## Blocked
- None

## Next
1. Merge prelive → main so release.yml cuts v4.2 automatically (first auto-release), then one manual `repo_setup.py update` per remote machine (bootstrap into the self-updating loop), then `apply --update-pipeline` per target repo (Perfect Portal first — move its hand-written reviewer section outside the pipeline markers BEFORE refreshing)
2. Investigate pre-existing flexiform PermissionError (~/Worklog logs) and usage-table token bar min-width distortion
