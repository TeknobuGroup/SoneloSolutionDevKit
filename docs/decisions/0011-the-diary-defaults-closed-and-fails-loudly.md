# ADR-0011 — The diary defaults closed, and a leak fails the collect rather than being redacted

- Date: 2026-09-06
- Status: Accepted

## Context

The kit now gathers a day of real work into one file (`diary_agent.py`) so a daily dev diary can be
written from it. The material is the most sensitive the machine holds: commit messages, file paths,
branch names, Claude Code transcripts, window titles, and the developer's own notes — across an estate
of repos that are almost all client work.

Three things about that material forced choices:

- **Most repos must never be written about, and nobody will remember to say so.** There are thirteen
  repos in the pot today and more arrive by being opened once in Claude Code. A feature that requires
  a per-repo opt-*out* leaks the first repo somebody forgets.
- **A filter that silently rewrites text teaches nothing.** If the collect quietly redacts a client's
  name, the day-file is safe and the *source* of the name — a tier set too high, a note written
  carelessly, a term missing from the blocklist — is still there tomorrow, and the day after.
- **`own` is not one permission but two.** "I may describe this work in detail" and "I may name this
  product" are different statements, and only the first is ever true for a client project — even one
  the developer owns outright, because the blog is public and the client is not a party to it.

## Decision

1. **Every project is `private` until a human raises it.** No `diary` block in a repo's
   `.teknobu.json`, an unreadable file, an unknown tier value, or a `nickname` tier with no nickname —
   all of them are `private`: the repo contributes its hours to the day and nothing else. `apply`
   writes `{"diary": {"tier": "private"}}` into every repo it touches, so the default is visible
   rather than implicit, and `doctor` warns, by name, about every repo still sitting on it.
2. **A leak fails the collect.** The check runs over every string in the finished day-file; a hit
   prints the term, the field it was found in and the text around it, and no file is written.
   `--force` exists, redacts instead, and records what it redacted inside the day-file.
3. **Product, client and person names are forbidden at every tier**, `own` included. A project is
   labelled by its `description` (`own`) or its `nickname` (`nickname`), never by the repo name.
4. **Raw transcripts never leave the machine.** The summariser is sent a digest of prompts and
   assistant prose plus tool *names*; tool results — which are file contents — are excluded by
   construction rather than by filtering. A `private` repo is never summarised, so nothing in it is
   read at all.

## Alternatives considered

- **Default `own`, opt out per repo.** Rejected: the failure mode is a client's commit messages in a
  public post, and it happens on the repo somebody forgot, which is the one they were busy in.
- **Redact silently and always succeed.** Rejected for the reason above: the source stays broken. It
  also makes the check unfalsifiable — a day-file with nothing in it looks identical to a day-file
  that was clean.
- **Blocklist only, no tiers.** Rejected: a blocklist catches names somebody thought of. Tiers catch
  the shapes nobody thinks of — a file path that names a client's table, a branch called
  `feature/acme-invoice-export`.
- **A second summariser provider configured separately.** Rejected: Claude Code's headless mode is
  already installed and already logged in on every machine the kit is on, and a second provider is a
  second thing to fall out of step. `diary.summariser` takes any command that reads stdin.
- **Reimplementing `session_day_minutes` inside the diary** to keep the file self-contained.
  Rejected: that arithmetic is load-bearing and has already drifted once between two copies (worklog
  1.18 pinned the dashboard's copy against the report's with a test). The diary imports the worklog
  agent and says plainly where it looked when it cannot find it.

## Consequences

- A first run reports mostly "client work" and a list of repos to classify. That is the intended
  first experience, and `doctor` is the thing that makes it a short task rather than a mystery.
- Some collects will fail. That is the feature working; the fix is at the source, and the message
  names it.
- The day-file's `hours` are Claude Code effort, so parallel sessions add up and a day can exceed 24
  hours. Every day-file carries a `time_note` saying so, and the machine's own `desk_hours` and
  `unlocked` sit beside it rather than replacing it.
- `totals.commits` and `totals.sessions` count private repos too — aggregate counts with no content —
  because a day-file that undercounts the day is a day-file you cannot trust to write from.
- The kit now ships three Python files instead of two. `install` copies the diary next to the
  worklog; `doctor` reports its version.

## Addendum — 2026-09-06, kit 4.13: the kit writes the block, but never chooses it

The default was right and, on its own, unlivable. `diary --list` on the machine that built it
reported **1 of 19 repos classified**: the only route out of `private` was hand-editing
`.teknobu.json` in each repo, so nobody did, and the diary could report hours and silence for
almost everything. A default nobody can leave is not a safe default; it is a switched-off feature.

So 4.13 gives the decision a route: `apply`/`refresh --diary-tier|--diary-nickname|--diary-description`
at setup time, `repo_setup.py diary` (`--list`, `--repo <path> --tier ...`) as a sweep over the
worklog pot, `/diary` to drive that conversationally, and a `doctor` count so an unclassified estate
is visible rather than quiet.

**What did not move is the line this ADR is about.** Automating the *route* to a classification is
not automating the classification:

- **Only the codename may be generated.** `--nickname auto` draws from a fixed list of ordinary
  nouns and avoids the ones in use. It is never derived from the repo's name, folder, remote or
  description — a codename you can reverse is not a codename.
- **The tier and the description have no automatic path at all**, and `/diary` is written to insist
  on it: one repo per message, a line of evidence the user can check, all three tiers offered with
  what each one means, and never a choice made for them. A tier inferred from a folder name would be
  a classification nobody made, which is the thing the whole default exists to prevent.
- **A plain re-run never lowers a repo.** A flag not passed changes nothing, and `apply` writes the
  `private` default only where there is no block at all.
- **A key the new tier does not use is kept, not cleared** — a codename that changed every time a
  repo was raised and lowered would make the diary incoherent from one post to the next.

Two mechanical consequences worth recording. `tier: nickname` with no nickname is the one
combination that cannot work (`label_for` raises, and the collect downgrades that project to
"client work" for the whole day, silently), so a codename is generated rather than the unusable
pair being written. And because the kit is one self-contained file per tool, `repo_setup.py`
duplicates the diary's normaliser instead of importing it; the two are pinned against each other by
a test that runs both over the same thirteen config shapes, label included, for the same reason
`session_day_minutes` is imported rather than copied.
