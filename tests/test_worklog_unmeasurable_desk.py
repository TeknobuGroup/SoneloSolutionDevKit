"""Failing-test-first reproduction: a desk figure the machine could not measure is not
printed as though it were measured.

The bug Phill reported: the W37 dashboard showed 1h 03m / 32m / 1h 53m / 12m / - / 9m at the
desk for Tue 8 - Sun 13 September, days he had worked through, remoting in. ActivityWatch
cannot see a remote session: `aw-watcher-afk` counts LOCAL input and so reports `afk` the
whole day, the window watcher freezes on the foreground window of a disconnected console
session, and the Win32 lock/unlock tasks stop firing. None of the three reports being blind.
They report a small number, confidently - and a confident wrong small number is worse than
nothing, because a blank already means zero and a reader cannot tell the two apart.

The independent witness is Claude Code's own session bursts, which are written locally by the
session process however the user is connected. A day is NOT MEASURABLE when Claude Code was
active for at least two hours and the desk figure is under a quarter of that. Calibrated over
28 days of this machine's pot: 9 days flagged (ratio 0.00-0.15), 18 kept (0.34-1.15).

The rule is applied at `load_slices()`, the one choke point every consumer comes through -
the report, the weekly CSVs, the dashboard payload, the morning page and the diary - so it is
written once rather than five times, one of them in JavaScript. ADR-0013 settled that shape.
It is applied at READ time, not collect time: `collect_machine()` freezes days before
yesterday, so a collect-time rule would never restate last week.

Every existing build_report test passes `machines=[]`, so the desk and editor readers have no
coverage at all today. These build a real pot on disk and go through `wa.load_slices()`,
because that is where the mark is applied and hand-built lists would not carry it.

The dashboard assertions go through `write_dashboard` and `build_morning` DIRECTLY, never
through `render()`, which wraps both in a bare `except Exception` that only logs - a break on
either path would otherwise leave the suite green and the pages stale.

Stdlib only; hermetic: every pot lives in a per-test temp dir. The JavaScript half is skipped,
not failed, where node is absent.
Run from the repo root with:  python -m unittest discover -s tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import diary_agent as da
import worklog_agent as wa
from test_worklog_dashboard_agrees import js_function

TZ = wa.local_tz()
NODE = shutil.which("node")
CFG = {"currency": "$", "prices": {}, "idle_minutes": 15, "window_days": 28}

TODAY = datetime.now(TZ).date()
# Yesterday, so build_morning picks it as the day it reports on.
CONTRADICTED = TODAY - timedelta(days=1)
MEASURED = TODAY - timedelta(days=2)
QUIET = TODAY - timedelta(days=3)
SINCE = TODAY - timedelta(days=7)


def at(day, hour, minute=0):
    return datetime.combine(day, dtime(hour, minute)).replace(tzinfo=TZ)


def session(a, b, sid):
    return {"id": sid, "start": a.isoformat(), "end": b.isoformat(),
            "active_min": int((b - a).total_seconds() / 60), "prompts": 1,
            "title": "work", "branch": "prelive",
            "bursts": [[a.isoformat(), b.isoformat()]]}


def aw_days():
    """Three days of ActivityWatch, one of them contradicted by six hours of Claude Code."""
    return {
        # 9m at the desk against 6h with a session active: ratio 0.025.
        CONTRADICTED.isoformat(): {"desk_s": 540, "editor_s": 480,
                                   "editor": {"Alpha - Visual Studio Code": 480}},
        # 7h against 8h: ratio 0.88, an ordinary day at the keyboard.
        MEASURED.isoformat(): {"desk_s": 7 * 3600, "editor_s": 3 * 3600,
                               "editor": {"Alpha - Visual Studio Code": 3 * 3600}},
        # 5m against 30m: the same low ratio, but far too little evidence to contradict
        # anything. The two-hour floor is what keeps a quiet day out.
        QUIET.isoformat(): {"desk_s": 300, "editor_s": 240,
                            "editor": {"Alpha - Visual Studio Code": 240}},
    }


def make_pot(testcase, days=None):
    pot = Path(tempfile.mkdtemp(prefix="worklog-unmeasured-pot-"))
    testcase.addCleanup(shutil.rmtree, str(pot), ignore_errors=True)
    (pot / "slices").mkdir(parents=True)
    sl = {"project": "Alpha", "repo": "alpha", "repo_id": "alpha-id",
          "since": at(SINCE, 0).isoformat(), "updated": at(TODAY, 0).isoformat(),
          "path": str(pot / "alpha"), "commits": [],
          "sessions": [session(at(CONTRADICTED, 9), at(CONTRADICTED, 15), "c1"),
                       session(at(MEASURED, 9), at(MEASURED, 17), "m1"),
                       session(at(QUIET, 10), at(QUIET, 10, 30), "q1")]}
    (pot / "slices" / "alpha__alpha.json").write_text(json.dumps(sl), encoding="utf-8")
    m = {"kind": "machine", "machine": "test-pc",
         "aw": {"ok": True, "days": aw_days() if days is None else days}}
    (pot / "slices" / "_machine__test-pc.json").write_text(json.dumps(m), encoding="utf-8")
    return pot


def report(pot):
    slices, machines = wa.load_slices(pot)
    return wa.build_report(slices, machines, at(SINCE, 0), wa.day_window(TODAY)[1], CFG)


def md_table(text, heading):
    """The rows of one Markdown table under `heading`, as [{column: cell}], in order."""
    lines = text.split("\n")
    i = lines.index(heading)
    head, out = None, []
    for ln in lines[i + 1:]:
        if not ln.startswith("|"):
            if head is not None and out:
                break
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if head is None:
            head = cells
        elif set("".join(cells)) <= set("-: "):
            continue
        else:
            out.append(dict(zip(head, cells)))
    if head is None:
        raise AssertionError("no table under %r" % heading)
    return out


def day_row(text, d):
    label = d.strftime("%a %d %b")
    for row in md_table(text, "## Days"):
        if row["Day"] == label:
            return row
    raise AssertionError("no Days row for %s" % label)


NOT_MEASURABLE = "not measurable"
# The narrow, repeated per-project columns of the Editor table, where the words do not fit.
NOT_MEASURABLE_SHORT = "n/m"


class TheReportSaysSoRatherThanPrintingASmallNumber(unittest.TestCase):
    """The words matter as much as the suppression: a blank cell already means zero."""

    def setUp(self):
        self.pot = make_pot(self)
        self.text, self.rows, _ = report(self.pot)

    def test_a_contradicted_desk_figure_is_not_printed_as_a_measurement(self):
        row = day_row(self.text, CONTRADICTED)
        self.assertNotEqual(row["At desk"], "9m",
                            "9m at the desk against 6h of Claude Code is not a measurement")
        self.assertEqual(row["At desk"], NOT_MEASURABLE)

    def test_a_blank_cell_is_not_how_it_is_said(self):
        """Sat 12 Sept and 17-19 Aug already render blank, and mean zero. Reusing the blank
        would tell a reader the machine measured no desk time, which is the same lie."""
        self.assertNotEqual(day_row(self.text, CONTRADICTED)["At desk"], "")

    def test_the_editor_figure_goes_with_it(self):
        """Editor time is measured by the same two watchers that failed, intersected."""
        self.assertEqual(day_row(self.text, CONTRADICTED)["Editor"], NOT_MEASURABLE)

    def test_a_measured_day_is_left_exactly_as_it_was(self):
        row = day_row(self.text, MEASURED)
        self.assertEqual(row["At desk"], "7h")
        self.assertEqual(row["Editor"], "3h")

    def test_a_quiet_day_is_left_exactly_as_it_was(self):
        """Below the two-hour floor there is not enough evidence to call anything wrong."""
        row = day_row(self.text, QUIET)
        self.assertEqual(row["At desk"], "5m")
        self.assertEqual(row["Editor"], "4m")

    def test_the_editor_table_carries_no_figure_for_a_contradicted_day(self):
        """Three of the five editor readers go through the per-title `editor` map, not
        `editor_s`, so suppressing only the scalar leaves this table still printing it.

        The cell carries the mark rather than a blank: a blank in this table already means
        under a minute FOR THIS PROJECT, so a blind day borrowing it would read as "this
        project was not open" - the same lie in a different sentence. The mark itself is
        pinned by TheEditorTableMarksTheCellAndNotOnlyTheFootnote; what this one pins is
        that the 8m in the per-title map never reaches the page."""
        rows = md_table(self.text, "## Editor time")
        self.assertEqual(rows[0]["Project"], "Alpha")
        self.assertEqual(rows[0][CONTRADICTED.strftime("%a %d")], NOT_MEASURABLE_SHORT)
        self.assertEqual(rows[0][MEASURED.strftime("%a %d")], "3h")

    def test_the_editor_table_says_what_its_mark_means(self):
        """The words are not in the cell, so they have to be under the table."""
        i = self.text.index("## Editor time")
        j = self.text.index("## Days")
        self.assertIn(NOT_MEASURABLE, self.text[i:j])

    def test_the_weekly_csv_does_not_record_a_suppressed_day_as_zero_editor_time(self):
        """read_weekly_csvs() reads this column back for the dashboard's Weeks chart."""
        by_day = {r[1]: r for r in self.rows}
        self.assertEqual(by_day[CONTRADICTED.isoformat()][5], "")
        self.assertEqual(by_day[MEASURED.isoformat()][5], 180)

    def test_the_single_day_header_says_it_too(self):
        slices, machines = wa.load_slices(self.pot)
        d0, d1 = wa.day_window(CONTRADICTED)
        text, _, _ = wa.build_report(slices, machines, d0, d1, CFG)
        head = [ln for ln in text.split("\n") if ln.startswith("**Day:**")][0]
        self.assertNotIn("9m at the desk", head)
        self.assertIn(NOT_MEASURABLE, head)


