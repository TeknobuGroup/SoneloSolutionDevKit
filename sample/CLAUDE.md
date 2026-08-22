# App

Some existing notes.

<!-- teknobu-kit:start v1.1 (managed by repo_setup.py; edit outside these markers) -->
## Teknobu standards

**Branches.** Work on `prelive`; it deploys to its own prelive URL and database. `main` is production and only changes through a pull request from `prelive` (`gh pr create --base main --head prelive --fill`). Never push to `main` directly and never force-push `prelive` or `main`. If you find yourself on `main` with uncommitted work, switch to `prelive` first.

**Commits.** Conventional Commits, enforced by a hook: `type(scope)?: summary`, types `feat fix chore docs refactor perf test build ci style revert`, summary imperative and under 100 characters. One logical change per commit; run the pre-push checks before pushing (`.githooks/checks`).

**Secrets.** Never commit `.env` files, keys, tokens or certificates; the pre-commit hook blocks them. Config comes from environment variables, documented in `.env.example` with empty values. Prelive and production have separate values; set them in the hosting provider, not in code.

**Before pushing.** Typecheck, lint and tests must pass locally (the pre-push hook runs `.githooks/checks`); CI runs the same on GitHub. Database or edge-function changes go to prelive first and are verified there before the pull request. Migrations are files under `supabase/migrations`, never hand edits in a dashboard.

**If a hook blocks you**, fix the cause. `TEKNOBU_SKIP=1` exists for false positives only; say so in the commit message if you use it.
<!-- teknobu-kit:end -->
