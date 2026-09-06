# UAT — kit 4.13 — classifying repos for the diary — 2026-09-06

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were NOT pushed to UAT Hub

**Pushed on 2026-09-06.** These cases are now in UAT Hub, project `teknobu-kit`, round 1 -
reconciled across releases and regrouped into six numbered modules, so a tester runs them in
order rather than per release. The section below records why they sat here until then.


`repo_setup.py doctor` reports `UAT_HUB_KEY not set` on this machine, and the `uat-hub` MCP
server failed to connect this session (CONNECTION_CLOSED). The cases below are written out in
full here instead and **must be pushed to UAT Hub before a tester picks them up** — nothing is
lost, but nothing is queued for a tester either. This is the fifth release in a row in that
position; the backlog is listed in `docs/STATUS.md`.

---

## What changed

4.12 shipped the diary with a safe default — every repo is `private` until a human says
otherwise — and no way out of it except hand-editing `.teknobu.json` in each repo. The result was
predictable: eighteen repos on this machine sat unclassified, so the diary could report their
hours and nothing else.

4.13 is the way out of it, in three places:

- **At setup.** `apply` and `refresh` take `--diary-tier private|nickname|own`,
  `--diary-nickname <name|auto>` and `--diary-description "<what it is>"`. `/repo-setup` asks for
  it as question 6, `/new-repo` as question 8, and both pass the answer through.
- **As a sweep.** `repo_setup.py diary --list` shows every repo the worklog knows about with its
  tier and the label a day-file would use; `repo_setup.py diary --repo <path> --tier ...` writes
  one repo's block and nothing else in the file. `/diary` drives it conversationally.
- **In `doctor`**, which now counts how many repos in the pot have a tier at all.

Two things are deliberately *not* automatic, and the cases below check both:

- **The tier and the description are never inferred.** A tier this tool guessed from a folder
  name would be a classification nobody made — the exact thing the private default exists to
  prevent (`docs/decisions/0011`). Only the codename may be generated, and it is taken from a
  fixed word list, never derived from the repo.
- **Nothing already classified is quietly lowered.** Re-running the kit on a repo that is set to
  `own` must leave it at `own`.

## Preconditions

- Windows, Python 3, this branch checked out. No network needed for any case.
- The worklog pot must exist with at least two repos reporting into it — `python
  repo_setup.py diary --list` prints them. Cases 01 to 03 only read.
- **Cases 04 onwards write into a repo's `.teknobu.json`.** Do them on a scratch repo you create
  in case 04, never on a client repo. Case 11 writes into this kit repo and puts it back.
- Read the exit code after each run with `echo $?` — the case says which is correct.
- Run everything from the repo root: `python repo_setup.py <command>`.

---

## Cases

### 01. The list shows every repo and marks the unclassified ones

**Steps.** Run `python repo_setup.py diary --list`.

**Expected.** A table with one row per repo, a `tier` column and a "what the diary would call it"
column. Rows with nothing recorded start with `!` and read `hours only, by default`. The last
lines say `N of M classified` and give a ready-to-paste command with a real path in it. Exit
code 0.

### 02. A repo that is not on disk is still listed, and said to be missing

**Steps.** Look through the output of case 01 for a repo you know is no longer on this machine.
If every repo is present, skip this case and say so.

**Expected.** That row appears like the others, with `(not on this machine)` after its label. The
command does not fail, and it does not silently drop the row.

### 03. Asking about one repo changes nothing

**Steps.** Run `python repo_setup.py diary --repo .` from this repo. Note what it prints. Run
`git status` afterwards.

**Expected.** It prints the tier (`own`), the path, and `the day-file would call it 'the
developer kit I work inside'`. `git status` shows no change to `.teknobu.json`. Exit code 0.

### 04. A scratch repo starts unclassified and can be set to private

**Steps.** In a folder outside this repo, run `git init uat-diary-scratch` and change into it.
Run `python <path to kit>/repo_setup.py diary --repo . ` — then run it again with
`--tier private`. Open `.teknobu.json`.

**Expected.** The first run says `private` and that nothing is recorded (`private is the
default`). The second writes the file, prints `private`, says the day-file `will call it 'client
work'`, and reminds you to commit `.teknobu.json`. The file contains exactly
`{"diary": {"tier": "private"}}` — nothing else.

### 05. A generated codename is not the repo's name

**Steps.** In the scratch repo, run
`python <path to kit>/repo_setup.py diary --repo . --tier nickname --nickname auto`.
Run it four more times.

**Expected.** Each run prints `codename <Word>, generated - it is not derived from the repo's
name` and then the tier line. The word is a plain English noun; across the five runs you get more
than one different word, and none of them contains "uat", "diary" or "scratch". `.teknobu.json`
holds the most recent one.

### 06. A codename already in use is not handed out twice

**Steps.** Note the codename now in the scratch repo. Create a second scratch repo the same way
and run the same `--tier nickname --nickname auto` command in it, ten times.

**Expected.** None of the ten runs produces the codename the first scratch repo is using. (Both
repos have to be reporting into the worklog pot for this to hold — if the second is brand new and
has never been opened in Claude Code, say so and skip.)

### 07. A tier that cannot work is never recorded

