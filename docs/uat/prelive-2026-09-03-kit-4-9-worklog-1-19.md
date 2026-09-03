# UAT — kit 4.9 & worklog 1.19 — context bands and machine settings — 2026-09-03

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were NOT pushed to UAT Hub

The `uat-hub` MCP server failed to connect this session (CONNECTION_CLOSED) and `UAT_HUB_KEY`
is not set on this machine — `repo_setup.py doctor` reports both. The cases below are written
out in full here instead, and **must be pushed to UAT Hub before a tester picks them up**;
nothing is lost, but nothing is queued for a tester either.

---

## What changed

**Kit 4.9.** `repo_setup.py doctor` gains a `Machine` line reporting the model default and
compaction cap from `~/.claude/settings.json`, and whether the 1M-context disable flag is set.
It reports only: it never prints an environment value and never fails the command. A new
built-in agent `.claude/agents/Explore.md` ships in the pipeline with `model: sonnet`, so
read-only search runs on Sonnet instead of inheriting the session model. The three gating
agents (code-reviewer, security-reviewer, impact-analyst) still declare no model and still
inherit — that is deliberate, and pinned by a test.

**Worklog 1.19.** Each request's context (input + cache-create + cache-read tokens) is bucketed
into three bands — normal (under 150,000), elevated (150,000–799,999), very high (800,000 and
above) — and cost is reported by band. Each session records `context_max`, its high-water mark.
Subagent tokens are split from main-thread tokens by transcript membership. The weekly report
gains a `## Cost and context` section; the morning page shows the same figures plus a footer
naming this machine's model default and compaction cap.

Slices collected by worklog 1.18 and earlier carry none of the new keys. They are reported as
not collected — never as a zero and never as an estimate.

## Preconditions

- Windows, Python 3, this branch checked out.
- `render` and `brief` have **no `--pot` option** — they read the pot recorded in the worklog
  config. To test against a scratch pot rather than your live one, run
  `python worklog_agent.py install --pot <folder>` in a throwaway repo first.
- Cost figures only appear where `prices` are configured in the worklog config. A pot with no
  prices is the correct way to test cases 11 and 13.
- Cases 2, 3, 4, 5, 20 and 21 all modify `~/.claude/settings.json`. Take a copy before you start
  and restore it when you finish.

---

## Test cases

### `doctor` — the Machine line

| # | Title | Steps | Expected result | source_ref |
|---|---|---|---|---|
| 1 | Machine line reports this machine's settings | Run `python repo_setup.py doctor` in this repo. Find the line beginning `Machine`. | A line reading ``Machine    model default `opus`; compaction cap 200k; 1M context disabled`` — column-aligned with spaces, no colon after `Machine`. The model and cap match the `model` and `autoCompactWindow` values in `~/.claude/settings.json`. | doctor-machine-line-present |
| 2 | Machine line when settings.json is missing | Rename `~/.claude/settings.json` to `settings.json.off`. Run `python repo_setup.py doctor`. | The Machine line is **still printed**, reading `Machine    model no default set; compaction no cap set; 1M context —`. It is not omitted. No traceback, and the rest of doctor is unchanged. Restore the file afterwards. | doctor-machine-missing-settings |
| 3 | Machine line when settings.json is not valid JSON | Back up `~/.claude/settings.json`, replace its contents with `{invalid json`, run `python repo_setup.py doctor`. | The same line as case 2 — `model no default set; compaction no cap set; 1M context —`. No traceback, doctor completes. Restore the backup afterwards. | doctor-machine-malformed-json |
| 4 | Machine line when settings.json is valid JSON but not an object | Back up `~/.claude/settings.json`. Replace its contents with `[]` (a JSON array). Run `python repo_setup.py doctor`. Repeat with `"env": "PATH=x"` in an otherwise normal settings file. | doctor completes both times with no traceback. The array case reads `Machine    model no default set; compaction no cap set; 1M context —`; the string-`env` case names the model and reads `1M context not disabled`. The repo-standards lines *after* the Machine line are still printed — an earlier build crashed here and lost them. Restore the backup. | doctor-machine-non-object-settings |
| 5 | Machine line says "not disabled" when the flag is absent | Back up settings.json. Replace it with `{"model": "haiku", "autoCompactWindow": 250000}` and no `env` section. Run doctor. | The line reads ``Machine    model default `haiku`; compaction cap 250000; 1M context not disabled``. Restore the backup. | doctor-machine-1m-not-disabled |
| 6 | doctor prints no secret or environment values | Run `python repo_setup.py doctor` and read every line of output. | No API key, token or environment-variable *value* appears anywhere — not in full, not as a prefix. The UAT Hub line says only whether the key is set. The Machine line names the model and the cap, which are settings rather than secrets, and reports nothing from `env` beyond disabled or not disabled. | doctor-prints-no-values |

