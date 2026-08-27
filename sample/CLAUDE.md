# App

Some existing notes.

<!-- sonelo-devkit:pipeline:start -->
## Change pipeline

Every change goes through: plan -> implement -> review -> test -> verdict -> docs. The lead is this session; the agents are its specialists. Run `/post-change` once per work block - before reporting the work done, not per edit.

### Risk tiers
- **Fast lane**: docs, copy, styling, comments, and design-lane changes (below). No plan mode, no impact report. Reviewers, hooks, the Stop gate and CI still apply.
- **Full pipeline**: anything touching the database or migrations, auth, edge functions, shared types or contracts, or code used in more than one place. Plan mode and the impact-analyst report are mandatory before editing; after the report, record `.claude/state/<branch>/impact.json` (`{"at": "<ISO time>", "touches": ["..."]}`) - the post-edit hook nudges once per branch until it exists.
- If unsure which tier a change is, it is full pipeline.

### Reviewers are triggered by the diff, not by memory
The hooks compute what is due from the changed files (`sh .claude/hooks/pipeline-state.sh due`), the session is briefed at start, and the Stop gate requires a fresh verdict covering:

| Changed | Reviewer due |
|---|---|
| any code | `code-reviewer` |
| *.tsx, *.jsx, *.css, *.scss, tailwind.config.* | `design-reviewer` |
| supabase/, functions/, auth paths, .github/workflows/ | `security-reviewer` |

Run the due reviewers in one message, in parallel; `/post-change` does this and records the verdict. If something blocks a reviewer from running - a missing tool, a worktree, a session instruction - say so in the same message as the work: after two blocked stops the gate lets the session end so the gap is reported, never hidden.

### Rules that prevent bugs
- Any bug fix starts with a failing test that reproduces it, then the fix, then the test goes green. No exceptions.
- Migrations are append-only: never edit an existing file under `supabase/migrations/`; add a new one. After any migration change, regenerate types and commit them.
- Errors must surface: a request that can fail has a visible failure state in the interface and a logged error on the server. A silent catch is a bug.
- The type checker and linter run on every edit (PostToolUse hook). Fix what they report before moving on; never disable a rule to pass.
- Never report a visual change as done on the strength of type checks, lint, tests and the build alone - none of them can see the screen. Render it, or run `design-reviewer`.
- "Done" means: reviewers' verdict clear, tests green, CHANGELOG.md entry, UAT document for the PR, STATUS.md current.

### Design-led, build-safe
- When building or changing a screen, make the design decisions yourself, within `.claude/rules/design.md`: hierarchy, empty/loading/error states, spacing, reuse of the existing component for the same job. Do not ask; decide and say what you decided.
- A design decision may never change data flow, contracts, or logic. If it would, it is a full-pipeline change and is planned first.
- `/design-pass <screen>` applies the design-reviewer's polish and consistency findings in the fast lane and leaves anything that blocks or hurts the task for a human.

### Loop cap
- Review -> fix -> re-review runs at most twice. If a reviewer still reports a blocker after two rounds, stop and ask the user. The Stop gate blocks at most twice per work-state, then requires plain disclosure of what is unmet.
<!-- sonelo-devkit:pipeline:end -->

<!-- sonelo-devkit:start v4.2 (managed by repo_setup.py; edit outside these markers) -->
## Sonelo standards

**Branches.** Work on `prelive`; it deploys to its own URL and database. `main` is production and only changes through a pull request from `prelive` (`gh pr create --base main --head prelive --fill`). Never push to `main` directly and never force-push `prelive` or `main`. If you find yourself on `main` with uncommitted work, switch to `prelive` first.

**Commits.** Conventional Commits, enforced by a hook: `type(scope)?: summary`, types `feat fix chore docs refactor perf test build ci style revert`, summary imperative and under 100 characters. One logical change per commit; run the pre-push checks before pushing (`.githooks/checks`).

**Secrets.** Never commit `.env` files, keys, tokens or certificates; the pre-commit hook blocks them. Config comes from environment variables, documented in `.env.example` with empty values. Prelive and production have separate values; set them in the hosting provider, not in code.

**Before pushing.** Typecheck, lint and tests must pass locally (the pre-push hook runs `.githooks/checks`); CI runs the same on GitHub. Database or edge-function changes go to prelive first and are verified there before the pull request. Migrations are files under `supabase/migrations`, never hand edits in a dashboard.

**If a hook blocks you**, fix the cause. `SONELO_SKIP=1` exists for false positives only; say so in the commit message if you use it.
<!-- sonelo-devkit:end -->
