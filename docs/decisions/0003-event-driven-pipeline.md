# ADR-0003 — The pipeline is event-driven: hooks compute what is due, the gate requires a fresh verdict

- Date: 2026-08-25
- Status: Accepted

## Context
ADR-0001 rejected convention-only enforcement, but the shipped implementation did not
deliver it: the Stop gate only blocked when a verdict said "blocked" — a *missing*
verdict passed silently, so a session that never ran the reviewers ended cleanly. In
target repos (Perfect Portal) the reviewer triggers lived in CLAUDE.md prose and were
skipped; the compromise attempted there ("reviewers are not optional" in bold) is
exactly the alternative ADR-0001 rejected. Separately, "rendered output changed" was a
judgment call the model made inconsistently, and kit updates needed a hand-cut GitHub
release plus remembered per-machine and per-repo steps, so repos drifted.

## Decision
Kit v4.2 moves the triggers from prose to computed state. A shared hook
(`.claude/hooks/pipeline-state.sh`) derives from git: the changed set, the reviewable
subset, which reviewers are due (code always; design on tsx/jsx/css/tailwind; security
on supabase/functions/auth paths), and a content signature ("sig") of the reviewable
work — the diff of only the filtered file list plus untracked file contents, hashed via
`git hash-object`. `/post-change` records that sig in
`.claude/state/<branch>/review.json`; the Stop gate requires a verdict that is present,
covers every due reviewer, and matches the current sig — missing or stale blocks, same
as a missing changelog. A SessionStart hook states outstanding debt at session open.
The gate's loop valve is count-based: whenever a signature can be computed, at most
two blocks per sig (the second demands plain disclosure to the user), then it allows
the stop; signature-less states (detached HEAD, repos without pipeline-state.sh) keep
v4.1 semantics — a session that cannot review
ends honestly, never trapped. `.claude/state/` becomes gitignored. Releases are cut by
CI on every merge to main, and the SessionStart nudge offers `update` (daily throttled,
3s network timeout, silent offline) plus `apply --update-pipeline` per repo — consent
asked at both steps, never auto-applied.

## Alternatives considered
- Stronger CLAUDE.md wording: rejected by ADR-0001 already; advisory text loses to
  context pressure precisely on long sessions where review matters most.
- mtime-based verdict freshness: rejected — clones and checkouts equalise mtimes, and
  the docs/changelog tail agents write after the verdict, so any mtime scheme either
  deadlocks or lies. Content signature over the filtered set is immune to both.
- Hard PreToolUse block until impact.json exists: rejected — blocks are for
  irreversible actions (migrations guard keeps its block); process gets a once-per-
  branch nudge, enforcement waits at the ship boundary.
- Trusting stop_hook_active for loop prevention: rejected — a stdin parse failure
  would loop forever; the count-based marker caps blocks whenever a sig exists.
- Silent auto-update of the kit: rejected — the kit rewrites hooks and gates in every
  repo; the worklog self-upgrades silently because it only observes.

## Consequences
Every kit repo's sessions now refuse to stop while review debt exists — twice — then
disclose instead of looping; "reviewed" becomes a property the gate can check rather
than a claim. The review.json contract gains a "sig" field (old files read as stale,
never crash; mixed-version repos fall back to legacy gate behaviour when
pipeline-state.sh is absent). Verdicts stop being committed. Push to main now publishes
a release automatically, and machines/repos learn about it at session open; the first
manual `update` per machine is the last. The shipped shell templates commit to
lowercase unbraced variables (fill() token safety) and LF endings (.gitattributes),
pinned by tests. `.github/workflows/` counts as code (security reviewer due) since it
is deploy surface; `.claude/` stays outside the reviewable set — the hooks cannot
police edits to themselves, so changes there rely on PR diff review, an accepted
blind spot.
