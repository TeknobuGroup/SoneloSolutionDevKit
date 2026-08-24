---
description: Manage git worktrees for parallel sessions - new <branch> creates a sibling worktree wired for the worklog, list shows state, clean removes merged ones
argument-hint: new <branch> | list | clean
---
Run `python "$HOME/.claude/sonelo/repo_setup.py" worktree $ARGUMENTS` from the repo root (default to `list` when no argument was given) and relay its output plainly.
- `new <branch>`: report the created path and tell the user to open their next Claude Code session there; the worklog is pre-stamped to report under this repo's project.
- `clean`: a "kept" line is information for the user - uncommitted work, or a branch git cannot prove merged (squash merges look unmerged). Never force-remove a worktree and never delete branches to make clean succeed.