**Steps.** In the scratch repo, remove the `nickname` line from `.teknobu.json` by hand, leaving
`{"diary": {"tier": "nickname"}}`. Then run
`python <path to kit>/repo_setup.py diary --repo . --tier nickname`.

**Expected.** It says `tier nickname needs a codename and none was given, so: <Word>` and writes
that word into the file. It never leaves the file with a `nickname` tier and no nickname — that
combination makes the whole project fall back to "client work" for the day, silently.

### 08. A description that would break the day-file is refused

**Steps.** Run each of these against the scratch repo:
`--tier own --description ""`, then
`--tier own --description "<130 characters — paste any long sentence>"`.

**Expected.** Both are refused before anything is written: the first says the description is
empty, the second says how many characters it is and what the limit is, and both mention it is a
label rather than a paragraph. Exit code 2, and `.teknobu.json` is unchanged.

### 09. A pasted line break is folded, not refused

**Steps.** Run `--tier own --description "a scheduling` then press Enter, type `tool"` and press
Enter (a genuine line break inside the quotes).

**Expected.** It is accepted and recorded as the single line `a scheduling tool`. A typing
accident is not treated as an attack — but the break must not reach the file.

### 10. Nothing already classified is lowered by a plain run

**Steps.** With the scratch repo at `own`, run `python <path to kit>/repo_setup.py apply` in it
with no diary flags at all. Open `.teknobu.json`.

**Expected.** The `diary` block is exactly as it was — still `own`, still with its description.
`apply` writing the private default must only ever apply to a repo that has no block.

### 11. Setting a tier does not disturb the rest of the file

**Steps.** In **this** kit repo, note the whole contents of `.teknobu.json`. Run
`python repo_setup.py diary --repo . --tier own --description "a developer kit" --dry-run`, then
without `--dry-run`. Compare with `git diff`.

**Expected.** The dry run changes nothing on disk. The real run changes only the `description`
inside the `diary` block; `kit`, `work_branch`, `protected`, `applied`, `stack` and
`generated_types` are untouched, and the file is still valid JSON. Put it back with
`git checkout .teknobu.json`.

### 12. A config that cannot be read stops the command

**Steps.** In the scratch repo, corrupt `.teknobu.json` — delete a closing brace. Run
`python <path to kit>/repo_setup.py diary --repo . --tier private`. Check the file afterwards.

**Expected.** It refuses, saying the file exists but is not readable JSON and what that would
cost, and exits non-zero. **The corrupt file is exactly as you left it** — not replaced, not
"repaired". Restore it by hand before continuing.

### 13. Refresh records a tier on a repo that is already up to date

**Steps.** In the scratch repo, run `python <path to kit>/repo_setup.py refresh` once (so it
records the current kit version), then run
`python <path to kit>/repo_setup.py refresh --diary-tier nickname --nickname Kestrel`. Open
`.teknobu.json`.

**Expected.** The second run reports `diary tier nickname` in its file list and the block in the
file is `{"tier": "nickname", "nickname": "Kestrel", ...}`. A flag that is accepted and reported
but not written is the specific failure this case exists for.

### 14. Doctor says how much of the estate is classified

**Steps.** Run `python repo_setup.py doctor`.

**Expected.** Under the `diary` line, a line reading `N of M repos in the pot have a diary tier`,
and — while any are unclassified — a pointer to `repo_setup.py diary --list`. No repo name, no
path, and no tier value is printed here.

### 15. The slash command asks rather than decides

**Steps.** Run `python repo_setup.py install`, then open `~/.claude/commands/diary.md`.

**Expected.** The file exists. Reading it as a tester: it tells the session to go one repo at a
time, to show evidence the user can check themselves, to offer all three tiers with what each
one means, and — in as many words — never to choose a tier for the user or infer one from the
repo. It tells the session not to commit in repos it is not in.

### 16. In a session, /diary walks the unclassified repos

**Steps.** Open Claude Code in this repo and run `/diary`. Answer "private" for the first repo it
offers, then say "stop".

**Expected.** It reports how many repos are unclassified, offers them one message at a time with
the path and something it can see about the repo, and asks which tier. After your answer it runs
one command and shows its output. When you say stop, it stops asking and does not classify
anything you did not answer for. It never picks a tier itself, and it never commits in another
repo.

### 17. The two tools agree about what a tier means

**Steps.** Set the scratch repo to `--tier own --description "a scheduling tool"`. Then run
`python diary_agent.py doctor` from this repo.

**Expected.** The diary's own doctor lists the scratch repo at tier `own` with the label
`a scheduling tool` — the same words `repo_setup.py` printed when it wrote them. If the two ever
disagree about a repo's tier or label, stop and report it: that is the one defect this release
most needs to not have.

---

## Not covered

- Repos that have never reported into the worklog pot. They are invisible to `--list` and have to
  be set with `--repo <path>`; case 04 does this deliberately.
- Committing the changed `.teknobu.json` files. The sweep writes them and says so; committing in
  eighteen repos is a separate job and the command deliberately does not do it.
- Whether a *chosen* tier is the right one for a given client. That is a human judgement and no
  test can make it — which is the reason nothing here infers a tier.
- The blog and the publishing step: a separate repo, unchanged by this release.
