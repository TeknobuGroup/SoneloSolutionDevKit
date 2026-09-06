# UAT — kit 4.12 — the diary agent — 2026-09-06

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were NOT pushed to UAT Hub

**Pushed on 2026-09-06.** These cases are now in UAT Hub, project `teknobu-kit`, round 1 -
reconciled across releases and regrouped into six numbered modules, so a tester runs them in
order rather than per release. The section below records why they sat here until then.


`repo_setup.py doctor` reports `UAT_HUB_KEY not set` on this machine, and the `uat-hub` MCP
server failed to connect this session (CONNECTION_CLOSED). The cases below are written out in
full here instead and **must be pushed to UAT Hub before a tester picks them up** — nothing is
lost, but nothing is queued for a tester either. This is the fourth release in a row in that
position; the backlog is listed in `docs/STATUS.md`.

---

## What changed

A new third tool in the kit: `diary_agent.py` (v1.0), which gathers one day of real work into
one file that is safe to write a public post from, and serves it to Claude over a local stdio
MCP server.

It reads only what the machine already records — the worklog pot (hours and sessions), each
repo's git log for the day, Claude Code transcripts, ActivityWatch and the presence stamps —
plus the notes and photos added during the day with `diary note`. Output is
`~/Diary/<YYYY-MM-DD>.json`.

The whole design turns on two decisions, recorded in
`docs/decisions/0011-the-diary-defaults-closed-and-fails-loudly.md`:

- **Every repo is `private` until a human raises it.** No `diary` block in `.teknobu.json`, an
  unreadable file, an unknown tier, or `nickname` with no nickname — all mean hours only,
  labelled "client work". `apply` now writes the private default into every repo it touches, and
  `doctor` names the repos still sitting on it.
- **A leak fails the collect.** Every string in the finished file is checked against the
  blocklist, the repo and person names in the day, and (below `own`) branch names and four
  shapes — URL, file path, commit subject, `feature/` branch. A hit prints the term, the field
  and the surrounding text, and writes nothing. `--force` redacts instead and records what it
  redacted inside the file.

Session summaries are produced locally from a digest of prompts and assistant prose plus tool
*names*; tool results never enter it, and raw transcripts never leave the machine.

## Preconditions

- Windows, Python 3, this branch checked out. No network needed except in case 12, which needs
  the `claude` CLI available and logged in — skip it if that is not the case and say so.
- The worklog pot must exist with at least one repo reporting into it (`python
  worklog_agent.py report` prints it). Every case below is local and read-only apart from the
  files it writes under `~/Diary/`.
- **Do not run these against a real client repo's configuration.** Cases 04 to 07 ask you to set
  tiers deliberately; set them on this kit repo and on one scratch repo you create, and put them
  back when you are done.
- Read the exit code after each run with `echo $?` — `0` and `1` are both correct answers
  depending on the case, and the case says which.
- Run everything from the repo root: `python diary_agent.py <command>`.

---

## Cases

### 01. A note is written and read back

**Steps.** Run `python diary_agent.py note "he was right about the subject line"`.
Then open `~/Diary/notes/<today>.jsonl` in a text editor.

**Expected.** The command prints `noted HH:MM  he was right about the subject line` and the path
to the notes file, and exits 0. The file has one line of JSON containing today's time and that
exact text. The whole command returns in well under a second.

### 02. A note with a photo keeps the photo

**Steps.** Save any small `.jpg` to your desktop. Run
`python diary_agent.py note "the sandwich place" --image <path to that jpg>`.

**Expected.** The command prints the note, then an `image` line pointing inside
`~/Diary/assets/<today>/`. That folder contains a copy of the picture, and the original is still
on your desktop. Exit code 0.

### 03. A note with nothing in it is refused

**Steps.** Run `python diary_agent.py note` with no text and no image. Then run
`python diary_agent.py note "x" --image C:/nope/missing.jpg`.

**Expected.** The first prints `nothing to record - give some text, an --image, or both` and
exits 2. The second reports `no such image` and the path, and exits 1. Neither writes anything
to `~/Diary/`.

### 04. A day collects, and an unclassified repo shows hours only

**Steps.** Make sure at least one repo in the pot has **no** `diary` block in its
`.teknobu.json`. Run `python diary_agent.py collect yesterday`.

**Expected.** A warning line naming that repo and saying it has no diary tier, then a summary
line with the day's hours, commits, sessions and notes, then a list of projects, then the path
to the day-file. In the list, that repo appears as `client work` with a tier of `private` and a
number of hours, and a `-` rather than a `0` in both the commits and the sessions column —
the file is not allowed to say what it did, which is not the same as it having done nothing.
Exit code 0.

### 05. The day-file withholds what the tier withholds

**Steps.** Open the day-file printed by case 04 in a text editor. Find the project entry
labelled `client work`.

**Expected.** That entry has exactly three fields: `label`, `tier` and `hours`. There is no
commit message, no session, no summary and no description anywhere in it. The repository's real
name does not appear anywhere in the file — search for it to be sure.

