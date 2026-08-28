"""Unit tests for the v1.14, v1.15 and v1.17 changes to worklog_agent.py.

v1.14 coverage:
  - agent_name_map(cfg): built-in names merged with cfg["agent_names"] overrides,
    sanitisation, malformed-config tolerance, no mutation of the module constant.
  - build_report(): the per-project "Agents and commands" table (friendly names,
    bold project totals, wall-time ordering, unknown ids, agent-less sessions).
  - dashboard_data(): embeds the merged agent-name map in the payload.

v1.15 coverage:
  - whatsnew_note(pot, days, text): every state-file shape (missing, malformed,
    non-dict, version mismatch, fresh/old/unparsable first_render), the default
    text, and the WHATS_NEW / WHATS_NEW_SHORT constants.
  - render(): the .whats-new.json restamp rules, exercised end to end against a
    temp pot holding one minimal slice (older version restamps, newer never,
    equal only when the recorded date is unreadable).
  - dashboard_data(): the new "version" / "whats_new" payload fields and the
    default when the new parameter is omitted.
  - version_of() and the tuple comparison the cmd_run self-upgrade guard relies on.

v1.17 coverage:
  - the identity active_min == sum(bursts) + idle_minutes * (bursts - 1), exercised
    through collect_sessions against a real transcript. Effort computed any other
    way (a burst union, say) runs tens of percent low.
  - the report's two time figures keep saying which is which: the Summary column is
    effort and labels itself, the Days column is elapsed and labels itself, and the
    explanation prints whether or not ActivityWatch data exists.

Stdlib only; hermetic: nothing is read or written outside the repo or per-test
temp dirs (never ~/Worklog or ~/.claude); the render tests point wa.LOG into
their temp pot for the duration of the test.
Run from the repo root with:  python -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worklog_agent as wa

TZ = wa.local_tz()
SINCE = datetime(2026, 8, 10, 0, 0, 0, tzinfo=TZ)
UNTIL = datetime(2026, 8, 12, 23, 59, 59, tzinfo=TZ)
DAY = datetime(2026, 8, 11, 9, 0, 0, tzinfo=TZ)          # squarely inside the window

CFG = {"currency": "$", "prices": {}, "idle_minutes": 15, "window_days": 28}

# A pot path that is never created: dashboard_data only globs under it.
MISSING_POT = Path(__file__).resolve().parent / "nonexistent-pot"


def make_session(start=DAY, minutes=30, **extra):
    """Minimal session shape build_report requires: start/end ISO, active_min, prompts."""
    s = {"start": start.isoformat(), "end": (start + timedelta(minutes=minutes)).isoformat(),
         "active_min": minutes, "prompts": 1, "title": "synthetic work"}
    s.update(extra)
    return s


def make_slice(project, sessions):
    return {"project": project, "repo": project.lower(), "sessions": sessions, "commits": []}


def make_agent(runs, wall_s, tokens=None):
    a = {"runs": runs, "wall_s": wall_s}
    if tokens is not None:
        a["tokens"] = tokens
    return a


def report(slices, cfg_extra=None):
    cfg = dict(CFG)
    cfg.update(cfg_extra or {})
    md, _rows, _totals = wa.build_report(slices, [], SINCE, UNTIL, cfg)
    return md


def standard_slices():
    """Alpha: one known agent with tokens. Beta: known + unknown agent, more wall time.
    Gamma: a session with no 'agents' key at all."""
    alpha = make_slice("Alpha", [make_session(
        agents={"code-reviewer": make_agent(2, 300, {"in": 1000, "cache_create": 1000, "out": 200})},
        commands={"/review": 2}, tools={"Read": 5, "Edit": 2})])
    beta = make_slice("Beta", [make_session(
        agents={"security-reviewer": make_agent(1, 600), "mystery-agent": make_agent(3, 60)})])
    gamma = make_slice("Gamma", [make_session()])
    return [alpha, beta, gamma]


class AgentNameMapTests(unittest.TestCase):

    def test_builtin_name_is_returned_without_any_override(self):
        self.assertEqual(wa.agent_name_map({})["code-reviewer"], "Stephen - Tech Nerd")

    def test_map_equals_builtins_when_config_has_no_agent_names(self):
        self.assertEqual(wa.agent_name_map({}), wa.AGENT_NAMES)

    def test_override_wins_over_builtin_name(self):
        m = wa.agent_name_map({"agent_names": {"code-reviewer": "Bob"}})
        self.assertEqual(m["code-reviewer"], "Bob")

    def test_override_can_add_a_name_for_a_new_agent_id(self):
        m = wa.agent_name_map({"agent_names": {"my-agent": "Milo"}})
        self.assertEqual(m["my-agent"], "Milo")

    def test_unknown_raw_id_is_absent_so_display_falls_back_to_raw(self):
        self.assertNotIn("no-such-agent", wa.agent_name_map({}))

    def test_empty_string_override_is_dropped_keeping_builtin(self):
        m = wa.agent_name_map({"agent_names": {"code-reviewer": ""}})
        self.assertEqual(m["code-reviewer"], "Stephen - Tech Nerd")

    def test_none_override_is_dropped_keeping_builtin(self):
        m = wa.agent_name_map({"agent_names": {"code-reviewer": None}})
        self.assertEqual(m["code-reviewer"], "Stephen - Tech Nerd")

    def test_string_valued_agent_names_config_is_ignored_without_raising(self):
        self.assertEqual(wa.agent_name_map({"agent_names": "oops"}), wa.AGENT_NAMES)

    def test_list_valued_agent_names_config_is_ignored_without_raising(self):
        self.assertEqual(wa.agent_name_map({"agent_names": ["a", "b"]}), wa.AGENT_NAMES)

    def test_pipe_in_override_value_becomes_slash(self):
        m = wa.agent_name_map({"agent_names": {"code-reviewer": "A|B"}})
        self.assertEqual(m["code-reviewer"], "A/B")

    def test_newlines_and_whitespace_runs_collapse_to_single_spaces(self):
        m = wa.agent_name_map({"agent_names": {"code-reviewer": "  New\nName\t  here "}})
        self.assertEqual(m["code-reviewer"], "New Name here")

    def test_non_string_override_value_is_coerced_to_text(self):
        m = wa.agent_name_map({"agent_names": {"code-reviewer": 7}})
        self.assertEqual(m["code-reviewer"], "7")

    def test_module_level_agent_names_is_not_mutated_by_calls(self):
        before = dict(wa.AGENT_NAMES)
        wa.agent_name_map({"agent_names": {"code-reviewer": "Bob", "my-agent": "Milo"}})
        self.assertEqual(wa.AGENT_NAMES, before)


class ReportAgentsSectionTests(unittest.TestCase):

    def setUp(self):
        self.md = report(standard_slices())

    def test_report_contains_agents_and_commands_heading(self):
        self.assertIn("## Agents and commands", self.md)

    def test_project_with_agents_gets_a_bold_total_row(self):
        self.assertIn("| **Alpha** | **2** | **5m** | **2k** | **200** |", self.md)

    def test_project_total_row_shows_dashes_when_agents_report_no_tokens(self):
        self.assertIn("| **Beta** | **4** | **11m** | **-** | **-** |", self.md)

    def test_agent_row_uses_friendly_name_not_raw_id(self):
        self.assertIn("| · Stephen - Tech Nerd | 2 | 5m | 2k | 200 |", self.md)

    def test_raw_id_does_not_appear_when_a_friendly_name_exists(self):
        self.assertNotIn("code-reviewer", self.md)

    def test_unknown_agent_id_appears_under_its_raw_name(self):
        self.assertIn("| · mystery-agent | 3 | 1m | - | - |", self.md)

    def test_projects_are_ordered_by_summed_agent_wall_time_descending(self):
        # Alpha precedes Beta alphabetically and in the summary ordering; Beta has
        # more agent wall time (660s vs 300s), so it must come first in this table.
        self.assertLess(self.md.index("| **Beta** |"), self.md.index("| **Alpha** |"))

    def test_agents_within_a_project_are_ordered_by_wall_time_descending(self):
        self.assertLess(self.md.index("· Dwayne - Security"),
                        self.md.index("· mystery-agent"))

    def test_project_whose_session_has_no_agents_key_gets_no_total_row(self):
        self.assertNotIn("| **Gamma**", self.md)

    def test_project_whose_session_has_no_agents_key_still_reports_elsewhere(self):
        self.assertIn("## Gamma", self.md)

    def test_commands_line_aggregates_slash_commands(self):
        self.assertIn("Commands: /review x2", self.md)

    def test_tools_line_lists_tools_by_count_descending(self):
        self.assertIn("Tools: Read 5, Edit 2", self.md)

    def test_per_project_agents_summary_line_uses_friendly_names(self):
        self.assertIn("Agents: Stephen - Tech Nerd x2 (5m)", self.md)

    def test_config_override_reaches_the_report(self):
        md = report(standard_slices(), {"agent_names": {"code-reviewer": "Custom Carl"}})
        self.assertIn("| · Custom Carl | 2 | 5m | 2k | 200 |", md)

    def test_config_override_replaces_the_builtin_name_in_the_report(self):
        md = report(standard_slices(), {"agent_names": {"code-reviewer": "Custom Carl"}})
        self.assertNotIn("Stephen - Tech Nerd", md)

    def test_agent_stats_aggregate_across_sessions_of_one_project(self):
        tokens = {"in": 1000, "cache_create": 1000, "out": 200}
        sl = make_slice("Alpha", [
            make_session(agents={"code-reviewer": make_agent(2, 300, dict(tokens))}),
            make_session(start=DAY + timedelta(hours=2),
                         agents={"code-reviewer": make_agent(2, 300, dict(tokens))})])
        self.assertIn("| · Stephen - Tech Nerd | 4 | 10m | 4k | 400 |", report([sl]))

    def test_session_outside_the_window_contributes_no_agents(self):
        sl = make_slice("Late", [
            make_session(),                                             # in window, no agents
            make_session(start=SINCE - timedelta(days=2),
                         agents={"qa-runner": make_agent(5, 900)})])    # out of window
        self.assertNotIn("Testing Tim", report([sl]))

    def test_section_absent_when_no_session_has_agents_or_commands(self):
        self.assertNotIn("## Agents and commands", report([make_slice("Solo", [make_session()])]))

    def test_section_absent_and_report_builds_with_no_slices_at_all(self):
        self.assertNotIn("## Agents and commands", report([]))

    def test_commands_alone_still_render_the_section(self):
        md = report([make_slice("Solo", [make_session(commands={"/deploy": 1})])])
        self.assertIn("Commands: /deploy x1", md)

    def test_commands_alone_render_no_agent_table(self):
        md = report([make_slice("Solo", [make_session(commands={"/deploy": 1})])])
        self.assertNotIn("Project / agent", md)


class DashboardDataAgentNamesTests(unittest.TestCase):

    def test_dashboard_payload_embeds_builtin_agent_names(self):
        data = wa.dashboard_data([], [], dict(CFG), MISSING_POT)
        self.assertEqual(data["agent_names"]["security-reviewer"], "Dwayne - Security")

    def test_dashboard_payload_embeds_config_overrides(self):
        cfg = dict(CFG, agent_names={"code-reviewer": "Custom Carl"})
        data = wa.dashboard_data([], [], cfg, MISSING_POT)
        self.assertEqual(data["agent_names"]["code-reviewer"], "Custom Carl")


# ---------------------------------------------------------------------------- v1.15 helpers

def make_temp_dir(testcase, prefix="worklog-test-"):
    """A per-test temp dir, removed on cleanup; nothing outside it is touched."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def write_state(pot, content):
    """Write <pot>/.whats-new.json; dicts are serialised, strings written verbatim
    so tests can plant malformed JSON."""
    p = Path(pot) / ".whats-new.json"
    p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return p


