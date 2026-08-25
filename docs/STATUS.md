# STATUS - teknobu-kit

## Now
- kit v4.2 shipped: PR #4 merged, release.yml cut v4.2 automatically in 9s (first auto-release, zip attached), this machine updated. Rollout continues per Next; v4.3 parked (see Next 2)

## Done recently
- 2026-08-25: v4.2 released and adopted here — first CI-cut release verified end to end (tag v4.2 + SoneloSolutionDevKit-v4.2.zip); `config.json` source pinned to TeknobuGroup/SoneloSolutionDevKit (was the pre-rename name, working only via redirect); Fortex nudge confirmed working (offered /repo-setup unprompted), its pipeline block verified stock so the refresh is safe
- 2026-08-25: kit v4.1 → v4.2 (event-driven pipeline; dogfooding caught and fixed --update-pipeline wiping living docs; full pipeline 2 reviewers clear, findings fixed same round)
- 2026-08-24: kit v4.0 → v4.1 (new `worktree` command: new/list/clean; `/worktree` shipped to every repo via pipeline set; ADR-0002 records feature-branch-worktrees decision)
- 2026-08-24: worklog v1.15 → v1.16 (works in git worktrees — hook install resolved via git rev-parse --git-path; failing-test-first; full pipeline 3 reviewers clear over 2 rounds, 98 tests green, CI runs the suite)
- 2026-08-24: worklog v1.14 → v1.15 (mid-session self-upgrade: atomic adoption of newer pot/bin copies, compile-checked; pot bin writes atomic; what's-new announcements; full pipeline 3-reviewer clear over 2 rounds, 75 tests green)
- 2026-08-24: all repos on this machine hand-upgraded to current (stale v1.11 session re-rendered old reports; v1.15 self-upgrade now prevents)
- 2026-08-24: PR #1 prelive → main merged (checks + gates green); fixed kit self-test workflow stale v3 paths, renamed job to `checks` for branch protection

## Blocked
- None

## Next
1. Finish the v4.2 rollout: one manual `repo_setup.py update` per REMOTE machine (this one is done; v4.1's nudge cannot see releases, so each machine needs this once — after it they self-offer);
   then `apply --update-pipeline` per repo. Fortex: safe to refresh now (block verified stock, nudge already offering). Perfect Portal: HELD by Phill while serious work is in flight —
   move its hand-written reviewer section below the `pipeline:end` marker BEFORE refreshing, or delete it (v4.2's shipped section now carries its table and honesty rule, gate-backed)
2. Kit v4.3 "cost becomes visible" — PARKED, plan drafted at ~/.claude/plans/refactored-brewing-pebble.md.
   Budget gate (`budgets` in .teknobu.json, checked by pre-push + CI), test-runner treats a warning that
   recurs every run as a finding, impact-analyst prices a standard before it propagates. Prompted by
   Perfect Portal's 11.2 MB bundle: v4.2 made reviewers run, but nothing in the kit measures cost.
   BLOCKED ON: the mandatory impact-analyst report did not run (Fable 5 usage limit) — re-run it and the
   design check on another model before any edit; the plan lists the open questions (du portability,
   stale dist/, budgets key surviving apply).
3. Investigate pre-existing flexiform PermissionError (~/Worklog logs) and usage-table token bar min-width distortion