### The Explore agent

| # | Title | Steps | Expected result | source_ref |
|---|---|---|---|---|
| 7 | Explore ships to a refreshed repo | In a scratch git repo, run `python <path>/repo_setup.py refresh`. Open `.claude/agents/Explore.md`. | The file exists. Its frontmatter contains `name: Explore`, `model: sonnet`, and `tools: Read, Grep, Glob`. | explore-agent-shipped |
| 8 | The three gating agents still inherit the session model | In the same repo, open `.claude/agents/code-reviewer.md`, `.claude/agents/security-reviewer.md` and `.claude/agents/impact-analyst.md`. | None of the three has a `model:` line in its frontmatter. This is intended — they inherit the session model, and a test pins the absence. | gating-agents-inherit |
| 9 | check reports the repo complete after refresh | In the same scratch repo, run `python <path>/repo_setup.py check`. | It reports the standards as complete and lists no missing agent. | check-after-refresh |

### Weekly report — `## Cost and context`

| # | Title | Steps | Expected result | source_ref |
|---|---|---|---|---|
| 10 | Cost and context section appears | With prices configured and at least one session collected by 1.19, run `python worklog_agent.py render`, then open `latest-week.md` in the pot. | A section headed exactly `## Cost and context`, followed by one line of the form `$123.45 · 26% elevated context (7% very high) · 19% subagents.` Note the words "elevated context", and the closing full stop. | cost-section-present |
| 11 | Section omitted when no prices are configured | Use a pot whose config has no `prices`. Render. | No `## Cost and context` section at all. No `$0.00`, and no placeholder line. | cost-section-omitted-no-prices |
| 12 | Section omitted when every slice predates 1.19 | Use a pot holding only slices collected by worklog 1.18 or earlier. Render. | No `## Cost and context` section. Nothing is shown as a zero or as an estimate for those sessions. | cost-section-omitted-legacy |
| 13 | Unpriced models are marked, not silently dropped | Render a range containing a model that has no entry in `prices`. | The cash amount is followed by an asterisk, e.g. `$123.45* · …`, marking the total as incomplete. | cost-unpriced-marker |
| 14 | Sessions that reached elevated context are listed | Render a range containing at least one session whose context passed 150,000 tokens. | Under the cost line: `Sessions that reached elevated context (150k+ tokens) in this range:` followed by bullets of the form `- <project> — <first 80 characters of the opening prompt> (<n> tokens)`. | elevated-session-list |
| 15 | The elevated list stops at ten | Render a range containing more than ten sessions above 150,000 tokens. | Exactly ten bullets, the ten highest by context high-water mark. | elevated-session-list-cap |
| 16 | Sessions that stayed below 150k are not listed | Render a range in which some sessions stayed under 150,000 tokens. | Those sessions do not appear in the elevated list. They still count towards the cost total. | elevated-list-excludes-normal |

### Morning page

