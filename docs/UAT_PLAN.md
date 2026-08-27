# UAT PLAN - teknobu-kit

Master list of user-observable behaviours, kept current by uat-writer. Per-PR documents live in docs/uat/.

## Changed in this cycle (kit v4.3)

### New: `repo_setup.py refresh` — take a release without the rest of apply
- UAT-4.3-1: In a repo already on the kit, `refresh --dry-run` reports what would change and writes nothing.
- UAT-4.3-2: `refresh` updates `.claude/agents/`, `.claude/commands/`, `.claude/hooks/`, the kit's gates (`.github/workflows/ci-gates.yml`, `.github/pull_request_template.md`) and the managed CLAUDE.md section. It leaves the repo's **own** `.github/workflows/ci.yml`, the deploy workflow, the environment doc, `.githooks/`, `.env*` and `.claude/rules/design.md` byte-identical.
- UAT-4.3-2b: every file `refresh` replaced is named in its output, not just counted — a rewritten workflow or agent must be visible to the operator.
- UAT-4.3-2c: a CLAUDE.md carrying hand-written policy outside the kit markers is backed up before the managed section is rewritten.
- UAT-4.3-3: `refresh` never creates or checks out a branch. The branch you were on is the branch you are on.
- UAT-4.3-4: A hand-edited `.githooks/checks` survives `refresh`; a hand-edited shipped agent is replaced, with the original in `.claude/.backup/<timestamp>/`.
- UAT-4.3-5: After `refresh`, `.teknobu.json` records the new kit version and the session-start nudge stops reporting the repo as out of date. Other keys in that file are unchanged.
- UAT-4.3-6: `.claude/.backup/` does not appear in `git status` after a refresh.
- UAT-4.3-7: In a worklog-only repo, `refresh` says so and does nothing.

### Fixed: apply and refresh no longer fight over the PR template
- UAT-4.3-15: run `apply` then `refresh` immediately. The refresh reports `0 files added` with nothing replaced and no backup directory — previously it replaced `.github/pull_request_template.md` every time, and an `apply` afterwards replaced it back.

### Changed: agent model routing
- UAT-4.3-8: Every file in `.claude/agents/` carries a `model:` line except code-reviewer, security-reviewer and impact-analyst, which carry none by design.
- UAT-4.3-9: `/landing` shows the model against each agent; four now read `sonnet`, four `haiku`, three blank.
- UAT-4.3-10: A repo whose `design-reviewer.md` predates v4.3 gets the new frontmatter on `refresh` — this never used to happen. Its `.claude/rules/design.md` is untouched.
- UAT-4.3-11 (judgement, needs a real change): code-reviewer still reports a regression in a file the diff does not touch, when a changed signature has callers there. The reading budget must not have cost that.

## Changed in a previous cycle (kit v4.2)

### New: Event-driven pipeline with stop gate and review verdicts
- Stop gate now blocks when code changes exist without a fresh /post-change verdict
- Session start briefly reports outstanding review debt; silent on clean repo
- /post-change records a content signature so gate detects stale verdicts
- /release-ready cuts a GitHub release on merge to main (automated CI)
- `repo_setup.py update` offers the new version at session start; consent required for install
- First code-path edit on a branch produces an advisory nudge; second edit is silent
- Editing .github/workflows files marks the security reviewer as due

### Scenarios affected by new stop gate behaviour
UAT-4 (CI gates): no change, still tests the ci-gates workflow.

### New scenarios for kit v4.2
- UAT-79 to UAT-100: Stop gate, session start, update loop, post-edit nudge, workflow reviewer trigger, and auto-release. Full test procedures in docs/uat/prelive-2026-08-25-kit-4-2-pipeline.md.

