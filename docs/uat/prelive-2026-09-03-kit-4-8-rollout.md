# UAT — taking kit 4.8 into teknobu-kit (the first rollout) — 2026-09-03

**Branch:** prelive → main   **Prepared by:** Claude Code   **Status:** awaiting sign-off

**Not pushed to UAT Hub.** `UAT_HUB_KEY` is not set on this machine, and the slug this repo now
records (`teknobu-kit`) is the folder-name default rather than a project that exists in the hub.
A push would be refused, so the cases are written out in full here instead.

## What changed

Nothing in this PR was hand-written. `repo_setup.py refresh` took the released kit 4.8 into this
repo, which was still on **4.2** — six releases in one step, and the first repo of the rollout.
The whole point of testing it is that a refresh rewrites files a repo depends on: the agent
definitions, the git hooks, the CI gates and the managed sections of `CLAUDE.md`.

The risk being tested is not "does the new text read well" — that shipped in #10. It is: **did the
refresh replace the right things, leave the repo's own things alone, and keep a way back.**

## Preconditions

- A machine with kit 4.8 installed (`~/.claude/sonelo/repo_setup.py`, `VERSION = "4.8"`).
- A checkout of this repo at this branch.
- No UAT Hub key is needed for any case below.

---

## Cases

### The release actually arrived

- **UAT-R-1** — Run `python "$HOME/.claude/sonelo/repo_setup.py" check` in the repo root.
  *Expected:* it reports kit **v4.8**. Before this PR it reported v4.2.
- **UAT-R-2** — Open `.teknobu.json`.
  *Expected:* `"kit": "4.8"` and an `applied` date of 2026-09-03. It read `4.2` / `2026-08-25`.
- **UAT-R-3** — Search `CLAUDE.md` for `updates nothing and creates nothing`.
  *Expected:* no match. That instruction was false — it told a session a same-`source_ref` re-push
  does nothing, so it would never re-push a rebuilt feature. Search for `refreshes that one case`:
  exactly one match.
- **UAT-R-4** — Find the `sonelo-devkit:uat:start` marker in `CLAUDE.md`.
  *Expected:* it reads `v4.8`.
- **UAT-R-5** — In `CLAUDE.md`, find the fast-lane bullet under Risk tiers.
  *Expected:* it now ends `a .tsx is application code, so code-reviewer is due on it like any other`.
  That is the 4.7 correction; on 4.2 the fast lane implied the opposite.
- **UAT-R-6** — In the reviewer-trigger table in `CLAUDE.md`, find the `security-reviewer` row.
  *Expected:* it lists `.mcp.json` among the paths. That is the 4.6 change.

### The repo's own files were left alone

- **UAT-R-7** — `git diff main..prelive -- .githooks/checks`.
  *Expected:* empty. That file is the repo's own; a refresh must never rewrite it.
- **UAT-R-8** — `git diff main..prelive -- .github/workflows/ci.yml`.
  *Expected:* empty, and the refresh output said `skipped (exists without kit marker)`. This repo
  owns its CI and it runs a superset of `.githooks/checks`. **This is the marker mechanism working,
  not a failure** — and it is the case most likely to be misread as one.
- **UAT-R-9** — Confirm `.claude/rules/design.md`, `PRELIVE.md` and any `.env*` are unchanged.
  *Expected:* unchanged. They are on the refresh's "untouched" list.
- **UAT-R-10** — Open `CLAUDE.md` and confirm this repo's own sections survive outside the markers:
  Session start, Commands, Conventions, Where knowledge lives.
  *Expected:* all four present and unaltered. A refresh rewrites managed blocks *in place*; losing
  the surrounding prose would be the worst failure of this change.

### There is a way back

- **UAT-R-11** — List `.claude/.backup/20260903-101730/`.
  *Expected:* it holds the pre-refresh copy of every file that was replaced — seven agents,
  `/pr`, `ci-gates.yml`, `pull_request_template.md` and `CLAUDE.md`.
- **UAT-R-12** — Confirm `.claude/.backup/` is git-ignored.
  *Expected:* the backup does not appear in `git status`. A refresh must not leave a repo dirty
  with copies of its own files.

### The wiring the refresh added

- **UAT-R-13** — Open `.mcp.json`.
  *Expected:* one `uat-hub` server; `UAT_HUB_KEY` is the literal `${UAT_HUB_KEY}` placeholder and
  **never a value**; `UAT_HUB_URL` is exactly `https://testing.teknobugroup.com`; the server path is
  `${HOME:-${USERPROFILE}}/uat-hub/mcp/server.mjs`, naming no machine and no username.
- **UAT-R-14** — With a real key exported, `grep -r` the repo for it.
  *Expected:* no match anywhere. The file is committed; the key never is.
- **UAT-R-15** — Note that `.mcp.json` records project `teknobu-kit`, the folder-name default.
  *Expected:* a push to a slug the hub does not know is **refused**, not silently created — so this
  is inert rather than wrong. `refresh --uat-project <slug>` corrects it in one command.
- **UAT-R-16** — Run `python "$HOME/.claude/sonelo/repo_setup.py" doctor`.
  *Expected:* it reports the UAT Hub host, the MCP server path, that `UAT_HUB_KEY` is **not set**,
  and it never prints a key value.

### The repo still works

- **UAT-R-17** — `python -m unittest discover -s tests`.
  *Expected:* 353 tests, OK. The refresh replaced the agent definitions and CI gates that several
  of these tests pin.
- **UAT-R-18** — Make a trivial commit on a branch and push it.
  *Expected:* the refreshed `commit-msg`, `pre-commit` and `pre-push` hooks run and pass. These
  three were rewritten by the refresh, so a repo that cannot commit afterwards is the failure mode
  that matters most.

### Known and accepted

- **UAT-R-19** — A session that was already running when the refresh happened holds the *old*
  `CLAUDE.md`, agent definitions and hook registrations until it restarts.
  *Expected:* this is understood, not a defect. It is the reason the rollout order says to refresh
  a client repo **when its sessions are quiet**; it was accepted deliberately here, on our own repo.

## Sign-off

| | |
|---|---|
| Tester | |
| Date | |
| Result | |
| Notes | |
