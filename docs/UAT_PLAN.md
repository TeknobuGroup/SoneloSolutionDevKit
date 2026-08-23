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
