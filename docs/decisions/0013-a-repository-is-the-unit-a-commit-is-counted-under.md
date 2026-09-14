# ADR-0013 — a repository, not a directory, is the unit a commit is counted under

- Date: 2026-09-14
- Status: Accepted

## Context

The worklog collects one slice per directory it is installed in, and each slice asks git for that
directory's commits with `git log --all`. Git answers for the **repository**, not for the directory
it was asked in: a linked worktree shares the object store and the refs, and a plain subdirectory
of a checkout is resolved by walking up to the checkout that contains it. So a second checkout of
one repository returns that repository's entire history, and every consumer counted it again.

Measured on the machine where this was found: over the 28-day window the pot reported **2,632
commits where 1,772 were made**, and across everything its slices hold - history older than the
window included - **3,098 against 2,238**. Either way the same **860 duplicates**. Three pairs of
slices were doing it — two linked worktrees and one
nested directory — and the inflation ran at roughly a third of every week, not a rounding error.
One of the pairs carried a different project name, so the duplicate also appeared as a project of
its own on the dashboard.

The counting is not in one place. `build_report` counts commits and builds the day timeline;
`dashboard_data` ships the per-slice lists into the HTML payload, which the dashboard's JavaScript
flattens for the projects table; `build_morning` counts them again for the morning page; and
`diary_agent.build_day` counts them a fourth time. `docs/STATUS.md` already records why that
matters: `session_day_minutes()` and the dashboard's `dayMinutes()` are two implementations of one
rule, and they have drifted before.

## Decision

Record the repository's identity on the slice at collect time — `repo_id`, the `--git-common-dir`
resolved against the slice's root and normalised — and deduplicate **once**, in `load_slices()`,
which every consumer already comes through. Within a group of slices of one repository, take the
**union** of their commits by hash and give it to the checkout at the repository root; the others
keep their sessions and their uncommitted count and are marked `dup_of`.

## Alternatives considered

**A worktree flag.** Recording "is this a linked worktree?" is the obvious identity and it misses
the commonest case on this machine: a nested directory with no `.git` has the same `--git-dir` and
`--git-common-dir` as its parent, so the flag is false on both sides while their histories are
identical. The identity subsumes the flag; the flag does not subsume the identity.

**The `origin` URL.** Two clones of one GitHub repository on one machine are separate working
copies whose histories genuinely diverge, and there is real work in each. A URL would merge them
and lose it.

**Electing one slice's commit list per group.** Simpler, and wrong: group members carry different
`since` windows, so a slice that stopped being collected is often the only remaining holder of
older history the live slice's window has since dropped. Newest-wins loses that; oldest-wins loses
this week. Only the union keeps both.

**Deduplicating in each consumer.** Four copies of a rule that has to agree with a fifth written in
JavaScript. Rejected on the evidence of the last time this repo had two copies of one rule.

**Deduplicating on commit hashes alone, with no identity.** Nearly enough, and not quite: two
repositories seeded with the same content, message, author and second produce the same root commit
— which the test fixture does by accident, and which real repositories do whenever they start from
the same template.
A hash match is therefore strong evidence of a shared history, not proof. Hashes are used only to
group slices that cannot say what repository they belong to — ones written before 1.20, here or on
another machine, and ones where git could not answer at collect time — and a hash match never
merges two slices that both name a repository and name different ones.

**One shared hash is not enough either**, and the first version of this rule acted on one. The
protection above covers only the slices that carry `repo_id`, and the hash pass exists for the
ones that do not — so a single coincidental root commit folded a whole project into an unrelated
repository, its commits re-attributed and its name gone from the report and the dashboard.
**Two** shared hashes are now required: a coincidence is one commit, a shared history is more. The
cost is a repository with exactly one commit and two identity-less checkouts, which stays counted
twice; every slice written from 1.20 on carries `repo_id` and never reaches this pass at all.

That last clause has a consequence for the machine-to-machine import this release does not cover:
a slice written by 1.20 on another machine names a repository, using **that** machine's path. Two
checkouts of one GitHub repository on two machines therefore each name a repository, name different
ones, and are not merged on their shared hashes — correctly, since the rule cannot tell them from
two clones that genuinely diverge. An importer has to strip or translate `repo_id` for the hash
pass to group them; pre-1.20 slices, which have none, group on hashes today.

## Consequences

- **Completed weeks change.** `render()` rewrites every weekly `.md` and `.csv` in the window on
  each run, so four weeks are restated downward and the trend chart moves with them. Weeks older
  than the window are never re-rendered and keep their inflated numbers permanently. Counts quoted
  from a report written before this release were too high.
- **A checkout that only ever contributed commits stops being a project.** It still appears, as
  quiet, and its sessions — if it ever collects any — stay under its own name.
- The slice files on disk are untouched; only the reporting view changes, so the fix applies to
  history already collected rather than only to what is collected from now on. `cmd_status` and the
  collect path keep showing the raw per-file truth, because they describe files, not work.
