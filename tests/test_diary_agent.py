"""Unit tests for diary_agent.py (v1.0).

Coverage:
  - date parsing, per-repo tier config, and what a project may be CALLED at each tier
    (never the repo name, at any tier).
  - `note`: append, timestamp, image copy into the day's assets, refusal of an empty note.
  - `collect`: the tier filter (own keeps commits and the timeline, nickname keeps
    feature-level summaries only, private keeps hours only), and totals counted from the
    real day rather than from what survived the filter.
  - the leak check: blocklist terms, repo and person names at EVERY tier, shape rules
    (URL, file path, commit message, branch) at non-own tiers only, the failure that names
    the term and where it came from, and --force redacting instead of failing.
  - transcript digests: prompts and prose in, tool RESULTS out.
  - summary caching by session id and day, and re-summarising when the tier changes.
  - the MCP server: initialize, tools/list, tools/call, notifications, unknown methods,
    and stdout carrying protocol and nothing else.
  - doctor: never prints a blocklist term.

Stdlib only; hermetic: every test runs against its own temp HOME-equivalents. The module
constants that point at ~/.claude and ~/Worklog are redirected for the duration of each
test, so nothing here reads or writes the developer's real diary, worklog or settings.
Run from the repo root with:  python -m unittest discover -s tests
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import diary_agent as da


class FakeWorklog(object):
    """Stands in for worklog_agent.py: the diary only ever asks it two things."""

    DEFAULT_POT = "/nonexistent-pot"

    def __init__(self, slices=None, machines=None):
        self.slices = list(slices or [])
        self.machines = list(machines or [])

    def load_slices(self, pot):
        return self.slices, self.machines

    def session_day_minutes(self, s, idle):
        out = {}
        for iso, mins in (s.get("minutes_by_day") or {}).items():
            out[datetime.strptime(iso, "%Y-%m-%d").date()] = mins
        return out


def a_session(sid, start, minutes, day, title=""):
    return {"id": sid, "start": start, "title": title, "minutes_by_day": {day: minutes}}


def a_slice(path, project, repo, sessions=(), commits=()):
    return {"path": str(path), "project": project, "repo": repo,
            "sessions": list(sessions), "commits": list(commits)}


class DiaryTest(unittest.TestCase):
    """Redirects every path the module resolves from the home directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="diary-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self._saved = {k: getattr(da, k) for k in
                       ("CENTRAL_CFG", "WORKLOG_CFG", "USER_SETTINGS", "KIT_HOME", "QUIET")}
        da.CENTRAL_CFG = self.tmp / "claude" / "diary.json"
        da.WORKLOG_CFG = self.tmp / "claude" / "worklog.json"
        da.USER_SETTINGS = self.tmp / "claude" / "settings.json"
        da.KIT_HOME = self.tmp / "claude" / "sonelo"
        da.QUIET = True
        self.addCleanup(self._restore)
        self.pot = self.tmp / "Worklog"
        (self.pot / "slices").mkdir(parents=True)
        self.cfg = json.loads(json.dumps(da.DEFAULTS))
        self.cfg["out_dir"] = str(self.tmp / "Diary")
        self.cfg["transcripts"] = str(self.tmp / "projects")
        self.cfg["pot"] = str(self.pot)
        self.cfg["authors"] = ["Test Dev"]
        self.day = datetime.now(da.local_tz()).date()
        self.iso = self.day.isoformat()

    def _restore(self):
        for k, v in self._saved.items():
            setattr(da, k, v)

    def repo(self, name, diary_block=None):
        """A directory with a .teknobu.json in it. Not a git repo: the off-disk path is what
        keeps these tests free of a git dependency, and it exercises the same tier filter."""
        root = self.tmp / "repos" / name
        root.mkdir(parents=True, exist_ok=True)
        cfg = {"kit": "4.11"}
        if diary_block is not None:
            cfg["diary"] = diary_block
        (root / ".teknobu.json").write_text(json.dumps(cfg), encoding="utf-8")
        return root

    def build(self, slices, machines=None, summarise=False):
        return da.build_day(self.cfg, self.day, FakeWorklog(slices, machines), summarise=summarise)


