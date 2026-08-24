# UAT — worklog v1.15 upgrade and what's-new announcements — 2026-08-24

**Branch:** prelive  **Environment:** local machine with kit installed and worklog agent in test repos  **Prepared by:** Claude Code  **Status:** awaiting sign-off

## What changed

Worklog agent v1.15 introduces two major capabilities:
1. **Mid-session self-upgrade**: Every hook run (end-of-session, stop, or manual collect) now compares the pot's machine binary (`<pot>/bin/worklog_agent.py`) with the running repo copy and atomically adopts a newer version for the next run. Older repo copies also self-upgrade on SessionStart. Version numbers are parsed from the VERSION line; corrupt or torn binaries are refused with a logged error.
2. **What's-new announcements**: When the agent detects a version upgrade, it announces the change in three places: a session-start message prints the full description, the dashboard header shows a short note for 7 days after the version first renders in that pot, and the morning page displays the full description for 3 days. State is recorded in `<pot>/.whats-new.json` (only a newer version restamps the first_render timestamp, preventing clock resets from older agents on shared pots). The unit test suite now includes 75 stdlib-only tests covering both features.

## Preconditions

- Machine with Python 3.8+ installed.
- One or more git repos with worklog agent installed (`.worklog/worklog_agent.py` from a prior release, e.g. v1.14).
- `~/.claude/worklog.json` with at least `{"pot": "<path>"}`, or use the default `~/Worklog`.
- At least one Claude Code session session.jsonl file in `~/.claude/projects/<repo-dir>/` with at least one session record (to ensure `python worklog_agent.py render` can complete).
- A test pot directory (e.g. `~/Worklog-test`) separate from any live worklog pot.

## Test data

**For mid-session self-upgrade testing:**
1. Create a test pot: `mkdir -p ~/Worklog-test/slices`.
2. Place an older version binary in the test pot: create a file `~/Worklog-test/bin/worklog_agent.py` (copy the current worklog_agent.py but edit line `VERSION = "1.14"` to downgrade it).
3. Place a minimal valid slice for rendering: write `~/Worklog-test/slices/Alpha__alpha.json` with:
   ```json
   {"project": "Alpha", "repo": "alpha", "path": "/home/user/alpha", "machine": "testmachine",
    "updated": "2026-08-24T12:00:00+00:00", "since": "2026-07-27T00:00:00+00:00",
    "uncommitted": 0, "commits": [], "sessions": [], "version": "1.14"}
   ```
4. Create a test git repo with `.worklog/worklog_agent.py` at v1.15 (the current version in the branch).
5. Set the test pot in `~/.claude/worklog.json`: `{"pot": "~/Worklog-test"}`.

**For what's-new state testing:**
   Create a test pot with an existing `.whats-new.json` file. For expiration tests, hand-edit the `first_render` timestamp to 8 days in the past.

**For unit tests:**
   The test suite is self-contained and hermetic; it creates temp pots and repo dirs internally. No special setup is needed.