- `diary_agent.build_day` re-reads git for itself wherever a path is on disk, so it needs the
  `dup_of` marker as well as the deduplicated list; it is the one consumer for which the shared
  loader is not sufficient on its own. Silencing the duplicate then puts a second requirement on
  the keeper: **its git read has to be the repository's, not its own HEAD's.** `day_commits` ran
  `git log` without `--all`, so a linked worktree's unmerged commit — the normal mid-flight state
  of a worktree — was reachable from neither side and dropped out of the day entirely. It now
  passes `--all`, as `collect_commits` always has, which is also what makes the diary and the
  worklog agree instead of applying two rules. A worktree left on a detached HEAD is reached as
  well: `--all` examines every working tree's `HEAD` unless `--single-worktree` is passed, which
  neither side passes.
- **A stash is not work, a git note is not work, and `--all` was reaching both.** `refs/stash` is a ref under `refs/`, and
  hanging off it are `index on <branch>` and `untracked files on <branch>` — single-parent commits
  that `--no-merges` does not filter. So a shelved change was counted, and counted a second time
  for real when it was unstashed and committed. Both sides now pass `--exclude=refs/stash` before
  `--all` (the only order in which `--exclude` applies). Measured in this machine's pot: 4 of the
  3,215 commits its slices held, two of them the same pair seen from both checkouts of one
  repository. `refs/notes` is the same ref one directory over: `git notes add` writes a commit,
  single-parent, authored and dated by whoever annotated, so it survives `--no-merges` and the
  diary's author filter alike and reads as a second piece of work on a commit that already
  counted. Both are excluded now. Small, and the same class of mistake as the directory one —
  asking git a question whose answer is wider than the question.
- **`--all` also reaches `refs/remotes`, and that is deliberate.** The worklog counts every
  author, so a colleague's commits fetched into a clone here appear as activity. The diary filters
  by author instead — and `git_identity()` returns nothing when a repo has no `user.name` or
  `user.email`, which makes that filter fall open. Falling open plus remote-tracking refs means a
  day can be filled with someone else's commits, so `build_day` now says so in its warnings rather
  than letting the day quietly belong to another person.
- **Nothing unusable reaches any consumer, from any slice, from any field.** `build_report`, the dashboard payload
  and the weekly CSVs index these entries without asking — `c["hash"][:7]`, and `c.hash.slice(0, 7)`
  in the dashboard's JavaScript — and `build_report` is not inside `render()`'s try, so one bad
  entry anywhere in the pot stops every report rather than costing the file it came from. So
  `commit_list()` cleans **every** slice on the way in, not only the ones that turn out to be
  duplicates: a slice with no duplicate is the commonest kind and its junk reaches the report just
  the same. A `commits` field that is not a list becomes an empty one; an entry that is not a dict
  is dropped; and a dict whose `hash` or `subject` is the wrong type is **kept with that field
  blanked**, not discarded — its time and its subject may be perfectly good, and dropping it would
  take a real commit out of the count in order to remove a duplicate that was never there. Entries
  with no hash to key on are all kept for the same reason: there is nothing to dedupe them
  against. And `commits` was only the first field to prove the point: `project` is bucketed on,
  `repo` is joined, `uncommitted` is formatted with `%d` and `sessions` is iterated, each of them
  on the same unprotected path, so `clean_slice()` normalises the whole slice at `load_slices()`
  rather than one field at a time. And a slice is deeper than its own fields: `active_min` is
  apportioned across days, `bursts` is walked as pairs, `agents`, `tools` and `commands` are
  added up, and a machine slice's `aw["days"]` and `presence["events"]` are merged and sorted -
  so `clean_session()` and `clean_machine()` sit beside it, and `tok_of()` puts the guard at the
  leaf where the four token sums add rather than cleaning every token map in the pot on every
  run. Twenty-nine malformed shapes were measured stopping every report before this; none after.
  A null is left alone everywhere, because every consumer already reads one as an absent field. `project` is the only field whose absence drops a slice —
  it is the label every count hangs off and there is no honest default — and a dropped or
  repaired file is named in the log, because a slice that vanishes silently looks exactly like a
  quiet week.
- **The dashboard escapes every value it takes from a slice, including the ones from git.** A
  branch name may contain `<`, which git permits in a refname, and the page is opened from disk
  with every project, path, session title and prompt on the machine in reach. `write_dashboard`
  escaping `<` to `\u003c` in the JSON payload prevents a `</script>` breakout of the literal
  and nothing more — the string still holds a real `<` at runtime, so the escaping that matters
  is `esc()` at the point of use.
- **`cmd_status` reads the pot raw, and that is the reason it has to survive it.** It describes
  files rather than work, so it is the one consumer that must not be handed the cleaned view -
  and it is also the command someone runs *because* the pot looks wrong, which makes it the one
  place a malformed file is expected rather than exceptional. It takes its counts through
  `commit_list()` and `clean_machine()` to report them, not to hide them.
- Sessions are per-checkout and are never merged. Nothing here changes tokens, cost or hours.
