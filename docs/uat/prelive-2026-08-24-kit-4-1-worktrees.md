# UAT — kit v4.1 worktree management and worklog v1.16 worktree support — 2026-08-24

**Branch:** prelive  **Environment:** local machine with git 2.7+  **Prepared by:** Claude Code  **Status:** awaiting sign-off

## What changed

Kit v4.1 adds parallel session management and worklog v1.16 fixes worktree support:

1. **Worktree management** (`repo_setup.py worktree new | list | clean`): New command creates sibling worktrees (`<repo>-wt-<branch>`, branch name sanitised) with automatic worklog project setup so all worktrees in a repo roll up to one project in reports. `list` shows each worktree's state (dirty / committed but unmerged / merged / no commits yet / directory missing). `clean` removes only worktrees that are clean AND provably merged into the work branch, never deletes branches, keeps dirty and unmerged worktrees with actionable reasons, and prunes stale records. The `/worktree` command ships to every repo in the pipeline.

2. **Worklog v1.16 worktree support**: Fixed a bug where `worklog install` crashed in a linked git worktree — a worktree's `.git` is a file (a gitdir pointer), not a directory. The hook now resolves the real hooks directory via `git rev-parse --git-path`, so post-commit hooks land correctly and worktrees work out of the box.

## Preconditions

- Git 2.7+ is installed (worktree command was added in 2.7).
- Python 3.8+ is available.
- A git repository on the work branch (e.g. `prelive`, or a test repo initialised with `git init`).
- For kit worktree tests: the repo_setup.py module from this branch in the .claude/sonelo/ user directory (or run from the local file).
- For worklog tests: worklog_agent.py from this branch.

## Test data

**For worktree new/list/clean:** Create a scratch repo:
```bash
mkdir -p ~/tmp-worktree-test && cd ~/tmp-worktree-test
git init test-repo && cd test-repo
git checkout -b work
git config user.name "Test" && git config user.email "test@test.local"
echo "seed" > README.md && git add README.md && git commit -m "seed"
```

**For worklog in worktree:** Use the same scratch repo plus `worklog_agent.py` from this branch.

**For unit tests:** No setup needed; tests run in temporary directories.

