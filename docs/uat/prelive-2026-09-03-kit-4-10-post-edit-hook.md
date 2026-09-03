# UAT — kit 4.10 — the post-edit hook reports regressions, not debt — 2026-09-03

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were NOT pushed to UAT Hub

`repo_setup.py doctor` reports `UAT_HUB_KEY not set`, and the `uat-hub` MCP server failed to
connect this session (CONNECTION_CLOSED). The cases below are written out in full here instead
and **must be pushed to UAT Hub before a tester picks them up** — nothing is lost, but nothing
is queued for a tester either. This is the second release in a row in that position; the 28
cases in `prelive-2026-09-03-kit-4-9-worklog-1-19.md` have not reached the hub either.

---

## What changed

Since kit 4.2 the PostToolUse hook has run a whole-project type check plus a full lint of the
edited file on **every** Edit/Write/MultiEdit. Measured on this machine: 1,411 firings in one
repo, 786 in another, 344 in a third. The type check was `tsc --noEmit -p tsconfig.json`, and a
Vite/React `tsconfig.json` is a solution file (`"files": []` plus `"references"`), so without
`-b` it compiled the empty file list — 2-4 seconds per edit that could not report an error even
in principle. The lint reported every error in the file, so in a repo with an eslint ratchet
(~450 of 826 files carry accepted errors) the hook stopped the session on more than half of all
edits and handed it debt it had not written.

Kit 4.10: the hook lints only the edited file and reports **only errors the change added** over
the accepted level — the ratchet baseline where one exists, floored by a per-file cache under
`.claude/state/lint/`, and zero for a file the session created. It calls the installed eslint
binary rather than `npx`. The whole-project type check is not dropped, it moves to
`.githooks/checks` on pre-push and to CI.

The managed `CLAUDE.md` block asserted the old behaviour to every repo the kit has touched and
is corrected. Nothing is relaxed: `never disable a rule` stands, and `never raise the lint
baseline` is added.