class TestDates(DiaryTest):

    def test_words_offsets_and_iso(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=da.local_tz())
        self.assertEqual(da.parse_date("today", now).isoformat(), "2026-09-06")
        self.assertEqual(da.parse_date("", now).isoformat(), "2026-09-06")
        self.assertEqual(da.parse_date(None, now).isoformat(), "2026-09-06")
        self.assertEqual(da.parse_date("yesterday", now).isoformat(), "2026-09-05")
        self.assertEqual(da.parse_date("Yesterday", now).isoformat(), "2026-09-05")
        self.assertEqual(da.parse_date("-3", now).isoformat(), "2026-09-03")
        self.assertEqual(da.parse_date("2026-01-31", now).isoformat(), "2026-01-31")

    def test_nonsense_says_what_it_wanted(self):
        with self.assertRaises(ValueError) as e:
            da.parse_date("last tuesday")
        self.assertIn("YYYY-MM-DD", str(e.exception))


class TestTierConfig(DiaryTest):

    def test_absent_block_is_private_not_own(self):
        cfg = da.repo_diary_cfg(self.repo("no-block"))
        self.assertEqual(cfg["tier"], "private")
        self.assertFalse(cfg["declared"])

    def test_missing_file_is_private(self):
        cfg = da.repo_diary_cfg(self.tmp / "nowhere")
        self.assertEqual(cfg["tier"], "private")
        self.assertFalse(cfg["declared"])

    def test_malformed_block_is_private(self):
        root = self.repo("junk")
        (root / ".teknobu.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(da.repo_diary_cfg(root)["tier"], "private")
        root2 = self.repo("listy", diary_block=None)
        (root2 / ".teknobu.json").write_text(json.dumps({"diary": ["own"]}), encoding="utf-8")
        self.assertEqual(da.repo_diary_cfg(root2)["tier"], "private")

    def test_unknown_tier_falls_back(self):
        root = self.repo("weird", {"tier": "public"})
        cfg = da.repo_diary_cfg(root)
        self.assertEqual(cfg["tier"], "private")
        self.assertFalse(cfg["declared"])

    def test_declared_tiers_are_read(self):
        cfg = da.repo_diary_cfg(self.repo("mine", {"tier": "own", "description": "a client CRM rebuild"}))
        self.assertEqual((cfg["tier"], cfg["description"], cfg["declared"]),
                         ("own", "a client CRM rebuild", True))


class TestLabels(DiaryTest):

    def test_private_is_client_work(self):
        self.assertEqual(da.label_for({"tier": "private", "nickname": "", "description": "x"}),
                         da.PRIVATE_LABEL)

    def test_nickname_requires_one(self):
        self.assertEqual(da.label_for({"tier": "nickname", "nickname": "Kestrel", "description": ""}),
                         "Kestrel")
        with self.assertRaises(da.TierError):
            da.label_for({"tier": "nickname", "nickname": "", "description": "a CRM"})

    def test_own_uses_description_never_the_repo_name(self):
        self.assertEqual(da.label_for({"tier": "own", "nickname": "", "description": "a field service app"}),
                         "a field service app")
        self.assertEqual(da.label_for({"tier": "own", "nickname": "", "description": ""}), "a project")


class TestNotes(DiaryTest):

    def test_append_and_read_back(self):
        now = datetime(2026, 9, 6, 13, 45, tzinfo=da.local_tz())
        da.add_note(self.cfg, "  he was right   about the subject line ", now=now)
        da.add_note(self.cfg, "second", now=now.replace(hour=17))
        notes = da.read_notes(self.cfg, now.date())
        self.assertEqual([n["time"] for n in notes], ["13:45", "17:45"])
        self.assertEqual(notes[0]["text"], "he was right about the subject line")

    def test_image_is_copied_into_the_day_and_recorded_relative(self):
        src = self.tmp / "lunch pic!.jpg"
        src.write_bytes(b"jpegjpeg")
        now = datetime(2026, 9, 6, 12, 0, tzinfo=da.local_tz())
        rec = da.add_note(self.cfg, "the sandwich place", image=str(src), now=now)
        self.assertEqual(rec["image"], "assets/2026-09-06/lunch_pic_.jpg")
        copied = da.out_dir(self.cfg) / rec["image"]
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), b"jpegjpeg")
        self.assertEqual(da.read_notes(self.cfg, now.date())[0]["image"], rec["image"])

    def test_same_name_different_image_does_not_overwrite(self):
        now = datetime(2026, 9, 6, 12, 0, tzinfo=da.local_tz())
        one, two = self.tmp / "a" / "shot.png", self.tmp / "b" / "shot.png"
        one.parent.mkdir(); two.parent.mkdir()
        one.write_bytes(b"1111")
        two.write_bytes(b"22222222")
        first = da.add_note(self.cfg, "one", image=str(one), now=now)
        second = da.add_note(self.cfg, "two", image=str(two), now=now)
        self.assertNotEqual(first["image"], second["image"])
        self.assertEqual((da.out_dir(self.cfg) / first["image"]).read_bytes(), b"1111")

    def test_empty_note_and_missing_image_are_refused(self):
        with self.assertRaises(ValueError):
            da.add_note(self.cfg, "   ")
        with self.assertRaises(ValueError):
            da.add_note(self.cfg, "text", image=str(self.tmp / "nope.jpg"))

    def test_note_needs_no_worklog_and_no_model(self):
        """A note is the one command that must stay instant, so it must not reach for either."""
        calls = []
        saved_wl, saved_run = da.worklog, da.run_summariser
        da.worklog = lambda *a, **k: calls.append("worklog")
        da.run_summariser = lambda *a, **k: calls.append("model")
        try:
            da.add_note(self.cfg, "quick")
        finally:
            da.worklog, da.run_summariser = saved_wl, saved_run
        self.assertEqual(calls, [])


