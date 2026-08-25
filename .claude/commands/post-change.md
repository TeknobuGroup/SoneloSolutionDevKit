---
description: Run the change pipeline on the current work block - parallel review, fix loop (max 2), tests, verdict, docs. Once per block, not per edit.
---
Run the pipeline on everything changed since the last commit on this branch (plus any uncommitted work). Do not ask questions; report each stage in a line or two.

1. **Tier.** Decide fast lane or full pipeline per CLAUDE.md. Say which and why in one line.
2. **Review, in parallel.** Launch `code-reviewer` and `security-reviewer` together (and `design-reviewer` if anything under the UI changed). Wait for all three.
3. **Fix loop.** Fix every finding marked *blocks the task* or *hurts the task*. Re-run only the reviewer(s) that reported them. At most two rounds; if a blocker survives two rounds, stop and ask the user with the finding quoted.
4. **Tests.** Run `test-writer` for the changed behaviour (and the failing-test-first rule for any bug fix), then `test-runner`. Red means fix and re-run; same two-round cap.
5. **Verdict.** After the last code or test edit of the block, run `sh .claude/hooks/pipeline-state.sh sig` from the repo root, then write `.claude/state/<branch>/review.json`: `{"branch": "...", "at": "<ISO time>", "sig": "<the sig output>", "verdict": "clear" | "blocked", "blocking": ["..."], "reviewers": {"code": "clear|blocked", "security": "clear|blocked", "design": "clear|blocked|skipped"}, "tests": "green|red"}`. The Stop gate blocks until this exists, covers the reviewers the diff makes due, and matches the current sig - any later code edit makes it stale.
6. **Tail, in parallel.** `changelog-scribe`, `docs-maintainer` and `uat-plan-maintainer` together. Then, if this block is heading for a pull request, `uat-writer`.
7. **Summary.** Five lines: tier, findings fixed, tests, what is in the changelog, what is still open.

Rules: reviewers never edit; only the lead (you) and test-writer write. Never weaken a test to pass it. Never print secrets or env values.
