# UAT — kit 4.14 — the MCP launch path and the types gate — 2026-09-06

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were NOT pushed to UAT Hub

**Pushed on 2026-09-06.** These cases are now in UAT Hub, project `teknobu-kit`, round 1 -
reconciled across releases and regrouped into six numbered modules, so a tester runs them in
order rather than per release. The section below records why they sat here until then.


The `uat-hub` MCP server failed to connect at the start of this session (CONNECTION_CLOSED) — which
is the defect this release fixes, so it could not have been otherwise. The fix reaches a session
only after `refresh` **and** a restart of Claude Code, and the project's MCP server must then be
approved once (`claude mcp list` reports it as `⏸ Pending approval` because `.mcp.json` changed).

The cases below are written out in full here instead and **must be pushed to UAT Hub once a session
can reach it** — this is the sixth release in a row in that position, and the backlog is listed in
`docs/STATUS.md`. Pushing that backlog is the first real exercise of the fix.

---

## What changed

Two gates that had never worked, both failing in the direction that looks like working.

**The `uat-hub` MCP server has never started, in any repo, on any machine, since 4.6.** The kit
wrote the launch path as `${HOME:-${USERPROFILE}}/uat-hub/mcp/server.mjs`. Claude Code expands
`${VAR}` and `${VAR:-literal}` but not a `${...}` nested inside a `:-` default: it resolves the
inner variable and strands the outer brace, so `node` was launched on
`C:/Users/<user>}/uat-hub/mcp/server.mjs` and exited MODULE_NOT_FOUND. The kit now writes
`${USERPROFILE}/uat-hub/mcp/server.mjs` on Windows and `${HOME}/uat-hub/mcp/server.mjs` elsewhere,
and accepts **both** in `mcp_ok`, in the generated pre-commit hook and in `doctor`.

**The types gate could not be satisfied by a policy-only migration.** It demanded a diff to the
generated types file that a policy, grant or data-only migration cannot produce. It now accepts a
`Types-not-affected: <reason>` commit trailer, with the reason mandatory.

Three pieces of kit behaviour hid the first bug and are fixed with it: the pre-commit hook rejected
any `.mcp.json` that did not carry the broken string, `PRELIVE.md` said not to hand-edit the path,
and `doctor`'s guard (`if not HOME and not USERPROFILE`) can never be true on Windows.

## Preconditions

- Windows, Python 3, Node.js, git, and this branch checked out. Cases 05 to 13 need `sh` and `git`.
- `~/uat-hub/mcp/server.mjs` must exist on the machine (the UAT Hub checkout in its usual place).
- `UAT_HUB_KEY` must be set in the user environment **before Claude Code is started**, or case 02
  cannot pass for a reason that is not this release's fault. `python repo_setup.py doctor` says
  whether the process running it can see it.
- Cases 04 and 06 write into a scratch repo you create. Never run them in a client repo.
- Read the exit code after each run with `echo $?` where the case asks for it.

---

## Cases

### 01. The committed launch path names a variable, not a machine

**Steps.** In this repo, run `python repo_setup.py refresh`, then open `.mcp.json`.

**Expected.** The `uat-hub` entry reads `"args": ["${USERPROFILE}/uat-hub/mcp/server.mjs"]` on
Windows (`${HOME}/...` on Mac or Linux). There is no `:-` anywhere in it, no second `${` inside the
string, and your own user name does not appear anywhere in the file.

### 02. The server actually starts — the only case that proves the release

**Steps.** After case 01, **close Claude Code completely and start it again** in this repo. Approve
the project MCP server when asked. Then run `claude mcp list`.

**Expected.** `uat-hub` is listed as **connected** — not "failed", not CONNECTION_CLOSED. If it says
`⏸ Pending approval`, you have not approved it yet; run `claude` in the repo and approve, then list
again. If it warns `Missing environment variables: UAT_HUB_KEY`, the key was set after Claude Code
started — that is the documented trap and not this release: set it, restart, try once more.

*A green test suite cannot see this case. The old, broken path passed every test in the repo.*

### 03. A session can reach the hub

