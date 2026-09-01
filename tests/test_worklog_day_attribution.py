"""Unit tests for the v1.18 change to worklog_agent.py: work lands on the day it happened.

Until 1.18 a session was selected for a date range by its START time and its whole
active_min was attributed to the start day. Claude Code keeps one session id until you
exit, so a session opened on 27 August and still answering on 1 September reported:

  - nothing at all in a range that begins after it started (the project row showed
    commits and editor time but "0 sessions" and no cost), and
  - all five days of effort piled onto 27 August in a range that did include it.

Coverage here:
  - session_day_minutes(): the per-day split, and the invariant that it still sums to
    active_min == sum(bursts) + idle * (bursts - 1), which the whole report rests on.
  - build_report(): selection by burst overlap, per-day effort, in-range-only totals,
    and that a legacy burstless session behaves exactly as it did before.
  - collect_sessions(): tokens bucketed by local day, so cost can be asked per day.
  - build_report(): per-day cost from that map, and the prorate-and-mark fallback for
    slices written before the field existed.
  - atomic_write(): the Windows sharing violation that froze a project's slice.

Stdlib only; hermetic (temp dirs only, never ~/Worklog or ~/.claude).
Run from the repo root with:  python -m unittest discover -s tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worklog_agent as wa

TZ = wa.local_tz()
CFG = {"currency": "$", "prices": {}, "idle_minutes": 15, "window_days": 28}
PRICED = dict(CFG, prices={"claude-opus-5": {"in": 5, "cache_create": 6.25, "cache_read": 0.5, "out": 25}})


def at(day, hour, minute=0):
    return datetime(2026, 8, day, hour, minute, tzinfo=TZ)


def temp_dir(case):
    d = Path(tempfile.mkdtemp())
    case.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
    return d


def burst(a, b):
    return [a.isoformat(), b.isoformat()]


def session(start, end, active_min, bursts=None, **extra):
    s = {"id": "s1", "start": start.isoformat(), "end": end.isoformat(),
         "active_min": active_min, "prompts": 1, "title": "spanning work", "branch": "prelive"}
    if bursts is not None:
        s["bursts"] = bursts
    s.update(extra)
    return s


def slice_of(project, sessions, commits=None):
    return {"project": project, "repo": project.lower(), "sessions": sessions, "commits": commits or []}


def report(slices, since, until, cfg=None):
    return wa.build_report(slices, [], since, until, cfg or CFG)


def five_day_session():
    """The shape that started this: opened 27 Aug, still answering days later, worked on three."""
    return session(at(27, 15, 44), at(31, 18, 30), active_min=60 + 60 + 30 + 15 * 2,
                   bursts=[burst(at(27, 16, 0), at(27, 17, 0)),
                           burst(at(29, 10, 0), at(29, 11, 0)),
                           burst(at(31, 18, 0), at(31, 18, 30))])


class SessionDayMinutesTests(unittest.TestCase):
    """The split itself. Effort is bursts plus one idle cap per gap, so the split has to
    place the idle term somewhere - it goes on the day the gap opens - or the per-day
    figures stop summing to the session total the Summary column prints."""

    def split(self, s, idle=15):
        return wa.session_day_minutes(s, idle)

    def test_a_single_burst_inside_one_day_lands_wholly_on_that_day(self):
        s = session(at(11, 9), at(11, 9, 30), 30, [burst(at(11, 9), at(11, 9, 30))])
        self.assertEqual(self.split(s), {at(11, 9).date(): 30})

    def test_a_burst_across_midnight_splits_on_the_clock(self):
        s = session(at(11, 23, 30), at(12, 0, 30), 60, [burst(at(11, 23, 30), at(12, 0, 30))])
        self.assertEqual(self.split(s), {at(11, 9).date(): 30, at(12, 9).date(): 30})

    def test_the_idle_cap_for_a_gap_lands_on_the_day_the_gap_opens(self):
        s = session(at(11, 9), at(12, 10), 30 + 15, [burst(at(11, 9), at(11, 9, 30)),
                                                     burst(at(12, 10), at(12, 10))])
        self.assertEqual(self.split(s), {at(11, 9).date(): 45, at(12, 9).date(): 0})

    def test_the_per_day_split_sums_to_active_min(self):
        """The identity the report rests on, now per day. If this drifts, the At-a-glance
        row stops adding up to the Summary column for the same project."""
        s = five_day_session()
        self.assertEqual(sum(self.split(s).values()), s["active_min"])

    def test_a_burstless_session_falls_back_to_its_start_plus_active_minutes(self):
        """Slices written before bursts existed, and every session in the older tests."""
        s = session(at(11, 9), at(11, 12), 30)
        self.assertEqual(self.split(s), {at(11, 9).date(): 30})

    def test_a_burstless_session_that_runs_past_midnight_still_splits(self):
        s = session(at(11, 23, 40), at(12, 1), 40)
        self.assertEqual(self.split(s), {at(11, 9).date(): 20, at(12, 9).date(): 20})


class SpanningSessionSelectionTests(unittest.TestCase):
    """A range selects sessions that were ACTIVE in it, not sessions that started in it."""

    def only(self, day):
        return wa.day_window(at(day, 12).date())

    def test_a_session_opened_before_the_range_is_reported_in_it(self):
        since, until = self.only(31)
        md, _, totals = report([slice_of("Perfect", [five_day_session()])], since, until)
        self.assertIn("Perfect", md, "the project vanished from a day it worked")
        self.assertEqual(totals[1], 1, "one session was active on 31 Aug")

    def test_that_session_reports_only_the_effort_spent_inside_the_range(self):
        since, until = self.only(31)
        _, _, totals = report([slice_of("Perfect", [five_day_session()])], since, until)
        self.assertEqual(totals[2], 30, "30 minutes of burst on 31 Aug, no gap opens that day")

    def test_the_whole_window_still_totals_the_whole_session(self):
        since, _ = wa.day_window(at(27, 12).date())
        _, until = wa.day_window(at(31, 12).date())
        _, _, totals = report([slice_of("Perfect", [five_day_session()])], since, until)
        self.assertEqual(totals[2], five_day_session()["active_min"])

    def test_effort_lands_on_each_day_worked_not_on_the_opening_day(self):
        since, _ = wa.day_window(at(27, 12).date())
        _, until = wa.day_window(at(31, 12).date())
        _, rows, _ = report([slice_of("Perfect", [five_day_session()])], since, until)
        by_day = {r[1]: r[4] for r in rows}
        self.assertEqual(by_day.get("2026-08-27"), 75, "60 worked, and one 15 min gap opens")
        self.assertEqual(by_day.get("2026-08-29"), 75)
        self.assertEqual(by_day.get("2026-08-31"), 30)

    def test_a_session_that_closed_before_the_range_is_excluded(self):
        since, until = self.only(31)
        s = session(at(11, 9), at(11, 10), 60, [burst(at(11, 9), at(11, 10))])
        _, _, totals = report([slice_of("Perfect", [s])], since, until)
        self.assertEqual(totals[1], 0)

    def test_a_session_that_opens_after_the_range_is_excluded(self):
        since, until = self.only(11)
        _, _, totals = report([slice_of("Perfect", [five_day_session()])], since, until)
        self.assertEqual(totals[1], 0)

    def test_a_burstless_session_is_still_reported_on_its_own_day(self):
        """Regression guard for every slice written before bursts existed."""
        since, until = self.only(11)
        s = session(at(11, 9), at(11, 9, 30), 30)
        md, _, totals = report([slice_of("Alpha", [s])], since, until)
        self.assertEqual((totals[1], totals[2]), (1, 30))
        self.assertIn("Alpha", md)


class PerDayTokenTests(unittest.TestCase):
    """Cost has to be answerable per day, or a five-day session's spend can only ever be
    smeared across the range it is asked about."""

    def collect(self, events, idle=15):
        home, root = temp_dir(self), temp_dir(self)
        proj = home / ".claude" / "projects" / wa.encode_cwd(root)
        proj.mkdir(parents=True)
        lines = []
        for i, (ts, tokens) in enumerate(events):
            if tokens:
                rec = {"type": "assistant", "timestamp": ts.isoformat(), "cwd": str(root),
                       "sessionId": "s1", "uuid": "u%d" % i, "requestId": "r%d" % i,
                       "message": {"role": "assistant", "model": "claude-opus-5", "content": [],
                                   "usage": {"input_tokens": tokens, "cache_creation_input_tokens": 0,
                                             "cache_read_input_tokens": 0, "output_tokens": 0}}}
            else:
                rec = {"type": "user", "timestamp": ts.isoformat(), "cwd": str(root),
                       "sessionId": "s1", "uuid": "u%d" % i, "message": {"role": "user", "content": "hi"}}
            lines.append(json.dumps(rec))
        (proj / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
        try:
            return wa.collect_sessions(root, events[0][0] - timedelta(days=1), idle)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_tokens_are_bucketed_by_the_local_day_they_were_spent(self):
        got = self.collect([(at(11, 9), 100), (at(12, 9), 300)])
        self.assertTrue(got, "fixture produced no session - the HOME override or the encoded "
                             "directory name is wrong")
        by_day = got[0]["tokens_by_day_by_model"]
        self.assertEqual(by_day["2026-08-11"]["claude-opus-5"]["in"], 100)
        self.assertEqual(by_day["2026-08-12"]["claude-opus-5"]["in"], 300)

    def test_the_per_day_buckets_sum_to_the_session_total(self):
        got = self.collect([(at(11, 9), 100), (at(12, 9), 300)])
        s = got[0]
        summed = sum(m["in"] for day in s["tokens_by_day_by_model"].values() for m in day.values())
        self.assertEqual(summed, s["tokens"]["in"])

    def test_a_one_day_range_costs_only_that_days_tokens(self):
        s = session(at(11, 9), at(12, 10, 30), 60,
                    [burst(at(11, 9), at(11, 9, 30)), burst(at(12, 10), at(12, 10, 30))],
                    tokens={"in": 400, "cache_create": 0, "cache_read": 0, "out": 0},
                    tokens_by_model={"claude-opus-5": {"in": 400, "cache_create": 0, "cache_read": 0, "out": 0}},
                    tokens_by_day_by_model={
                        "2026-08-11": {"claude-opus-5": {"in": 100, "cache_create": 0, "cache_read": 0, "out": 0}},
                        "2026-08-12": {"claude-opus-5": {"in": 300, "cache_create": 0, "cache_read": 0, "out": 0}}})
        since, until = wa.day_window(at(12, 12).date())
        _, _, _ = report([slice_of("Perfect", [s])], since, until, PRICED)
        totals = wa.build_report([slice_of("Perfect", [s])], [], since, until, PRICED)[0]
        usage = totals.split("## Claude Code usage")[1]
        self.assertIn("300", usage, "only 12 August's tokens belong to a 12 August range")
        self.assertNotIn("400", usage)

    def test_a_legacy_session_without_the_map_is_prorated_and_marked(self):
        """Slices written before 1.18 have no per-day tokens. Apportioning by active minutes
        is the only honest answer available, and it has to say so rather than look exact."""
        s = session(at(11, 9), at(12, 10, 30), 60,
                    [burst(at(11, 9), at(11, 9, 30)), burst(at(12, 10), at(12, 10, 30))],
                    tokens={"in": 400, "cache_create": 0, "cache_read": 0, "out": 0},
                    tokens_by_model={"claude-opus-5": {"in": 400, "cache_create": 0, "cache_read": 0, "out": 0}})
        since, until = wa.day_window(at(12, 12).date())
        md, _, _ = report([slice_of("Perfect", [s])], since, until, PRICED)
        self.assertIn("†", md, "the estimated row carries a mark, the way * marks an unpriced model")
        self.assertIn("estimated cost, not a measured one", md,
                      "and the mark explains itself under the table it qualifies")


class AtomicWriteRetryTests(unittest.TestCase):
    """os.replace raises WinError 32 when another repo's agent holds the target. That is not
    an error condition, it is two writers meeting; it froze one project's slice for hours."""

    def setUp(self):
        self.dir = temp_dir(self)
        self.target = self.dir / "slice.json"
        self.real_replace = os.replace
        self.addCleanup(setattr, os, "replace", self.real_replace)
        self.addCleanup(setattr, wa, "ATOMIC_RETRY_S", wa.ATOMIC_RETRY_S)
        wa.ATOMIC_RETRY_S = 0.2          # the real 5s is for a live pot, not for a test suite
        self.addCleanup(setattr, wa, "LOG", wa.LOG)
        wa.LOG = self.dir / "agent.log"  # hermetic: never append to the installed copy's log

    def failing_replace(self, times):
        state = {"n": 0}
        real = self.real_replace

        def fake(src, dst):
            state["n"] += 1
            if state["n"] <= times:
                raise PermissionError(32, "The process cannot access the file")
            return real(src, dst)
        return fake, state

    def test_a_sharing_violation_is_retried_until_it_succeeds(self):
        fake, state = self.failing_replace(2)
        os.replace = fake
        wa.atomic_write(self.target, "written")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "written")
        self.assertEqual(state["n"], 3, "two refusals then the write")

    def test_it_gives_up_and_raises_rather_than_retrying_for_ever(self):
        fake, _ = self.failing_replace(10 ** 6)
        os.replace = fake
        with self.assertRaises(PermissionError):
            wa.atomic_write(self.target, "written")

    def test_giving_up_leaves_no_temporary_file_behind(self):
        fake, _ = self.failing_replace(10 ** 6)
        os.replace = fake
        with self.assertRaises(PermissionError):
            wa.atomic_write(self.target, "written")
        self.assertEqual([p.name for p in self.dir.glob(".tmp-*")], [])


