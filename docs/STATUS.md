# STATUS - teknobu-kit

## Now
- v1.15 ready for main merge (self-upgrade mechanism + what's-new announcements complete; 3-reviewer clear over 2 rounds; 75 tests green)

## Done recently
- 2026-08-24: worklog v1.14 → v1.15 (mid-session self-upgrade: atomic adoption of newer pot/bin copies, compile-checked; pot bin writes atomic; what's-new announcements with session-start message, dashboard header 7-day window, morning page 3-day window, state in pot/.whats-new.json; full pipeline 3-reviewer clear over 2 rounds, 75 tests green)
- 2026-08-24: all repos on this machine hand-upgraded to current (stale v1.11 session re-rendered old reports; v1.15 self-upgrade now prevents)
- 2026-08-24: PR #1 prelive → main merged (checks + gates green); fixed the kit self-test workflow's stale v3 machine-home paths and renamed its job to `checks` to satisfy branch protection
- 2026-08-23: Repo refreshed to Sonelo Kit v4.0, all standards applied; remote renamed to TeknobuGroup/SoneloSolutionDevKit, main branch protected with gates
- 2026-08-23: worklog agent v1.13 → v1.14 (Agents card regrouped by project, friendly persona names, share-bar accuracy, raw-id tooltips, stdlib tests wired into hooks, full pipeline 3-reviewer clear, 36 tests green)

## Blocked
- None

## Next
1. Release decision: cut a new GitHub release (kit version decision pending) so remote machines' `repo_setup.py update` picks up worklog v1.15
2. Investigate pre-existing flexiform PermissionError (~/Worklog logs) and usage-table token bar min-width distortion
