"""Unit tests for the v1.19 change to worklog_agent.py: cost broken down by context band
and subagent share, plus a line on the machine's model default and compaction cap.

Coverage here:
  - collect_sessions(): context_max is the largest main-thread context (input + cache_create
    + cache_read) seen in the session, and a subagent's own context never inflates it.
  - collect_sessions(): sub_keys set membership - built from what a subagent transcript
    itself wrote, not from which file a request lives in - is what splits every request
    into "main thread" or "subagent" once, after every file for the session is merged.
  - collect_sessions(): tokens_by_day_by_band_by_model buckets main-thread requests by
    local day, then context_band(), then model; the 150k/800k boundaries are exclusive on
    the low side (149_999 is normal, 150_000 is elevated; 799_999 is elevated, 800_000 is
    very high).
  - collect_sessions(): subagent_tokens_by_day_by_model buckets subagent requests by local
    day and model, with no band split.
  - session_band_tokens_in_range() / session_subagent_tokens_in_range(): the range-filtered
    summaries cost_and_context() is built on, including the backwards-compat rule that a
    session collected before 1.19 - missing both maps entirely - returns {} rather than
    guessing at a per-band history that was never recorded.
  - cost_and_context(): per-band and subagent cost from cfg["prices"], total_cost as their
    sum, the priced flag when a contributing model has no price entry, the bands_available
    flag when nothing in range carries 1.19 data, and high_context_sessions (>=150k,
    ending inside the range, sorted by context_max descending).
  - machine_context_note(): None on a missing or unparseable settings.json or one that
    doesn't parse to a JSON object; the exact wording for model default, compaction cap,
    and the "1M context not disabled" note, including its two suppression rules (the
    CLAUDE_CODE_DISABLE_1M_CONTEXT flag, and both model and window absent).

Stdlib only; hermetic (temp dirs only, never ~/Worklog or ~/.claude; machine_context_note
is always called with an explicit settings_path so the real ~/.claude/settings.json is
never touched).
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
CFG_PRICED = {"currency": "$", "idle_minutes": 15, "window_days": 28,
              "prices": {"opus": {"in": 5, "cache_create": 6.25, "cache_read": 0.5, "out": 25}}}


def at(day, hour, minute=0):
    return datetime(2026, 8, day, hour, minute, tzinfo=TZ)


def temp_dir(case):
    d = Path(tempfile.mkdtemp())
    case.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
    return d


def tok(i=0, cc=0, cr=0, o=0):
    return {"in": i, "cache_create": cc, "cache_read": cr, "out": o}


def arec(ts, root, model, tk, uid, sid=None):
    """One assistant transcript line carrying usage - the only record type collect_sessions
    needs to populate rec["usage"] (and, under a subagents/ path, rec["sub_files"])."""
    rec = {"type": "assistant", "timestamp": ts.isoformat(), "cwd": str(root),
           "uuid": uid, "requestId": uid,
           "message": {"role": "assistant", "model": model, "content": [],
                       "usage": {"input_tokens": tk.get("in", 0),
                                 "cache_creation_input_tokens": tk.get("cache_create", 0),
                                 "cache_read_input_tokens": tk.get("cache_read", 0),
                                 "output_tokens": tk.get("out", 0)}}}
    if sid:
        rec["sessionId"] = sid
    return rec


def collect(case, main_events, sub_events=None, idle=15, main_sid="s1"):
    """Writes one session's transcript (main_events, as [(ts, model, tok), ...]) under a
    fake HOME, plus - if sub_events is given - a second transcript for the same events
    nested at <main_sid>/subagents/sub1.jsonl, the directory shape collect_sessions reads
    as "belongs to session main_sid, but is a subagent's own file" (see the forced_key
    derivation in collect_sessions). Returns the single collected session dict."""
    home, root = temp_dir(case), temp_dir(case)
    proj = home / ".claude" / "projects" / wa.encode_cwd(root)
    proj.mkdir(parents=True)
    main_lines = [json.dumps(arec(ts, root, model, tk, "u%d" % i, sid=main_sid))
                  for i, (ts, model, tk) in enumerate(main_events)]
    (proj / (main_sid + ".jsonl")).write_text("\n".join(main_lines) + "\n", encoding="utf-8")
    if sub_events:
        sub_dir = proj / main_sid / "subagents"
        sub_dir.mkdir(parents=True)
        sub_lines = [json.dumps(arec(ts, root, model, tk, "su%d" % i))
                     for i, (ts, model, tk) in enumerate(sub_events)]
        (sub_dir / "sub1.jsonl").write_text("\n".join(sub_lines) + "\n", encoding="utf-8")
    all_ts = [e[0] for e in main_events] + [e[0] for e in (sub_events or [])]
    since = min(all_ts) - timedelta(days=1)
    saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
    try:
        out = wa.collect_sessions(root, since, idle)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    case.assertEqual(len(out), 1, "fixture produced more or fewer sessions than the one written")
    return out[0]


# --------------------------------------------------------------------- context_max (item 1)

class ContextMaxTests(unittest.TestCase):

    def test_context_max_is_the_largest_of_several_main_thread_requests(self):
        s = collect(self, [(at(11, 9), "claude-opus-5", tok(i=1000)),
                            (at(11, 9, 1), "claude-opus-5", tok(i=50000)),
                            (at(11, 9, 2), "claude-opus-5", tok(i=20000))])
        self.assertEqual(s["context_max"], 50000)

    def test_context_max_sums_input_cache_create_and_cache_read_not_just_input(self):
        s = collect(self, [(at(11, 9), "claude-opus-5", tok(i=1000, cc=2000, cr=3000))])
        self.assertEqual(s["context_max"], 6000)

    def test_context_max_ignores_output_tokens(self):
        s = collect(self, [(at(11, 9), "claude-opus-5", tok(i=100, o=999999))])
        self.assertEqual(s["context_max"], 100)

    def test_context_max_ignores_subagent_requests_even_when_far_larger(self):
        """A subagent re-reading a huge context is a different question from how deep the
        main conversation itself got; context_max answers the second one only."""
        s = collect(self, main_events=[(at(11, 9), "claude-opus-5", tok(i=10000))],
                    sub_events=[(at(11, 9, 30), "claude-opus-5", tok(i=900000))])
        self.assertEqual(s["context_max"], 10000)


# ------------------------------------------------------ main vs subagent split (item 2)

class MainVsSubagentSplitTests(unittest.TestCase):
    """sub_keys - built from what a subagent transcript itself wrote - is what decides
    "main" vs "subagent" below, not which file happened to hold a request."""

    def setUp(self):
        self.s = collect(self,
                          main_events=[(at(11, 9), "claude-opus-5", tok(i=100, o=10)),
                                       (at(11, 9, 1), "claude-opus-5", tok(i=200, o=20))],
                          sub_events=[(at(11, 9, 30), "claude-opus-5", tok(i=5000, o=50))])

    def test_the_session_total_includes_both_main_and_subagent_tokens(self):
        self.assertEqual(self.s["tokens"]["in"], 100 + 200 + 5000)

    def test_the_band_map_holds_only_the_main_thread_requests(self):
        band = self.s["tokens_by_day_by_band_by_model"]["2026-08-11"]["normal"]["claude-opus-5"]
        self.assertEqual(band["in"], 100 + 200, "the 5000-token subagent request leaked into the band map")

    def test_the_subagent_map_holds_only_the_subagent_requests(self):
        sub = self.s["subagent_tokens_by_day_by_model"]["2026-08-11"]["claude-opus-5"]
        self.assertEqual(sub["in"], 5000, "a main-thread request leaked into the subagent map")

    def test_the_subagent_map_does_not_also_contain_the_main_thread_share(self):
        sub = self.s["subagent_tokens_by_day_by_model"]["2026-08-11"]["claude-opus-5"]
        self.assertNotEqual(sub["in"], 100 + 200 + 5000, "main-thread tokens were double counted into the subagent bucket")


# --------------------------------------------- tokens_by_day_by_band_by_model (item 3)

class MainThreadBandBucketingTests(unittest.TestCase):

    def test_requests_are_bucketed_by_context_band_with_the_150k_and_800k_boundaries_exclusive_below(self):
        s = collect(self, [(at(11, 9, 0), "claude-opus-5", tok(i=149999)),   # just under 150k -> normal
                            (at(11, 9, 1), "claude-opus-5", tok(i=150000)),   # exactly 150k -> elevated
                            (at(11, 9, 2), "claude-opus-5", tok(i=799999)),   # just under 800k -> elevated
                            (at(11, 9, 3), "claude-opus-5", tok(i=800000))])  # exactly 800k -> very high
        bands = s["tokens_by_day_by_band_by_model"]["2026-08-11"]
        self.assertEqual(bands["normal"]["claude-opus-5"]["in"], 149999)
        self.assertEqual(bands["elevated"]["claude-opus-5"]["in"], 150000 + 799999)
        self.assertEqual(bands["very high"]["claude-opus-5"]["in"], 800000)

    def test_two_models_in_the_same_band_on_the_same_day_get_separate_entries(self):
        s = collect(self, [(at(11, 9), "claude-opus-5", tok(i=1000)),
                            (at(11, 9, 1), "claude-haiku-5", tok(i=2000))])
        normal = s["tokens_by_day_by_band_by_model"]["2026-08-11"]["normal"]
        self.assertEqual((normal["claude-opus-5"]["in"], normal["claude-haiku-5"]["in"]), (1000, 2000))

    def test_the_same_band_and_model_on_different_days_are_kept_on_separate_days(self):
        s = collect(self, [(at(11, 9), "claude-opus-5", tok(i=1000)),
                            (at(12, 9), "claude-opus-5", tok(i=3000))])
        by_day = s["tokens_by_day_by_band_by_model"]
        self.assertEqual((by_day["2026-08-11"]["normal"]["claude-opus-5"]["in"],
                          by_day["2026-08-12"]["normal"]["claude-opus-5"]["in"]), (1000, 3000))


# ------------------------------------------------ subagent_tokens_by_day_by_model (item 4)

class SubagentBucketingTests(unittest.TestCase):

    def test_subagent_requests_are_summed_by_day_and_model(self):
        s = collect(self, main_events=[(at(11, 9), "claude-opus-5", tok(i=1))],
                    sub_events=[(at(11, 9, 1), "claude-opus-5", tok(i=1000)),
                                (at(11, 9, 2), "claude-opus-5", tok(i=2000)),
                                (at(12, 9), "claude-haiku-5", tok(i=500))])
        by_day = s["subagent_tokens_by_day_by_model"]
        self.assertEqual(by_day["2026-08-11"]["claude-opus-5"]["in"], 1000 + 2000)
        self.assertEqual(by_day["2026-08-12"]["claude-haiku-5"]["in"], 500)

    def test_a_day_carries_only_the_models_that_actually_ran_that_day(self):
        s = collect(self, main_events=[(at(11, 9), "claude-opus-5", tok(i=1))],
                    sub_events=[(at(11, 9, 1), "claude-opus-5", tok(i=1000)),
                                (at(12, 9), "claude-haiku-5", tok(i=500))])
        by_day = s["subagent_tokens_by_day_by_model"]
        self.assertNotIn("claude-haiku-5", by_day["2026-08-11"])
        self.assertNotIn("claude-opus-5", by_day["2026-08-12"])


# -------------------------------------- session_*_tokens_in_range summaries (item 5)

def band_session(**extra):
    s = {"start": at(11, 9).isoformat(), "end": at(13, 9).isoformat()}
    s.update(extra)
    return s


class SessionBandTokensInRangeTests(unittest.TestCase):

    def setUp(self):
        self.s = band_session(tokens_by_day_by_band_by_model={
            "2026-08-11": {"normal": {"m1": tok(i=100)}},
            "2026-08-12": {"elevated": {"m1": tok(i=200000)}},
            "2026-08-13": {"very high": {"m2": tok(i=900000)}},
        })

    def test_a_one_day_range_returns_only_that_days_band(self):
        since, until = at(11, 0), at(11, 23, 59)
        got = wa.session_band_tokens_in_range(self.s, since, until)
        self.assertEqual(got, {"normal": {"m1": tok(i=100)}})

    def test_a_range_spanning_two_days_keeps_their_bands_separate(self):
        since, until = at(11, 0), at(12, 23, 59)
        got = wa.session_band_tokens_in_range(self.s, since, until)
        self.assertEqual(set(got.keys()), {"normal", "elevated"})
        self.assertEqual(got["elevated"]["m1"]["in"], 200000)

    def test_a_day_outside_the_range_is_excluded(self):
        since, until = at(12, 0), at(12, 23, 59)
        got = wa.session_band_tokens_in_range(self.s, since, until)
        self.assertNotIn("normal", got, "11 August's band leaked into a range that starts on 12 August")
        self.assertNotIn("very high", got, "13 August's band leaked into a range that ends on 12 August")

    def test_a_session_collected_before_1_19_has_no_band_map_and_returns_empty(self):
        legacy = band_session()  # no tokens_by_day_by_band_by_model key at all
        since, until = at(11, 0), at(13, 23, 59)
        self.assertEqual(wa.session_band_tokens_in_range(legacy, since, until), {})


class SessionSubagentTokensInRangeTests(unittest.TestCase):

    def setUp(self):
        self.s = band_session(subagent_tokens_by_day_by_model={
            "2026-08-11": {"m1": tok(i=50)},
            "2026-08-13": {"m2": tok(i=70)},
        })

    def test_a_range_covering_one_day_returns_only_that_days_subagent_tokens(self):
        since, until = at(11, 0), at(11, 23, 59)
        self.assertEqual(wa.session_subagent_tokens_in_range(self.s, since, until), {"m1": tok(i=50)})

    def test_a_range_covering_neither_recorded_day_returns_empty(self):
        since, until = at(12, 0), at(12, 23, 59)
        self.assertEqual(wa.session_subagent_tokens_in_range(self.s, since, until), {})

    def test_a_session_collected_before_1_19_has_no_subagent_map_and_returns_empty(self):
        legacy = band_session()  # no subagent_tokens_by_day_by_model key at all
        since, until = at(11, 0), at(13, 23, 59)
        self.assertEqual(wa.session_subagent_tokens_in_range(legacy, since, until), {})


# --------------------------------------------------------- cost_and_context() (item 6)

def cc_session(band_map=None, sub_map=None, context_max=0, end=None, title=""):
    s = {"start": at(11, 9).isoformat(), "end": (end or at(11, 10)).isoformat(),
         "context_max": context_max, "title": title}
    if band_map is not None:
        s["tokens_by_day_by_band_by_model"] = band_map
    if sub_map is not None:
        s["subagent_tokens_by_day_by_model"] = sub_map
    return s


def cc_slice(project, sessions):
    return {"project": project, "sessions": sessions}


class CostAndContextAggregationTests(unittest.TestCase):

    def test_band_token_totals_are_summed_across_sessions(self):
        s1 = cc_session(band_map={"2026-08-11": {"normal": {"opus": tok(i=100)}}})
        s2 = cc_session(band_map={"2026-08-11": {"normal": {"opus": tok(i=300)}}})
        got = wa.cost_and_context([cc_slice("P", [s1, s2])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertEqual(got["bands"]["normal"]["tok"]["in"], 400)

    def test_per_band_cost_is_computed_from_the_configured_price(self):
        s = cc_session(band_map={"2026-08-11": {"elevated": {"opus": tok(i=1000000)}}})
        got = wa.cost_and_context([cc_slice("P", [s])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertAlmostEqual(got["bands"]["elevated"]["cost"], 5.0, places=6)  # 1e6 tok * $5/1e6

    def test_total_cost_is_the_sum_of_every_band_plus_the_subagent_cost(self):
        s = cc_session(band_map={"2026-08-11": {"elevated": {"opus": tok(i=1000000)}}},
                        sub_map={"2026-08-11": {"opus": tok(o=200000)}})
        got = wa.cost_and_context([cc_slice("P", [s])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertAlmostEqual(got["total_cost"], 5.0 + 5.0, places=6)  # elevated $5 + subagent $5 (200k out * $25/1e6)

    def test_priced_is_false_when_a_contributing_model_has_no_price_entry(self):
        s = cc_session(band_map={"2026-08-11": {"normal": {"no-such-model": tok(i=1000)}}})
        got = wa.cost_and_context([cc_slice("P", [s])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertFalse(got["priced"])

    def test_priced_stays_true_when_every_contributing_model_is_priced(self):
        s = cc_session(band_map={"2026-08-11": {"normal": {"opus": tok(i=1000)}}})
        got = wa.cost_and_context([cc_slice("P", [s])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertTrue(got["priced"])

    def test_bands_available_is_false_when_every_session_in_range_predates_1_19(self):
        legacy = cc_session()  # no band or subagent map at all
        got = wa.cost_and_context([cc_slice("P", [legacy])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertFalse(got["bands_available"])

    def test_bands_available_is_true_when_at_least_one_session_carries_1_19_data(self):
        legacy = cc_session()
        modern = cc_session(band_map={"2026-08-11": {"normal": {"opus": tok(i=1)}}})
        got = wa.cost_and_context([cc_slice("P", [legacy, modern])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertTrue(got["bands_available"])

    def test_high_context_sessions_includes_150k_and_excludes_below_it(self):
        low = cc_session(context_max=149999, end=at(11, 10), title="low")
        high = cc_session(context_max=150000, end=at(11, 10), title="just over")
        got = wa.cost_and_context([cc_slice("P", [low, high])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        titles = [t for _, t, _ in got["high_context_sessions"]]
        self.assertEqual(titles, ["just over"])

    def test_high_context_sessions_excludes_a_session_that_ended_outside_the_range(self):
        outside = cc_session(context_max=900000, end=at(9, 10), title="ended early")
        got = wa.cost_and_context([cc_slice("P", [outside])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertEqual(got["high_context_sessions"], [])

    def test_high_context_sessions_are_sorted_by_context_max_descending(self):
        a = cc_session(context_max=200000, end=at(11, 10), title="a")
        b = cc_session(context_max=900000, end=at(11, 10), title="b")
        c = cc_session(context_max=150000, end=at(11, 10), title="c")
        got = wa.cost_and_context([cc_slice("P", [a, b, c])], at(11, 0), at(11, 23, 59), CFG_PRICED)
        self.assertEqual([t for _, t, _ in got["high_context_sessions"]], ["b", "a", "c"])


# ------------------------------------------------------- machine_context_note (item 7)

class MachineContextNoteMissingOrBadSettingsTests(unittest.TestCase):

    def write(self, text):
        d = temp_dir(self)
        p = d / "settings.json"
        p.write_text(text, encoding="utf-8")
        return p

    def test_a_missing_settings_file_returns_none(self):
        missing = temp_dir(self) / "nonexistent-settings.json"
        self.assertIsNone(wa.machine_context_note(missing))

    def test_unparseable_json_returns_none(self):
        p = self.write("{ not valid json")
        self.assertIsNone(wa.machine_context_note(p))

    def test_a_json_value_that_is_not_an_object_returns_none(self):
        p = self.write("[]")
        self.assertIsNone(wa.machine_context_note(p))


class MachineContextNoteContentTests(unittest.TestCase):

    def note(self, settings):
        d = temp_dir(self)
        p = d / "settings.json"
        p.write_text(json.dumps(settings), encoding="utf-8")
        return wa.machine_context_note(p)

    def test_reports_model_compaction_cap_and_that_1m_context_is_not_disabled(self):
        got = self.note({"model": "claude-opus-5", "autoCompactWindow": 500000})
        self.assertEqual(got, "This machine: model default `claude-opus-5`; compaction cap 500000; "
                               "1M context not disabled.")

    def test_a_missing_model_is_reported_as_no_default_set(self):
        got = self.note({"autoCompactWindow": 500000})
        self.assertIn("no model default set", got)

    def test_a_missing_compaction_window_is_reported_as_no_cap_set(self):
        got = self.note({"model": "claude-opus-5"})
        self.assertIn("no compaction cap set", got)

    def test_a_zero_compaction_window_is_reported_as_not_set_same_as_missing(self):
        got = self.note({"model": "claude-opus-5", "autoCompactWindow": 0})
        self.assertIn("no compaction cap set", got)

    def test_the_disable_1m_context_flag_suppresses_the_not_disabled_note(self):
        got = self.note({"model": "claude-opus-5", "autoCompactWindow": 500000,
                          "env": {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}})
        self.assertNotIn("1M context not disabled", got)

    def test_the_disable_flag_as_a_json_number_is_also_honoured(self):
        """Settings written by hand or by another tool may store this as 1 rather than "1"."""
        got = self.note({"model": "claude-opus-5", "autoCompactWindow": 500000,
                          "env": {"CLAUDE_CODE_DISABLE_1M_CONTEXT": 1}})
        self.assertNotIn("1M context not disabled", got)

    def test_when_model_and_window_are_both_absent_the_1m_note_is_also_omitted(self):
        got = self.note({})
        self.assertEqual(got, "This machine: no model default set; no compaction cap set.")

    def test_a_non_dict_env_value_does_not_raise_and_is_treated_as_1m_not_disabled(self):
        got = self.note({"model": "claude-opus-5", "env": "oops"})
        self.assertIn("1M context not disabled", got)


if __name__ == "__main__":
    unittest.main()
