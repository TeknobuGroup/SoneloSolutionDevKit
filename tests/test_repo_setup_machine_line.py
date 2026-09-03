"""Tests for doctor's `Machine` line (kit v4.9).

Two reasons this file exists.

The first is a review finding: the line read `~/.claude/settings.json` and then called `.get` on
whatever came back. `json.loads` is perfectly happy to return a list or a string, and neither has
`.get`, so a settings file holding `[]` - or holding an `env` that is a string rather than an
object - crashed `doctor` with a raw traceback part-way through its report. doctor is the command
you run *because* your environment is suspect, so dying on a malformed settings file is the worst
possible moment to die; it also took the repo-standards lines after it down with it. The sibling
implementation in worklog_agent (`machine_context_note`) already guarded both cases. This is the
same class of bug as `McpOkChecksWhatItClaims` in test_repo_setup_security.py, where `check` and
`doctor` died on hostile input instead of reporting not-ok.

The second is the standing rule that doctor never prints a value. The Machine line is the first
thing in doctor that reads a file which routinely holds an `env` block, so it gets a test that
says so.

Run from the repo root with:  python -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import repo_setup as rs


def settings(case, value):
    """Write `value` as this case's settings.json and return its path. `value` is written raw
    when it is a string, so a case can hand over something that is not valid JSON at all."""
    d = Path(tempfile.mkdtemp(prefix="repo-setup-machine-"))
    p = d / "settings.json"
    p.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return p


class MachineLineReportsTheSettings(unittest.TestCase):
    def test_a_fully_configured_machine(self):
        p = settings(self, {"model": "opus", "autoCompactWindow": "200k",
                            "env": {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}})
        self.assertEqual(rs.machine_line(p),
                         "Machine    model default `opus`; compaction cap 200k; 1M context disabled")

    def test_a_machine_with_no_1m_disable_flag_is_named_as_such(self):
        """The whole point of the line: a machine back on a 1M model is the regression it exists
        to surface, so it has to say so rather than stay quiet."""
        p = settings(self, {"model": "haiku", "autoCompactWindow": 250000})
        self.assertEqual(rs.machine_line(p),
                         "Machine    model default `haiku`; compaction cap 250000; 1M context not disabled")

    def test_an_env_without_the_flag_still_reads_not_disabled(self):
        p = settings(self, {"model": "opus", "env": {"SOMETHING_ELSE": "1"}})
        self.assertIn("1M context not disabled", rs.machine_line(p))

    def test_the_flag_must_be_exactly_1(self):
        p = settings(self, {"model": "opus", "env": {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "true"}})
        self.assertIn("1M context not disabled", rs.machine_line(p))

    def test_an_unconfigured_machine_says_so_rather_than_inventing_a_default(self):
        p = settings(self, {})
        self.assertEqual(rs.machine_line(p),
                         "Machine    model no default set; compaction no cap set; 1M context —")

    def test_an_unconfigured_machine_does_not_claim_1m_is_not_disabled(self):
        """With nothing set at all there is nothing to warn about, so the third clause is a dash.
        Claiming `not disabled` there would report every fresh machine as a regression."""
        self.assertIn("1M context —", rs.machine_line(settings(self, {})))


class MachineLineSurvivesABadSettingsFile(unittest.TestCase):
    """Each of these crashed doctor with an AttributeError before the fix."""

    def test_a_missing_file_is_nothing_to_report(self):
        missing = Path(tempfile.mkdtemp(prefix="repo-setup-machine-")) / "settings.json"
        self.assertEqual(rs.machine_line(missing),
                         "Machine    model no default set; compaction no cap set; 1M context —")

    def test_a_file_that_is_not_json_is_nothing_to_report(self):
        self.assertIn("no default set", rs.machine_line(settings(self, "{invalid json")))

    def test_a_top_level_array_does_not_crash_doctor(self):
        self.assertEqual(rs.machine_line(settings(self, [])),
                         "Machine    model no default set; compaction no cap set; 1M context —")

    def test_a_top_level_string_does_not_crash_doctor(self):
        self.assertIn("no default set", rs.machine_line(settings(self, '"just a string"')))

    def test_a_top_level_number_does_not_crash_doctor(self):
        self.assertIn("no default set", rs.machine_line(settings(self, "42")))

    def test_an_env_that_is_a_string_does_not_crash_doctor(self):
        """`"env": "PATH=x"` is truthy, so `(... or {})` did not save it."""
        line = rs.machine_line(settings(self, {"model": "opus", "env": "PATH=x"}))
        self.assertIn("1M context not disabled", line)

    def test_an_env_that_is_a_list_does_not_crash_doctor(self):
        line = rs.machine_line(settings(self, {"model": "opus", "env": ["PATH=x"]}))
        self.assertIn("1M context not disabled", line)

    def test_an_empty_env_is_fine(self):
        self.assertIn("1M context not disabled", rs.machine_line(settings(self, {"model": "opus", "env": {}})))


class MachineLineNeverPrintsAValue(unittest.TestCase):
    def test_no_env_value_reaches_the_line(self):
        """doctor's contract is that it never prints a value, and settings.json is exactly where a
        machine keeps its environment. The line may say whether the 1M flag is set; it may not
        carry anything out of `env`."""
        p = settings(self, {"model": "opus", "autoCompactWindow": "200k",
                            "env": {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1",
                                    "UAT_HUB_KEY": "uat-not-a-real-key-abcdef123456",  # sonelo:allow - fabricated fixture; the assertion below is that it never reaches the line
                                    "AWS_SECRET_ACCESS_KEY": "secret-value-should-never-appear"}})  # sonelo:allow - fabricated fixture; the assertion below is that it never reaches the line
        line = rs.machine_line(p)
        self.assertNotIn("uat-not-a-real-key-abcdef123456", line)
        self.assertNotIn("secret-value-should-never-appear", line)
        self.assertNotIn("UAT_HUB_KEY", line)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", line)

    def test_not_even_a_prefix_of_a_key_reaches_the_line(self):
        p = settings(self, {"model": "opus", "env": {"UAT_HUB_KEY": "uat-abcdefghijklmnop"}})  # sonelo:allow - fabricated fixture; the assertion below is that it never reaches the line
        self.assertNotIn("uat-abcd", rs.machine_line(p))


class DoctorUsesTheHelper(unittest.TestCase):
    def test_doctor_prints_the_machine_line_through_machine_line(self):
        """Guards the extraction: if the block were ever inlined back into cmd_doctor, the tests
        above would keep passing while doctor itself went unguarded again."""
        source = Path(rs.__file__).with_suffix(".py").read_text(encoding="utf-8")
        self.assertIn("say(machine_line())", source)


if __name__ == "__main__":
    unittest.main()