Two defects found reviewing the change before release are also fixed: the eslint report used a
single fixed filename (two sessions in one checkout could read each other's report), and the
repo root was stripped from the edited path case-sensitively (on Windows `C:/` against a
`getcwd()` of `c:/` left the path absolute and re-reported the whole file).

Decision recorded in `docs/decisions/0009-the-post-edit-hook-reports-regressions-not-debt.md`.

## Preconditions

- Windows, Python 3, this branch checked out.
- Cases 01-08 need a **scratch TypeScript repo** with eslint installed and at least one file
  that already fails lint. Do not use a real project: several cases require you to introduce
  lint errors deliberately.
- The hook only runs inside Claude Code. To exercise it directly from a terminal, run
  `printf '{"tool_input":{"file_path":"src/App.tsx"}}' | sh .claude/hooks/post-edit.sh` from the
  repo root and read the exit code (`echo $?`) — `0` means silent, `2` means it stopped the
  session and printed a reason.
- Timings below were measured on this machine and are indicative, not pass criteria. The pass
  criterion is always what the hook says and whether it exits 0 or 2.

---

## 01. Create the scratch repo the later cases use

**Steps.** In an empty folder run `git init`, then `npm init -y`, then install eslint and a
TypeScript config so `npx eslint src/App.tsx` runs. Add `src/App.tsx` containing at least two
things eslint reports as errors. Commit everything. Then from the kit repo run
`python repo_setup.py refresh --path <that folder>`.

**Expected result.** The refresh finishes and names the files it replaced. `.claude/hooks/post-edit.sh`
exists in the scratch repo, and `.teknobu.json` records `"kit_version": "4.10"`. Call this repo
**Scratch Repo** — every case from 02 to 08 uses it.

## 02. A file that already fails lint does not stop the session

**Steps.** In Scratch Repo, with `src/App.tsx` committed and still failing lint, run the hook on
it directly (see Preconditions) and read the exit code.

**Expected result.** Exit code `0` and no output at all. The pre-existing errors are not
mentioned. (Before 4.10 this printed every error and exited 2.)

## 03. An error the edit adds is reported, and named as added

**Steps.** Run the hook on `src/App.tsx` once so its current level is recorded. Now edit
`src/App.tsx` to introduce **two more** lint errors, save, and run the hook again.

**Expected result.** Exit code `2`, and the first line names the rise in the form
`src/App.tsx: lint errors went from 2 to 4, so this change added 2.` The numbers must match what
you actually did. The message also says the other errors were already accepted and to leave them
alone, and lists the individual errors with line and column.

## 04. Fixing the added errors makes it silent again

**Steps.** Continuing from case 03, remove the two errors you introduced. Save and run the hook.

**Expected result.** Exit code `0` and no output. It does not keep reporting the errors that
were there before.

## 05. A file created in this session owns every error in it

**Steps.** In Scratch Repo create a **new** file `src/Fresh.tsx` that has three lint errors. Do
not `git add` it. Run the hook on it.

**Expected result.** Exit code `2`, and the message reads `went from 0 to 3, so this change
added 3`. Nothing was accepted for a file that did not exist before.

## 06. A ratchet baseline sets the accepted level

**Steps.** In Scratch Repo create `scripts/eslint-baseline.json` containing
`{"counts": {"src/App.tsx": 5}}`. Make `src/App.tsx` contain exactly five lint errors. Delete the
folder `.claude/state/lint` so nothing is cached. Run the hook. Then add a sixth error and run it
again.

**Expected result.** The first run exits `0` and says nothing. The second exits `2` and says
`added 1`.

## 07. A file the baseline does not list accepts nothing

**Steps.** With the baseline from case 06 in place (it lists only `src/App.tsx`), make sure
`src/Fresh.tsx` has at least one lint error, delete `.claude/state/lint`, and run the hook on
`src/Fresh.tsx`.

**Expected result.** Exit code `2`. A baseline is authoritative: a file it does not mention
accepts zero errors, so every error in that file is reported.

## 08. Editing a TypeScript file no longer type-checks the whole project

**Steps.** In Scratch Repo, introduce a **type** error in `src/App.tsx` that eslint does not
report (for example, assign a string to a variable declared as `number`). Leave lint clean. Run
the hook and time it.

**Expected result.** Exit code `0`, no output, and it returns in a few seconds rather than
stopping the session. The type error is **not** reported here — that is the intended change.
Confirm it is caught elsewhere by running `sh .githooks/checks` (or pushing), which must fail on
that same type error. If `.githooks/checks` passes with a type error present, that is a fail:
the check has not moved, it has been lost.

## 09. Two sessions in one checkout do not corrupt each other's report

**Steps.** In Scratch Repo, open two terminals in the **same folder** (not a worktree). In each,
run the hook on a *different* file at the same time — one on `src/App.tsx`, one on
`src/Fresh.tsx`. Repeat a few times. Afterwards run `ls -a .claude/state/lint`.

**Expected result.** Each terminal's message names the file that terminal was given, and the
counts match that file. The folder contains only short cache files with hex names — **no
`.json` file is left behind**, and in particular no `.last-report.json`.

## 10. An absolute path with a differently-cased drive letter still works

**Steps.** In Scratch Repo, make `src/App.tsx` fail lint but stay at its accepted level (case 02
state). Run the hook passing the **full absolute path** with the drive letter's case flipped —
if the repo is at `C:/scratch`, pass `c:/scratch/src/App.tsx`.

**Expected result.** Exit code `0` and silence, exactly as in case 02. If it instead reports the
whole file as newly added errors, that is a fail — it means the repo path was not recognised.

## 11. The instructions the kit ships no longer claim a per-edit type check

**Steps.** Open `CLAUDE.md` in Scratch Repo and find the managed pipeline section (between the
`sonelo-devkit` markers). Read the bullet about the linter.

**Expected result.** It describes a linter that runs on the edited file and reports only what
the change added, and says whole-project type checking runs on push and in CI. It must **not**
say "The type checker and linter run on every edit". It must still say `never disable a rule`
and must also say `never raise the lint baseline`.

## 12. A repo with no eslint config is unaffected

**Steps.** In a folder with a `.claude/hooks/post-edit.sh` but no eslint config file at all
(no `eslint.config.*`, no `.eslintrc.*`), run the hook on any `.ts` file.

**Expected result.** Exit code `0`, no output, returns immediately. The absence of eslint is not
an error and must not stop the session.

## 13. A full-pipeline path still demands the impact report

**Steps.** In Scratch Repo, on a branch with no `.claude/state/<branch>/impact.json`, run the
hook on a path under `supabase/` — for example `supabase/migrations/x.sql`.

**Expected result.** Exit code `2` with a `[pipeline]` message saying the impact-analyst report
is due. Run it a second time on the same branch: it must now be silent (it nudges once per
branch, not once per edit). This behaviour is unchanged by 4.10 and is here to prove it survived.

## 14. The kit's own suite passes

**Steps.** In the kit repo run `python -m unittest discover -s tests` and then `echo $?`.

**Expected result.** `OK`, 426 tests, and exit code `0`. Note the exit code specifically — a
green-looking summary with a non-zero exit code is a fail.

---

## Known limitations to check against, not bugs to raise

- A repo with **no** ratchet baseline relies on the per-file cache, so the *first* edit of any
  tracked file after the cache is cleared is always silent. This is deliberate: it under-reports
  rather than nagging. Adding a baseline makes it strict.
- A type error now surfaces on push rather than on the edit that wrote it. That is the trade
  recorded in ADR-0009, not a regression.
- Nothing recomputes the hook's cost automatically. If it gets slow again, no gate will say so.
