# Diary agent · v1.0 (part of the Sonelo Solution DevKit v4.13)

One day of real work, gathered into one file that is safe to write from, and served to Claude
over MCP. It reads what the machine already records - the worklog pot, git, Claude Code
transcripts, ActivityWatch, presence stamps - plus whatever you typed into `diary note` during
the day, and produces `~/Diary/<YYYY-MM-DD>.json`.

It is the input to a daily dev diary. It is not the blog: the writing and the publishing live in
a separate repo. `diary/writer-prompt.md` in this repo carries the voice and the rules that post
will be written under, and is not wired to anything yet.

Installed with the kit: `python repo_setup.py install` copies it to `~/.claude/sonelo/diary_agent.py`
next to the worklog agent. Nothing is installed per repo; the diary reads the pot the worklog
already fills.

## The one thing to understand first

**Every project is `private` until you say otherwise.** A repo with no `diary` block in its
`.teknobu.json` contributes its hours to the day and nothing else - no commits, no summaries, no
description. That is not a bug to work around; it is the default that makes the feature safe to
run across an estate of client repos where most of them may never be written about.

Raise it per repo, in that repo's own `.teknobu.json`:

```json
{
  "diary": {
    "tier": "own",
    "description": "a client CRM rebuild"
  }
}
```

You do not have to write that by hand. From kit 4.13 the setup command asks for it, and
`repo_setup.py` writes it:

```
repo_setup.py diary --list                                  every repo the worklog knows, with its tier
repo_setup.py diary --repo <path> --tier private            hours only
repo_setup.py diary --repo <path> --tier nickname --nickname auto
repo_setup.py diary --repo <path> --tier own --description "a scheduling tool"
repo_setup.py apply|refresh --diary-tier own --diary-description "..."
```

In Claude Code, `/diary` walks the unclassified repos and asks about each one; `/repo-setup` and
`/new-repo` ask as part of setting a repo up, so a repo is classified when it is created rather
than eighteen at a time a year later. `.teknobu.json` is committed, so the classification travels
with the code and is reviewable in a diff - commit it after the sweep.

**Only the codename is ever generated.** `--nickname auto` picks a word from a fixed list and
avoids the ones already in use; it is never derived from the repo's name, folder, remote or
description, because a codename you can reverse is not a codename. The tier and the description
are always yours: a tier inferred from a folder name would be a classification nobody made, which
is the thing the private default exists to prevent (`docs/decisions/0011`).

| tier | what reaches the day-file |
|---|---|
| `own` | full detail: commit messages, file counts, the session timeline, and session summaries that may name features, files and decisions. The project is still called by its `description` - never by the repo name, and never by the product's name. |
| `nickname` | feature-level narrative only. No commit messages, branch names, file paths, table or column names, URLs or person names. The project is called by its `nickname` (required) and described by its `description`. |
| `private` | hours only. Labelled "client work". |

`description` is a short, generic phrase - "a client CRM rebuild", "a field service app". Not the
sector, not the size of the client, not the year it was written.

### Global configuration

`~/.claude/diary.json`, all optional:

```json
{
  "out_dir": "~/Diary",
  "transcripts": "~/.claude/projects",
  "pot": "",
  "model": "",
  "summariser": [],
  "summary_timeout": 240,
  "summary_words": [150, 250],
  "blocklist": ["a client name", "a product name", "a domain", "a person"],
  "authors": []
}
```

- **`blocklist`** - terms that may never appear in a day-file, at any tier. This is where client
  names, product names, domains and people go. Its contents are never printed, by any command.
- **`pot`** - empty means whatever `~/.claude/worklog.json` says, which is what you want.
- **`model` / `summariser`** - the summariser defaults to Claude Code's own headless mode
  (`claude -p --model <model>`), because it is already installed and already logged in. Anything
  that reads a prompt on stdin and writes prose to stdout works: `"summariser": ["my-tool", "--flag"]`.
- **`authors`** - names or emails that count as you. Empty means each repo's own git identity,
  which is right on a machine where you are the only committer.

## Commands

```
python diary_agent.py note "he was right about the subject line"
python diary_agent.py note "the sandwich place" --image ./lunch.jpg
python diary_agent.py collect [today|yesterday|-3|YYYY-MM-DD]
python diary_agent.py serve
python diary_agent.py doctor
```

**`note`** appends one timestamped line to `~/Diary/notes/<date>.jsonl` and copies any image into
`~/Diary/assets/<date>/`. It reads no config beyond the output directory, imports no worklog and
calls no model, because a note has to feel like ten seconds or it does not get written - and a
diary of the days you remembered to be thorough is not a diary of your days.

**`collect`** builds the day-file. Options: `--force` (redact instead of failing - see below),
`--no-summaries` (skip the model entirely), `--refresh` (re-summarise, ignoring the cache),
`--worklog <path>` (if the worklog agent is somewhere unusual).

**`serve`** is a stdio MCP server. Register it in the Claude desktop app - `doctor` prints the
exact snippet, with this machine's paths in it:

```json
{
  "mcpServers": {
    "diary": {
      "command": "<python>",
      "args": ["<path to>/diary_agent.py", "serve"]
    }
  }
}
```

