# UAT — worklog 1.20 — a commit is counted once — 2026-09-14

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were pushed to UAT Hub

**Pushed on 2026-09-14** to project `teknobu-kit`, module `07. Worklog - a commit is counted once`:
18 cases, into round 1. The hub read back **123 cases across 7 modules**, up from 105, so all 18
landed and none duplicated.

They are numbered and must be run top to bottom. Six of them deliberately damage files in the pot:
case 01 takes the backup first, cases 13–16 break a slice, a session field and the machine file and
then run `status` against the wreckage, and case 18 puts everything back. A tester who starts in
the middle will be editing their own work-log history with no copy of it.

---

## What changed

### A repository's commits are counted once, however many checkouts of it report

`collect_commits()` runs `git log --all` at a slice's path, and git answers for the **repository**,
not the directory. So any second checkout of one repository reported that repository's whole
history again — a linked worktree, or a plain subdirectory of a checkout that has no `.git` of its
own and which `git -C` simply walks up from.

Measured on this machine on 14 September, across the 28-day window: **2,084 commits where the same
slices without the fix say 3,212** — 1,128 of them duplicates. Per week: W34 521, W35 595, W36 493,
W37 468.

Three pairs on this machine, all confirmed by `git rev-parse --git-common-dir`:

| slice | why it duplicated |
|---|---|
| `flexiform-shutter-vercel-wt-codex-work` | linked worktree of `flexiform-shutter-vercel` |
| `nurture-loop-codex` | linked worktree of `nurture-loop-tek`, reporting under Knecta |
| `PuppyParent/my-puppy-pal` | plain subdirectory, **no `.git` at all** |

The third is why a "is this a worktree?" flag would not have been enough: `my-puppy-pal` has no
`.git`, so the flag reads false on both sides. Only the repository's identity catches it.

Slices now record `repo_id` when they are written, and `dedupe_repositories()` groups on it at
`load_slices()`. Slices with no `repo_id` — ones written by older agents, and every slice the
machine-to-machine import brings in, whose paths belong to another machine — fall back to sharing
a commit hash, with **two** shared hashes as the threshold. One is a coincidence: two repositories
seeded from the same template share their first commit exactly, and absorbing a whole project on
the strength of that would be worse than the bug.

A group's commits are **unioned by hash**, not taken from an elected slice. Members hold different
windows: `nurture-loop-codex` is frozen at 7 September and still carries 24 commits from 11–14
August that Knecta's live slice has dropped past. Newest-wins would lose those; oldest-wins would
lose this week.

The slice **files on disk are untouched**. Only the reporting view changes, and `status` still
reads them raw, because it describes files rather than work.

### Two other things `git log --all` was counting

`refs/stash` and `refs/notes` both hold single-parent commits, which `--no-merges` does not filter.
Stashing work added `index on <branch>: ...` and `untracked files on <branch>: ...` to the log;
`git notes add` added `Notes added by 'git notes add'`. Both are excluded now — and `--exclude=`
has to come **before** `--all` to have any effect, which is the kind of thing that fails silently.

### No single malformed slice can stop every report

`load_slices()` is the one choke point every report comes through — the weekly reports, the CSVs,
the dashboard payload, the morning page and `diary collect`. `build_report()` is **not** inside
`render()`'s `try`, so one bad file in the pot stopped every project's report for every project,
and did it silently: the hook worker logs the traceback and the reports simply go stale.

Slice files are untrusted input. They are written by other machines' agents, can be truncated
mid-write, and are copied between machines by hand.

`clean_slice()`, `clean_session()` and `clean_machine()` now normalise a slice, its sessions and a
machine's desk time at that choke point, and `tok_of()` guards the leaf where the four token sums
actually add — rather than walking every token map in the pot on every run to promise it from
above. **Twenty-nine malformed shapes were measured stopping every report before this, and none
after.** A `null` is left alone throughout: every consumer already reads one as an absent field,
and flagging it would make the log cry wolf over ordinary slices.

`cmd_status` is hardened separately rather than moved to the cleaned view, because it is the
command someone runs *because* the pot looks wrong — which makes it the one place a malformed file
is expected rather than exceptional.

### A branch name cannot put markup into the dashboard

Git permits `<` in a refname. `write_dashboard`'s `<` JSON escaping stops a `</script>`
breakout but leaves a real `<` at runtime, so only `esc()` at the point of use protects the page.

### The diary's author filter falls open off disk too, and only the on-disk half said so

`build_day` filters a slice's commits by author, and falls open when it has no author to filter on.
On disk that happens when the repo has no `user.name` or `user.email`; off disk there is no git to
ask at all. Those commits came from `git log --all`, which reaches `refs/remotes`, so an unfiltered
day publishes colleagues' work as yours. Only the on-disk branch said so; the off-disk branch
warned that its commits carry no file counts, which is a different fact and reads like the only one.

---

## What a reader of old numbers needs to know

**Every commit figure recorded before 1.20 is too high.** `render()` rewrites each
`weekly/worklog-YYYY-Www.md|.csv` inside the 28-day window on every run, so the four weeks in it
restate themselves downward on the first render and the Weeks chart moves with them. Weeks
**older** than the window are never re-rendered and keep their inflated numbers permanently.
Nothing recomputes them. That is disclosed rather than fixed.

Sessions, hours, tokens and cost never went through the duplicated lists and are unchanged
everywhere. The way to check the fix against live data is the difference, not the absolute.

`nurture-loop-codex` stops being a project of its own: its commits belong to the `nurture-loop-tek`
repository and count under Knecta. With no sessions of its own it lists as quiet.

Two separate clones of one upstream repository on one machine now merge into whichever is the
repository root, even under different project names. That is the same rule that fixes
`nurture-loop-codex`, and it is the one behaviour in this release worth disagreeing with.

---

## Verification

- **631 tests, OK** — `python -m unittest discover -s tests`, run by `.githooks/pre-push` on both
  pushes of this branch.
- `python -m py_compile repo_setup.py worklog_agent.py diary_agent.py` — clean.
- Four review rounds. Round three: `security-reviewer` blocked on 4 findings, all fixed red-first.
  Round four: `code-reviewer` **clear**, 6 findings, all 6 fixed — round four verified round three's
  fixes independently rather than taking them on trust. `design-reviewer` not due: no `.tsx`,
  `.jsx`, `.css`, `.scss` or tailwind config in the diff; the one dashboard change is an `esc()`
  call in JavaScript embedded in `worklog_agent.py`.
- Re-rendered against this machine's pot and checked against the figures measured before the fix.

## Not in this release

No `repo_setup.py` version bump: release tags come from its own `VERSION`, and this is a
worklog-only change. The fleet converges on **1.20.2** through the pot's `bin/worklog_agent.py`
(refreshed 2026-09-14) and the self-upgrade in `cmd_run`; the other repos take it at their next
session start or `run --sync`.

## Known, and deliberately not fixed here

`norm()` is normcase plus normpath, not a resolve. A checkout reached through a symlink, a junction,
a `subst` drive or an 8.3 name spells its `repo_id` differently and so names a different repository
— and because both slices then *have* a `repo_id`, the shared-hash fallback is deliberately closed
to them, so that pair silently goes back to being counted twice.

`repo_root()` is `HERE.parent`, which is right for the installed copy in `<repo>/.worklog/` and
wrong for anyone running the kit's own checkout copy from the repo root: it resolves to the folder
*above* the checkout. On 14 September that wrote a phantom `TeknobuKitRepo` project into the pot,
duplicating this repo's sessions, tokens and cost. The artifacts were removed by hand the same day.
The guard is not in this release.