| ID | Area | Steps | Expected | Result | Tester | Date |
|----|------|-------|----------|--------|--------|------|
| UAT-25 | Self-upgrade from older pot binary | 1. Set up a test pot with `.whats-new.json` and `bin/worklog_agent.py` at v1.14. 2. Copy a repo-local v1.15 agent into `.worklog/worklog_agent.py`. 3. Run `python .worklog/worklog_agent.py run --sync` from the repo (uses v1.15 running, checks the pot bin). 4. Check `.worklog/agent.log` for "self-upgrade 1.14 -> 1.15" message. 5. Verify `~/Worklog-test/bin/worklog_agent.py` now contains v1.15. | The repo agent (v1.15) adopts the pot binary (v1.14), detects it is older, replaces it atomically, and logs the action. On the next run, the repo agent runs v1.15 and does not upgrade again. | | | |
| UAT-26 | Refuse to adopt a corrupt pot binary | 1. Set up a test pot with `bin/worklog_agent.py` at v1.14 but with the last 50 bytes replaced with random garbage (leaving VERSION = "1.16" intact). 2. Copy v1.15 repo agent. 3. Run `python .worklog/worklog_agent.py run --sync`. 4. Check `.worklog/agent.log`. 5. Verify the local repo agent is still v1.15. | The agent detects v1.16 in the corrupt pot binary but fails to import/parse it, logs "self-upgrade skipped" with traceback, and continues using the repo copy (v1.15). The corrupt pot binary is left in place (not replaced, no forced adoption). | | | |
| UAT-27 | No upgrade if versions are equal | 1. Set up a test pot with `bin/worklog_agent.py` at v1.15 (same as repo copy). 2. Run `python .worklog/worklog_agent.py run --sync`. 3. Check `.worklog/agent.log` for upgrade messages. | No "self-upgrade" message is logged. The check finds version equality, skips the upgrade, and continues normally. | | | |
| UAT-28 | No downgrade if pot binary is older | 1. Set up a test pot with `bin/worklog_agent.py` at v1.13. 2. Copy v1.15 repo agent. 3. Run `python .worklog/worklog_agent.py run --sync`. 4. Check `.worklog/agent.log`. | No upgrade is attempted (version_of(pot) <= version_of(repo)), no message logged, continue normally. | | | |
| UAT-29 | Atomic write: torn file check during concurrent read | 1. Set up a test pot with `bin/worklog_agent.py` at v1.14. 2. Start a background process that continuously reads the pot binary and checks for compilation: `python -c "import py_compile; py_compile.compile('~/Worklog-test/bin/worklog_agent.py')"` in a loop. 3. While looping, run `python .worklog/worklog_agent.py run --sync` (which upgrades to v1.15 and writes atomically). 4. Stop the loop after 2 cycles. 5. Verify all reads succeed (no syntax errors from torn files) and pot binary is v1.15. | Atomic write (tempfile + os.replace) ensures the pot binary is never in a half-written state. All read attempts complete without corruption; the pot binary transitions cleanly from v1.14 to v1.15. | | | |
| UAT-30 | Session-start message on first install (new repo) | 1. In a new git repo with no `.worklog/` directory, run `python -m worklog_agent install` (or `python worklog_agent.py install` if run from outside). 2. Check stdout for the installation message. | Stdout prints "Worklog agent v1.15 installed in this repo; it now reports to <pot>." | | | |
| UAT-31 | Session-start message on upgrade (bootstrap) | 1. Copy an older v1.14 `.worklog/worklog_agent.py` into a repo. 2. Run `python -m worklog_agent install` (simulating SessionStart bootstrap). 3. Check stdout. | Stdout prints "Worklog agent upgraded v1.14 to v1.15 in this repo - new: agent usage grouped by project with friendly team names; the worklog now upgrades itself mid-session and announces what's new." (or similar, containing "- new: " + WHATS_NEW). | | | |
| UAT-32 | Dashboard header: 7-day what's-new window | 1. Set up a test pot with a slice and render reports: `python .worklog/worklog_agent.py render --pot ~/Worklog-test`. 2. Open `~/Worklog-test/dashboard.html` in a browser. 3. Look at the meta line at the top (after "rendered", "repo count", etc.). 4. Verify it contains "· worklog v1.15 · new: per-project agent usage with friendly names; self-upgrading". 5. Hand-edit `.whats-new.json` to set `first_render` 8 days in the past (e.g. "2026-08-16T12:00:00+00:00"). 6. Re-render. 7. Check the meta line again. | Step 4: Meta line includes "· worklog v1.15 · new: per-project..." Step 7: Meta line shows "· worklog v1.15" with no "new: ..." suffix (the note has expired after 7 days, but the version marker remains). | | | |
| UAT-33 | Dashboard header: version marker persists after expiration | 1. After step 5-7 of UAT-32 (first_render is 8 days old), check the dashboard meta line. | The meta line still includes "· worklog v1.15" (version number persists). Only the "new: ..." suffix is gone. | | | |
| UAT-34 | Morning page: 3-day what's-new window | 1. Set up a test pot with a slice. 2. Ensure `.whats-new.json` exists with current `first_render` (set it to now or just before running render). 3. Run `python .worklog/worklog_agent.py render --pot ~/Worklog-test` to generate `morning.html`. 4. Open `~/Worklog-test/morning.html` in a browser and scroll to the top section. 5. Verify a line appears: "Worklog upgraded to v1.15 — agent usage grouped by project with friendly team names; the worklog now upgrades itself mid-session and announces what's new." 6. Hand-edit `.whats-new.json` to set `first_render` 4 days in the past. 7. Re-render. 8. Check `morning.html` again. | Step 5: The upgrade announcement appears. Step 8: The upgrade announcement is gone (it expires after 3 days). | | | |
| UAT-35 | What's-new state: version mismatch restamps the clock | 1. Create a test pot and set `.whats-new.json` to `{"version": "1.14", "first_render": "2026-08-20T12:00:00+00:00"}`. 2. Run render with the pot. 3. Check `.whats-new.json` after render. | The file is updated to `{"version": "1.15", "first_render": "<now>"}` (version bumped from 1.14 to 1.15 triggers a restamp with a new timestamp). | | | |
| UAT-36 | What's-new state: equal version with no recorded date restamps once | 1. Create a test pot and set `.whats-new.json` to `{"version": "1.15"}` (no `first_render`). 2. Run render. 3. Check the file content. 4. Run render again immediately. 5. Check the file content again. | Step 3: File now has `first_render` set to the render time. Step 5: `first_render` is unchanged (equal version, date already recorded, so no restamp). | | | |
| UAT-37 | What's-new state: older agent does not reset the clock | 1. Create a test pot with `.whats-new.json` set to `{"version": "1.15", "first_render": "2026-08-24T10:00:00+00:00"}`. 2. Set `.worklog/worklog_agent.py` to v1.14. 3. Run render with this older agent. 4. Check `.whats-new.json`. | The file is unchanged; first_render remains "2026-08-24T10:00:00+00:00". An older agent running on a shared pot must not reset the what's-new clock (older version check prevents restamp). | | | |
| UAT-38 | What's-new state: malformed JSON is recovered | 1. Create a test pot and set `.whats-new.json` to `{broken json}`. 2. Run render. 3. Check the render succeeds and `.whats-new.json` is now valid. | Render completes without error. `.whats-new.json` is overwritten with valid JSON: `{"version": "1.15", "first_render": "<now>"}`. The malformed file is recovered gracefully. | | | |
| UAT-39 | What's-new state: nonexistent pot/.whats-new.json on first render | 1. Create a test pot with no `.whats-new.json`. 2. Run render. 3. Check the file was created. | After render, `.whats-new.json` exists with `{"version": "1.15", "first_render": "<render-time>"}`. Dashboard and morning page show what's-new content for the 7-day and 3-day windows, respectively. | | | |
| UAT-40 | Unit tests — all 75 pass | 1. From the repo root, run `python -m unittest discover -s tests`. | All tests pass. Output shows "Ran 75 tests" and "OK" at the end. No FAIL or ERROR lines. | | | |
| UAT-41 | Unit tests — what's-new note tests | 1. Run `python -m unittest tests.test_worklog_agent.WhatsNewNoteTests`. | All test methods pass (includes: missing state file, custom text, old/equal/fresh versions, malformed state). | | | |
| UAT-42 | Unit tests — what's-new constants | 1. Run `python -m unittest tests.test_worklog_agent.WhatsNewConstantsTests`. | All test methods pass. WHATS_NEW and WHATS_NEW_SHORT are nonempty strings; WHATS_NEW_SHORT is single-line and fits within 80 characters. | | | |
| UAT-43 | Unit tests — render restamp logic | 1. Run `python -m unittest tests.test_worklog_agent.RenderRestampTests`. | All test methods pass. End-to-end render tests with the pot and state file verify version bump restamps, equal version does not restamp if date is missing, and older agent does not reset the clock. | | | |
| UAT-44 | Unit tests — dashboard payload | 1. Run `python -m unittest tests.test_worklog_agent.DashboardDataVersionTests`. | All test methods pass. Dashboard payload embeds "version" field (set to MODULE version) and "whats_new" field (echoes the argument or defaults to empty). | | | |
| UAT-45 | Unit tests — version parsing and comparison | 1. Run `python -m unittest tests.test_worklog_agent.VersionOfTests`. | All test methods pass. version_of() correctly reads VERSION line; tuple comparison ranks versions (1.15 < 1.16, 1.15 == 1.15, etc.). | | | |
| UAT-46 | Unit tests — upgrade guard comparison | 1. Run `python -m unittest tests.test_worklog_agent.UpgradeGuardComparisonTests`. | All test methods pass. Upgrade logic: newer > current (adopt), equal == current (no upgrade), older < current (no downgrade). | | | |
| UAT-47 | .githooks/checks includes unit tests | 1. Run `.githooks/checks` (or on Windows, `bash .githooks/checks`). | Script runs without error. Output shows `python -m unittest discover -s tests` passes with 75 tests. py_compile also passes. | | | |

## Not covered here

- **Actual Claude Code SessionStart and Stop hook integration**: The UAT assumes the agent can be run manually from the command line; testing the full hook invocation (Claude Code calling the agent at session start/stop) is deferred to integration testing in Claude Code itself.
- **Multiple concurrent agent processes upgrading the pot binary simultaneously**: Edge cases where two sessions on different machines both try to upgrade `<pot>/bin/worklog_agent.py` are mitigated by atomic write but full stress testing of concurrent writes is out of scope.
- **ActivityWatch and presence tracking**: The upgrade and what's-new features are orthogonal to desk-time collection; ActivityWatch correctness is not touched here.
- **Historical upgrade paths from v1.12 or earlier**: The agent has been at v1.13+ for several releases; testing upgrade chains (v1.12 -> v1.14 -> v1.15) is not covered.
- **Custom WHATS_NEW text overrides**: The announcement text is hardcoded in the module; testing admin-level override of the message is out of scope.
- **Windows vs. macOS vs. Linux file system semantics**: Atomic write relies on os.replace; platform-specific behaviour (e.g. replacing a file in use on Windows) is not tested in detail.

## Sign-off

| Name | Role | Date | Decision |
|------|------|------|----------|
| | Tester | | |