### 06. Raising a repo to `own` gives it detail, but never its own name

**Steps.** In this kit repo's `.teknobu.json`, confirm the `diary` block reads
`{"tier": "own", "description": "the developer kit I work inside"}`. Run
`python diary_agent.py collect yesterday --no-summaries` and open the day-file.

**Expected.** The kit's project entry is labelled `the developer kit I work inside` — not
`teknobu-kit` — and now carries a `commits` list with real commit messages and file counts, and
a `worklog` list of the day's commits and sessions in time order. Searching the file for
`teknobu-kit` finds nothing.

### 07. `nickname` gives narrative without identifiers

**Steps.** Create a scratch folder, `git init` it, make one commit as yourself today, and give
it a `.teknobu.json` containing
`{"diary": {"tier": "nickname", "nickname": "Kestrel", "description": "a scheduling tool"}}`.
Open a Claude Code session in it briefly so the worklog records it, then run
`python diary_agent.py collect today --no-summaries`.

**Expected.** The project appears as `Kestrel`. It has hours and may have sessions, but **no**
`commits` list and no `worklog` list. The commit message you wrote does not appear anywhere in
the day-file.

### 08. A blocklisted term fails the collect and says where it came from

**Steps.** Add a term you know appears in one of today's notes to `~/.claude/diary.json`, e.g.
`{"blocklist": ["sandwich"]}` if you ran case 02. Run `python diary_agent.py collect today`.

**Expected.** No day-file is written for today (check the modification time in `~/Diary/`). The
command prints `The day-file was NOT written:`, then the field it was found in (something like
`notes[0].text`), the term, and the text around it, then a line explaining the three ways to fix
it. Exit code 1.

### 09. `--force` redacts instead, and records that it did

**Steps.** With the same blocklist in place, run `python diary_agent.py collect today --force`.

**Expected.** The command prints a `redacted` line saying how many values it replaced and why,
then the normal summary, and exits 0. The day-file now exists; the blocklisted term is nowhere
in it, `[redacted]` appears where it was, and there is a top-level `redacted` list naming the
field and the reason. Remove the blocklist term afterwards.

### 10. `doctor` never prints a blocklist term

**Steps.** With at least two terms in the `blocklist` in `~/.claude/diary.json`, run
`python diary_agent.py doctor`.

**Expected.** A line reading `blocklist  2 terms (values are never printed)`. Neither term
appears anywhere in the output. The output also names the transcript folder, says the output
directory is writable, gives the worklog version and pot, lists every repo with its tier and
label, warns by name about repos defaulting to private, and finishes with a registration block
headed `Register the MCP server in the Claude desktop app with:` — a JSON snippet, then a line
beginning `in ` that names the Claude desktop config file for your operating system, then a line
telling you to quit the app fully and reopen it.

### 11. The MCP server answers on stdin

**Steps.** Run `python diary_agent.py serve`. Paste this line and press Enter:
`{"jsonrpc":"2.0","id":1,"method":"initialize"}`
Then paste `{"jsonrpc":"2.0","id":2,"method":"tools/list"}` and press Enter. Then Ctrl+C.

**Expected.** Each line is answered with one line of JSON. The first contains
`"protocolVersion": "2025-06-18"` and a `serverInfo` naming `teknobu-diary`. The second lists
exactly four tools: `diary_day`, `diary_sessions`, `diary_note`, `diary_list`. Nothing else is
printed to the terminal between the two replies.

### 12. Session summaries appear, and are cached

**Steps.** Requires the `claude` CLI on PATH and logged in. Run
`python diary_agent.py collect yesterday` and time it. Then run exactly the same command again
and time it.

**Expected.** The first run takes noticeably longer and produces `summary` text of a couple of
hundred words on the sessions of any `own` or `nickname` project. The second run is much faster
and produces the same summaries — they are read from `~/Diary/.cache/summaries/`. Neither run
puts a client name, a file path from a nicknamed project, or any raw transcript text into the
file.

### 13. Registering the server in the desktop app works end to end

**Steps.** Copy the JSON snippet from case 10 into the Claude desktop app's MCP configuration,
restart it, and ask Claude "what did I work on yesterday?".

**Expected.** Claude calls `diary_day` and answers from the day-file — hours, projects by their
labels, and the notes you wrote. It does not name any repository, and any project you left at
`private` is described only as client work.

### 14. The kit still installs and reports the diary

**Steps.** Run `python repo_setup.py install` (safe to re-run), then `python repo_setup.py doctor`.

**Expected.** `doctor` prints a `diary` line giving version `1.0` and the path to run its own
doctor with. `~/.claude/sonelo/diary_agent.py` exists and is the same size as the one in this
repo.

---

## Not covered

- The blog itself — the writing and publishing step is a separate repo. `diary/writer-prompt.md`
  ships the voice and rules but is deliberately not wired to anything.
- Claude.ai chat sessions. They are not on this machine; every day-file carries a
  `chat_sessions_note` saying so, and a `diary note` is the way to include one.
- Days before the worklog was collecting, and repos that have never reported into the pot.