class TestTierFilter(DiaryTest):

    def slices_at_every_tier(self):
        own = self.repo("crm", {"tier": "own", "description": "a client CRM rebuild"})
        nick = self.repo("kestrel-app", {"tier": "nickname", "nickname": "Kestrel",
                                         "description": "a scheduling tool"})
        priv = self.repo("acme-portal", {"tier": "private"})
        c = lambda subj: {"time": "%sT10:30:00+00:00" % self.iso, "subject": subj, "author": "Test Dev"}
        return [
            a_slice(own, "crm", "crm",
                    [a_session("s-own", "%sT09:00:00+00:00" % self.iso, 90, self.iso, "fix the importer")],
                    [c("feat(import): accept a second column order")]),
            a_slice(nick, "kestrel-app", "kestrel-app",
                    [a_session("s-nick", "%sT11:00:00+00:00" % self.iso, 60, self.iso)],
                    [c("fix(rota): stop double-booking a shift")]),
            a_slice(priv, "acme-portal", "acme-portal",
                    [a_session("s-priv", "%sT14:00:00+00:00" % self.iso, 45, self.iso)],
                    [c("chore: bump deps"), c("feat: add the export")]),
        ]

    def test_each_tier_keeps_only_what_it_promises(self):
        day, metas, warnings = self.build(self.slices_at_every_tier())
        by = {p["label"]: p for p in day["projects"]}
        self.assertEqual(set(by), {"a client CRM rebuild", "Kestrel", da.PRIVATE_LABEL})

        own = by["a client CRM rebuild"]
        self.assertEqual(own["hours"], 1.5)
        self.assertEqual([c["message"] for c in own["commits"]],
                         ["feat(import): accept a second column order"])
        self.assertTrue(own["worklog"])
        self.assertEqual(own["sessions"][0]["id"], "s-own")

        nick = by["Kestrel"]
        self.assertNotIn("commits", nick)
        self.assertNotIn("worklog", nick)
        self.assertEqual(len(nick["sessions"]), 1)
        self.assertNotIn("id", nick["sessions"][0])
        self.assertNotIn("start", nick["sessions"][0])

        priv = by[da.PRIVATE_LABEL]
        self.assertEqual(priv["hours"], 0.75)
        self.assertNotIn("commits", priv)
        self.assertNotIn("sessions", priv)
        self.assertNotIn("worklog", priv)
        self.assertEqual(set(priv) - {"_key"}, {"label", "tier", "hours"})

    def test_totals_count_the_real_day_not_the_filtered_one(self):
        day, _m, _w = self.build(self.slices_at_every_tier())
        self.assertEqual(day["totals"]["commits"], 4)
        self.assertEqual(day["totals"]["sessions"], 3)
        self.assertEqual(day["totals"]["hours"], 3.25)

    def test_undeclared_repo_defaults_private_and_warns(self):
        root = self.repo("unclassified")
        day, _m, warnings = self.build(
            [a_slice(root, "unclassified", "unclassified",
                     [a_session("s1", "%sT09:00:00+00:00" % self.iso, 30, self.iso)])])
        self.assertEqual(day["projects"][0]["label"], da.PRIVATE_LABEL)
        self.assertTrue(any("no diary tier" in w for w in warnings))

    def test_nickname_without_a_nickname_falls_back_to_private(self):
        root = self.repo("half-done", {"tier": "nickname"})
        day, _m, warnings = self.build(
            [a_slice(root, "half-done", "half-done",
                     [a_session("s1", "%sT09:00:00+00:00" % self.iso, 30, self.iso)])])
        self.assertEqual(day["projects"][0]["tier"], "private")
        self.assertTrue(any("treated as private" in w for w in warnings))

    def test_a_day_with_no_work_in_a_repo_leaves_it_out(self):
        root = self.repo("idle", {"tier": "own", "description": "a thing"})
        day, _m, _w = self.build([a_slice(root, "idle", "idle")])
        self.assertEqual(day["projects"], [])
        self.assertEqual(day["totals"], {"hours": 0.0, "commits": 0, "sessions": 0})