**Steps.** With the server connected (case 02), in a Claude Code session in this repo, ask it to
read the UAT cases for any module in the `teknobu-kit` project.

**Expected.** It returns an answer from the hub — including "no cases found", which is a real
answer. It does not report the MCP tool as unavailable and does not fall back to writing a file.

### 04. A repo written by the old kit heals itself on refresh

**Steps.** In a scratch folder, `git init uat-mcp-scratch` and change into it. Create `.mcp.json`
containing a `uat-hub` entry whose `args` is `["${HOME:-${USERPROFILE}}/uat-hub/mcp/server.mjs"]`
(copy the shape from this repo's file and change only that string). Run
`python <path to kit>/repo_setup.py refresh`. Open the file.

**Expected.** The path has been rewritten to the current one. Nobody had to edit it by hand, and no
other server in the file was touched. This is how every repo in the estate recovers.

### 05. A path someone redirected is still rewritten, and still cannot be committed

**Steps.** In the scratch repo, change `args` to `["./tools/evil.mjs"]`. Try to commit `.mcp.json`
(the kit's pre-commit hook must be installed — `refresh` installs it). Then run `refresh` again.

**Expected.** The commit is **blocked**, with a message saying command/args must be node followed by
the kit's path. After `refresh` the file is back to the kit's path. Both halves matter: the hook is
the control, the rewrite is the recovery.

### 06. The other platform's path is accepted and left alone

**Steps.** On Windows, set the scratch repo's `args` to `["${HOME}/uat-hub/mcp/server.mjs"]` — the
Mac and Linux form. Commit it. Then run `refresh` and look at the file again.

**Expected.** The commit is **allowed** — a repo set up on a Mac and cloned onto Windows is not an
error. `refresh` leaves that path exactly as it is; it does not flip it to the Windows form. If it
rewrote it, every mixed-platform team would churn this committed file on every refresh.

### 07. Doctor warns about the variable the repo's own file names, not the platform's

**Steps.** Leave the `${HOME}` path from case 06 in place. On Windows, run
`python repo_setup.py doctor` and read the UAT Hub lines.

**Expected.** A line naming **HOME** — not USERPROFILE — saying it is not set, that this repo's
`.mcp.json` names it, that Claude Code cannot resolve the launch path so the MCP server never
starts, and that the reference was written on another platform so **`refresh`** is the fix rather
than setting HOME. Checking USERPROFILE here instead would report the repo healthy while nothing
starts, which is the whole defect this release exists to end.

### 08. Doctor is silent once the reference is back to this platform's form

**Steps.** Run `python repo_setup.py refresh` to put the path back to the Windows form. Run
`python repo_setup.py doctor`. Then run it once more from a shell where `USERPROFILE` is not set
(`env -u USERPROFILE python repo_setup.py doctor` in Git Bash).

**Expected.** The first run says nothing about a missing variable. The second prints a line saying
`USERPROFILE is not set, and this repo's .mcp.json names it: Claude Code cannot resolve the launch
path, so the MCP server never starts and sessions fall back to the HTTP endpoint; set it, then
start a new session - a running one keeps the environment it started with`. Before this release
that warning could never appear on Windows at all.

### 09. A policy-only migration is blocked without a reason

**Steps.** On a branch, add a new file under `supabase/migrations/` that only changes a policy or a
grant. Do not regenerate types (there is nothing to regenerate). Open a pull request.

**Expected.** The **Types regenerated after migrations** check fails, and its message tells you what
to do: say so in a commit trailer, with a reason, and shows the exact form
`Types-not-affected: policy-only migration`.

### 10. Declaring the reason lets it through, and the reason is visible

**Steps.** On the same branch as case 09, add a commit whose message body contains
`Types-not-affected: policy-only migration`. Push and let the checks run.

**Expected.** The **Types regenerated after migrations** check passes, and the CI log for that step
reads `Types gate waived by the author. The reason, from the commit history:` followed by an
indented line `Types-not-affected: policy-only migration` — a reviewer who never opens the commits
can still see why.

### 11. A trailer with no reason is not a declaration

**Steps.** Start a **new** branch off the production branch — not the branch from cases 09 and 10,
which already carries a valid trailer that would still be in range. Add a new file under
`supabase/migrations/` that only changes a policy. Add a commit whose message body has only
`Types-not-affected:` and nothing after it. Open a pull request.

**Expected.** The **Types regenerated after migrations** check **fails**, with the same message as
case 09. A trailer anyone can paste without thinking is the unsatisfiable gate again, only silent.

### 12. One declaration waives the whole pull request — which is why the reason has to be true

**Steps.** On a new branch, make two commits, each adding a different new file under
`supabase/migrations/`. Put `Types-not-affected: policy-only migration` in the body of the first
commit only. Do not regenerate types. Open a pull request.

**Expected.** The check **passes**, and the log prints the one reason that was given. This is the
declared behaviour, not a gap that slipped through: the trailer is a statement on the record for a
reviewer to read, not a check that every migration was considered. A pull request from the work
branch to production carries every commit since the last release, by every author, so a reviewer
seeing one reason next to two migrations is the control — the software cannot tell which migration
the reason was about. If this case **fails** instead, the release has gone back to blocking authors
who split or renumber a migration, which is what it exists to stop.

### 13. A real schema migration is still stopped

**Steps.** On a branch, add a migration that adds a column, and do not regenerate types. No trailer.
Open a pull request.

**Expected.** The check fails. This is the gate doing its job, and the release must not have
loosened it.

### 14. The diary registration snippet names the installed copy, not the folder you ran it from

**Steps.** Make sure the kit is installed on this machine — run `python repo_setup.py install` once
if you are not sure, which puts a copy at `~/.claude/sonelo/diary_agent.py`. Then, from the kit
checkout, run `python diary_agent.py doctor` and read the JSON snippet at the end.

**Expected.** The first entry of `args` is a path ending `.claude/sonelo/diary_agent.py`. It is
**not** the folder you ran the command from. Nothing warns you about a working copy.

### 15. Without an installed copy it falls back and says the path will move

**Steps.** Rename `~/.claude/sonelo/diary_agent.py` to `diary_agent.py.off`. Run
`python diary_agent.py doctor` from the kit checkout. Rename the file back afterwards.

**Expected.** The `args` path is now the file you actually ran, and two extra lines appear under the
snippet: one saying the path is this working copy, so it moves with the branch and the folder, and
one telling you to run `repo_setup.py install` for a stable one. Without those lines a reader pastes
a path into the desktop app that stops working the next time the branch changes.

### 16. It says which file the snippet goes in, and that a reload is not enough

**Steps.** Run `python diary_agent.py doctor` and read the two lines after the JSON snippet.

**Expected.** A line beginning `in ` that names the Claude **desktop app** config file for this
operating system — on Windows `%APPDATA%\Claude\claude_desktop_config.json` — and a line saying to
quit the app fully and reopen it, because a reload keeps the environment it started with. Knowing
the JSON and not knowing the file is where this stalls.

---

## Not covered

- Whether the reason given in a `Types-not-affected:` trailer is *true*, and whether it covers every
  migration in the pull request. Nothing in the gate checks either; it is a declaration on the
  record, which is the point of putting it in git history. Case 12 is the shape of that limit, and
  the migrations rule in `CLAUDE.md` states it rather than implying a guarantee.
- That a commit message cannot open a workflow command in the CI log. The gate strips carriage
  returns from the reason before printing it, and a test in `tests/test_repo_setup_types_gate.py`
  fails if that guard is removed — but it is not something a tester can see from the interface.
- Any platform other than Windows, on this machine. The Mac and Linux path is exercised by case 06
  as a committed value and by the test suite, but no case here starts the server on a Mac.
- The backlog push itself. It happened on 2026-09-06 — 99 cases into round 1 — and it is what
  proved the fix in anger, but it is not a case a tester re-runs.
- Whether the Claude desktop app actually starts the diary server from the snippet in cases 13-15.
  The app is not installed on this machine, so the cases check what `doctor` tells you to do, not
  the app doing it.