class TheUnionOfBurstsHasOneImplementation(unittest.TestCase):
    """`wall_clock` is a closure inside build_report, and the rule needs the same number
    outside it. Lifting it must not change what the report prints."""

    def test_day_active_union_returns_what_the_elapsed_column_prints(self):
        pot = make_pot(self)
        text, _, _ = report(pot)
        slices, _machines = wa.load_slices(pot)
        union = wa.day_active_union(slices)
        for d in (CONTRADICTED, MEASURED, QUIET):
            self.assertEqual(wa.fmt_dur(union.get(d, 0) / 60),
                             day_row(text, d)["Claude Code (elapsed)"],
                             "the lifted union disagrees with the report for %s" % d)

    def test_a_burstless_session_falls_back_the_same_way_the_report_does(self):
        """session_bursts() is the shared fallback; the union must not walk `bursts` itself."""
        pot = make_pot(self)
        p = Path(pot) / "slices" / "alpha__alpha.json"
        sl = json.loads(p.read_text(encoding="utf-8"))
        for s in sl["sessions"]:
            del s["bursts"]
        p.write_text(json.dumps(sl), encoding="utf-8")
        slices, _machines = wa.load_slices(pot)
        # 8h plus the one-second clamp build_report and the dashboard both apply, without which
        # a burst ending at 23:59:59 loses its last second. Pinned, not rounded away.
        self.assertEqual(int(wa.day_active_union(slices).get(MEASURED, 0)), 8 * 3600 + 1)