class TestLeakCheck(DiaryTest):

    def a_day(self, tier, text, blocklist=(), extra=None):
        block = {"tier": tier}
        if tier == "own":
            block["description"] = "a client CRM rebuild"
        if tier == "nickname":
            block["nickname"] = "Kestrel"
        root = self.repo("hearta", block)
        self.cfg["blocklist"] = list(blocklist)
        slices = [a_slice(root, "hearta", "hearta",
                          [a_session("s1", "%sT09:00:00+00:00" % self.iso, 60, self.iso)])]
        day, metas, _w = self.build(slices)
        day["projects"][0]["sessions"] = [{"minutes": 60, "summary": text}]
        if extra:
            day.update(extra)
        return day, metas

    def test_blocklist_term_is_caught_at_own_tier(self):
        day, metas = self.a_day("own", "We rebuilt the importer for Acme Group.", ["Acme Group"])
        hits = da.leak_check(day, self.cfg, metas)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["term"], "Acme Group")
        self.assertEqual(hits[0]["why"], "on the blocklist")
        self.assertIn("projects[0]", hits[0]["where"])
        self.assertIn("Acme Group", hits[0]["sample"])

    def test_the_repo_name_is_forbidden_at_every_tier(self):
        for tier in ("own", "nickname"):
            day, metas = self.a_day(tier, "A quiet morning inside hearta, mostly reading.")
            hits = da.leak_check(day, self.cfg, metas)
            self.assertTrue(any(h["why"] == "names the repository" for h in hits), tier)

    def test_a_word_that_merely_contains_the_name_is_not_a_hit(self):
        day, metas = self.a_day("own", "There was some heartache about the import order.")
        self.assertEqual(da.leak_check(day, self.cfg, metas), [])

    def test_shape_rules_apply_below_own_only(self):
        text = "We changed src/lib/importer.ts and shipped it."
        day, metas = self.a_day("nickname", text)
        hits = da.leak_check(day, self.cfg, metas)
        self.assertTrue(any(h["why"].startswith("a file path") for h in hits))
        day, metas = self.a_day("own", text)
        self.assertEqual(da.leak_check(day, self.cfg, metas), [])

    def test_urls_and_commit_messages_below_own(self):
        for text, why in (("See https://portal.example.com/admin for the rest.", "a URL"),
                          ("Landed feat(rota): stop double-booking today.", "a commit message"),
                          ("Merged feature/rota-fix into prelive.", "a branch name")):
            day, metas = self.a_day("nickname", text)
            hits = da.leak_check(day, self.cfg, metas)
            self.assertTrue(any(h["why"].startswith(why) for h in hits), text)

    def test_a_note_is_checked_too(self):
        day, metas = self.a_day("own", "nothing to see", ["Acme Group"],
                                extra={"notes": [{"time": "13:00", "text": "call with Acme Group"}]})
        hits = da.leak_check(day, self.cfg, metas)
        self.assertTrue(any(h["where"].startswith("notes") for h in hits))

    def test_the_tools_own_fixed_notes_are_not_scanned(self):
        # A repo whose commits are authored by a bot called "Claude" made every collect fail on
        # the tool's OWN time_note, which says "Claude Code effort". The tool's fixed prose is
        # not anybody's data and there is nothing in it to leak.
        root = self.repo("hearta", {"tier": "own", "description": "a client CRM rebuild"})
        slices = [a_slice(root, "hearta", "hearta",
                          [a_session("s1", "%sT09:00:00+00:00" % self.iso, 60, self.iso)],
                          [{"time": "%sT09:10:00+00:00" % self.iso, "author": "Claude",
                            "subject": "chore: tidy"}])]
        day, metas, _w = self.build(slices)
        hits = da.leak_check(day, self.cfg, metas)
        self.assertEqual([h for h in hits if h["where"] in ("time_note", "chat_sessions_note")], [])

    def test_a_note_the_operator_wrote_themselves_is_still_scanned(self):
        day, metas = self.a_day("own", "nothing to see", ["Acme Group"],
                                extra={"chat_sessions_note": "ask Acme Group for the chat log"})
        hits = da.leak_check(day, self.cfg, metas)
        self.assertTrue(any(h["where"] == "chat_sessions_note" for h in hits))

    def test_redaction_replaces_and_reports(self):
        day, metas = self.a_day("own", "We rebuilt it for Acme Group, twice.", ["Acme Group"])
        hits = da.leak_check(day, self.cfg, metas, redact=True)
        self.assertEqual(len(hits), 1)
        self.assertNotIn("Acme Group", json.dumps(day))
        self.assertIn("[redacted]", day["projects"][0]["sessions"][0]["summary"])

    def test_the_report_names_the_term_and_where_it_came_from(self):
        day, metas = self.a_day("own", "It was for Acme Group.", ["Acme Group"])
        report = da.leak_report(da.leak_check(day, self.cfg, metas))
        self.assertIn("Acme Group", report)
        self.assertIn("projects[0]", report)
        self.assertIn("on the blocklist", report)
        self.assertIn("--force", report)


