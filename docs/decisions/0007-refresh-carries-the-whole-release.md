# ADR-0007 — `refresh` carries the git hooks and the CI workflow

- Date: 2026-08-28
- Status: Accepted
- Narrows the scope decision recorded for `refresh` in kit 4.3 (see `cmd_refresh`'s docstring and
  ADR-0004's neighbourhood): the git hooks and `ci.yml` were explicitly out of scope. They are now in.

## Context

4.3 introduced `refresh` as the narrow verb. `apply --update-pipeline` also rewrote CI, the
environment doc, `.gitignore`, `.env.example` and the design contract, and ended by creating and
checking out the work branch — a lot of blast radius for "give me this release's agents". So
`refresh` was scoped to `.claude/`, the two kit-owned files under `.github/`, and the managed
`CLAUDE.md` sections. That was right, and it held for three releases, because every release since
had lived under `.claude/`.

4.7 does not. Its feature is a `[glob]` prefix parsed by **`.githooks/pre-push`**, and a CI step
that reads `.githooks/checks` at run time. Under the old scoping, `refresh` on a 4.6 repo:

- left `.githooks/pre-push` at 4.6, so the release's headline feature never arrived;
- left `.github/workflows/ci.yml` at 4.6, so a `[glob]`-scoped line was absent from CI as well;
- **wrote `"kit": "4.7"` into `.teknobu.json` anyway**, so the session-start nudge went quiet and
  `check` reported `ok .teknobu.json (kit v4.7)`.

The repo was marked current while running none of the release. A rollout verb that does not carry
the release, and then says it did, is worse than a wide one — the failure is silent, which is the
same class of defect this release spent four review rounds removing.

## Decision

`refresh` also regenerates `.githooks/commit-msg`, `.githooks/pre-commit`, `.githooks/pre-push` and
`.github/workflows/ci.yml`.

It still does **not** touch: `.githooks/checks` (its own header invites editing, and `pre-push`
reads it at run time), `.env*`, the environment doc, `.claude/rules/design.md`, the deploy workflow,
branches, or the worklog.

## Alternatives considered

- **Leave the scoping and document that 4.7 needs `apply`.** Rejected: `refresh` is what the
  session-start nudge, `update` and `/repo-setup` all recommend, so the documentation would be
  contradicted by three prompts. And it would leave the `"kit": "4.7"` lie in place.
- **Widen only `.githooks/`, not `ci.yml`.** Rejected: a repo would then scope a check locally that
  CI never ran, which is precisely the hole the CI step exists to close.
- **Have `check` report files left at an older version, and change nothing else.** Rejected as the
  whole answer — it turns a silent failure into a visible one, which is an improvement, but the
  operator's only remedy is still `apply`. Worth doing anyway, separately.

## Consequences

- `refresh` is no longer "the narrow verb" in the sense 4.3 meant. It is "take this release",
  which is what its users assumed it already was.
- **A repo that has taken ownership of a generated file keeps it.** `rep.put` only replaces a file
  whose kit marker is intact, so a hand-edited `ci.yml` with the header removed is skipped and
  reported as skipped. That mechanism, not the scoping, is what protects a repo's own work — and
  it is stronger, because it is per-file and visible in the output.
- Every replaced file is still named in the output rather than counted, and backed up under
  `.claude/.backup/`. A workflow remains the highest-privilege thing this command rewrites.
- The blast radius of `refresh` is now closer to `apply --update-pipeline`. The remaining
  difference is real and is why both still exist: `refresh` never writes env files, never rewrites
  the design contract, and never creates or checks out a branch.

## Revisit if

- A release lands a change to `.githooks/checks` itself. That file is the repo's own, so the kit
  would have to merge rather than replace, and this decision does not cover that.
- `refresh` starts being used to move a repo across several major versions at once, where
  regenerating CI from current detection may not match what the repo's build actually needs.
