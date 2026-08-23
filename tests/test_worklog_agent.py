"""Unit tests for the v1.14 changes to worklog_agent.py.

Covers:
  - agent_name_map(cfg): built-in names merged with cfg["agent_names"] overrides,
    sanitisation, malformed-config tolerance, no mutation of the module constant.
  - build_report(): the per-project "Agents and commands" table (friendly names,
    bold project totals, wall-time ordering, unknown ids, agent-less sessions).
  - dashboard_data(): embeds the merged agent-name map in the payload.

Stdlib only; hermetic: nothing is read or written outside the repo (build_report
and agent_name_map touch no files; dashboard_data is given a pot path that does
not exist, which its glob tolerates).
Run from the repo root with:  python -m unittest discover -s tests
"""

import sys
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


if __name__ == "__main__":
    unittest.main()