def iso_ago(**kwargs):
    return (datetime.now(TZ) - timedelta(**kwargs)).isoformat()


class WhatsNewNoteTests(unittest.TestCase):
    """whatsnew_note(pot, days, text=None) against .whats-new.json fixtures in a temp pot."""

    def setUp(self):
        self.pot = make_temp_dir(self, "worklog-test-pot-")

    def test_missing_state_file_returns_the_default_whats_new(self):
        self.assertEqual(wa.whatsnew_note(self.pot, 7), wa.WHATS_NEW)

    def test_missing_state_file_returns_the_given_text(self):
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "custom")

    def test_malformed_json_state_returns_text(self):
        write_state(self.pot, "{not json")
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "custom")

    def test_non_dict_json_state_returns_text(self):
        write_state(self.pot, "[1, 2, 3]")
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "custom")

    def test_version_mismatch_returns_text_even_with_an_old_stamp(self):
        write_state(self.pot, {"version": "0.1", "first_render": iso_ago(days=30)})
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "custom")

    def test_matching_version_with_fresh_stamp_returns_text_within_days(self):
        write_state(self.pot, {"version": wa.VERSION, "first_render": datetime.now(TZ).isoformat()})
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "custom")

    def test_matching_version_with_stamp_older_than_days_returns_empty(self):
        write_state(self.pot, {"version": wa.VERSION, "first_render": iso_ago(days=8)})
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "")

    def test_matching_version_with_unparsable_stamp_returns_text(self):
        write_state(self.pot, {"version": wa.VERSION, "first_render": "not-a-date"})
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "custom")

    def test_matching_version_with_missing_stamp_returns_text(self):
        write_state(self.pot, {"version": wa.VERSION})
        self.assertEqual(wa.whatsnew_note(self.pot, 7, "custom"), "custom")

    def test_zero_days_window_is_already_closed_for_a_past_stamp(self):
        write_state(self.pot, {"version": wa.VERSION, "first_render": iso_ago(seconds=5)})
        self.assertEqual(wa.whatsnew_note(self.pot, 0, "custom"), "")


