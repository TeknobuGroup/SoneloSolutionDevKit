# ADR-0012 — the types gate waiver is a disclosure, not an enforcement

- Date: 2026-09-06
- Status: Accepted

## Context

The generated `ci-gates.yml` failed any pull request that touched `supabase/migrations/` without a
diff to the generated types file. A policy, grant or data-only migration cannot produce that diff,
so the pull request was unmergeable and the only ways out were editing the workflow or not
shipping. Kit 4.14 added a `Types-not-affected: <reason>` commit trailer as the way through.

That raised an obvious question: what stops one author's honest trailer from waiving a *schema*
migration somebody else added to the same batch? Under this kit's own branching standard the batch
is a whole release train — work happens on `prelive`, the pull request is `prelive` -> `main`, so
every commit since the last release is in range, by every author.

An answer was built: count the commits in range that touched `supabase/migrations/`, count the
reasoned trailers, and require at least as many of the second as the first. It was implemented,
tested, and documented in the migrations rule the kit ships into every `CLAUDE.md`. Review then
found both halves of it wrong.

**It did not enforce.** A single commit body carrying the trailer four times gives three migrations
and four declarations. A docs-only commit carrying a trailer counts as a declaration while touching
no migration. `git cherry-pick -x` copies a trailer body wholesale. The reviewer's summary was that
it "raises the price of the bypass from zero to approximately zero".

**It blocked honest authors.** Two migrations landing with the same timestamp prefix means the
author renames one — a second commit touching `supabase/migrations/`, with no second reason to
give. That is precisely the author 4.14 exists to unblock, blocked again by the fix.

And the documentation asserted the property the shell did not deliver, in four files that ship to
every repo in the estate. A false assurance in a generator is worse than the known-weak gate it
replaced, because the weak gate does not tell anyone it is strong.

## Decision

Any `Types-not-affected:` trailer carrying a reason waives the gate for the pull request. CI prints
the reason in the log. The shipped documentation describes it as what it is — a declaration on the
record for a reviewer to read — and states plainly that one trailer covers every migration in the
range, so the reason has to be true of all of them.

## Alternatives considered

**The per-commit count.** Rejected for the two reasons above: bypassed trivially, and it blocks the
legitimate case. Removed before release rather than shipped.

**`Types-not-affected: <sha> <reason>`, matched against the SHAs of commits that touch
`supabase/migrations/`.** This is the only shape that genuinely enforces per-migration, and it was
rejected on cost rather than on principle. A commit cannot name its own SHA, so it needs a
follow-up commit; and rebase, squash-merge and `cherry-pick` all invalidate every SHA it names.
Across thirteen repos that trades a gate authors can satisfy for one they cannot. If the estate
ever needs real enforcement here, this is the shape to revisit — the constraint to solve first is
naming the migration without naming a SHA.

**Leaving the gate unsatisfiable.** Rejected: it is what stopped a downstream repo and started this
release.

## Consequences

- The gate stops schema migrations with stale types by default and gets out of the way when an
  author says why. It does not, and does not claim to, verify that the reason covers everything.
- The control is a human reading the CI log. That is worth exactly what the reviewer puts into it,
  and the documentation says so rather than implying otherwise.
- The reason is attacker-influenced text printed into a CI log, so the gate strips carriage returns
  before echoing it — `^`-anchoring in the `grep` closes the newline route, a lone CR is the other
  one, and the runner splits log lines on both. `tests/test_repo_setup_types_gate.py` fails if that
  guard is removed.
- Tests run the gate's own shell out of `BUILTIN_PIPELINE` against real git history, under `sh -e`,
  because Actions runs a `run:` block under `bash -e` and a harness without it never exercises the
  `|| true` guards.
