# ADR-0002 — Worktrees hold feature branches that merge into the work branch

- Date: 2026-08-24
- Status: Accepted

## Context
Phill runs several Claude Code sessions in parallel and machines stay on for days.
Git worktrees are the natural mechanism, but the Sonelo standard says "work on
prelive", and two papercuts made worktrees awkward: the worklog reported every
worktree as a separate project (folder-name default), and merged or abandoned
worktrees accumulated with no safe cleanup.

## Decision
Worktrees hold short-lived feature branches that merge INTO the work branch
(prelive) through normal commits; prelive remains the only branch that goes to
main, via pull request. The kit manages them: `repo_setup.py worktree new <branch>`
creates a sibling directory `<repo>-wt-<branch>` (branch name sanitised) and
pre-stamps `.worklog/worklog.json` with the parent repo's project label so
reporting stays under one project; `worktree list` shows dirty/merged state;
`worktree clean` removes only worktrees that are clean AND provably merged, never
deletes branches, and never touches the main worktree. The `/worktree` command
ships to every repo via the pipeline set. This amends the interpretation of "work
on prelive" only; the shipped standards text is unchanged.

## Alternatives considered
- A standing worktree agent: rejected — upkeep is deterministic housekeeping
  (a handful of git commands plus a naming convention), not judgement work.
- Leaving worktrees unmanaged: rejected — the worklog splintering and stale
  worktree litter were already biting on day one.
- Aggressive clean (force-remove, branch deletion, squash-merge heuristics):
  rejected — clean stays conservative; a squash-merged branch looks unmerged to
  git and is removed by hand. A freshly created, untouched worktree counts as
  merged (its branch tip equals the work branch) and may be cleaned; nothing is
  lost — the branch survives and `worktree new` recreates it in seconds.

## Consequences
Parallel sessions get isolated working copies whose worklog activity still rolls
up under one project (the repo column shows which worktree). A freshly created,
untouched worktree (branch tip equal to the work branch) counts as merged and may
be cleaned — shown as "no commits yet"; the branch survives and `worktree new`
recreates it. Feature branches
must actually merge into prelive to be cleaned automatically. The worklog needed
worktree support (v1.16: hook install resolved through `git rev-parse
--git-path`, since a worktree's `.git` is a pointer file); kit v4.1 carries both.