class TheRuleIsOnePythonFunctionAndOneJavaScriptOne(unittest.TestCase):
    """The dashboard recomputes desk and editor time client-side from the same records."""

    def setUp(self):
        self.pot = make_pot(self)
        self.slices, self.machines = wa.load_slices(self.pot)

    def test_the_flag_reaches_the_dashboard_payload(self):
        data = wa.dashboard_data(self.slices, self.machines, CFG, self.pot)
        days = data["machine"]["aw_days"]
        self.assertTrue(days[CONTRADICTED.isoformat()].get("unmeasured"))
        self.assertFalse(days[MEASURED.isoformat()].get("unmeasured"))
        self.assertFalse(days[QUIET.isoformat()].get("unmeasured"))

    def test_the_record_keeps_its_numbers(self):
        """Marked, never nulled or deleted: `rec["desk_s"]` is indexed in two places,
        `fmt_dur(None)` raises, `null / 60` is 0 in JavaScript, and deleting the day would
        turn the columns off for the measurable days as well."""
        data = wa.dashboard_data(self.slices, self.machines, CFG, self.pot)
        rec = data["machine"]["aw_days"][CONTRADICTED.isoformat()]
        self.assertEqual(rec["desk_s"], 540)
        self.assertEqual(rec["editor_s"], 480)

    def test_write_dashboard_carries_it_into_the_page(self):
        """Asserted here rather than through render(), whose bare except would hide a break."""
        wa.write_dashboard(self.slices, self.machines, CFG, self.pot)
        html = (Path(self.pot) / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('"unmeasured":true', html)

    @unittest.skipUnless(NODE, "node is not on PATH; the dashboard half cannot be run")
    def test_the_javascript_agrees_with_the_python(self):
        try:
            body = "\n".join(js_function(n) for n in ("isMeasured", "deskMinutes"))
        except ValueError:
            self.fail("the dashboard has no isMeasured/deskMinutes; the rule is still written "
                      "out in each of the places the page uses a desk figure")
        # `{}` is the case the file already warns about 100 lines below the pair - truthy in
        # JavaScript, falsy in Python - and a record missing desk_s is what clean_machine()
        # actually guarantees, which is a dict and nothing about the keys in it.
        cases = {"measured": {"desk_s": 7 * 3600}, "marked": {"desk_s": 540, "unmeasured": True},
                 "missing": None, "empty": {}, "no desk key": {"editor_s": 100}}
        harness = ("var DATA = {};\n%s\n"
                   "var cases = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));\n"
                   "var out = {};\n"
                   "Object.keys(cases).forEach(function (k) {\n"
                   "  out[k] = [isMeasured(cases[k]), deskMinutes(cases[k])];\n"
                   "});\n"
                   "process.stdout.write(JSON.stringify(out));\n") % body
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(tmp), ignore_errors=True)
        (tmp / "harness.js").write_text(harness, encoding="utf-8")
        (tmp / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        run = subprocess.run([NODE, str(tmp / "harness.js"), str(tmp / "cases.json")],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        got = json.loads(run.stdout)
        for name, rec in cases.items():
            with self.subTest(case=name):
                self.assertEqual(got[name], [wa.desk_measured(rec), wa.desk_minutes(rec)],
                                 "the dashboard and the report disagree about %r" % name)


class TheMorningPageAndTheDiaryReadItToo(unittest.TestCase):

    def setUp(self):
        self.pot = make_pot(self)
        self.slices, self.machines = wa.load_slices(self.pot)

    def test_the_morning_page_does_not_open_on_a_figure_the_machine_never_saw(self):
        """Asserted directly, not through render(): build_morning is inside the same bare
        except, so a break here ships a stale page with the suite green."""
        html = wa.build_morning(self.slices, self.machines, CFG, self.pot)
        self.assertNotIn("9m at the desk", html)
        self.assertIn(NOT_MEASURABLE, html)

    def test_the_diary_skips_a_day_it_cannot_measure(self):
        aw = da.aw_day(self.machines, CONTRADICTED)
        self.assertEqual(aw["desk_s"], 0)
        self.assertEqual(aw["editor_s"], 0)
        self.assertEqual(da.editor_minutes(aw, {"Alpha", "alpha"}), 0)

    def test_the_diary_keeps_a_day_it_can(self):
        aw = da.aw_day(self.machines, MEASURED)
        self.assertEqual(aw["desk_s"], 7 * 3600)
        self.assertEqual(da.editor_minutes(aw, {"Alpha", "alpha"}), 180)


class ADayTheWatchersNeverRecordedAtAllSaysSoToo(unittest.TestCase):
    """A missing record is the same lie told by omission.

    17, 18 and 19 August in the real pot carry 6-13 hours of Claude Code each and no
    ActivityWatch record at all - it was not installed yet - and Saturday 12 September, one of
    the remote days Phill reported, has none either. All four render an empty desk cell today,
    and an empty cell means the machine measured no desk time. It did not measure anything.

    So the rule reaches a day nothing recorded, on a machine that DOES record desk time: the
    record is created and marked rather than left absent. A machine that has never run
    ActivityWatch is a different statement - it has no `aw` days at all, `have_aw` is false and
    the report already says "ActivityWatch: no data" - and gains nothing here, which the last
    test in this class pins."""

    def setUp(self):
        # The machine records desk time - MEASURED is there - but has nothing for the day
        # Claude worked six hours through, and nothing for the quiet day either.
        self.pot = make_pot(self, days={MEASURED.isoformat(): {
            "desk_s": 7 * 3600, "editor_s": 3 * 3600,
            "editor": {"Alpha - Visual Studio Code": 3 * 3600}}})
        self.text, self.rows, _ = report(self.pot)

    def test_a_day_with_no_record_and_six_hours_of_claude_code_is_not_left_blank(self):
        row = day_row(self.text, CONTRADICTED)
        self.assertNotEqual(row["At desk"], "",
                            "a blank cell says the machine measured no desk time; it measured "
                            "nothing at all")
        self.assertEqual(row["At desk"], NOT_MEASURABLE)
        self.assertEqual(row["Editor"], NOT_MEASURABLE)

    def test_the_created_record_carries_the_flag_and_no_invented_numbers(self):
        _slices, machines = wa.load_slices(self.pot)
        rec = machines[0]["aw"]["days"][CONTRADICTED.isoformat()]
        self.assertTrue(rec.get("unmeasured"))
        self.assertEqual(rec["desk_s"], 0)
        self.assertEqual(rec["editor_s"], 0)
        self.assertEqual(rec["editor"], {})

    def test_a_measured_day_on_the_same_machine_is_still_untouched(self):
        self.assertEqual(day_row(self.text, MEASURED)["At desk"], "7h")

    def test_a_quiet_day_with_no_record_stays_blank(self):
        """The two-hour floor governs an absent record exactly as it governs a present one:
        half an hour of Claude Code contradicts nothing."""
        self.assertEqual(day_row(self.text, QUIET)["At desk"], "")

    def test_a_machine_that_has_never_run_activitywatch_gains_nothing(self):
        """`have_aw` off is a true statement about that machine, and the report already makes
        it - "ActivityWatch: no data". Filling the column with "not measurable" on every active
        day would be noise, not news."""
        pot = make_pot(self, days={})
        text, _rows, _ = report(pot)
        self.assertNotIn("At desk", md_table(text, "## Days")[0],
                         "a machine with no ActivityWatch at all was given a desk column")
        self.assertIn("ActivityWatch: no data", text)


class ThePotIsNotOneMachine(unittest.TestCase):
    """The witness has to be the machine being judged, not the pot.

    Repo slices are imported between machines - the kit's own guidance is to import the other
    machine's repo slices and never its machine slice - so this pot routinely holds sessions
    that ran somewhere else. This machine's pot has one: 20 slices from DESKTOP-R3M7664 and
    one from PhillLappie2. Judging DESKTOP's desk record against a union that includes the
    laptop's bursts suppresses real measured data on the strength of a file this machine did
    not write, which is the same fault as the bug, pointed the other way."""

    def setUp(self):
        self.pot = make_pot(self, days={CONTRADICTED.isoformat(): {
            "desk_s": 40 * 60, "editor_s": 30 * 60,
            "editor": {"Alpha - Visual Studio Code": 30 * 60}}})
        # The laptop worked six hours that day. Its slice is in this pot; its keyboard is not.
        other = {"project": "Beta", "repo": "beta", "repo_id": "beta-id", "machine": "other-pc",
                 "since": at(SINCE, 0).isoformat(), "updated": at(TODAY, 0).isoformat(),
                 "path": "/elsewhere/beta", "commits": [],
                 "sessions": [session(at(CONTRADICTED, 9), at(CONTRADICTED, 15), "o1")]}
        (Path(self.pot) / "slices" / "beta__beta.json").write_text(
            json.dumps(other), encoding="utf-8")
        # This machine did 40 minutes: under the two-hour floor on its own.
        q = Path(self.pot) / "slices" / "alpha__alpha.json"
        sl = json.loads(q.read_text(encoding="utf-8"))
        sl["machine"] = "test-pc"
        sl["sessions"] = [session(at(CONTRADICTED, 9), at(CONTRADICTED, 9, 40), "c1")]
        q.write_text(json.dumps(sl), encoding="utf-8")

    def test_another_machines_sessions_do_not_condemn_this_machines_desk_record(self):
        _slices, machines = wa.load_slices(self.pot)
        rec = machines[0]["aw"]["days"][CONTRADICTED.isoformat()]
        self.assertFalse(rec.get("unmeasured"),
                         "40m at this keyboard was marked unmeasurable because a DIFFERENT "
                         "machine ran six hours of Claude Code that day")
        self.assertEqual(day_row(report(self.pot)[0], CONTRADICTED)["At desk"], "40m")

    def test_another_machines_sessions_do_not_invent_a_record_either(self):
        """The creation half reads the same union and must be scoped the same way."""
        pot = make_pot(self, days={MEASURED.isoformat(): {"desk_s": 7 * 3600}})
        q = Path(pot) / "slices" / "alpha__alpha.json"
        sl = json.loads(q.read_text(encoding="utf-8"))
        sl["machine"] = "test-pc"
        sl["sessions"] = [session(at(MEASURED, 9), at(MEASURED, 17), "m1")]
        q.write_text(json.dumps(sl), encoding="utf-8")
        (Path(pot) / "slices" / "beta__beta.json").write_text(json.dumps(
            {"project": "Beta", "repo": "beta", "machine": "other-pc", "commits": [],
             "sessions": [session(at(CONTRADICTED, 9), at(CONTRADICTED, 15), "o1")]}),
            encoding="utf-8")
        _slices, machines = wa.load_slices(pot)
        self.assertNotIn(CONTRADICTED.isoformat(), machines[0]["aw"]["days"],
                         "a day only another machine worked was given a record here")

    def test_a_slice_that_names_no_machine_still_counts_everywhere(self):
        """Slices written before the machine name was recorded, and the kit's own copy: an
        unnamed slice is evidence about whatever machine is being judged, not about none."""
        pot = make_pot(self)
        q = Path(pot) / "slices" / "alpha__alpha.json"
        sl = json.loads(q.read_text(encoding="utf-8"))
        sl.pop("machine", None)
        q.write_text(json.dumps(sl), encoding="utf-8")
        _slices, machines = wa.load_slices(pot)
        self.assertTrue(machines[0]["aw"]["days"][CONTRADICTED.isoformat()].get("unmeasured"))


class NothingIsInventedOutsideTheWindow(unittest.TestCase):
    """The creation half is sized by timestamps out of a slice file, so it needs a bound.

    `clean_session` does not range-check a burst, and one pair spanning 2020-2035 fabricates
    5,480 day records - every one of which lands in dashboard_data's `machine.aw_days` and so
    in dashboard.html, built as a single string in memory by an unattended hook."""

    def add_session(self, pot, sid, a, b):
        q = Path(pot) / "slices" / "alpha__alpha.json"
        sl = json.loads(q.read_text(encoding="utf-8"))
        sl["sessions"].append({"id": sid, "start": a.isoformat(), "end": b.isoformat(),
                               "active_min": 60, "prompts": 1, "title": "work",
                               "branch": "prelive", "bursts": [[a.isoformat(), b.isoformat()]]})
        q.write_text(json.dumps(sl), encoding="utf-8")

    def test_a_burst_from_years_ago_does_not_fabricate_a_record_per_day(self):
        pot = make_pot(self)
        self.add_session(pot, "ancient", at(TODAY - timedelta(days=5 * 365), 9),
                         at(TODAY - timedelta(days=2 * 365), 17))
        _slices, machines = wa.load_slices(pot)
        days = machines[0]["aw"]["days"]
        self.assertLess(len(days), 40,
                        "%d aw day records were fabricated from one out-of-window burst"
                        % len(days))
        self.assertNotIn((TODAY - timedelta(days=3 * 365)).isoformat(), days)

    def test_a_day_in_the_future_is_never_created(self):
        pot = make_pot(self)
        ahead = TODAY + timedelta(days=3)
        self.add_session(pot, "ahead", at(ahead, 9), at(ahead, 17))
        _slices, machines = wa.load_slices(pot)
        self.assertNotIn(ahead.isoformat(), machines[0]["aw"]["days"])


class ADateKeyIsReadTheWayEveryReaderLooksItUp(unittest.TestCase):
    """Every reader fetches by `d.isoformat()`, so a record filed under "2026-9-8" is
    invisible to all of them - and, before this, silently cancelled the marking for that day
    by counting as a record that already existed."""

    @staticmethod
    def sloppy(d):
        return "%d-%d-%d" % (d.year, d.month, d.day)

    def test_a_non_canonical_key_does_not_hide_the_day(self):
        d = CONTRADICTED
        if self.sloppy(d) == d.isoformat():   # a two-digit month and day cannot show this
            self.skipTest("today's date is canonical either way")
        pot = make_pot(self, days={self.sloppy(d): {"desk_s": 540, "editor_s": 480, "editor": {}}})
        _slices, machines = wa.load_slices(pot)
        days = machines[0]["aw"]["days"]
        self.assertIn(d.isoformat(), days, "the record is filed where no reader looks")
        self.assertTrue(days[d.isoformat()].get("unmeasured"))
        self.assertEqual(day_row(report(pot)[0], d)["At desk"], NOT_MEASURABLE)

    def test_a_canonical_record_is_never_replaced_by_a_sloppy_one(self):
        d = MEASURED
        if self.sloppy(d) == d.isoformat():
            self.skipTest("today's date is canonical either way")
        pot = make_pot(self, days={
            d.isoformat(): {"desk_s": 7 * 3600, "editor_s": 0, "editor": {}},
            self.sloppy(d): {"desk_s": 1, "editor_s": 0, "editor": {}}})
        _slices, machines = wa.load_slices(pot)
        self.assertEqual(machines[0]["aw"]["days"][d.isoformat()]["desk_s"], 7 * 3600)


class TheEditorTableMarksTheCellAndNotOnlyTheFootnote(unittest.TestCase):
    """A blank cell in that table already means under a minute for that project."""

    def setUp(self):
        self.text, _rows, _ = report(make_pot(self))

    def test_an_unmeasurable_day_is_marked_in_the_cell(self):
        row = md_table(self.text, "## Editor time")[0]
        self.assertEqual(row[CONTRADICTED.strftime("%a %d")], NOT_MEASURABLE_SHORT)
        self.assertEqual(row[MEASURED.strftime("%a %d")], "3h")
        self.assertEqual(row[QUIET.strftime("%a %d")], "4m",
                         "a day below the two-hour floor is left exactly as it was")

    def test_a_day_this_project_was_barely_open_is_still_a_blank(self):
        """The two meanings have to stay apart, which is the whole reason for the mark.

        A blank cell here means under a minute of this project in the editor - the day was
        measured, this project was not in front of the user. If a blind day rendered the same
        blank there would be no way to tell that from a measured one."""
        days = aw_days()
        days[QUIET.isoformat()] = {"desk_s": 300, "editor_s": 30,
                                   "editor": {"Alpha - Visual Studio Code": 30}}
        text, _rows, _ = report(make_pot(self, days=days))
        row = md_table(text, "## Editor time")[0]
        self.assertEqual(row[QUIET.strftime("%a %d")], "")
        self.assertEqual(row[CONTRADICTED.strftime("%a %d")], NOT_MEASURABLE_SHORT)

    def test_the_footnote_still_says_what_the_mark_means(self):
        i, j = self.text.index("## Editor time"), self.text.index("## Days")
        self.assertIn(NOT_MEASURABLE_SHORT, self.text[i:j])
        self.assertIn(NOT_MEASURABLE, self.text[i:j])


class TheMorningPageSaysWhyAsWellAsWhat(unittest.TestCase):
    """It is the terse page opened first, and nothing else on it explains the phrase."""

    def test_the_reason_travels_with_the_fact(self):
        pot = make_pot(self)
        slices, machines = wa.load_slices(pot)
        html = wa.build_morning(slices, machines, CFG, pot)
        self.assertIn(NOT_MEASURABLE, html)
        self.assertIn("remote session", html)


class ARecordWithNothingInItIsNotHalfMarked(unittest.TestCase):
    """`clean_machine` guarantees a day record is a dict, and nothing about the keys in it.

    A record with no `desk_s` is what a hand-edited or truncated slice leaves behind, and
    `rec["desk_s"]` is indexed rather than fetched in two of the readers - inside
    `build_report`, which `render()` does NOT wrap in a try, so one such record used to stop
    every project's report with a KeyError. And an empty record must not be counted as
    unmeasurable: it would name a day in the Editor table's footnote for which no cell
    anywhere prints the mark."""

    def test_a_day_record_missing_desk_s_does_not_stop_the_whole_report(self):
        """It has to be a day BELOW the two-hour floor: with enough Claude Code behind it a
        missing desk_s reads as zero and the rule marks the day, which routes both readers
        down the guarded path. A quiet day is what actually reaches `rec["desk_s"]`."""
        days = aw_days()
        days[QUIET.isoformat()] = {"editor_s": 100}      # no desk_s at all
        text, _rows, _ = report(make_pot(self, days=days))
        self.assertEqual(day_row(text, QUIET)["At desk"], "0m")
        self.assertEqual(day_row(text, CONTRADICTED)["At desk"], NOT_MEASURABLE)

    def test_an_empty_record_is_not_named_as_unmeasurable(self):
        """`{}` is falsy in Python and truthy in JavaScript, and the two halves of the rule
        parted company on it. Python called the day unmeasurable and named it in the Editor
        table's footnote - while the Days row printed a blank for it, the per-project cells
        printed their figures, and the dashboard printed the desk figure too. A footnote
        explaining a mark that appears nowhere is worse than no footnote."""
        days = aw_days()
        days[QUIET.isoformat()] = {}
        text, _rows, _ = report(make_pot(self, days=days))
        i, j = text.index("## Editor time"), text.index("## Days")
        foot = text[i:j].split(NOT_MEASURABLE_SHORT + " = ")[-1]
        self.assertNotIn(QUIET.strftime("%a %d"), foot,
                         "the footnote names a day no cell marks")


class TheLiftIsTheSameArithmeticTheClosureDid(unittest.TestCase):
    """`build_report` drops a session whose `start` will not parse before it ever reaches
    `b["bursts"]`, so the closure this was lifted out of never counted one. The lift was
    documented as behaviour-preserving; a session with a broken `start` and a good burst list
    would otherwise start counting towards the elapsed column, which is a printed number."""

    def test_a_session_with_an_unparseable_start_is_dropped_by_both(self):
        pot = make_pot(self)
        q = Path(pot) / "slices" / "alpha__alpha.json"
        sl = json.loads(q.read_text(encoding="utf-8"))
        broken = session(at(MEASURED, 20), at(MEASURED, 22), "broken")
        broken["start"] = "not a timestamp"
        sl["sessions"].append(broken)
        q.write_text(json.dumps(sl), encoding="utf-8")
        slices, machines = wa.load_slices(pot)
        union = wa.day_active_union(slices)
        self.assertEqual(int(union.get(MEASURED, 0) / 3600), 8,
                         "the union counted a session build_report refuses to count")
        text, _rows, _ = wa.build_report(slices, machines, at(SINCE, 0),
                                         wa.day_window(TODAY)[1], CFG)
        self.assertEqual(day_row(text, MEASURED)["Claude Code (elapsed)"], "8h")


class TheReasonDoesNotClaimMoreThanTheEvidenceCarries(unittest.TestCase):
    """Near-zero desk time with Claude Code running has a third cause the first two do not
    cover: an unattended run with nobody at the machine. The watchers were not blind then -
    they measured an empty chair - so the sentence has to allow for it rather than telling
    the reader with the same confidence that they were remoting in."""

    def test_the_reason_names_the_unattended_case(self):
        self.assertIn("unattended", wa.UNMEASURED_WHY.lower())

    def test_every_page_that_says_it_carries_the_same_sentence(self):
        """The dashboard's copy is a fourth hand-written one, and nothing was watching it
        drift - it read "(a remote session, or ...)" while the report read "— a remote
        session, or ...". Pinned character for character so a reword has to do both."""
        pot = make_pot(self)
        slices, machines = wa.load_slices(pot)
        text, _rows, _ = wa.build_report(slices, machines, at(SINCE, 0),
                                         wa.day_window(TODAY)[1], CFG)
        self.assertIn(wa.UNMEASURED_WHY, text)
        self.assertIn(wa.UNMEASURED_WHY, wa.build_morning(slices, machines, CFG, pot))
        self.assertIn(wa.UNMEASURED_WHY, wa.DASHBOARD_HTML)


class NothingIsInventedWhereThereIsNoRecordAtAll(unittest.TestCase):
    """Treating `{}` as a measured zero has a shadow: everywhere a missing record was already
    being turned into `{}` on the way in, "no ActivityWatch at all" started reading as "zero
    at the desk". On the morning page that is a confident zero on the terse page opened first,
    every day, for every user who has never installed the watchers."""

    def test_a_machine_with_no_activitywatch_gets_no_desk_fact(self):
        pot = make_pot(self)
        q = Path(pot) / "slices" / "_machine__test-pc.json"
        m = json.loads(q.read_text(encoding="utf-8"))
        m["aw"] = {"ok": True, "days": {}}
        q.write_text(json.dumps(m), encoding="utf-8")
        slices, machines = wa.load_slices(pot)
        html = wa.build_morning(slices, machines, CFG, pot)
        self.assertNotIn("at the desk", html)


class AMeasuredZeroIsNotABlank(unittest.TestCase):
    """The Days table's Editor column kept its `truthy(editor_s)` test while the At desk
    column beside it - the same hunk - learned the difference. A measured day with the editor
    genuinely shut rendered the same blank as a day with no record at all, which is the
    ambiguity this release exists to end, one column over from where it was just ended."""

    def test_a_measured_day_with_no_editor_time_prints_a_zero(self):
        days = aw_days()
        days[MEASURED.isoformat()] = {"desk_s": 7 * 3600, "editor_s": 0, "editor": {}}
        text, _rows, _ = report(make_pot(self, days=days))
        self.assertEqual(day_row(text, MEASURED)["At desk"], "7h")
        self.assertEqual(day_row(text, MEASURED)["Editor"], "0m")

    def test_a_day_with_no_record_at_all_is_still_blank(self):
        days = aw_days()
        del days[QUIET.isoformat()]          # below the floor, so nothing creates one either
        text, _rows, _ = report(make_pot(self, days=days))
        self.assertEqual(day_row(text, QUIET)["At desk"], "")
        self.assertEqual(day_row(text, QUIET)["Editor"], "")


class TheCausesAreNamedInExactlyOnePlace(unittest.TestCase):
    """The sentence had been written by hand four times and the fourth had drifted. Pinning
    three of them left the fifth - the release banner, which the SessionStart hook prints once
    per repo and the morning page carries a line away from the sentence itself."""

    def test_the_release_banner_does_not_restate_them(self):
        self.assertNotIn("remote session", wa.WHATS_NEW)

    def test_the_dashboard_gets_the_sentence_as_a_javascript_literal(self):
        """It is interpolated into a single-quoted string inside the one script block. An
        apostrophe in a future reword - and the comment above it invites rewording - would
        close that string and blank every card and table on the page, with the suite green,
        because the tests search the text rather than parse it."""
        self.assertIn(json.dumps(wa.NOT_MEASURABLE + " — " + wa.UNMEASURED_WHY,
                                 ensure_ascii=False), wa.DASHBOARD_HTML)


class ADayFileWrittenUnderTheOldRuleIsRebuilt(unittest.TestCase):
    """diary_agent.VERSION went to 1.1 for this rule, and a stamp nothing reads back is not a
    mechanism. is_stale() compared the day-file's mtime against the notes and the slices only,
    so a day-file written last week keeps a desk_hours the machine was never in a position to
    take - on a quiet pot, forever."""

    def setUp(self):
        self.pot = make_pot(self)
        self.out = Path(self.pot) / "Diary"
        self.out.mkdir()
        self.cfg = {"out_dir": str(self.out), "pot": str(self.pot)}
        self.d = TODAY - timedelta(days=30)      # old enough that the today-branch cannot fire

    def write(self, version):
        day = {"date": self.d.isoformat(), "diary_version": version,
               "totals": {"hours": 1.0, "desk_hours": 9.1}, "projects": []}
        (self.out / ("%s.json" % self.d.isoformat())).write_text(json.dumps(day), encoding="utf-8")
        return day

    def test_a_file_stamped_with_an_older_version_is_stale(self):
        self.assertTrue(da.is_stale(self.cfg, self.d, self.write("1.0")))

    def test_a_file_stamped_with_this_version_is_not(self):
        self.assertFalse(da.is_stale(self.cfg, self.d, self.write(da.VERSION)))


class TheRuleDoesNotFireOnItsOwn(unittest.TestCase):
    """Over-suppression would be the same fault the other way round."""

    def test_a_machine_with_no_claude_activity_at_all_is_never_marked(self):
        pot = Path(tempfile.mkdtemp(prefix="worklog-unmeasured-bare-"))
        self.addCleanup(shutil.rmtree, str(pot), ignore_errors=True)
        (pot / "slices").mkdir(parents=True)
        (pot / "slices" / "alpha__alpha.json").write_text(json.dumps(
            {"project": "Alpha", "repo": "alpha", "sessions": [], "commits": []}), encoding="utf-8")
        (pot / "slices" / "_machine__test-pc.json").write_text(json.dumps(
            {"kind": "machine", "machine": "test-pc",
             "aw": {"ok": True, "days": {CONTRADICTED.isoformat(): {"desk_s": 540}}}}),
            encoding="utf-8")
        _slices, machines = wa.load_slices(pot)
        self.assertFalse(machines[0]["aw"]["days"][CONTRADICTED.isoformat()].get("unmeasured"))

    def test_a_slice_written_by_an_older_agent_still_loads(self):
        """Other machines' kit copies write no flag at all; every read must be a .get()."""
        pot = make_pot(self, days={MEASURED.isoformat(): {"desk_s": 7 * 3600}})
        text, _, _ = report(pot)
        self.assertEqual(day_row(text, MEASURED)["At desk"], "7h")


if __name__ == "__main__":
    unittest.main()
