# STATUS - teknobu-kit

## Now
- None (v1.14 merged to main)

## Done recently
- 2026-08-24: PR #1 prelive → main merged (checks + gates green); fixed the kit self-test workflow's stale v3 machine-home paths and renamed its job to `checks` to satisfy branch protection
- 2026-08-23: Repo refreshed to Sonelo Kit v4.0, all standards applied; remote renamed to TeknobuGroup/SoneloSolutionDevKit, main branch protected with gates
- 2026-08-23: worklog agent v1.13 → v1.14 (Agents card regrouped by project, friendly persona names, share-bar accuracy, raw-id tooltips, stdlib tests wired into hooks, full pipeline 3-reviewer clear, 36 tests green)

## Blocked
- None

## Next
1. Cut a new GitHub release (needs a kit version decision — latest release is still v4.0/worklog 1.13) so remote machines' `repo_setup.py update` picks up worklog v1.14; one-line URL installs already serve v1.14 from main
2. Monitor active old-version sessions (nurture-loop-tek v1.11, flexiform-shutter-vercel v1.12, ForeBalls v1.12) — they auto-upgrade at next session start; meantime hooks render with old layout
3. Investigate pre-existing flexiform PermissionError (~/Worklog logs) and usage-table token bar min-width distortion
