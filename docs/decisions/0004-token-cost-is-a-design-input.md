# ADR-0004 — Token cost is a design input, not an afterthought

- Date: 2026-08-27
- Status: Accepted
- Supersedes the scope of the parked "v4.3 — cost becomes visible" plan (bundle budgets), which
  moves to v4.4. The thesis is unchanged; the first instance of it is tokens, not bytes.

## Context

Measured over the retained 28-day window on this machine, across every repo the worklog sees:

| Bucket | Tokens | Cost | Share |
|---|---:|---:|---:|
| input | 207,617 | $1.02 | 0.0% |
| cache write | 165,865,722 | $1,071.55 | 14.8% |
| **cache read** | **10,319,292,449** | **$5,365.82** | **74.0%** |
| output | 31,799,414 | $815.52 | 11.2% |
| | | **$7,253.91** | |

Context re-reads are 98.1% of token volume and 74% of spend. Almost nothing is paid for what
Claude writes; nearly everything is paid for re-reading a context that never shrinks. Two causes,
both configuration rather than conduct:

1. The machine default was `opus[1m]`. A 1M window means auto-compact never fires, so a session
   grows without limit and every subsequent turn re-reads the whole of it. A session sitting at
   400k pays roughly $0.20 per turn before it emits a token.
2. Seven of eleven shipped agents declared no `model:`, so every reviewer, tester and analyst
   inherited the session's Opus. `/post-change` launches several of them in parallel, by design.

The kit had no opinion on either. ADR-0001 rejected convention-only instructions as "advisory,
skippable"; a CLAUDE.md paragraph asking sessions to be frugal is exactly that tier, and it decays
with context precisely when a long session most needs it.

## Decision

Cost is declared in the artefacts the kit ships, where it cannot be forgotten:

- **Every agent declares its model.** Four scribes on `haiku`; design-reviewer, test-writer,
  test-runner and qa-runner on `sonnet`. code-reviewer, security-reviewer and impact-analyst
  declare nothing and inherit the session model — they decide whether a change ships and how it
  is built, and are the ones worth paying for. A test pins all three groups, including the
  deliberate absence, so the gating agents cannot be quietly moved onto a cheap model.
- **Reviewers budget their reading.** code-reviewer and security-reviewer are told the diff is the
  source, not the repo. The budget is on *breadth* (no repo sweeps, no unrelated modules), never
  on depth: following callers of a changed signature is the check that catches regressions in
  files the diff does not touch, and remains in scope.
- **`refresh` exists so taking a release is cheap.** Model routing only helps a repo that adopts
  it. `apply --update-pipeline` refreshed the pipeline but as a flag on a command that also
  rewrote CI, the environment doc, `.gitignore`, `.env.example` and the design contract, and ended
  by creating and checking out the work branch. `refresh` does the pipeline, the hook
  registrations and the managed CLAUDE.md section, records the kit version, and stops.

## Alternatives considered

- **A CLAUDE.md section on context discipline** — rejected under ADR-0001: advisory, skippable,
  and it decays with the context it is trying to manage.
- **Downgrading code-reviewer and security-reviewer too.** Rejected. They are the gate; the saving
  is real but a missed regression costs more than the tokens. The saving comes from the four
  agents whose work is judged against a written contract.
- **A pre-flight hook that refuses to spawn an expensive agent.** No hook observes a subagent
  before it starts. Not implementable today; the measurement in v4.4 is the substitute.

## Consequences

- `refresh` is now the advice everywhere the kit used to say `apply --update-pipeline`: the
  session-start nudge, `update`, `/repo-setup`, README, ARCHITECTURE.
- design-reviewer ships from `BUILTIN_PIPELINE` like every other agent. Its old carve-out in
  `design_files()` kept the body and rewrote only a hardcoded `tools:` line, so **no kit-wide
  frontmatter change had reached an existing repo since that line was introduced**. The per-repo
  brand file `.claude/rules/design.md` — the actual reason for the carve-out — is still the
  repo's own and is never overwritten.
- `.claude/.backup/` is in the shipped `.gitignore`. It never was, so every repo that ran
  `--update-pipeline` was left with untracked backup copies of its own agents.
- A repo refreshed by `refresh` records the new kit version, or the session-start nudge would
  report it as stale forever and point back at the heavy command.
- The starter-folder precedence documented in README was wrong and is corrected rather than
  implemented: a starter seeds files the kit does not own; files the kit owns are restored to the
  current release on refresh. Verified on this machine — the starter held six agents that were
  strictly older than the built-ins, including a `test-runner` still carrying
  `<TODO: build command>`, which plain `apply` was seeding into every new repo.

## Still open (v4.4)

Bundle budgets, per the parked plan.

**Closed (v4.9/1.19):** The per-session context high-water mark was captured in ADR-0008. Worklog now records
`context_max` per session and `tokens_by_day_by_band_by_model` for main-thread requests, so "which session sat
at 400k for three hours" is answerable from the report and morning page. The budget gate remains future work.