class WhatsNewConstantsTests(unittest.TestCase):

    def test_whats_new_is_a_nonempty_string(self):
        self.assertTrue(isinstance(wa.WHATS_NEW, str) and wa.WHATS_NEW.strip())

    def test_whats_new_short_is_a_nonempty_string(self):
        self.assertTrue(isinstance(wa.WHATS_NEW_SHORT, str) and wa.WHATS_NEW_SHORT.strip())

    def test_whats_new_short_is_a_single_line(self):
        self.assertNotIn("\n", wa.WHATS_NEW_SHORT)

    def test_whats_new_short_fits_the_header_strip(self):
        self.assertLessEqual(len(wa.WHATS_NEW_SHORT), 80)


class RenderRestampTests(unittest.TestCase):
    """render()'s restamp of <pot>/.whats-new.json, verified through the file it
    leaves behind. The pot holds one minimal valid slice so render() runs end to
    end; wa.LOG is pointed into the temp pot so nothing lands outside it."""

    def setUp(self):
        self.pot = make_temp_dir(self, "worklog-test-pot-")
        (self.pot / "slices").mkdir()
        (self.pot / "slices" / "alpha.json").write_text(
            json.dumps({"project": "Alpha", "repo": "alpha", "sessions": [], "commits": []}),
            encoding="utf-8")
        self.cfg = dict(CFG, pot=str(self.pot))
        self.state = self.pot / ".whats-new.json"
        original_log = wa.LOG
        wa.LOG = self.pot / "agent.log"
        self.addCleanup(setattr, wa, "LOG", original_log)

    def read_state(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def assert_fresh(self, stamp):
        t = wa.parse_iso(stamp)
        self.assertIsNotNone(t)
        self.assertLess(abs((datetime.now(TZ) - t).total_seconds()), 600)

    def test_missing_state_file_is_created_with_the_current_version(self):
        wa.render(self.cfg)
        self.assertEqual(self.read_state()["version"], wa.VERSION)

    def test_missing_state_file_gets_a_fresh_first_render(self):
        wa.render(self.cfg)
        self.assert_fresh(self.read_state()["first_render"])

    def test_older_recorded_version_is_restamped_to_current(self):
        write_state(self.pot, {"version": "1.0", "first_render": iso_ago(days=30)})
        wa.render(self.cfg)
        self.assertEqual(self.read_state()["version"], wa.VERSION)

    def test_older_recorded_version_gets_a_fresh_first_render(self):
        write_state(self.pot, {"version": "1.0", "first_render": iso_ago(days=30)})
        wa.render(self.cfg)
        self.assert_fresh(self.read_state()["first_render"])

    def test_newer_recorded_version_is_not_restamped(self):
        p = write_state(self.pot, {"version": "9.9", "first_render": iso_ago(days=30)})
        before = p.read_text(encoding="utf-8")
        wa.render(self.cfg)
        self.assertEqual(p.read_text(encoding="utf-8"), before)

    def test_newer_patch_version_is_not_restamped(self):
        p = write_state(self.pot, {"version": wa.VERSION + ".1", "first_render": iso_ago(days=30)})
        before = p.read_text(encoding="utf-8")
        wa.render(self.cfg)
        self.assertEqual(p.read_text(encoding="utf-8"), before)

    def test_equal_version_with_valid_date_is_untouched(self):
        p = write_state(self.pot, {"version": wa.VERSION, "first_render": iso_ago(days=2)})
        before = p.read_text(encoding="utf-8")
        wa.render(self.cfg)
        self.assertEqual(p.read_text(encoding="utf-8"), before)

    def test_equal_version_with_unparsable_date_is_restamped(self):
        write_state(self.pot, {"version": wa.VERSION, "first_render": "not-a-date"})
        wa.render(self.cfg)
        self.assert_fresh(self.read_state()["first_render"])

    def test_non_numeric_recorded_version_is_restamped(self):
        write_state(self.pot, {"version": "v1.x!", "first_render": iso_ago(days=30)})
        wa.render(self.cfg)
        self.assertEqual(self.read_state()["version"], wa.VERSION)


class DashboardDataVersionTests(unittest.TestCase):

    def test_payload_version_is_the_module_version(self):
        self.assertEqual(wa.dashboard_data([], [], dict(CFG), MISSING_POT)["version"], wa.VERSION)

    def test_payload_whats_new_echoes_the_argument(self):
        data = wa.dashboard_data([], [], dict(CFG), MISSING_POT, whats_new="fresh out")
        self.assertEqual(data["whats_new"], "fresh out")

    def test_payload_whats_new_defaults_to_empty_when_omitted(self):
        self.assertEqual(wa.dashboard_data([], [], dict(CFG), MISSING_POT)["whats_new"], "")


class VersionOfTests(unittest.TestCase):

    def setUp(self):
        self.dir = make_temp_dir(self)

    def agent_file(self, version_line):
        p = self.dir / "agent.py"
        p.write_text('#!/usr/bin/env python3\n"""doc"""\n%s\nX = 1\n' % version_line, encoding="utf-8")
        return p

    def test_valid_version_line_parses_to_an_int_tuple(self):
        self.assertEqual(wa.version_of(self.agent_file('VERSION = "1.15"')), (1, 15))

    def test_three_part_version_parses(self):
        self.assertEqual(wa.version_of(self.agent_file('VERSION = "1.15.1"')), (1, 15, 1))

    def test_unquoted_version_line_yields_the_zero_tuple(self):
        self.assertEqual(wa.version_of(self.agent_file('VERSION = 1.15')), (0,))

    def test_indented_version_line_yields_the_zero_tuple(self):
        self.assertEqual(wa.version_of(self.agent_file('    VERSION = "1.15"')), (0,))

    def test_dots_only_version_yields_the_zero_tuple(self):
        self.assertEqual(wa.version_of(self.agent_file('VERSION = "..."')), (0,))

    def test_missing_file_yields_the_zero_tuple(self):
        self.assertEqual(wa.version_of(self.dir / "no-such-file.py"), (0,))


class UpgradeGuardComparisonTests(unittest.TestCase):
    """The cmd_run self-upgrade guard adopts the machine copy only when
    version_of(machine copy) > tuple(int(x) for x in VERSION.split("."))."""

    def setUp(self):
        self.dir = make_temp_dir(self)

    def parsed(self, version):
        p = self.dir / ("v-%s.py" % version.replace(".", "_"))
        p.write_text('VERSION = "%s"\n' % version, encoding="utf-8")
        return wa.version_of(p)

    def running(self):
        return tuple(int(x) for x in wa.VERSION.split("."))

    def test_nine_nine_outranks_one_fifteen(self):
        self.assertGreater(self.parsed("9.9"), self.parsed("1.15"))

    def test_equal_versions_do_not_outrank_so_no_upgrade(self):
        self.assertFalse(self.parsed("1.15") > self.parsed("1.15"))

    def test_a_patch_release_outranks_its_base(self):
        self.assertGreater(self.parsed("1.15.1"), self.parsed("1.15"))

    def test_ordering_is_numeric_not_lexicographic(self):
        self.assertGreater(self.parsed("1.15"), self.parsed("1.4"))

    def test_version_of_agrees_with_the_guard_parse_of_the_running_version(self):
        self.assertEqual(self.parsed(wa.VERSION), self.running())

    def test_machine_copy_at_the_running_version_does_not_trigger(self):
        self.assertFalse(self.parsed(wa.VERSION) > self.running())

    def test_machine_copy_newer_than_the_running_version_triggers(self):
        self.assertGreater(self.parsed("9.9"), self.running())

class ActiveTimeIdentityTests(unittest.TestCase):
    """The reporting design rests on one identity, so it is pinned:

        active_min == sum(burst durations) + idle_minutes * (bursts - 1)

    A gap inside a burst is under the idle cap, so those pairs telescope to the burst duration;
    a gap between bursts is over it, so each contributes exactly the cap. Anything that computes
    "effort" by unioning bursts silently drops the second term - for a multi-burst session that
    is tens of percent, and it would put the dashboard below the report it must agree with."""

    def collect(self, stamps, idle=15):
        home = make_temp_dir(self)
        root = make_temp_dir(self)
        proj = home / ".claude" / "projects" / wa.encode_cwd(root)
        proj.mkdir(parents=True)
        lines = [json.dumps({"type": "user", "timestamp": ts.isoformat(), "cwd": str(root),
                             "sessionId": "s1", "uuid": "u%d" % i,
                             "message": {"role": "user", "content": "hi"}})
                 for i, ts in enumerate(stamps)]
        (proj / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        import os
        saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
        try:
            return wa.collect_sessions(root, stamps[0] - timedelta(days=1), idle)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_active_minutes_equal_bursts_plus_the_cap_per_gap(self):
        # 30 min working, 40 away, 20 working, 60 away, 10 working.
        # Events inside a burst are 10 min apart so no internal gap trips the 15 min cap.
        base = datetime(2026, 8, 11, 9, 0, 0, tzinfo=TZ)
        offs = [0, 10, 20, 30,   70, 80, 90,   150, 160]
        got = self.collect([base + timedelta(minutes=m) for m in offs], idle=15)
        self.assertTrue(got, "fixture produced no session - the HOME override or the encoded "
                             "directory name is wrong; a skip here would hide the identity going stale")
        s = got[0]
        burst_total = sum((wa.parse_iso(b) - wa.parse_iso(a)).total_seconds() / 60
                          for a, b in s["bursts"])
        self.assertEqual(len(s["bursts"]), 3, "gaps of 40 and 60 min both exceed the 15 min cap")
        self.assertEqual(burst_total, 60, "30 + 20 + 10 minutes of contiguous work")
        self.assertEqual(s["active_min"], burst_total + 15 * (len(s["bursts"]) - 1))
        self.assertEqual(s["active_min"], 90)
        self.assertGreater(s["active_min"], burst_total,
                           "unioning bursts under-reports this session by a third")


class TimeColumnsSayWhatTheyAreTests(unittest.TestCase):
    """Two different numbers on purpose: the Summary column is effort (parallel sessions add up),
    the Days column is elapsed (concurrent sessions merge). Each must keep saying which it is."""

    def concurrent(self):
        """Two projects worked simultaneously for the same 30 minutes."""
        return [make_slice("Alpha", [make_session()]), make_slice("Beta", [make_session()])]

    def test_summary_adds_parallel_sessions_and_labels_itself(self):
        md = report(self.concurrent())
        self.assertIn("parallel sessions add up", md)
        # The whole release in one line: two sessions working the same 30 minutes is an hour of
        # effort, and the same day is 30 minutes elapsed.
        self.assertIn("| **Total** | **0** | **2** | **1h** |", md)
        self.assertRegex(md, r"Tue 11 Aug \|[^|]*\|\s*30m\s*\|", "the day itself is 30m elapsed")

    def test_days_column_names_itself_elapsed(self):
        md = report(self.concurrent())
        self.assertNotIn("| Claude Code |", md,
                         "a bare 'Claude Code' header reads as effort; the column is elapsed")
        self.assertIn("Claude Code (elapsed)", md)

    def test_the_elapsed_explanation_is_not_conditional_on_activitywatch(self):
        """It used to print only when ActivityWatch or presence data existed, so a machine with
        neither shipped the column with no explanation at all."""
        md = report(self.concurrent())
        self.assertIn("add parallel sessions together", md)



if __name__ == "__main__":
    unittest.main()
