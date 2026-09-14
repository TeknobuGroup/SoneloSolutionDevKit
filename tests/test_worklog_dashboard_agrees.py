"""The dashboard and the report must return the same number for the same session.

docs/UAT_PLAN.md pins it: the agent-hours tile equals the projects-table column equals the
report's Summary column. Those are two implementations of one rule - session_day_minutes()
in Python and dayMinutes() in the dashboard's JavaScript - and nothing has ever checked that
they agree. They drifted once already (a burstless session counted its whole span in one and
not the other), so the split introduced in v1.18 is pinned across both from the start.

The JS is lifted straight out of DASHBOARD_HTML and run under node. Skipped, not failed,
where node is absent - CI has it, a developer machine may not.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worklog_agent as wa

TZ = wa.local_tz()
NODE = shutil.which("node")

HELPERS = ("pad", "startOfDay", "addDays", "dateKey", "dayMinutes", "isMeasured", "deskMinutes")


def js_function(name):
    """Lift one function out of the dashboard source by matching its braces."""
    src = wa.DASHBOARD_HTML
    i = src.index("function %s(" % name)
    depth, j = 0, src.index("{", i)
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError("unbalanced braces reading %s out of DASHBOARD_HTML" % name)


def at(day, hour, minute=0):
    return datetime(2026, 8, day, hour, minute, tzinfo=TZ)


def burst(a, b):
    return [a.isoformat(), b.isoformat()]


CASES = {
    "one burst in one day": {"active_min": 30, "bursts": [burst(at(11, 9), at(11, 9, 30))]},
    "across midnight": {"active_min": 60, "bursts": [burst(at(11, 23, 30), at(12, 0, 30))]},
    "five days, three worked": {"active_min": 180,
                                "bursts": [burst(at(27, 16), at(27, 17)),
                                           burst(at(29, 10), at(29, 11)),
                                           burst(at(31, 18), at(31, 18, 30))]},
    "many short bursts in a day": {"active_min": 100,
                                   "bursts": [burst(at(11, 9), at(11, 9, 20)),
                                              burst(at(11, 10), at(11, 10, 20)),
                                              burst(at(11, 12), at(11, 12, 30))]},
    "a gap that opens before midnight and closes after": {
        "active_min": 50, "bursts": [burst(at(11, 23, 50), at(11, 23, 55)), burst(at(12, 9), at(12, 9, 40))]},
    "an instant, then work the next day": {
        "active_min": 40, "bursts": [burst(at(11, 9), at(11, 9)), burst(at(12, 9), at(12, 9, 25))]},
    "rounding that cannot divide evenly": {"active_min": 7,
                                           "bursts": [burst(at(11, 9), at(11, 9, 1)),
                                                      burst(at(12, 9), at(12, 9, 1)),
                                                      burst(at(13, 9), at(13, 9, 1))]},
    # parse_iso normalises every timestamp to the offset in force NOW, while the dashboard
    # uses true local time, so a date in the other half of the year is the case where the two
    # could label a day differently. Away from midnight they agree, which is what this pins.
    # KNOWN LIMIT, pre-existing and not fixed here: for a burst within an hour of local
    # midnight on a date in a different DST period, the two can put it on different days.
    "a date in the other DST period": {"active_min": 60,
                                       "bursts": [["2026-12-15T09:00:00+00:00", "2026-12-15T10:00:00+00:00"]]},
}


@unittest.skipUnless(NODE, "node is not on PATH; the dashboard half of the rule cannot be run")
class DashboardAgreesWithReportTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        body = "\n".join(js_function(n) for n in HELPERS)
        harness = """
var DATA = { idle_minutes: 15 };
%s
var cases = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
var out = {};
Object.keys(cases).forEach(function (name) {
  var c = cases[name];
  var bursts = c.bursts.map(function (pr) { return [new Date(pr[0]), new Date(pr[1])]; });
  out[name] = dayMinutes({ bursts: bursts, active: c.active_min });
});
process.stdout.write(JSON.stringify(out));
""" % body
        cls.tmp = Path(tempfile.mkdtemp())
        js, data = cls.tmp / "harness.js", cls.tmp / "cases.json"
        js.write_text(harness, encoding="utf-8")
        data.write_text(json.dumps(CASES), encoding="utf-8")
        run = subprocess.run([NODE, str(js), str(data)], capture_output=True, text=True)
        if run.returncode != 0:
            raise AssertionError("the dashboard's dayMinutes would not run:\n" + run.stderr)
        cls.js_result = json.loads(run.stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def python_result(self, case):
        s = {"start": case["bursts"][0][0], "end": case["bursts"][-1][1],
             "active_min": case["active_min"], "bursts": case["bursts"]}
        return {d.isoformat(): m for d, m in wa.session_day_minutes(s, 15).items()}

    def test_every_case_splits_identically_in_both_implementations(self):
        for name, case in CASES.items():
            with self.subTest(case=name):
                self.assertEqual(self.js_result[name], self.python_result(case),
                                 "the dashboard and the report disagree about %r" % name)

    def test_both_implementations_conserve_the_session_total(self):
        """Neither is allowed to lose or invent effort: the days must sum to active_min."""
        for name, case in CASES.items():
            with self.subTest(case=name):
                self.assertEqual(sum(self.js_result[name].values()), case["active_min"])
                self.assertEqual(sum(self.python_result(case).values()), case["active_min"])



class NothingFromThePotReachesInnerHtmlUnescaped(unittest.TestCase):
    """The dashboard is built from the pot, and the pot is not trusted input.

    Slice files are written by agents on other machines, arrive through an import, and carry
    strings that came from git - a branch name may contain `<`, which git permits. The page is
    opened from disk every morning, so markup that gets into `innerHTML` runs as script with
    the whole dashboard in reach: every project name, repo path, session title and prompt
    across every client on this machine.

    `write_dashboard` escapes `<` to `\u003c` when it writes the JSON payload, which stops a
    `</script>` breakout of the literal - but the string still holds a real `<` at runtime, so
    it is `esc()` at the point of use that does the work here, and only that.

    This reads the source rather than running it: the escaping happens in the browser, and
    lifting a DOM in to prove it would be testing jsdom rather than this rule.
    """

    def test_a_branch_name_is_escaped_before_it_is_put_in_the_page(self):
        src = js_function("renderLog")
        self.assertIn("x.branches", src, "renderLog no longer shows branches; update this test")
        bare = [ln.strip() for ln in src.split("\n")
                if "x.branches.join" in ln and "esc(x.branches.join" not in ln]
        self.assertEqual(bare, [], "a branch name goes into innerHTML unescaped: %s" % bare)

    def test_every_list_of_pot_values_joined_into_html_goes_through_esc(self):
        """The same mistake one field over: `join` is how these lists reach the page."""
        bare = []
        for line in wa.DASHBOARD_HTML.split("\n"):
            if "innerHTML" not in line and "html +=" not in line:
                continue
            for m in re.finditer(r"(\w[\w.]*\.join\(', '\))", line):
                if not line[:m.start()].rstrip().endswith("esc("):
                    bare.append(m.group(1))
        self.assertEqual(bare, [], "joined into the page without esc(): %s" % bare)


if __name__ == "__main__":
    unittest.main()