class TestCollect(DiaryTest):

    def leaky_slices(self):
        root = self.repo("crm", {"tier": "own", "description": "a client CRM rebuild"})
        return [a_slice(root, "crm", "crm",
                        [a_session("s1", "%sT09:00:00+00:00" % self.iso, 60, self.iso)],
                        [{"time": "%sT10:00:00+00:00" % self.iso, "author": "Test Dev",
                          "subject": "feat: invoice export for Acme Group"}])]

    def test_a_leak_fails_the_collect_and_writes_nothing(self):
        self.cfg["blocklist"] = ["Acme Group"]
        wl = FakeWorklog(self.leaky_slices())
        with self.assertRaises(da.LeakError) as e:
            da.collect(self.cfg, self.day, wl=wl, summarise=False)
        self.assertTrue(e.exception.hits)
        self.assertFalse(da.day_path(self.cfg, self.day).exists())

    def test_force_redacts_writes_and_says_what_it_did(self):
        self.cfg["blocklist"] = ["Acme Group"]
        wl = FakeWorklog(self.leaky_slices())
        day, warnings, hits = da.collect(self.cfg, self.day, wl=wl, force=True, summarise=False)
        path = da.day_path(self.cfg, self.day)
        self.assertTrue(path.exists())
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("Acme Group", json.dumps(written))
        self.assertTrue(written["redacted"])
        self.assertEqual(written["redacted"][0]["why"], "on the blocklist")

    def test_the_written_file_keeps_no_internal_keys(self):
        root = self.repo("crm", {"tier": "own", "description": "a client CRM rebuild"})
        wl = FakeWorklog([a_slice(root, "crm", "crm",
                                  [a_session("s1", "%sT09:00:00+00:00" % self.iso, 60, self.iso)])])
        day, _w, _h = da.collect(self.cfg, self.day, wl=wl, summarise=False)
        written = json.loads(da.day_path(self.cfg, self.day).read_text(encoding="utf-8"))
        self.assertNotIn("_key", json.dumps(written))
        self.assertEqual(written["date"], self.iso)
        self.assertEqual(written["diary_version"], da.VERSION)
        self.assertIn("chat_sessions_note", written)

    def test_no_worklog_says_where_it_looked(self):
        saved = da.worklog
        da.worklog = lambda *a, **k: None
        try:
            with self.assertRaises(RuntimeError) as e:
                da.collect(self.cfg, self.day, summarise=False)
        finally:
            da.worklog = saved
        self.assertIn("Looked in:", str(e.exception))


class TestRulesAndLabels(DiaryTest):

    def test_a_repo_name_inside_its_own_approved_description_is_not_a_leak(self):
        root = self.repo("crm", {"tier": "own", "description": "a client CRM rebuild"})
        metas = [{"key": "crm/crm", "project": "crm", "repo": "crm", "path": str(root),
                  "label": "a client CRM rebuild", "cfg": da.repo_diary_cfg(root),
                  "people": set(), "branches": []}]
        glob, _per = da.build_rules(self.cfg, metas)
        self.assertEqual([t for _rx, t, _why in glob], [])

    def test_the_blocklist_is_never_softened_by_a_label(self):
        root = self.repo("crm", {"tier": "own", "description": "a client CRM rebuild"})
        self.cfg["blocklist"] = ["CRM"]
        metas = [{"key": "crm/crm", "project": "crm", "repo": "crm", "path": str(root),
                  "label": "a client CRM rebuild", "cfg": da.repo_diary_cfg(root),
                  "people": set(), "branches": []}]
        glob, _per = da.build_rules(self.cfg, metas)
        self.assertEqual([why for _rx, _t, why in glob], ["on the blocklist"])

    def test_a_person_who_committed_is_blocked_everywhere(self):
        root = self.repo("crm", {"tier": "own", "description": "a CRM"})
        wl = FakeWorklog([a_slice(root, "crm", "crm",
                                  [a_session("s1", "%sT09:00:00+00:00" % self.iso, 30, self.iso)],
                                  [{"time": "%sT10:00:00+00:00" % self.iso, "author": "Dana Okonjo",
                                    "subject": "fix: a thing"}])])
        day, metas, _w = da.build_day(self.cfg, self.day, wl, summarise=False)
        day["projects"][0]["sessions"] = [{"minutes": 30, "summary": "Dana Okonjo reviewed it."}]
        hits = da.leak_check(day, self.cfg, metas)
        self.assertTrue(any(h["why"] == "is a committer name in the day's repos" for h in hits))


