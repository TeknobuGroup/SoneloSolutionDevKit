# ADR-0008 — Cost visibility by context band and machine settings

- Date: 2026-09-03
- Status: Accepted
- Closes: ADR-0004 "Still open (v4.4)" — the per-session context high-water mark

## Context

ADR-0004 (2026-08-27) fixed a machine regression where the default model had drifted to `fable[1m]`, and the session model, compaction cap, and agent routing choices are the largest levers on cost. But the report could not answer "which session sat at 400k context for three hours" — it collected per-model tokens but no per-request context, and the worklog had no way to show the user their context bands.

A week's usage review (2026-09-03) across this machine measured:
- 83% of spend in main-thread requests above 150k context
- Two sessions hit 999k context over 5–7 days
- Subagents were ~19% of total, but only 9% of the gating reviewers (code, security, impact-analyst), which inherit the main model

The two open questions from ADR-0004 are now answerable: context high-water per session, and cost breakdown by band.

## Decision

Worklog 1.19 and kit 4.9 make cost and context visible at three levels:

1. **Per-request context tracking.** `collect_sessions` records each request's context (input + cache_create + cache_read tokens) and buckets it by band: normal (<150k), elevated (150k–800k), very high (>800k). Bands appear per day in `tokens_by_day_by_band_by_model`; the session's `context_max` is the high-water mark.

2. **Main-thread vs subagent split.** Subagent tokens are moved to their own `subagent_tokens_by_day_by_model`, split from main-thread by transcript membership (sub_keys set) rather than by file, so resumed/sidechained requests deduplicate correctly. This matters because a main thread that spawns many cheap agents can be cheaper than one that doesn't.

3. **Cost visualization.** The weekly report's "## Cost and context" section and the morning page show cost by band, the subagent share, and sessions that hit elevated context. The morning page footer adds this machine's model default, compaction window, and whether 1M context is disabled — from `~/.claude/settings.json`.

4. **Machine settings in doctor.** `repo_setup.py doctor` reports the model default, compaction cap, and 1M disable flag, so regressions like [1m] reappearing are visible on the first run.

## Alternatives considered

- Store per-request context in `tokens_by_day_by_model` as a separate field per model. Rejected: the report would need to reconstruct bands from many small values, and slices from 1.18 would still have no data. Bucketing at collection time gives backward-compatible fallback (no bands → "not collected").
- Use `CLAUDE_CODE_SUBAGENT_MODEL` env var to route Explore/Plan. Rejected: that variable sits above the main model in resolution order, so gating agents (code/security/impact, which inherit) would silently drop to it. The Explore override agent is safer: it declares `model: sonnet` explicitly, and test `test_gating_agents_inherit` is unaffected.
- Show cost by model instead of context band. Rejected: the user question is "where is my spend going", and "opus 70% fable 30%" does not answer it — "150k context 26%, 400k+ context 51%, subagents 23%" does.

## Consequences

- New session keys in the slice schema: `context_max`, `tokens_by_day_by_band_by_model`, `subagent_tokens_by_day_by_model`. Slices from 1.18 and earlier lack these keys; the report and morning page show "not collected" rather than estimates, the same way they mark apportioned sessions.
- Every repo's worklog display will show context bands and subagent share once re-collected (sessions until then are unchanged).
- Machine settings visibility in doctor will surface any drift in `~/.claude/settings.json` immediately.
- The three-band model (150k / 800k thresholds) is a design choice: narrower bands would show more granularity, but the test for the report text guards against labels containing "400", so these specific thresholds are load-bearing.
- `build_morning` now reads `~/.claude/settings.json` for display; missing or unparseable file is a no-op (the line is omitted), not a failure.
