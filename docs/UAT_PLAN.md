# UAT PLAN - teknobu-kit

Master list of user-observable behaviours, kept current by uat-writer. Per-PR documents live in docs/uat/.

| ID | Area | Flow | Expected |
|----|------|------|----------|
| UAT-1 | Git hooks | Try to commit with invalid format | Commit is rejected; message explains Conventional Commits format |
| UAT-2 | Git hooks | Stage and commit to prelive with valid format, then force push | Commit succeeds; force push is allowed on prelive |
| UAT-3 | Git hooks | Try to commit directly to main | Commit fails; message says "Never push to main directly" |
| UAT-4 | CI gates workflow | Push to prelive and check GitHub Actions | ci-gates workflow is triggered; jobs include typecheck, lint, tests |
| UAT-5 | Markdown report — agent grouping | Run render and open weekly report, find "## Agents and commands" section | Table shows projects in bold rows with agents as indented rows below; projects sorted by wall time desc |
| UAT-6 | Markdown report — friendly names | Check agent names in the table | Agents show friendly names (e.g. "Stephen - Tech Nerd") not raw IDs (e.g. "code-reviewer") |
| UAT-7 | Markdown report — custom names | Set agent_names override in ~/.claude/worklog.json and render | Custom friendly name appears instead of builtin |
| UAT-8 | Dashboard — Agents card grouping | Open dashboard.html and check Agents card table | Table shows project rows in bold, agent rows below, all sorted by wall time; columns: Project/agent, Runs, Time, Share, Input, Output |
| UAT-9 | Dashboard — agent hover tooltip | Hover over a friendly agent name in the Agents card | Tooltip shows the raw agent ID |
| UAT-10 | Dashboard — share bars | Check "Share" column bar charts | Bars fill proportionally to agent wall time relative to the max; empty agents show minimal or no fill |
| UAT-11 | Dashboard — config overrides | Set agent_names override and reload dashboard.html | Custom friendly name appears in Agents card |
| UAT-12 | Config robustness — string value | Set agent_names to a string value and render | Report renders successfully; builtin names used; no error |
| UAT-13 | Config robustness — list value | Set agent_names to a list and render | Report renders successfully; builtin names used; no error |
| UAT-14 | Config robustness — empty/null values | Set agent_names with empty string or null values and render | Empty/null overrides ignored; builtin names used |
| UAT-15 | Config — name sanitisation | Set agent_names with pipe character (e.g. "A|B") and render | Pipe becomes slash; markdown renders without breakage |
| UAT-16 | Config — whitespace normalisation | Set agent_names with leading/trailing whitespace and newlines; render | Whitespace and newlines collapsed to single spaces |
| UAT-17 | Unit tests — command | Run `python -m unittest discover -s tests` | All 36 tests pass |
| UAT-18 | Unit tests — agent_name_map tests | Run AgentNameMapTests | 13 tests pass; includes builtin names, overrides, mutation safety, malformed config tolerance |
| UAT-19 | Unit tests — report grouping tests | Run ReportAgentsSectionTests | 15 tests pass; covers project totals, agent ordering, friendly names, edge cases |
| UAT-20 | Unit tests — dashboard payload test | Run DashboardDataAgentNamesTests | 2 tests pass; validates agent_names in dashboard payload |
| UAT-21 | .githooks integration | Run `.githooks/checks` | Checks complete successfully; py_compile and unittest all pass |
| UAT-22 | Status and docs structure | Verify docs structure: STATUS.md, ARCHITECTURE.md, UAT_PLAN.md, decisions/, etc. | All files/directories exist and are readable |
| UAT-23 | CLAUDE.md conventions | Open CLAUDE.md and verify content | Contains Session start, Commands, Conventions, Where knowledge lives sections |
| UAT-24 | .teknobu.json config | Open .teknobu.json | Valid JSON; project metadata present; ignored by git |
| UAT-25 | Self-upgrade from older pot binary | Run v1.15 repo agent against v1.14 pot binary; check pot bin upgrades and log records it | Pot binary is atomically replaced; agent.log shows "self-upgrade 1.14 -> 1.15" |
| UAT-26 | Refuse to adopt a corrupt pot binary | Corrupt the pot binary's tail while keeping VERSION line; run agent | Agent detects version but fails to parse/import corrupted file, logs "self-upgrade skipped" with traceback, continues using repo copy |
| UAT-27 | No upgrade if versions are equal | Run agent when pot binary and repo copy are both v1.15 | No "self-upgrade" message logged; version check skips upgrade |
| UAT-28 | No downgrade if pot binary is older | Run v1.15 agent against v1.13 pot binary | Version check prevents downgrade; no upgrade attempted |
| UAT-29 | Atomic write: concurrent reads during upgrade | Background process loops reading pot binary while agent upgrades it | All reads succeed without corruption; pot transitions cleanly from old to new version |
| UAT-30 | Session-start message on first install (new repo) | Run install command in a repo with no .worklog/ | Stdout prints "Worklog agent v1.15 installed in this repo; it now reports to <pot>." |
| UAT-31 | Session-start message on upgrade (bootstrap) | Run install on a repo with older v1.14 .worklog/agent | Stdout prints "Worklog agent upgraded v1.14 to v1.15 in this repo - new: <WHATS_NEW>" |
| UAT-32 | Dashboard header: 7-day what's-new window | Render with fresh version state, check dashboard meta line for "· worklog v1.15 · new: ..." | Meta line includes version and what's-new note; hand-edit first_render 8 days back and re-render to see note expire |
| UAT-33 | Dashboard header: version marker persists after expiration | After what's-new expires, check dashboard meta line | Meta line shows "· worklog v1.15" without "new: ..." suffix (version remains, note is gone) |
| UAT-34 | Morning page: 3-day what's-new window | Render with fresh version state and check morning.html for upgrade announcement | Announcement appears ("Worklog upgraded to v1.15 — ..."); hand-edit first_render 4 days back to see it expire |
| UAT-35 | What's-new state: version mismatch restamps the clock | Set .whats-new.json to v1.14, render with v1.15 agent | File restamps to current version and time: {"version": "1.15", "first_render": "<now>"} |
| UAT-36 | What's-new state: equal version with no recorded date restamps once | Set .whats-new.json to {"version": "1.15"} with no first_render, render twice | First render adds first_render timestamp; second render does not change it |
| UAT-37 | What's-new state: older agent does not reset the clock | Set .whats-new.json to v1.15 with a recorded date, run older v1.14 agent render | File unchanged; older version check prevents restamp (shared-pot safety) |
| UAT-38 | What's-new state: malformed JSON is recovered | Set .whats-new.json to invalid JSON, run render | Render succeeds; file is overwritten with valid JSON |
| UAT-39 | What's-new state: nonexistent pot/.whats-new.json on first render | Create test pot with no .whats-new.json, run render | File is created with {"version": "1.15", "first_render": "<render-time>"}; what's-new content appears in dashboard and morning page |
| UAT-40 | Unit tests — all 75 pass | Run `python -m unittest discover -s tests` | Output shows "Ran 75 tests" and "OK" (no FAIL or ERROR lines) |
| UAT-41 | Unit tests — what's-new note tests | Run WhatsNewNoteTests | All test methods pass (includes: missing state file, custom text, old/equal/fresh versions, malformed state) |
| UAT-42 | Unit tests — what's-new constants | Run WhatsNewConstantsTests | All test methods pass; WHATS_NEW and WHATS_NEW_SHORT are nonempty, single-line, within 80 chars |
| UAT-43 | Unit tests — render restamp logic | Run RenderRestampTests | All test methods pass; end-to-end render tests verify version bump, equal version, and older agent clock safety |
| UAT-44 | Unit tests — dashboard payload | Run DashboardDataVersionTests | All test methods pass; payload embeds "version" and "whats_new" fields with correct values |
| UAT-45 | Unit tests — version parsing and comparison | Run VersionOfTests | All test methods pass; version_of() reads VERSION line correctly; tuple comparison ranks versions |
| UAT-46 | Unit tests — upgrade guard comparison | Run UpgradeGuardComparisonTests | All test methods pass; upgrade logic: newer > current (adopt), equal (no-op), older < current (no downgrade) |
| UAT-47 | .githooks/checks includes v1.15 unit tests | Run `.githooks/checks` | Script completes successfully; python -m unittest passes with 75 tests; py_compile passes |