class TestTranscripts(DiaryTest):

    def write_transcript(self, root, session_id, lines):
        folder = Path(self.cfg["transcripts"]) / da.encode_cwd(root)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(da.local_tz()).replace(hour=10, minute=0, second=0).isoformat()
        out = []
        for obj in lines:
            rec = dict(obj)
            rec.setdefault("sessionId", session_id)
            rec.setdefault("timestamp", stamp)
            out.append(json.dumps(rec))
        (folder / ("%s.jsonl" % session_id)).write_text("\n".join(out) + "\n", encoding="utf-8")
        return folder

    def test_prompts_and_prose_are_in_and_tool_results_are_out(self):
        root = self.repo("crm", {"tier": "own", "description": "a CRM"})
        self.write_transcript(root, "s1", [
            {"type": "user", "message": {"content": "make the importer accept two column orders"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Reading the importer first."},
                {"type": "tool_use", "name": "Read"}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": "SECRET_TOKEN_abc123 lives in this file"}]}},
            {"type": "user", "isMeta": True, "message": {"content": "Caveat: some meta thing"}},
        ])
        digest = da.session_digest(self.cfg, root, "s1", self.day)
        self.assertIn("HUMAN: make the importer accept two column orders", digest)
        self.assertIn("CLAUDE: Reading the importer first.", digest)
        self.assertIn("TOOLS USED: Read x1", digest)
        self.assertNotIn("SECRET_TOKEN_abc123", digest)
        self.assertNotIn("Caveat", digest)

    def test_another_session_in_the_same_folder_is_not_mixed_in(self):
        root = self.repo("crm", {"tier": "own", "description": "a CRM"})
        self.write_transcript(root, "s1", [{"type": "user", "message": {"content": "mine"}}])
        self.write_transcript(root, "s2", [{"type": "user", "message": {"content": "theirs"}}])
        digest = da.session_digest(self.cfg, root, "s1", self.day)
        self.assertIn("mine", digest)
        self.assertNotIn("theirs", digest)

    def test_a_day_with_no_transcript_summarises_to_nothing_and_says_why(self):
        root = self.repo("crm", {"tier": "own", "description": "a CRM"})
        text, err = da.summarise_session(self.cfg, root, {"id": "s9", "_minutes": 10},
                                         self.day, "a CRM", "own")
        self.assertEqual(text, "")
        self.assertIn("no transcript", err)


class TestSummaries(DiaryTest):

    def setUp(self):
        DiaryTest.setUp(self)
        self.counter = self.tmp / "calls.txt"
        script = self.tmp / "fake_summariser.py"
        script.write_text(
            "import sys\n"
            "body = sys.stdin.read()\n"
            "open(sys.argv[1], 'a', encoding='utf-8').write('call' + chr(10))\n"
            "print('A summary of the session. It mentioned %d characters.' % len(body))\n",
            encoding="utf-8")
        self.cfg["summariser"] = [sys.executable, str(script), str(self.counter)]
        self.root = self.repo("crm", {"tier": "own", "description": "a CRM"})
        folder = Path(self.cfg["transcripts"]) / da.encode_cwd(self.root)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(da.local_tz()).replace(hour=10, minute=0, second=0).isoformat()
        (folder / "s1.jsonl").write_text(json.dumps(
            {"type": "user", "sessionId": "s1", "timestamp": stamp,
             "message": {"content": "make the importer accept two column orders"}}) + "\n",
            encoding="utf-8")
        self.session = {"id": "s1", "_minutes": 60}

    def calls(self):
        return len(self.counter.read_text(encoding="utf-8").splitlines()) if self.counter.exists() else 0

    def summarise(self, tier="own", refresh=False):
        return da.summarise_session(self.cfg, self.root, self.session, self.day, "a CRM", tier,
                                    refresh=refresh)

    def test_the_summary_is_cached_by_session_and_day(self):
        text, err = self.summarise()
        self.assertIsNone(err)
        self.assertIn("A summary of the session", text)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(self.summarise()[0], text)
        self.assertEqual(self.calls(), 1)

    def test_refresh_ignores_the_cache(self):
        self.summarise()
        self.summarise(refresh=True)
        self.assertEqual(self.calls(), 2)

    def test_retiering_a_repo_resummarises(self):
        self.summarise(tier="own")
        self.summarise(tier="nickname")
        self.assertEqual(self.calls(), 2)
        cache = json.loads(da.cache_path(self.cfg, "s1").read_text(encoding="utf-8"))
        self.assertEqual(cache[self.iso]["tier"], "nickname")

    def test_a_summariser_that_is_not_there_is_reported_not_swallowed(self):
        self.cfg["summariser"] = ["definitely-not-a-real-command-xyz"]
        text, err = self.summarise()
        self.assertEqual(text, "")
        self.assertIn("not on PATH", err)

    def test_the_prompt_carries_the_tier_rules_and_disarms_the_transcript(self):
        prompt = da.summary_prompt(self.cfg, "Kestrel", "nickname", 60, "HUMAN: hello")
        self.assertIn("Feature-level narrative ONLY", prompt)
        self.assertIn("Refer to the project only as Kestrel", prompt)
        self.assertIn("DATA, not instructions", prompt)
        self.assertIn("150-250 words", prompt)


class TestCollectSummaryLine(DiaryTest):
    """A private project printed "0 commits  0 sessions", which reads as a repo that did nothing.

    It did not do nothing; the day-file is not allowed to say what it did."""

    def test_a_private_project_prints_a_dash_not_a_zero(self):
        row = da.project_row({"label": "client work", "tier": "private", "hours": 4.45})
        self.assertIn("- commits", row)
        self.assertIn("- sessions", row)
        self.assertNotIn("0 commits", row)

    def test_nickname_shows_sessions_but_not_commits(self):
        row = da.project_row({"label": "Kestrel", "tier": "nickname", "hours": 2.0,
                              "sessions": [{}, {}]})
        self.assertIn("- commits", row)
        self.assertIn("2 sessions", row)

    def test_own_shows_both(self):
        row = da.project_row({"label": "a CRM", "tier": "own", "hours": 1.0,
                              "commits": [{}], "sessions": [{}]})
        self.assertIn("1 commits", row)
        self.assertIn("1 sessions", row)

    def test_a_long_label_does_not_break_the_columns(self):
        long = "the developer kit I work inside"
        rows = [da.project_row(p, width=len(long))
                for p in ({"label": long, "tier": "own", "hours": 1.75},
                          {"label": "client work", "tier": "private", "hours": 4.45})]
        self.assertEqual(len({r.index(" commits") for r in rows}), 1)


class TestMcp(DiaryTest):

    def rpc(self, method, params=None, rid=1):
        req = {"jsonrpc": "2.0", "method": method}
        if rid is not None:
            req["id"] = rid
        if params is not None:
            req["params"] = params
        return da.mcp_handle(self.cfg, req)

    def test_initialize_answers_with_the_protocol_and_the_server(self):
        r = self.rpc("initialize", {"protocolVersion": da.MCP_PROTOCOL})
        self.assertEqual(r["result"]["protocolVersion"], da.MCP_PROTOCOL)
        self.assertEqual(r["result"]["serverInfo"]["version"], da.VERSION)
        self.assertIn("tools", r["result"]["capabilities"])

    def test_the_four_tools_are_listed_with_schemas(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual(sorted(t["name"] for t in tools),
                         ["diary_day", "diary_list", "diary_note", "diary_sessions"])
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["description"])

    def test_a_notification_gets_no_reply(self):
        self.assertIsNone(self.rpc("notifications/initialized", rid=None))
        self.assertIsNone(self.rpc("notifications/cancelled", {"requestId": 1}, rid=None))

    def test_an_unknown_method_is_an_error_not_a_crash(self):
        r = self.rpc("resources/list")
        self.assertEqual(r["error"]["code"], -32601)

    def test_note_through_mcp_writes_the_same_file_the_cli_does(self):
        r = self.rpc("tools/call", {"name": "diary_note", "arguments": {"text": "via the chat"}})
        self.assertFalse(r["result"]["isError"])
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(payload["added"]["text"], "via the chat")
        self.assertEqual([n["text"] for n in da.read_notes(self.cfg, self.day)], ["via the chat"])

    def test_an_unknown_tool_is_reported_in_band(self):
        r = self.rpc("tools/call", {"name": "diary_invent", "arguments": {}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("diary_invent", r["result"]["content"][0]["text"])

    def test_a_failing_tool_does_not_take_the_server_down(self):
        r = self.rpc("tools/call", {"name": "diary_note",
                                    "arguments": {"text": "x", "image_path": str(self.tmp / "nope.png")}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("no such image", r["result"]["content"][0]["text"])

    def test_diary_list_reports_the_day_files_that_exist(self):
        wl = FakeWorklog([])
        da.collect(self.cfg, self.day, wl=wl, summarise=False)
        r = self.rpc("tools/call", {"name": "diary_list", "arguments": {}})
        days = json.loads(r["result"]["content"][0]["text"])["days"]
        self.assertEqual([d["date"] for d in days], [self.iso])

    def test_serve_writes_protocol_to_stdout_and_nothing_else(self):
        lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
                 json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                 "",
                 "{not json",
                 json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})]
        out = io.StringIO()
        da.serve(self.cfg, stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out)
        replies = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
        # the parse error goes to the same stream: nothing this server says escapes stdout
        self.assertEqual([r.get("id") for r in replies], [1, None, 2])
        self.assertEqual(replies[1]["error"]["code"], -32700)
        self.assertEqual(replies[0]["result"]["protocolVersion"], da.MCP_PROTOCOL)

    def test_a_malformed_line_is_a_parse_error_not_a_stack_trace(self):
        out = io.StringIO()
        saved = sys.stdout
        sys.stdout = out
        try:
            da.serve(self.cfg, stdin=io.StringIO("{not json\n"))
        finally:
            sys.stdout = saved
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], -32700)


class TestDoctor(DiaryTest):

    def run_doctor(self):
        out = io.StringIO()
        saved_stream, saved_quiet = da._STREAM, da.QUIET
        da._STREAM, da.QUIET = out, False
        try:
            class Args(object):
                worklog = None
            code = da.cmd_doctor(self.cfg, Args())
        finally:
            da._STREAM, da.QUIET = saved_stream, saved_quiet
        return code, out.getvalue()

    def test_it_never_prints_a_blocklist_term(self):
        self.cfg["blocklist"] = ["Acme Group", "portal.example.com"]
        _code, text = self.run_doctor()
        self.assertNotIn("Acme", text)
        self.assertNotIn("example.com", text)
        self.assertIn("2 terms", text)

    def test_it_prints_the_registration_snippet(self):
        _code, text = self.run_doctor()
        self.assertIn("mcpServers", text)
        self.assertIn("serve", text)
        snippet = text[text.index("{"):text.rindex("}") + 1]
        self.assertIn("diary", json.loads(snippet)["mcpServers"])

    def test_the_snippet_points_at_the_installed_copy_not_the_checkout(self):
        """The desktop app reads this path once and keeps it. A working copy is the wrong thing
        to hand it: it moves with the branch and disappears if the folder is renamed, and the
        failure is silent - the app just stops having a diary. `repo_setup.py install` maintains
        a stable copy under KIT_HOME, so that is what the snippet must name when it exists."""
        da.KIT_HOME.mkdir(parents=True, exist_ok=True)
        installed = da.KIT_HOME / "diary_agent.py"
        installed.write_text("# the installed copy\n", encoding="utf-8")
        _code, text = self.run_doctor()
        snippet = text[text.index("{"):text.rindex("}") + 1]
        args = json.loads(snippet)["mcpServers"]["diary"]["args"]
        self.assertEqual(args[0], installed.resolve().as_posix())
        self.assertEqual(args[1], "serve")

    def test_without_an_installed_copy_it_falls_back_and_says_so(self):
        """Falling back to the checkout is right - a snippet naming a file that is not there is
        worse - but it must not pass silently as the durable answer."""
        _code, text = self.run_doctor()
        snippet = text[text.index("{"):text.rindex("}") + 1]
        args = json.loads(snippet)["mcpServers"]["diary"]["args"]
        self.assertEqual(args[0], Path(da.__file__).resolve().as_posix())
        self.assertIn("repo_setup.py install", text)

    def test_it_says_which_file_the_snippet_goes_in(self):
        """Knowing the JSON and not knowing where it goes is where this actually stalled."""
        _code, text = self.run_doctor()
        self.assertIn("claude_desktop_config.json", text)

    def test_it_warns_about_repos_that_default_to_private(self):
        root = self.repo("unclassified")
        (self.pot / "slices").mkdir(parents=True, exist_ok=True)
        (self.pot / "slices" / "unclassified__unclassified.json").write_text(
            json.dumps({"project": "unclassified", "repo": "unclassified", "path": str(root),
                        "sessions": [], "commits": []}), encoding="utf-8")
        _code, text = self.run_doctor()
        self.assertIn("no diary tier", text)
        self.assertIn("unclassified", text)