class TempFileIsInvisibleToThePotTests(unittest.TestCase):
    """The other half of the atomic_write fix, which a green suite would otherwise hide.

    `Path.glob("*.json")` matches a leading dot, so a temp file named `.tmp-x.json` was visible
    as a slice to load_slices, to cmd_status, and to collect_and_write's superseded-slice sweep -
    which unlinks by that same glob and could delete a half-written slice under its writer.
    Asserting only that the write succeeds leaves `suffix=".tmp"` free to be reverted."""

    def test_an_in_flight_write_is_not_matched_by_the_pot_json_glob(self):
        d = temp_dir(self)
        (d / "existing.json").write_text("{}", encoding="utf-8")
        real, seen = os.replace, {}
        self.addCleanup(setattr, os, "replace", real)

        def spy(src, dst):
            seen["mid_flight"] = sorted(p.name for p in d.glob("*.json"))
            return real(src, dst)

        os.replace = spy
        wa.atomic_write(d / "slice.json", "{}")
        self.assertEqual(seen["mid_flight"], ["existing.json"],
                         "a half-written slice was visible to the pot's own *.json glob")


class DashboardReloadConfigTests(unittest.TestCase):
    """UAT-1.18-14 documents `dashboard_reload_s: 0` as the off switch, so it is pinned."""

    def payload(self, **over):
        cfg = dict(CFG)
        cfg.update(over)
        return wa.dashboard_data([], [], cfg, temp_dir(self))

    def test_the_default_is_the_shipped_constant(self):
        self.assertEqual(self.payload()["reload_s"], wa.DASHBOARD_RELOAD_S)

    def test_zero_turns_the_reload_off(self):
        self.assertEqual(self.payload(dashboard_reload_s=0)["reload_s"], 0)

    def test_a_negative_interval_is_floored_rather_than_reversing_time(self):
        self.assertEqual(self.payload(dashboard_reload_s=-5)["reload_s"], 0)

    def test_an_absurd_interval_is_capped_so_setTimeout_cannot_overflow(self):
        """setTimeout takes a 32-bit delay: over ~24.8 days it fires immediately, for ever."""
        self.assertEqual(self.payload(dashboard_reload_s=10 ** 9)["reload_s"], 86400)