| ID | Area | Steps | Expected | Result | Tester | Date |
|----|------|-------|----------|--------|--------|------|
| UAT-48 | worktree new — directory created | 1. cd into the scratch repo. 2. Run `python repo_setup.py worktree new topic`. 3. Check that a directory `test-repo-wt-topic` was created as a sibling of test-repo. | Directory exists and is a git worktree. | | | |
| UAT-49 | worktree new — branch checked out | 1. In test-repo, run `python repo_setup.py worktree new feature-x`. 2. cd into test-repo-wt-feature-x. 3. Run `git rev-parse --abbrev-ref HEAD`. | Output shows "feature-x" (the branch was created and checked out). | | | |
| UAT-50 | worktree new — existing branch reused | 1. In test-repo, create and checkout a branch: `git checkout -b existing-branch`. 2. Commit something on it. 3. Go back to work branch: `git checkout work`. 4. Run `python repo_setup.py worktree new existing-branch`. 5. cd into test-repo-wt-existing-branch. 6. Run `git log --oneline` and verify the commit from step 2 is there. | The worktree was created on the existing branch and contains the prior commit. | | | |
| UAT-51 | worktree new — branch sanitisation | 1. In test-repo, run `python repo_setup.py worktree new "feature/auth-ui"`. 2. Check the created directory name. | Directory is named test-repo-wt-feature-auth-ui (slashes become dashes). | | | |
| UAT-52 | worktree new — worklog stamped with parent project | 1. In test-repo, run `python repo_setup.py worktree new task-1`. 2. Check test-repo-wt-task-1/.worklog/worklog.json. | File exists and contains {"project": "test-repo"} (or the parent repo's configured project name if .worklog/worklog.json exists in test-repo). | | | |
| UAT-53 | worktree new — worklog inherits parent project name | 1. In test-repo, create .worklog/worklog.json with {"project": "My Project"}. 2. Run `python repo_setup.py worktree new inherit-test`. 3. Check test-repo-wt-inherit-test/.worklog/worklog.json. | File contains {"project": "My Project"} (parent's configured name was inherited). | | | |
| UAT-54 | worktree new — info/exclude updated to share .worklog/ | 1. In test-repo (with kit standards applied, so .gitignore exists), run `python repo_setup.py worktree new x`. 2. Inspect test-repo/.git/info/exclude. | File contains ".worklog/" on a line by itself (added if not present, so .worklog/ in worktrees does not report as dirty). | | | |
| UAT-55 | worktree new — duplicate branch fails gracefully | 1. In test-repo, run `python repo_setup.py worktree new dup`. 2. Run the same command again: `python repo_setup.py worktree new dup`. | Second command exits with error message: "test-repo-wt-dup already exists - open your session there, or pick another branch name". No worktree was created or removed. | | | |
| UAT-56 | worktree list — main worktree flagged and shown first | 1. In test-repo, run `python repo_setup.py worktree list`. | First line shows "test-repo  work  (main worktree)" or similar (main worktree clearly marked and first in output). | | | |
| UAT-57 | worktree list — fresh worktree marked "no commits yet" | 1. In test-repo, create a worktree: `python repo_setup.py worktree new fresh`. 2. Do NOT make any commits in the worktree. 3. Run `python repo_setup.py worktree list`. | The line for test-repo-wt-fresh shows: "test-repo-wt-fresh  fresh  · no commits yet". | | | |
| UAT-58 | worktree list — merged worktree shown as merged | 1. Create a worktree: `python repo_setup.py worktree new merged-task`. 2. cd into test-repo-wt-merged-task. 3. Commit a file: `echo 'work' > file.txt && git add file.txt && git commit -m 'task done'`. 4. Go back to test-repo and merge it: `git merge merged-task`. 5. Run `python repo_setup.py worktree list` from test-repo. | Line for test-repo-wt-merged-task shows: "test-repo-wt-merged-task  merged-task  · merged into work". | | | |
| UAT-59 | worktree list — unmerged worktree shown as unmerged | 1. Create a worktree: `python repo_setup.py worktree new unmerged-task`. 2. cd into test-repo-wt-unmerged-task and commit a unique file. 3. Run `python repo_setup.py worktree list` from test-repo. | Line shows: "test-repo-wt-unmerged-task  unmerged-task  · not merged into work". | | | |
| UAT-60 | worktree list — dirty worktree shown as uncommitted changes | 1. Create a worktree: `python repo_setup.py worktree new dirty`. 2. cd into test-repo-wt-dirty. 3. Add an untracked file: `echo 'wip' > wip.txt` (do NOT stage or commit). 4. Run `python repo_setup.py worktree list` from test-repo. | Line shows: "test-repo-wt-dirty  dirty  · uncommitted changes". | | | |
| UAT-61 | worktree list — missing directory shown as stale | 1. Create a worktree: `python repo_setup.py worktree new stale`. 2. Manually delete the directory: `rm -rf test-repo-wt-stale`. 3. Run `python repo_setup.py worktree list`. | Line shows: "test-repo-wt-stale  stale  · directory gone (run worktree clean)". | | | |
| UAT-62 | worktree clean — removes merged+clean worktrees | 1. Create two worktrees: `python repo_setup.py worktree new to-clean` and `python repo_setup.py worktree new to-keep`. 2. In test-repo-wt-to-clean, commit something: `echo 'x' > x.txt && git add . && git commit -m 'x'`. 3. Back in test-repo, merge it: `git merge to-clean`. 4. In test-repo-wt-to-keep, add an untracked file (do NOT commit): `echo 'wip' > wip.txt`. 5. Run `python repo_setup.py worktree clean`. 6. Check both directories exist or not. | test-repo-wt-to-clean is removed (clean and merged); output shows "removed test-repo-wt-to-clean ... branch to-clean kept". test-repo-wt-to-keep still exists (dirty); output shows "kept test-repo-wt-to-keep ... uncommitted changes". Final line shows "1 removed, 1 kept". | | | |
| UAT-63 | worktree clean — keeps unmerged worktrees | 1. Create a worktree: `python repo_setup.py worktree new unmerged`. 2. Commit something in it. 3. Run `python repo_setup.py worktree clean`. | Output shows "kept test-repo-wt-unmerged ... not merged into work" and directory still exists. | | | |
| UAT-64 | worktree clean — keeps dirty worktrees | 1. Create a worktree: `python repo_setup.py worktree new dirty-keep`. 2. Add an untracked file: `echo 'wip' > wip.txt`. 3. Run `python repo_setup.py worktree clean`. | Output shows "kept test-repo-wt-dirty-keep ... uncommitted changes" and directory still exists. | | | |
| UAT-65 | worktree clean — prunes stale records | 1. Create a worktree: `python repo_setup.py worktree new to-delete`. 2. Manually delete its directory: `rm -rf test-repo-wt-to-delete`. 3. Run `python repo_setup.py worktree clean`. | Output shows "removed test-repo-wt-to-delete - directory already gone; stale record pruned". Worktree list no longer shows it. | | | |
| UAT-66 | worktree clean — never deletes branches | 1. Create and clean a worktree: `python repo_setup.py worktree new nuke`. 2. Commit in it, merge into work, run clean. 3. Check the branch still exists: `git branch -a | grep nuke`. | Branch "nuke" still exists (clean removes the worktree, not the branch; output says "branch nuke kept"). | | | |
| UAT-67 | worktree clean — leaves main worktree untouched | 1. (Precondition: worktree new and clean commands only ever list/clean non-main worktrees.) 2. Run `python repo_setup.py worktree clean` in the main worktree. 3. Check that the main worktree still exists and is the current directory. | Main worktree is not removed or altered. | | | |
| UAT-68 | worktree clean — detached worktrees kept with reason | 1. In test-repo, create a detached worktree: `git worktree add test-repo-wt-detached --detach`. 2. Run `python repo_setup.py worktree clean`. | Output shows "kept test-repo-wt-detached ... detached HEAD; remove by hand: git worktree remove...". Worktree is not removed. | | | |
| UAT-69 | worktree clean — squash-merged branches kept with note | 1. Create a worktree: `python repo_setup.py worktree new squash`. 2. Commit in it. 3. Back in test-repo, squash-merge: `git merge --squash squash && git commit -m 'squash merge'`. 4. Run `python repo_setup.py worktree clean`. | Output shows "kept test-repo-wt-squash ... not merged into work" (squash merges do not register as merged; safe: the branch stays and worktree is kept). | | | |
| UAT-70 | worktree clean — tag shadowing branch name does not fool merge check | 1. Create a worktree on branch "feat": `python repo_setup.py worktree new feat`. 2. Commit in it so feat is ahead of work. 3. Create a tag named "feat" at work's tip: `git tag feat work`. 4. Run clean. 5. Check if the worktree is kept or removed. | Worktree is kept with "not merged into work" message (branch refs/heads/feat is consulted, not tag feat). The tag does not shadow the branch name in the merge check. | | | |
| UAT-71 | worklog v1.16 — install in main repo succeeds | 1. Copy worklog_agent.py v1.16 into a new git repo at .worklog/worklog_agent.py. 2. Run `python .worklog/worklog_agent.py install`. 3. Check that .git/hooks/post-commit was written. | Install succeeds; hook is in place at repo/.git/hooks/post-commit. | | | |
| UAT-72 | worklog v1.16 — install in linked worktree succeeds | 1. In test-repo (from preconditions), create a linked worktree: `git worktree add test-repo-wt-log-test -b log-test`. 2. Copy worklog_agent.py v1.16 into test-repo-wt-log-test/.worklog/. 3. cd into test-repo-wt-log-test and run `python .worklog/worklog_agent.py install`. 4. Check that the post-commit hook was written (in the shared .git/hooks directory, not the worktree's .git pointer). | Install succeeds; `git -C test-repo-wt-log-test rev-parse --git-path hooks` points to the shared hooks dir, and post-commit exists there. No OSError or FileNotFoundError raised. | | | |
| UAT-73 | worklog v1.16 — commit hook fires in worktree | 1. In test-repo-wt-log-test from UAT-72, create a new file: `echo 'test' > new.txt`. 2. Stage and commit: `git add new.txt && git commit -m 'test commit'`. 3. Check that .worklog/agent.log was created and contains a session.jsonl write. | Log file exists; it shows the session was logged (hook ran without error). | | | |
| UAT-74 | /worktree command in kit pipeline | 1. In a repo with kit standards applied (run `python repo_setup.py apply` first), check that .claude/commands/worktree.md exists. 2. Verify the file contains the worktree command hint and description. | File exists; description mentions "Manage git worktrees for parallel sessions", "new <branch>", "list", "clean". | | | |
| UAT-75 | Unit tests — repo_setup worktree functions | 1. Run `python -m unittest tests.test_repo_setup_worktree`. | All tests pass (wt_dirname, wt_list, wt_state, cmd_worktree tests). | | | |
| UAT-76 | Unit tests — worklog worktree hook install | 1. Run `python -m unittest tests.test_worklog_worktree`. | Both tests pass: InstallGitHookInWorktree and InstallGitHookInMainRepo. | | | |
| UAT-77 | .githooks/checks includes worktree tests | 1. Run `.githooks/checks` (or on Windows, `bash .githooks/checks`). | Script passes. Output shows `python -m unittest discover -s tests` runs all tests including worktree ones (98 total); py_compile passes. | | | |
| UAT-78 | Kit repo scenario — worktree new/list/clean on this kit repo | 1. cd into the teknobu-kit repo. 2. Run `python repo_setup.py worktree new feature-branch`. 3. Verify teknobu-kit-wt-feature-branch is created. 4. Run `python repo_setup.py worktree list`. 5. cd into the worktree, create a commit, go back. 6. Run `python repo_setup.py worktree clean` (the worktree is unmerged, so it stays). 7. Manually merge into prelive: `git merge feature-branch`. 8. Run clean again and verify the worktree is removed. | Step 3: Directory created. Step 4: List output shows the worktree. Step 6: Clean output shows "kept ... not merged". Step 8: Clean output shows "removed ... merged into prelive". | | | |

## Not covered here

- **Squash merge cleanup heuristics**: Squash merges are not detected by standard git ancestry checks, so worktrees with squash-merged branches remain unmerged and are kept by design. Future automation (e.g. a branch deletion script) is out of scope.
- **Network/remote tracking during clean**: The clean check consults local refs only (refs/heads). Unpushed branches are never pruned; this is conservative and safe.
- **Concurrent clean operations**: Running `worktree clean` from multiple sessions simultaneously may race. Worktree safety is left to git; the kit does not add locking.
- **Worktree creation in shallow clones or with non-standard git configs**: Tests assume standard git setup; edge cases (shallow clone, custom hooks paths, split git directories) are not exercised.
- **Historical cleanup for worktrees created by older kit versions**: This kit version is the first to introduce worktree management. Pre-existing worktrees from hand-managed git workflows are not imported or tagged.
- **CloudSync or other git-synced folder conflicts**: The worktree naming scheme and .worklog/ sharing are designed for a single machine or NFS mounts; behaviour on cloud-synced folders (Dropbox, OneDrive) is untested.

## Sign-off

| Name | Role | Date | Decision |
|------|------|------|----------|
| | Tester | | |