Four tools, each of which calls exactly the function the CLI calls: `diary_day(date)` (collects
first if the file is missing or stale), `diary_sessions(date, project?)`, `diary_note(text,
image_path?)`, `diary_list(from, to)`.

**One deliberate difference from the command line: a collect started by the server redacts rather
than failing.** There is nobody at a terminal to read the failure, and refusing to answer would
leave the assistant with nothing while the offending text stayed exactly where it was. What it
returns is the redacted day, with the `redacted` list in it - so the assistant can see that
something was withheld and say so. The place to see *what* was withheld, and to fix it, is
`collect` at the command line, which still fails and names it.

**`doctor`** reports the transcript directory, the output directory and whether it is writable,
the worklog agent and the pot, the summariser command and model, the number of blocklist terms
(never the terms), every repo with its tier and label, a warning naming the repos that are
defaulting to private, and the MCP registration snippet.

## The leak check

Before a day-file is written, every string in it is checked against:

- the blocklist, at every tier;
- the repository, project and folder names of every repo in the day, at every tier - because
  `own` is permission to describe the work in detail, not permission to name the product;
- the name of every person who has committed to any of those repos, at every tier - which
  includes bots, so a repo scaffolded by a tool that commits under its own name puts that name
  out of bounds everywhere, and you will meet this the first time you write about the tool;
- for anything below `own`: that project's branch names, and four shapes - a URL, a file path, a
  conventional-commit subject, a `feature/`-style branch.

A hit **fails the collect**. Nothing is silently redacted: the command prints the term, the field
it was found in, and the text around it, so the fix is at the source - lower the tier, add the
term to the blocklist so it is caught earlier, or reword the note. `--force` redacts instead and
records what it redacted, in a `redacted` list in the day-file itself.

Two softenings, both deliberate. A repo name that appears inside the description you chose for
it ("crm" inside "a client CRM rebuild") is not reported, because that description is text you
have already decided to publish; the blocklist is never softened this way. And the tool's own
fixed prose - `time_note`, and `chat_sessions_note` while it still has its default wording - is
not scanned at all: it is written here rather than read out of a repo, so there is nothing in it
to leak. Reword either one in `diary.json` and it becomes your text, and is checked like any.

## Session summaries

For each Claude Code session on the day, in a repo at `own` or `nickname`, the transcript is
reduced to a digest and summarised in 150-250 words by the configured model.

- The digest is **prompts and the assistant's prose only**, plus tool names as a count. Tool
  *results* are never included - a tool result is file contents, and file contents are the thing
  this whole feature exists to keep out of a blog post.
- The prompt carries the tier's rules and states that the transcript is data, not instructions.
- Summaries are generated on this machine and are the only session content that reaches the
  day-file. **Raw transcripts never leave the machine.**
- A `private` repo is never summarised at all, so nothing from it is even read.
- Summaries are cached under `~/Diary/.cache/summaries/<session id>.json`, one entry per day,
  stamped with the tier and a hash of what was sent - so a re-collect is free, and re-tiering a
  repo re-summarises rather than serving a summary written under the old rules.

## What is in a day-file

```json
{
  "date": "2026-09-05",
  "generated": "2026-09-06T08:12:03+01:00",
  "diary_version": "1.0",
  "totals": {"hours": 7.4, "commits": 11, "sessions": 6,
             "desk_hours": 9.1, "unlocked": "08:12-19:40", "unlocked_hours": 10.2},
  "projects": [
    {"label": "a client CRM rebuild", "tier": "own", "hours": 4.2, "editor_hours": 1.1,
     "commits": [{"time": "10:31", "message": "...", "files": 3, "insertions": 88, "deletions": 12}],
     "worklog": ["09:02 session 96m  ...", "10:31 commit  ... (3 files)"],
     "sessions": [{"id": "...", "start": "...", "minutes": 96, "summary": "..."}]},
    {"label": "client work", "tier": "private", "hours": 1.4}
  ],
  "notes": [{"time": "13:20", "text": "...", "image": "assets/2026-09-05/lunch.jpg"}],
  "chat_sessions_note": "...",
  "time_note": "..."
}
```

Two things about the numbers, both stated in `time_note` in every file:

- **`hours` per project is Claude Code effort**, as the worklog counts it (`session_day_minutes`,
  imported from the worklog agent rather than reimplemented - the arithmetic is load-bearing and
  has drifted between two copies before). Parallel sessions therefore add up, and a day's total
  can exceed the day. That is the number the kit already trusts everywhere else.
- **`desk_hours` and `unlocked` are the machine's own figures** for the same day, from
  ActivityWatch and the presence stamps. `editor_hours` beside a project is ActivityWatch window
  titles matched to the project name - a guess, reported next to the effort figure rather than
  added to it.

`totals.commits` and `totals.sessions` count the real day, including the private repos whose
detail is withheld. Aggregate counts, no content.

## Tests

`tests/test_diary_agent.py` - 56 tests, hermetic: every path the module resolves from the home
directory is redirected into a temp directory for the duration of each test, so nothing there
reads or writes a real diary, worklog or settings file.