class NoUsageDoesNotMarkTheRangeTests(unittest.TestCase):
    """Both markers - `*` for an unpriced model, `†` for an apportioned cost - exist to be
    believed. A session that spent nothing must trip neither."""

    def test_a_session_with_no_tokens_leaves_the_cost_unmarked(self):
        priced = session(at(11, 9), at(11, 9, 30), 30, [burst(at(11, 9), at(11, 9, 30))],
                         tokens={"in": 1000, "cache_create": 0, "cache_read": 0, "out": 0},
                         tokens_by_day_by_model={"2026-08-11": {"claude-opus-5": {"in": 1000, "cache_create": 0, "cache_read": 0, "out": 0}}},
                         tokens_by_model={"claude-opus-5": {"in": 1000, "cache_create": 0, "cache_read": 0, "out": 0}})
        empty = session(at(11, 10), at(12, 10, 30), 30, [burst(at(11, 10), at(11, 10, 15)), burst(at(12, 10), at(12, 10, 15))])
        since, until = wa.day_window(at(11, 12).date())
        md, _, _ = report([slice_of("Perfect", [priced, empty])], since, until, PRICED)
        usage = md.split("## Claude Code usage")[1]
        row = [l for l in usage.splitlines() if l.startswith("| Perfect ")][0]
        self.assertEqual(row.split("|")[6].strip(), "$0.01",
                         "an empty session marked the cost partial (*) or estimated (†); it is neither")
        self.assertNotIn("no entry in `prices`", md, "no model was missing a price")
        self.assertNotIn("estimated cost, not a measured one", md, "nothing was apportioned")

    def test_a_share_that_rounds_entirely_away_is_not_called_apportioned(self):
        """The other half of the guard, which the no-tokens early return would otherwise mask:
        a legacy session that DID spend tokens, but whose share of this range rounds to nothing.
        Nothing was apportioned into this range, so nothing may be marked as though it was."""
        s = session(at(11, 9), at(12, 10, 30), 60,
                    [burst(at(11, 9), at(11, 9, 30)), burst(at(12, 10), at(12, 10, 30))],
                    tokens={"in": 1, "cache_create": 0, "cache_read": 0, "out": 0},
                    tokens_by_model={"claude-opus-5": {"in": 1, "cache_create": 0, "cache_read": 0, "out": 0}})
        per_day = wa.session_day_minutes(s, 15)
        in_range = {d: m for d, m in per_day.items() if d == at(12, 9).date()}
        since, until = wa.day_window(at(12, 12).date())
        share, apportioned = wa.session_tokens_in_range(s, per_day, in_range, since, until)
        self.assertEqual(share, {}, "one token halved rounds to none, so the model contributes nothing")
        self.assertFalse(apportioned, "and an empty share must not mark the row estimated")

    def test_the_share_for_a_session_with_no_tokens_is_empty_and_exact(self):
        empty = session(at(11, 10), at(12, 10, 30), 30, [burst(at(11, 10), at(11, 10, 15)), burst(at(12, 10), at(12, 10, 15))])
        per_day = wa.session_day_minutes(empty, 15)
        in_range = {d: m for d, m in per_day.items() if d == at(11, 9).date()}
        since, until = wa.day_window(at(11, 12).date())
        self.assertEqual(wa.session_tokens_in_range(empty, per_day, in_range, since, until), ({}, False))


if __name__ == "__main__":
    unittest.main()
