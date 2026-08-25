# UAT — prelive -> main — 2026-08-25 — Kit v4.2 event-driven pipeline

**Branch:** prelive  **Environment:** local machine with kit installed, GitHub actions available  **Prepared by:** Claude Code  **Status:** awaiting sign-off

## What changed

Kit v4.2 introduces a computed event-driven pipeline. Instead of trusting developers to run reviews, the pipeline now computes what is due from code changes and enforces it at the stop gate. A new hook (pipeline-state.sh) watches the git diff and calculates which reviewers are required (code always; design for tsx/jsx/css/tailwind; security for supabase/functions/auth paths). The stop gate blocks a session from ending without a fresh review verdict that matches the current work's content signature; it blocks at most twice, then demands disclosure. Session start reports outstanding review debt in one line so developers know what the gate will require. The kit now publishes GitHub releases automatically on every merge to main (via release.yml), and at session start nudges the user to update if a newer release exists (daily throttled, network timeout 3 seconds, always asks first). The post-edit hook nudges once per branch when a full-pipeline path is edited without an impact report. Workflows-as-code now treats .github/workflows files as code (security reviewer due on edits). Verdicts are no longer committed — `.claude/state/` is gitignored. The release zip can be unpacked and `repo_setup.py update` will atomically upgrade worklog_agent.py and repo_setup.py on any machine without affecting other repos.

## Preconditions

- Windows or POSIX machine with Python 3.8+, git, and sh installed.
- This repo cloned to a working state on `prelive` branch (upstream tracking configured).
- GitHub CLI (`gh`) installed and authenticated for the remote repository (for UAT-93 only).
- At least one prior session logged in ~/.claude/projects/ (to test session-start nudge).
- Network connectivity or ability to simulate offline (for update tests).

## Test data

**Setup for stop-gate tests:** Create test files and make edits to trigger different verdict states.

```bash
# Test file for code changes
echo "#!/usr/bin/env python\nprint('test')" > test_code.py

# Test file for workflow changes  
mkdir -p .github/workflows
echo "name: test\non: push" > .github/workflows/test.yml

# Test file for full-pipeline paths
mkdir -p supabase/migrations
echo "-- test" > supabase/migrations/001_test.sql
```

**Setup for update tests:** Ensure the release.yml workflow will run (push to a branch tracked upstream, or manually trigger via GitHub Actions UI).

**Setup for session-start debt:** Create a file with code changes on a clean branch without running /post-change.

