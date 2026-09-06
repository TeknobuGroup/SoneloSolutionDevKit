# UAT — kit 4.14 — the MCP launch path and the types gate — 2026-09-06

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were NOT pushed to UAT Hub

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

- Windows, Python 3, Node.js, git, and this branch checked out. Cases 05 to 09 need `sh` and `git`.
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

### 07. Doctor says so when the variable the path needs is missing

**Steps.** Run `python repo_setup.py doctor` and read the UAT Hub lines. Then run it once more from
a shell where `USERPROFILE` is not set (`env -u USERPROFILE python repo_setup.py doctor` in Git
Bash).

**Expected.** The first run says nothing about a missing variable. The second prints a line saying
`USERPROFILE is not set, and .mcp.json names it: the MCP server will not start and sessions fall
back to the HTTP endpoint`. Before this release that warning could never appear on Windows at all.

### 08. A policy-only migration is blocked without a reason

**Steps.** On a branch, add a new file under `supabase/migrations/` that only changes a policy or a
grant. Do not regenerate types (there is nothing to regenerate). Open a pull request.

**Expected.** The **Types regenerated after migrations** check fails, and its message tells you what
to do: say so in a commit trailer, with a reason, and shows the exact form
`Types-not-affected: policy-only migration`.

### 09. Declaring the reason lets it through, and the reason is visible

**Steps.** On the same branch, add a commit whose message body contains
`Types-not-affected: policy-only migration`. Push and let the checks run. Then repeat with a commit
whose body has only `Types-not-affected:` and nothing after it.

**Expected.** The first passes, and the CI log for that step reads
`Types gate waived by the author: policy-only migration` — a reviewer who never opens the commits
can still see why. The second **fails**: a trailer with no reason is not a declaration.

### 10. A real schema migration is still stopped

**Steps.** On a branch, add a migration that adds a column, and do not regenerate types. No trailer.
Open a pull request.

**Expected.** The check fails. This is the gate doing its job, and the release must not have
loosened it.

---

## Not covered

- Whether the reason given in a `Types-not-affected:` trailer is *true*. Nothing can check that; it
  is a declaration on the record, which is the point of putting it in git history.
- Any platform other than Windows, on this machine. The Mac and Linux path is exercised by case 06
  as a committed value and by the test suite, but no case here starts the server on a Mac.
- The 90-case backlog itself. Pushing it is the next job, not a test of this release — though it is
  the first thing that will exercise the fix in anger.
