# ADR-0009 — The post-edit hook reports regressions, not the whole project

- Date: 2026-09-03
- Status: Accepted

## Context
The PostToolUse hook has run a whole-project type check and a full lint of the edited
file on **every** Edit/Write/MultiEdit since kit 4.2. Seven releases later, nobody had
measured it. Measured on this machine:

- It fired **1,411** times in one repo (786 in another, 344 in a third).
- The type check was `tsc --noEmit -p tsconfig.json`. A Vite/React `tsconfig.json` is a
  solution file — `"files": []` plus `"references"` — so without `-b` that command
  compiles the empty file list. It cost 2-4 seconds per edit and could not, even in
  principle, report an error.
- The lint reported every error in the file. With an eslint ratchet, ~450 of 826 source
  files carry accepted errors, so the hook `exit 2`'d on more than half of all edits and
  fed the session debt it had not written. Each of those is a wasted turn at full
  context, and cost is turns × context.
- It invoked both through `npx`, which re-resolves the package every time: 6-7s against
  3.0-3.9s for the installed binary, for an identical result.

`.githooks/checks` already runs `npm run typecheck` on pre-push, and CI runs it again.
The per-edit check was a third copy that checked nothing. ADR-0004 says token cost is a
design input; this hook was the largest cost in the kit and had never been measured
against it.

## Decision
The hook lints the edited file and reports **only errors the change added** on top of
what the repo already accepts — the ratchet baseline where one exists, floored by a
per-file cache under `.claude/state/lint/`, and zero for a file the session created. It
calls the installed eslint binary directly. The whole-project type check is removed; it
runs on push and in CI, which is where a whole-project check belongs.

The managed `CLAUDE.md` block asserted the old behaviour to nine repos and is corrected.
Nothing is relaxed: `never disable a rule` stands, and `never raise the lint baseline` is
added, because reporting less must not mean permitting more.

## Alternatives considered
- **`tsc -b` instead of removing it** — fixes the no-signal bug but not the cost: a
  project build on every edit is worse, not better, and pre-push already does it.
- **Type-check only the edited file** — `tsc` has no honest single-file mode under a
  project config; you get either the project or a file with no module resolution.
- **Keep reporting all lint errors, but exit 0** — the session still reads them, still
  spends the context, and still tends to "fix" them. Silence is the feature.
- **Do nothing per edit** — rejected: an error the change actually introduced is worth
  catching at the moment it is written, while the reasoning is still in context.

## Consequences
- A type error is now caught on push rather than on the edit that wrote it. That is a
  real loss of immediacy, accepted knowingly: it was being paid for on all 1,411 edits
  and collected on none.
- The hook is stateful per file (`.claude/state/lint/`, gitignored). A cleared cache with
  no baseline re-accepts a tracked file's current count — it under-reports rather than
  nagging, deliberately.
- A repo with no ratchet baseline gets the cache alone, so the first edit of a file is
  always silent. Adding a baseline makes it strict.
- Reverses part of ADR-0001's "enforce at the moment of the edit". The pipeline still
  enforces; it enforces on the change rather than on the repo.
- Nothing recomputes this cost automatically yet. A benchmark that fails CI when a hook
  gets slower is the obvious follow-on and is not in this release.
- Reading a per-file accepted level makes the hook stateful, and state has two failure
  modes the first cut had. The eslint report needs a per-process name: worktrees hold
  separate state directories, but two sessions in one checkout share one, and a report read
  by the wrong hook scores a file against another file's count. And the repo root must be
  stripped from the edited path case-insensitively: Windows returns `C:/...` for a cwd
  Python reports as `c:/...`, and a missed strip leaves the path absolute, matches no
  baseline key, and reports the whole file as new. Both were caught in review before
  release; both are pinned by tests that fail against the unfixed hook.