| ID | Area | Steps | Expected | Result | Tester | Date |
|----|------|-------|----------|--------|--------|------|
| UAT-79 | Stop gate — initial block | 1. On a clean branch, edit a .py file under the repo root. 2. Stage and commit the change with `git add test_code.py && git commit -m "feat: test"`  3. Attempt to push to prelive with `git push origin HEAD`. | Push is blocked by the stop gate with message mentioning "reviewers due". The block is counted as 1/2. | | | |
| UAT-80 | Stop gate — second block | 1. (Following UAT-79, without running /post-change) 2. Attempt to push again with `git push origin HEAD`. | Push is blocked a second time with the same message mentioning "reviewers due". The block is counted as 2/2. The message now includes disclosure language ("state plainly to the user which are unmet and why"). | | | |
| UAT-81 | Stop gate — disclosure demand | 1. (Following UAT-80, without running /post-change) 2. Attempt to push a third time with `git push origin HEAD`. | Push is allowed (disclosure has been made twice). The session can now stop. Block counter resets on the next signature change. | | | |
| UAT-82 | Stop gate — fresh verdict clears block | 1. Edit a .py file and commit it. 2. Attempt push (blocked). 3. Run `/post-change` to record a fresh review verdict (or `python repo_setup.py post-change`). 4. Attempt push again. | First push is blocked. After /post-change runs and records a new signature and verdict, the second push succeeds. | | | |
| UAT-83 | Stop gate — changelog debt still blocks | 1. Edit a .py file under the repo root (code change). 2. Stage and commit without adding a CHANGELOG.md entry. 3. Attempt push. | Push is blocked with a message mentioning "Code changed but CHANGELOG.md has no entry for it." This maintains v4.1 changelog-blocking behavior. | | | |
| UAT-84 | Stop gate — migration types check | 1. Edit a file under supabase/migrations/. 2. Commit the change without regenerating the types file (specified in .teknobu.json as generated_types or defaulting to src/types/database.ts). 3. Attempt push. | Push is blocked with a message mentioning that the types file must be regenerated. | | | |
| UAT-85 | Session start — report outstanding debt | 1. On a branch with code changes (no prior /post-change verdict), run `python repo_setup.py` or start a new Claude session in this repo. | Session start output includes a one-line brief: "N changed code file(s) on <branch>; reviewers due: <list>; verdict: <state>. The Stop gate will require a fresh /post-change verdict before this session can end." | | | |
| UAT-86 | Session start — silent on clean state | 1. On a branch with all review debt cleared (verdict is "clear"), run `python repo_setup.py` or start a new session. | Session start produces no debt message. Output is silent (no debt summary line). | | | |
| UAT-87 | Post-edit nudge — first code-path edit | 1. On a clean branch with no impact.json, edit a file under supabase/ or functions/ (e.g., supabase/migrations/001.sql). 2. Use Claude Code's Write/Edit tool to make the change. | Advisory message appears once, mentioning that the impact-analyst report is due for full-pipeline paths. Message directs user to create .claude/state/<branch>/impact.json before continuing. | | | |
| UAT-88 | Post-edit nudge — second edit silent | 1. (Following UAT-87, without creating impact.json) 2. Edit another file in supabase/ or functions/. | No advisory message appears. Nudge fires only once per branch; the second edit is silent. | | | |
| UAT-89 | Post-edit nudge — impact.json suppresses advisory | 1. Create an empty file .claude/state/<branch>/impact.json. 2. Edit a file under supabase/ or functions/. 3. Use Write/Edit tool to make the change. | No advisory message appears. Nudge is skipped when impact report exists. | | | |
| UAT-90 | Workflow editor triggers security reviewer | 1. Edit .github/workflows/release.yml (or any file under .github/workflows/). 2. Commit the change. 3. Do NOT run /post-change. 4. Check git status or review.json. | The pipeline-state hook detects .github/workflows/ files as code changes. Stop gate will list "security" as a due reviewer. /post-change will require a security reviewer sign-off. | | | |
| UAT-91 | Signature changes clear block count | 1. Edit file_a.py and commit. 2. Push (blocked, 1/2). 3. Add another change to file_b.py and commit it (new content, different signature). 4. Push (blocked, but now 1/2 for the new signature, not 2/2). | Block counter resets to 1/2 when the content signature changes, even if prior edits on this branch were already blocked twice. | | | |
| UAT-92 | Apply --update-pipeline preserves docs | 1. Run `python repo_setup.py apply --update-pipeline` on this repo with filled-in docs/STATUS.md, docs/ARCHITECTURE.md, and docs/decisions/. 2. Check the files after the command completes. | Files docs/STATUS.md, docs/ARCHITECTURE.md, docs/decisions/, and docs/UAT_PLAN.md are preserved unchanged. Only hook/workflow/config files in managed sections (marked by sonelo-devkit markers) are updated. | | | |
| UAT-93 | Auto-release on main merge — GitHub Actions (CLIENT-SIDE) | 1. Create a pull request from prelive to main. 2. Merge the PR after checks pass. 3. Go to the GitHub repository Actions tab. 4. Check for the `release` workflow run. | The release workflow is triggered by the push to main. It reads VERSION from repo_setup.py, checks if a tag with that version already exists, and if not, packages the kit into a zip and creates a GitHub release with a tag (e.g. v4.2). The zip file contains repo_setup.py, worklog_agent.py, install.sh, install.cmd, and README.md. Release notes are auto-generated. (Verification requires GitHub UI and org/repo access.) | | | |
| UAT-94 | Session nudge offers update (CLIENT-SIDE) | 1. On a machine with v4.2 kit installed (or older), within 24 hours of release v4.2+ being published on GitHub. 2. Start a new session in this repo (or any kit repo on that machine). 3. Check the session start output. | If a newer release exists (checked daily, cached, throttled 3s network timeout), session start prints: "Sonelo kit v4.2 (or newer) is released; this machine has vX.Y. Ask the user: update now? If yes, run `python <path> update`, then offer `apply --update-pipeline` in this repo." Offer is made only once per day per machine (throttled by UPDATE_STAMP mtime). If network is down or times out, the nudge is silent; previous check result is reused from cache. (Verification requires network access and a real released version on GitHub.) | | | |
| UAT-95 | Update from release zip (CLIENT-SIDE) | 1. Run `python repo_setup.py update` on a machine with an older version installed. 2. Accept the prompt (consent is required). 3. Verify that the files have been updated. | Tool downloads the latest release zip from GitHub (or reads from cache if already downloaded within the session). Tool extracts repo_setup.py and worklog_agent.py to the machine home (~/.claude/sonelo/ or machine-specific config). Files are written atomically so interrupted downloads do not corrupt existing versions. Session output shows "kit v4.1 -> v4.2 from <url>" and lists each line from install output (indented with "  "). Message ends with "Repos pick the new worklog up on open; run `apply --update-pipeline` in a repo to refresh its agents, commands and hooks." (Verification requires file system access and network.) | | | |
| UAT-96 | Update consent required | 1. Run `python repo_setup.py update` when an update is available. | Tool displays a prompt asking for consent (e.g., "Update to v4.2? (y/n)") and waits for user input. Update proceeds only if user confirms. No automatic install. | | | |
| UAT-97 | Offline update silent (CLIENT-SIDE) | 1. Simulate offline or disable network (or use a machine with no network). 2. Run `python repo_setup.py update`. | Tool exits cleanly with no error message. No crash or timeout. Next session with network available will retry. (Verification requires network simulation or air-gapped machine.) | | | |
| UAT-98 | Gitattributes LF enforcement | 1. Check the repo for .gitattributes file. 2. Verify its content. | File exists and contains `*.sh text eol=lf` (or similar) to ensure shell scripts use LF line endings cross-platform. Shipped with kit standards. | | | |
| UAT-99 | .claude/state is gitignored | 1. Manually create .claude/state/<branch>/review.json with dummy content (e.g., `{"verdict": "clear", "sig": "abc123"}`). 2. Run `git status`. 3. Check .gitignore. | File does not appear in `git status` output. .gitignore contains `.claude/state/` (or equivalent pattern) to keep verdicts local. | | | |
| UAT-100 | Unit tests — 128+ tests pass | 1. From the repo root, run `python -m unittest discover -s tests`. 2. Check the output for test count and result. | All tests pass (stdout shows "OK" at the end, no FAIL or ERROR lines). Test count is 128 or higher (reflecting new pipeline-state and stop-gate tests in addition to prior v4.0/4.1 suites). | | | |

## Not covered here

- **Perfect Portal and other target repos:** This UAT tests the kit itself. Target repos (Perfect Portal) will receive `apply --update-pipeline` and must verify the new hooks and gates work in their own codebase. Repo-specific review groups and disclosure workflows are not tested here.
- **Supabase migrations and edge functions:** The kit gates enforce that migrations are followed by type regeneration, but the actual migration correctness and edge-function invocation is out of scope.
- **Worklog (v1.16+) in parallel worktrees:** Worklog tests are separate (worklog-oriented UAT documents); worktree-aware v1.16 changes are minimal (git rev-parse --git-path resolution) and already covered in kit-4-1 UAT.
- **GitHub Actions CI/CD:** The ci-gates workflow (typecheck, lint, tests) is assumed working; new release.yml is tested in UAT-93 (CLIENT-SIDE verification of GitHub Actions execution).
- **Vercel, Supabase CLI, and other integrations:** Kit standards document them but do not change them; they are out of scope.
- **Manual release cutting and announcement:** Before v4.2, releases were hand-cut. That workflow is deprecated. The kit now auto-releases on merge to main and sends update nudges; the old manual workflow is not tested.

## Sign-off

| Name | Role | Date | Decision |
|------|------|------|----------|
| | Tester | | |