| # | Title | Steps | Expected result | source_ref |
|---|---|---|---|---|
| 17 | Yesterday's cost line | Run `python worklog_agent.py brief` and read the section for yesterday. | A cost line worded exactly as in the weekly report: `$X.XX · Y% elevated context (Z% very high) · W% subagents.` | morning-cost-line |
| 18 | This week's cost line | On the same page, read the block under the heading `This week so far`. | The same cost line, covering the week to date rather than yesterday. | morning-week-cost-line |
| 19 | Footer names this machine's settings | Scroll to the foot of the morning page. | A line reading ``This machine: model default `opus`; compaction cap 200k.`` On a machine where the 1M disable flag is set there is **no** third clause — its absence is what "disabled" looks like here. | morning-machine-footer |
| 20 | Footer warns when 1M context is not disabled | Back up `~/.claude/settings.json`; replace it with `{"model": "haiku", "autoCompactWindow": 250000}`. Run `python worklog_agent.py brief`. | The footer reads ``This machine: model default `haiku`; compaction cap 250000; 1M context not disabled.`` Restore the backup. | morning-machine-footer-1m-clause |
| 21 | Footer omitted when settings.json is missing or unreadable | Rename `~/.claude/settings.json` aside. Run `python worklog_agent.py brief`. | No `This machine:` line anywhere on the page. The page renders and opens normally — a missing settings file is nothing to report, not a failure. Restore the file. | morning-machine-footer-omitted |

### Boundaries and the fragile parts

These are driven by the unit tests: the values sit on exact token boundaries that cannot be
produced by hand from a real session.

| # | Title | Steps | Expected result | source_ref |
|---|---|---|---|---|
| 22 | Band boundaries at exactly 150,000 and 800,000 | Run `python -m unittest tests.test_worklog_context_bands.MainThreadBandBucketingTests -v`. | All pass. 149,999 tokens is `normal` and 150,000 is `elevated`; 799,999 is `elevated` and 800,000 is `very high`. Each boundary belongs to the upper band. | band-boundaries |
| 23 | A subagent request never raises the main thread's high-water mark | Run `python -m unittest tests.test_worklog_context_bands.ContextMaxTests -v`. | All pass, including the case where a large subagent request is present: `context_max` reflects main-thread requests only, and is the maximum, not a sum or an average. | subagent-not-in-context-max |
| 24 | Main-thread and subagent tokens are split, with nothing double-counted | Run `python -m unittest tests.test_worklog_context_bands.MainVsSubagentSplitTests tests.test_worklog_context_bands.SubagentBucketingTests -v`. | All pass. Every request lands in exactly one of the two maps, and a request repeated across transcript lines is counted once. | main-subagent-split |
| 25 | Pre-1.19 slices return empty maps, not zeros | Run `python -m unittest tests.test_worklog_context_bands.SessionBandTokensInRangeTests tests.test_worklog_context_bands.SessionSubagentTokensInRangeTests -v`. | All pass, including a session carrying none of the 1.19 keys: the readers return an empty map, so the report can say "not collected" rather than show a zero. | legacy-slice-empty-maps |
| 26 | The machine note handles a missing, empty or malformed settings file | Run `python -m unittest tests.test_worklog_context_bands.MachineContextNoteMissingOrBadSettingsTests tests.test_worklog_context_bands.MachineContextNoteContentTests -v`. | All pass. A missing or unparsable file yields no line at all rather than an error, and the composed sentences match exactly. | machine-note-unit |
| 27 | The whole suite is green | Run `python -m unittest discover -s tests`. This is what `.githooks/checks` runs on pre-push and in CI. | The run ends `OK`, with no failures and no errors. | full-suite-green |
| 28 | Both tools still compile | Run `python -m py_compile repo_setup.py worklog_agent.py`. | No output, and exit status 0. | py-compile-clean |

---

## Not covered here

- **Live context growth.** These cases test what the report does with collected data. Watching a
  real session climb through the bands takes days and is not a UAT step.
- **Whether Sonnet is good enough for Explore.** Case 6 checks that the routing is declared;
  whether the search results are as useful is a judgement made in use, not a pass or a fail.
- **The `Plan` agent.** It was deliberately left on the inherited model this release, so there is
  nothing to test.
- **The machine settings themselves.** `~/.claude/settings.json` is machine configuration, not
  repository content. Cases 1 and 18 read it; nothing in this release writes it.

---

## Sign-off

| Name | Role | Date | Decision |
|------|------|------|----------|
| | Tester | | |