---

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
| UAT-48 | worktree new — directory created | Run `python repo_setup.py worktree new <branch>` in a repo | Directory <repo>-wt-<branch> is created as a sibling of the repo |
| UAT-49 | worktree new — branch checked out | Create a worktree with new branch, check HEAD | Worktree is on the requested branch |
| UAT-50 | worktree new — existing branch reused | Create a worktree on a branch that already exists | Worktree is created on the existing branch with all prior commits |
| UAT-51 | worktree new — branch sanitisation | Create a worktree with branch name containing slashes or special characters | Directory name has branch name sanitised: slashes become dashes, weird chars collapse to one dash |
| UAT-52 | worktree new — worklog stamped with parent project | Create a worktree, check .worklog/worklog.json | File contains {"project": "<repo-name>"} by default |
| UAT-53 | worktree new — worklog inherits parent project name | Parent repo has .worklog/worklog.json with custom project name; create a worktree | Worktree's .worklog/worklog.json inherits the parent's project name |
| UAT-54 | worktree new — info/exclude updated to share .worklog/ | Create a worktree in a kit-standardised repo | .git/info/exclude contains ".worklog/" to keep worktree's .worklog/ from reading as dirty |
| UAT-55 | worktree new — duplicate branch fails gracefully | Try to create two worktrees with the same branch name | Second attempt exits with error message mentioning the directory already exists |
| UAT-56 | worktree list — main worktree flagged and shown first | Run `python repo_setup.py worktree list` | First line shows main worktree marked "(main worktree)" |
| UAT-57 | worktree list — fresh worktree marked "no commits yet" | Create a worktree with a new branch, make no commits | List shows "no commits yet" for the worktree |
| UAT-58 | worktree list — merged worktree shown as merged | Create a worktree, commit in it, merge into work branch, run list | Worktree shows "merged into work" |
| UAT-59 | worktree list — unmerged worktree shown as unmerged | Create a worktree, commit in it, do NOT merge into work branch, run list | Worktree shows "not merged into work" |
| UAT-60 | worktree list — dirty worktree shown as uncommitted changes | Create a worktree and add an untracked file without staging or committing | List shows "uncommitted changes" |
| UAT-61 | worktree list — missing directory shown as stale | Create a worktree, manually delete its directory, run list | List shows "directory gone (run worktree clean)" |
| UAT-62 | worktree clean — removes merged+clean worktrees | Create merged+clean and dirty worktrees, run clean | Merged worktree is removed; dirty one is kept with reason |
| UAT-63 | worktree clean — keeps unmerged worktrees | Create an unmerged worktree, run clean | Worktree is kept with "not merged into work" message |
| UAT-64 | worktree clean — keeps dirty worktrees | Create a dirty worktree, run clean | Worktree is kept with "uncommitted changes" message |
| UAT-65 | worktree clean — prunes stale records | Create a worktree, delete its directory, run clean | Output shows "stale record pruned"; worktree no longer appears in list |
| UAT-66 | worktree clean — never deletes branches | Clean a merged+clean worktree, verify the branch survives | Branch still exists in git; output says "branch <name> kept" |
| UAT-67 | worktree clean — leaves main worktree untouched | Run clean from the main worktree | Main worktree is not removed or altered |
| UAT-68 | worktree clean — detached worktrees kept with reason | Create a detached worktree, run clean | Worktree is kept with message about detached HEAD; remove-by-hand instruction provided |
| UAT-69 | worktree clean — squash-merged branches kept with note | Create a worktree, squash-merge into work, run clean | Worktree is kept with "not merged into work" message (safe: branch survives) |
| UAT-70 | worktree clean — tag shadowing branch name does not fool merge check | Create branch "feat", commit on it, create tag "feat" at work's tip, run clean | Worktree is kept as "not merged" (tag does not shadow branch in merge check) |
| UAT-71 | worklog v1.16 — install in main repo succeeds | Copy worklog_agent.py into a repo .worklog/ and run install | post-commit hook is written to .git/hooks/ without error |
| UAT-72 | worklog v1.16 — install in linked worktree succeeds | Create a linked worktree, copy worklog_agent.py, run install | post-commit hook lands in the shared hooks directory; no OSError raised |
| UAT-73 | worklog v1.16 — commit hook fires in worktree | Create a worktree with worklog installed, make a commit | Post-commit hook runs without error; agent.log shows session was logged |
| UAT-74 | /worktree command in kit pipeline | Apply kit standards to a repo, check .claude/commands/worktree.md | File exists with description of worktree command (new, list, clean verbs) |
| UAT-75 | Unit tests — repo_setup worktree functions | Run `python -m unittest tests.test_repo_setup_worktree` | All tests pass (wt_dirname, wt_list, wt_state, cmd_worktree) |
| UAT-76 | Unit tests — worklog worktree hook install | Run `python -m unittest tests.test_worklog_worktree` | Both tests pass (install in main repo and in linked worktree) |
| UAT-77 | .githooks/checks includes worktree tests | Run `.githooks/checks` | Script passes; python -m unittest discover runs all tests including worktree (98 total); py_compile passes |
| UAT-78 | Kit repo scenario — worktree new/list/clean on this kit repo | Create a worktree on the kit repo, make commits, merge, clean | Worktree creation, listing, and cleanup work as expected on the kit repo itself |
| UAT-79 | Stop gate — initial block: code changes without verdict | Edit a .py file under supabase/ or functions/, do not run /post-change, attempt to push to prelive | Push is blocked with "reviewers due" message; block is counted (block 1/2) |
| UAT-80 | Stop gate — second block: stale verdict not refreshed | Re-push without running /post-change again | Push is blocked again with "reviewers due" message; block is counted (block 2/2 — disclosure mode next) |
| UAT-81 | Stop gate — disclosure demand: third attempt without refresh | Third push attempt without /post-change | Push is blocked with a disclosure message asking user to confirm they understand review is due; block is marked as disclosure |
| UAT-82 | Stop gate — allow after disclosure: gate can pass after disclosure demand | After disclosure block, run /post-change to record fresh verdict, then push | Push succeeds; gate clears; block counter resets on new signature |
| UAT-83 | Stop gate — fresh verdict clears block: /post-change refreshes the gate | Edit a .py file, push (blocked), run /post-change, push again | Second push attempt succeeds; fresh verdict in review.json matches current sig |
| UAT-84 | Stop gate — changelog-only debt still blocks | Edit only CHANGELOG.md (no code changes), attempt to push | Push is blocked with changelog debt message; gate maintains v4.1 changelog-blocking behavior |
| UAT-85 | Stop gate — detached HEAD or no pipeline-state.sh: fallback to legacy gate | On a branch without .claude/hooks/pipeline-state.sh or in detached HEAD state, attempt push | Gate falls back to v4.1 semantics: session can stop without verdict (signature-less state) |
| UAT-86 | Session start — report outstanding debt | Start a session (run repo_setup.py or clone a repo with review debt) in a kit repo with pending verdict | First line of output shows brief debt summary (e.g., "Code review pending: code reviewer"); clean output if no debt |
| UAT-87 | Session start — clean repo silent | Start a session in a kit repo with all review debt cleared | No debt message is printed; startup is silent |
| UAT-88 | apply --update-pipeline — docs survival | Run `repo_setup.py apply --update-pipeline` on a repo with filled-in docs/STATUS.md, ARCHITECTURE.md, decisions/ | Docs files are preserved; only hook/workflow/config files in managed sections are updated |
| UAT-89 | post-edit nudge — first edit advisory | Edit a file under supabase/ or functions/ on a branch without impact.json | Advisory message appears once, mentioning the impact-report requirement |
| UAT-90 | post-edit nudge — second edit silent | Make a second edit to supabase/ or functions/ without running impact-report | No advisory message is printed; nudge fires only once per branch |
| UAT-91 | post-edit nudge — impact.json suppresses advisory | Create impact.json, edit supabase/ or functions/ | No advisory message appears; nudge is skipped when impact report exists |
| UAT-92 | Editing .github/workflows makes security reviewer due | Edit .github/workflows/release.yml (or any file in .github/workflows/), do not run /post-change | Stop gate: security reviewer is listed as due; /post-change requires security sign-off |
| UAT-93 | Auto-update: release published on main merge (CI) | Merge a PR from prelive to main, check GitHub Actions | release.yml workflow is triggered; release is published with a tag and binary/zip artifact (CLIENT-SIDE VERIFICATION: GitHub UI) |
| UAT-94 | Auto-update: next session offers update (daily throttled) | Within 24 hours of a release, start a new session on a machine with v4.2 kit installed, in a different repo | Session start message offers "run `repo_setup.py update`" (throttled: once per day per machine, 3s network timeout) (CLIENT-SIDE VERIFICATION: network, release download) |
| UAT-95 | Auto-update: update from release zip succeeds | Run `repo_setup.py update` when prompted | Tool downloads latest release, extracts it, updates worklog_agent.py and repo_setup.py atomically in the machine home; consent is required (no auto-apply) (CLIENT-SIDE VERIFICATION: network, file system write) |
| UAT-96 | Auto-update: update consent required | Run `repo_setup.py update` | Tool prompts for consent before any file is modified; updating proceeds only on user approval |
| UAT-97 | Auto-update: offline update silent | With network disabled (or 3s timeout exhausted), run `repo_setup.py update` | Tool exits gracefully with no error; next session with network available will retry (CLIENT-SIDE VERIFICATION: network simulation or air-gapped machine) |
| UAT-98 | Unit tests — all 98+ pass | Run `python -m unittest discover -s tests` | Output shows "Ran 98 tests" (or higher) and "OK" with no FAIL or ERROR lines |
| UAT-99 | Unit tests — pipeline-state and stop-gate tests | Run pipeline-state test suite | All tests pass covering signature computation, verdict matching, block counting, and fallback logic |
| UAT-100 | Unit tests — auto-update and release tests | Run worklog update tests | All tests pass covering version checks, release download logic, consent flow, and offline handling |

## Client-Side Verification (Real accounts, live integrations, third-party services)

The following scenarios require real GitHub accounts, live network, or third-party integrations and must be verified manually or in CI:

- **UAT-93**: Verify GitHub Actions publishes a release artifact (requires GitHub org/repo, release.yml execution, artifact visibility)
- **UAT-94**: Verify session start offers update prompt on a real machine within 24h of release (requires machine with internet, throttling logic, release availability)
- **UAT-95**: Verify release zip can be downloaded and extracted successfully; file permissions and atomicity on real file system (requires network, write access to `~/.claude/sonelo/`)
- **UAT-97**: Verify offline graceful exit and retry behavior; requires network simulation or air-gapped machine

## Notes

- Verdicts are no longer committed (`.claude/state/` is gitignored); old `review.json` files in git are stale and harmless
- Scenario IDs are stable; if a scenario retires, it moves to an Archive section rather than being renumbered
- The stop gate uses content signatures (`sig` field in `review.json`) to detect stale verdicts independent of file timestamps
- Block counter resets on every new signature; a fresh /post-change recording a new sig clears all prior blocks
