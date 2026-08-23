# CLAUDE.md — teknobu-kit (Sonelo Solution DevKit)

The Sonelo Solution DevKit: repo standards, an agent pipeline, infrastructure creation and a work log for Claude Code projects — one Python file per tool, standard library only, Windows first. Used by Teknobu Group developers on every project.

## Session start

At the start of every session, read `docs/STATUS.md` before doing anything else.

## Commands

- Syntax check: `python -m py_compile repo_setup.py worklog_agent.py`
- Environment check: `python repo_setup.py doctor` (reports tool/login presence, never values)
- Build: none — plain Python scripts, nothing to compile or bundle.
- Tests: none yet — `.githooks/checks` is empty; add commands there when a suite exists (pre-push and CI run that list).
- Supabase: not applicable — this repo has no database; the Supabase rules it ships apply to target repos.

## Conventions

- Python 3, standard library only; each tool stays a single self-contained file
  (`repo_setup.py`, `worklog_agent.py`) so the one-line install keeps working. Windows first.
- `sample/` shows what the kit generates in a target repo; keep it in step with the generators.
- Files between `sonelo-devkit` markers are managed by `repo_setup.py` — edit outside the
  markers only; `apply --update-pipeline` refreshes the managed parts (backups kept).
- `.claude/rules/supabase.md` and the multi-tenant rules are standards this kit ships to
  product repos; they do not describe this repo itself.
- Decisions that change architecture or reverse a prior choice get a dated record in
  `docs/decisions/` — check there before proposing to undo existing behaviour.

## Where knowledge lives

- Current state / in-flight work: `docs/STATUS.md`
- System map: `docs/ARCHITECTURE.md`
- Why it's like this: `docs/decisions/`
- Domain deep dives: `docs/modules/`
- UAT scenarios: `docs/UAT_PLAN.md`

<!-- sonelo-devkit:pipeline:start -->
## Change pipeline

Every change goes through: plan -> implement -> review -> test -> verdict -> docs. The lead is this session; the agents are its specialists. Run `/post-change` once per work block, not per edit.

### Risk tiers
- **Fast lane**: docs, copy, styling, comments, and design-lane changes (below). No plan mode, no impact report. Hooks, the Stop gate and CI still apply.
- **Full pipeline**: anything touching the database or migrations, auth, edge functions, shared types or contracts, or code used in more than one place. Plan mode and the impact-analyst report are mandatory before editing.
- If unsure which tier a change is, it is full pipeline.

### Rules that prevent bugs
- Any bug fix starts with a failing test that reproduces it, then the fix, then the test goes green. No exceptions.
- Migrations are append-only: never edit an existing file under `supabase/migrations/`; add a new one. After any migration change, regenerate types and commit them.
- Errors must surface: a request that can fail has a visible failure state in the interface and a logged error on the server. A silent catch is a bug.
- The type checker and linter run on every edit (PostToolUse hook). Fix what they report before moving on; never disable a rule to pass.
- "Done" means: reviewers' verdict clear, tests green, CHANGELOG.md entry, UAT document for the PR, STATUS.md current.

### Design-led, build-safe
- When building or changing a screen, make the design decisions yourself, within `.claude/rules/design.md`: hierarchy, empty/loading/error states, spacing, reuse of the existing component for the same job. Do not ask; decide and say what you decided.
- A design decision may never change data flow, contracts, or logic. If it would, it is a full-pipeline change and is planned first.
- `/design-pass <screen>` applies the design-reviewer's polish and consistency findings in the fast lane and leaves anything that blocks or hurts the task for a human.

### Loop cap
- Review -> fix -> re-review runs at most twice. If a reviewer still reports a blocker after two rounds, stop and ask the user.
<!-- sonelo-devkit:pipeline:end -->

<!-- sonelo-devkit:start v4.0 (managed by repo_setup.py; edit outside these markers) -->
## Sonelo standards

**Branches.** Work on `prelive`; it deploys to its own URL and database. `main` is production and only changes through a pull request from `prelive` (`gh pr create --base main --head prelive --fill`). Never push to `main` directly and never force-push `prelive` or `main`. If you find yourself on `main` with uncommitted work, switch to `prelive` first.

**Commits.** Conventional Commits, enforced by a hook: `type(scope)?: summary`, types `feat fix chore docs refactor perf test build ci style revert`, summary imperative and under 100 characters. One logical change per commit; run the pre-push checks before pushing (`.githooks/checks`).

**Secrets.** Never commit `.env` files, keys, tokens or certificates; the pre-commit hook blocks them. Config comes from environment variables, documented in `.env.example` with empty values. Prelive and production have separate values; set them in the hosting provider, not in code.

**Before pushing.** Typecheck, lint and tests must pass locally (the pre-push hook runs `.githooks/checks`); CI runs the same on GitHub. Database or edge-function changes go to prelive first and are verified there before the pull request. Migrations are files under `supabase/migrations`, never hand edits in a dashboard.

**If a hook blocks you**, fix the cause. `SONELO_SKIP=1` exists for false positives only; say so in the commit message if you use it.
<!-- sonelo-devkit:end -->
