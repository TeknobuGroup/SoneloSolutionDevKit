"""Failing-test-first reproduction: one repository's commits are reported once, not once
per checkout of it.

The bug: collect_commits() (worklog_agent.py) runs `git log --all` at the slice's path, and
git answers for the REPOSITORY, not the directory. So any second checkout of one repository
reports that repository's whole history a second time, and the report, the dashboard, the
weekly CSVs and the diary all count it twice. Two shapes occur on this machine:

  * a linked worktree - `git worktree add` beside the repo, its own branch;
  * a plain subdirectory of a checkout with no .git of its own - `git -C` walks up to the
    parent, so the slice silently reports the parent's history. A "is this a worktree?"
    flag cannot see this one: --git-dir and --git-common-dir are the same path.

Both are fixed by recording the repository's identity when the slice is written
(`repo_id`, the resolved and normalised --git-common-dir) and taking the union of the
group's commits by hash in dedupe_repositories(), which load_slices() applies so that every
consumer inherits it.

The union matters: slices in one group carry different `since` windows, so a frozen slice
can be the only holder of older commits the live slice has already dropped. Electing one
slice's list and discarding the rest loses real history.

Stdlib only; hermetic: every repository and pot lives in a per-test temp dir, and all git
invocations ignore the user's global/system config (see run_git in
test_worklog_worktree.py). Tests needing git skip if it is not on PATH.
Run from the repo root with:  python -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import diary_agent as da
import worklog_agent as wa
from test_worklog_worktree import GIT, add_worktree, make_repo, make_temp_dir, run_git

TZ = wa.local_tz()
CFG = {"currency": "$", "prices": {}, "idle_minutes": 15, "window_days": 28}


def commit(path, name, message):
    """One commit in whatever checkout `path` is, with this repo's hermetic git settings."""
    (Path(path) / name).write_text(name + "\n", encoding="utf-8")
    run_git("-C", str(path), "add", name)
    run_git("-C", str(path), "-c", "commit.gpgsign=false", "commit", "-m", message)


def real_commit_count(repo):
    return int(run_git("-C", str(repo), "rev-list", "--all", "--no-merges", "--count").strip())


def pot_cfg(case):
    return dict(CFG, pot=str(make_temp_dir(case, prefix="worklog-dedupe-pot-")))


def report_totals(pot):
    """What the report says, through the real loader - which is where the fix lives."""
    slices, machines = wa.load_slices(pot)
    now = datetime.now(TZ)
    return wa.build_report(slices, machines, now - timedelta(days=2), now + timedelta(days=1), CFG)[2]


def slice_of(project, repo, commits, sessions=None, **extra):
    """A slice as an older agent wrote it: no repo_id, and a path off this machine."""
    d = {"version": "1.19", "project": project, "repo": repo, "path": "C:\\gone\\" + repo,
         "machine": "OTHER", "updated": "2026-09-01T09:00:00+01:00",
         "since": "2026-08-04T00:00:00+01:00", "uncommitted": 0,
         "commits": [dict(x) for x in commits], "sessions": sessions or []}
    d.update(extra)
    return d


def c(h, day, subject="work"):
    return {"time": datetime(2026, 9, day, 10, 0, tzinfo=TZ).isoformat(), "hash": h,
            "author": "Test", "subject": subject}


@unittest.skipUnless(GIT, "git is not on PATH")
class OneRepositoryCountsOnce(unittest.TestCase):
    """Two checkouts of one repository must not report its history twice."""

    def setUp(self):
        self.cfg = pot_cfg(self)
        # project_name() reads a worklog.json beside the agent file, which in this repo is the
        # kit's own. Force the fallback so each checkout's project is its directory name -
        # the realistic worst case, where the duplicate also arrives as a second project.
        real = wa.REPO_CFG
        wa.REPO_CFG = Path(tempfile.gettempdir()) / "worklog-dedupe-no-such-config.json"
        self.addCleanup(lambda: setattr(wa, "REPO_CFG", real))

    def test_a_linked_worktree_does_not_double_the_repositorys_commits(self):
        base, repo = make_repo(self)
        commit(repo, "a.txt", "second commit")
        worktree = add_worktree(base, repo)
        commit(worktree, "b.txt", "commit made in the worktree")
        truth = real_commit_count(repo)

        wa.collect_and_write(self.cfg, repo)
        wa.collect_and_write(self.cfg, worktree)

        commits, _sessions, _active = report_totals(self.cfg["pot"])
        self.assertEqual(commits, truth,
                         "the worktree reported the repository's history a second time: "
                         "%d commits reported for a repository with %d" % (commits, truth))

    def test_a_subdirectory_with_no_git_of_its_own_does_not_double_them(self):
        """The class a worktree flag cannot see: --git-dir == --git-common-dir on both sides."""
        _base, repo = make_repo(self)
        sub = repo / "sub"
        sub.mkdir()
        commit(sub, "c.txt", "a commit from inside the subdirectory")
        truth = real_commit_count(repo)
        self.assertFalse((sub / ".git").exists(), "precondition: the subdirectory has no .git")

        wa.collect_and_write(self.cfg, repo)
        wa.collect_and_write(self.cfg, sub)

        commits, _sessions, _active = report_totals(self.cfg["pot"])
        self.assertEqual(commits, truth,
                         "a plain subdirectory reported the parent checkout's history again: "
                         "%d commits reported for a repository with %d" % (commits, truth))

    def test_two_unrelated_repositories_are_not_merged(self):
        """And note what make_repo() builds: two repositories seeded with the same content,
        message, author and second have the SAME root commit hash. Which is the point - a
        shared hash is good evidence of a shared history but not proof, so a slice that knows
        its own repository must not be merged into another on the strength of one."""
        _b1, repo1 = make_repo(self)
        _b2, second = make_repo(self)
        repo2 = second.parent / "other-repo"   # make_repo names them all "repo"; one slice each
        second.rename(repo2)
        commit(repo2, "d.txt", "only in the second repository")
        truth = real_commit_count(repo1) + real_commit_count(repo2)

        wa.collect_and_write(self.cfg, repo1)
        wa.collect_and_write(self.cfg, repo2)

        commits, _sessions, _active = report_totals(self.cfg["pot"])
        self.assertEqual(commits, truth,
                         "separate repositories with disjoint histories were merged")

    def test_repo_id_is_absolute_even_where_git_answers_a_relative_path(self):
        """git rev-parse --git-common-dir returns `../.git` from a subdirectory."""
        _base, repo = make_repo(self)
        sub = repo / "sub"
        sub.mkdir()
        commit(sub, "e.txt", "seed the subdirectory")
        raw = run_git("-C", str(sub), "rev-parse", "--git-common-dir").strip()
        self.assertFalse(Path(raw).is_absolute(),
                         "precondition: git answers relatively here (got %r)" % raw)

        here = wa.collect_and_write(self.cfg, sub)
        there = wa.collect_and_write(self.cfg, repo)

        self.assertTrue(Path(here["repo_id"]).is_absolute(),
                        "repo_id was stored as git gave it (%r), not resolved against the root"
                        % here["repo_id"])
        self.assertEqual(here["repo_id"], there["repo_id"],
                         "the subdirectory and its checkout are one repository, so their "
                         "repo_id must match")
        self.assertEqual(here["repo_id"], wa.norm(repo / ".git"))

    def test_the_dashboard_payload_carries_the_same_total_as_the_report(self):
        """docs/UAT_PLAN.md pins it: the projects table is the report's Summary column.

        The dashboard flattens the payload's per-repo commit lists in JavaScript, so the
        only way the two can agree is for the payload to be deduplicated before it ships."""
        base, repo = make_repo(self)
        worktree = add_worktree(base, repo)
        commit(worktree, "f.txt", "worktree work")
        wa.collect_and_write(self.cfg, repo)
        wa.collect_and_write(self.cfg, worktree)

        slices, machines = wa.load_slices(self.cfg["pot"])
        payload = wa.dashboard_data(slices, machines, self.cfg, self.cfg["pot"])
        in_payload = sum(len(r["commits"]) for p in payload["projects"] for r in p["repos"])

        commits, _sessions, _active = report_totals(self.cfg["pot"])
        self.assertEqual(in_payload, commits,
                         "the dashboard payload and the report disagree about the commit count")


class UnionAcrossSlicesOfOneRepository(unittest.TestCase):
    """No git needed: the rule itself, including the slices an older agent wrote."""

    def test_a_frozen_slices_older_commits_are_kept_not_discarded(self):
        """nurture-loop-codex's shape: a stale slice is the only holder of older history,
        because the live slice's window has already moved past it."""
        live = slice_of("Knecta", "nurture-loop-tek", [c("aaa", 8), c("bbb", 9), c("ccc", 10)])
        frozen = slice_of("codex", "nurture-loop-codex", [c("zzz", 7), c("bbb", 9), c("ccc", 10)])

        out = wa.dedupe_repositories([live, frozen])
        hashes = [x["hash"] for sl in out for x in sl.get("commits", [])]

        self.assertEqual(sorted(hashes), ["aaa", "bbb", "ccc", "zzz"],
                         "the union of the group's commits must be reported exactly once each")

    def test_the_duplicate_slice_keeps_its_sessions_and_uncommitted_work(self):
        """A second checkout is a real place work happened; only its commits are another
        slice's to report."""
        s = {"id": "s1", "start": datetime(2026, 9, 9, 9, 0, tzinfo=TZ).isoformat(),
             "end": datetime(2026, 9, 9, 10, 0, tzinfo=TZ).isoformat(), "active_min": 60,
             "prompts": 1, "title": "work in the second checkout", "branch": "prelive"}
        parent = slice_of("PuppyParent", "PuppyParent", [c("aaa", 8), c("bbb", 9), c("ccc", 10)])
        nested = slice_of("PuppyParent", "my-puppy-pal", [c("aaa", 8), c("bbb", 9)],
                          sessions=[s], uncommitted=3)

        out = wa.dedupe_repositories([parent, nested])
        by_repo = {sl["repo"]: sl for sl in out}

        self.assertEqual(len(by_repo["my-puppy-pal"]["sessions"]), 1,
                         "sessions are per-checkout and must never be merged away")
        self.assertEqual(by_repo["my-puppy-pal"]["uncommitted"], 3,
                         "uncommitted work belongs to the checkout that has it")
        self.assertEqual(len(by_repo["PuppyParent"]["commits"]), 3)
        self.assertEqual(by_repo["my-puppy-pal"]["commits"], [])
        self.assertEqual(by_repo["my-puppy-pal"]["dup_of"], "PuppyParent")

    def test_slices_that_share_no_commits_are_left_alone(self):
        a = slice_of("One", "one", [c("aaa", 8)])
        b = slice_of("Two", "two", [c("bbb", 9)])
        out = wa.dedupe_repositories([a, b])
        self.assertEqual([len(sl["commits"]) for sl in out], [1, 1])
        self.assertFalse(any(sl.get("dup_of") for sl in out))

    def test_the_input_slices_are_not_mutated(self):
        """load_slices hands these to four consumers; the helper must not edit under them."""
        parent = slice_of("P", "p", [c("aaa", 8), c("bbb", 9)])
        child = slice_of("P", "c", [c("aaa", 8)])
        wa.dedupe_repositories([parent, child])
        self.assertEqual(len(child["commits"]), 1, "the caller's slice was mutated in place")

    def test_a_malformed_slice_does_not_take_the_whole_pot_down_with_it(self):
        """load_slices() is the single choke point: render, the dashboard, the morning page and
        the diary all come through it, so one unreadable file in the pot must cost that file and
        nothing else. It already skips JSON that is not a dict; this is the same rule one level
        down. The importer for another machine's slices is the reason it matters now."""
        good = slice_of("Good", "good", [c("aaa", 8), c("bbb", 9)])
        rubbish = slice_of("Bad", "bad", [])
        rubbish["commits"] = [{"hash": ["not", "a", "hash"]}, {"hash": {"n": 1}},
                              {"hash": None}, {"no_hash_at_all": True}, "not a dict at all",
                              c("aaa", 8), c("bbb", 9)]
        rubbish["repo_id"] = ["also", "not", "a", "path"]

        out = wa.dedupe_repositories([good, rubbish])

        hashes = sorted(x["hash"] for sl in out for x in sl["commits"] if x["hash"])
        self.assertEqual(hashes, ["aaa", "bbb"],
                         "the real commits the two slices share must still be counted once each")

    def test_nothing_unusable_reaches_the_keepers_list(self):
        """The keeper's list is what build_report, the dashboard and the CSVs iterate.

        Skipping a bad entry while grouping is only half the job: if it is then merged INTO the
        keeper, the crash simply moves downstream to a consumer, where it stops the whole pot
        rendering rather than costing one file. build_report is not inside render()'s try.

        Note which way this goes: an entry that is not a commit at all is dropped, but a dict
        whose hash is the wrong type is KEPT with its hash and subject blanked. Its time and its
        subject may be perfectly good, and that is real work - dropping it would remove a commit
        from the count in order to remove a duplicate that was never there."""
        good = slice_of("Good", "good", [c("aaa", 8), c("bbb", 9)])
        rubbish = slice_of("Bad", "bad", [])
        rubbish["commits"] = ["not a dict at all", {"hash": ["list"]}, c("aaa", 8), c("bbb", 9)]

        out = wa.dedupe_repositories([good, rubbish])
        keeper = max(out, key=lambda sl: len(sl["commits"]))

        self.assertTrue(all(isinstance(x, dict) and isinstance(x.get("hash"), str)
                            and isinstance(x.get("subject"), str) for x in keeper["commits"]),
                        "the keeper carries an entry a consumer cannot render: %r"
                        % (keeper["commits"],))
        self.assertEqual(sorted(x["hash"] for x in keeper["commits"] if x["hash"]),
                         ["aaa", "bbb"],
                         "the shared commits must survive the junk around them, once each")

    def test_commits_with_no_hash_are_all_kept_not_all_but_one(self):
        """Two checkouts each holding commits with no hash recorded: there is nothing to key
        them on, so there is nothing to dedupe them against either. Collapsing them onto one
        key silently discards real work - the opposite of what unioning the group is for."""
        a = slice_of("A", "a", [c("shared", 8), c("also-shared", 9)])
        a["commits"] = a["commits"] + [{"time": c("x", 9)["time"], "subject": "one"},
                                       {"time": c("x", 10)["time"], "subject": "two"}]
        b = slice_of("B", "b", [c("shared", 8), c("also-shared", 9), c("other", 11)])

        out = wa.dedupe_repositories([a, b])
        keeper = max(out, key=lambda sl: len(sl.get("commits") or []))
        subjects = sorted(str(x.get("subject") or "") for x in keeper["commits"]
                          if not x.get("hash"))

        self.assertEqual(subjects, ["one", "two"],
                         "a hashless commit was dropped: they all key on None, so only the "
                         "first survives (kept: %r)" % (subjects,))

    def test_one_shared_hash_alone_does_not_absorb_a_project(self):
        """ADR-0013's collision, arriving from the side it does not protect.

        Two repositories seeded with the same content, message, author and second produce the
        same ROOT commit. Identity beats a hash - but the hash pass exists precisely for slices
        that have no identity, so a pre-1.20 slice sharing one coincidental hash with an
        unrelated repository was folded into it whole: its commits re-attributed and the project
        gone from the report and the dashboard. Sharing a history means sharing more than one
        commit."""
        known = slice_of("Alpha", "alpha", [c("root", 8), c("a1", 9), c("a2", 10)])
        stranger = slice_of("Beta", "beta", [c("root", 8), c("b1", 11), c("b2", 12)])

        out = wa.dedupe_repositories([known, stranger])
        beta = [sl for sl in out if sl["repo"] == "beta"][0]

        self.assertNotIn("dup_of", beta,
                         "one coincidental root commit absorbed a whole project into another")
        self.assertEqual(len(beta["commits"]), 3,
                         "beta's own history was re-attributed on the strength of one hash")

    def test_a_slice_with_no_duplicate_is_cleaned_too(self):
        """The report is what a bad slice actually breaks, and most slices have no duplicate.

        Guarding only the slices that get merged leaves every ordinary one to hand its junk
        straight to build_report - which reads `c["hash"][:7]` and `c["subject"]`, and which
        render() does not call inside a try. Sixteen of this machine's nineteen slices are in
        that position. The loader is where a file stops costing anything but itself."""
        lone = slice_of("Lone", "lone", [c("aaa", 8)])
        lone["commits"] = [c("aaa", 8), "not a commit", 42, {"hash": {}, "time": c("x", 9)["time"]},
                           {"hash": [], "subject": None, "time": c("x", 9)["time"]},
                           {"time": c("x", 10)["time"], "subject": "no hash key at all"}]

        out = wa.dedupe_repositories([lone])
        now = datetime.now(TZ)
        text, _rows, totals = wa.build_report(out, [], now - timedelta(days=40),
                                              now + timedelta(days=1), CFG)

        self.assertIsInstance(text, str)
        self.assertEqual(totals[0], 4, "the four dict entries are the commits; the string and "
                                       "the number are not commits at all")
        self.assertNotIn("commits", [type(x).__name__ for x in out[0]["commits"]])
        self.assertTrue(all(isinstance(x, dict) and isinstance(x.get("hash"), str)
                            and isinstance(x.get("subject"), str) for x in out[0]["commits"]),
                        "every entry the loader hands on must be a dict whose hash and subject "
                        "are strings: %r" % (out[0]["commits"],))

    def test_a_commits_field_that_is_not_a_list_costs_that_slice_only(self):
        """One field up from the entries, and the same rule. A truncated or mangled `commits`
        is an ordinary corruption in a hand-copied file, and hand-copying is what comes next."""
        good = slice_of("Good", "good", [c("aaa", 8), c("bbb", 9)])
        broken = slice_of("Broken", "broken", [])
        broken["commits"] = 0

        out = wa.dedupe_repositories([good, broken])

        self.assertEqual(len(out), 2)
        self.assertEqual([x["hash"] for x in out[0]["commits"]], ["aaa", "bbb"])
        self.assertEqual(out[1]["commits"], [])

    def test_the_checkout_at_the_repository_root_is_the_one_that_reports(self):
        base = Path(tempfile.gettempdir()) / "worklog-dedupe-rep"
        parent = slice_of("P", "p", [c("aaa", 8)], path=str(base),
                          repo_id=wa.norm(base / ".git"))
        child = slice_of("Child", "child", [c("aaa", 8), c("bbb", 9)], path=str(base / "wt"),
                         repo_id=wa.norm(base / ".git"))
        out = wa.dedupe_repositories([parent, child])
        by_repo = {sl["repo"]: sl for sl in out}
        self.assertEqual(len(by_repo["p"]["commits"]), 2,
                         "the checkout at the repository root should carry the group's commits")
        self.assertEqual(by_repo["child"]["commits"], [])


class NoOneSliceCanStopEveryReport(unittest.TestCase):
    """The pot is untrusted input, and `commits` was only the first field to prove it.

    A slice file is written by an agent on some machine - possibly another one, possibly
    mid-write when the power went - and `load_slices()` is where every consumer meets it:
    render, cmd_brief, the dashboard, the morning page, diary collect. `build_report` is not
    inside `render()`'s try, so one unusable value anywhere in the pot stops the reports for
    every project rather than costing the file it came from, and it fails silently: the hook
    worker logs a traceback and the reports simply stop being written.

    Hardening `commits` alone left its siblings on the same path - `sessions`, `project`,
    `repo`, `uncommitted` - each of which does the same thing from one field over. The rule is
    the whole slice, at the one choke point, not one field at a time.
    """

    def _pot(self, junk):
        """One healthy slice and one carrying `junk`, both on disk, read the real way."""
        pot = Path(make_temp_dir(self, prefix="worklog-dedupe-junk-"))
        (pot / "slices").mkdir(parents=True)
        good = slice_of("Good", "good", [c("aaa", 8), c("bbb", 9)])
        bad = slice_of("Bad", "bad", [c("ccc", 8)])
        bad.update(junk)
        for name, d in (("Good__good.json", good), ("Bad__bad.json", bad)):
            (pot / "slices" / name).write_text(json.dumps(d), encoding="utf-8")
        return str(pot)

    def _totals(self, pot):
        slices, machines = wa.load_slices(pot)
        now = datetime.now(TZ)
        return wa.build_report(slices, machines, now - timedelta(days=40),
                               now + timedelta(days=1), CFG)[2]

    def test_no_single_bad_field_stops_the_healthy_slice_reporting(self):
        """Each of these was measured raising out of build_report, killing the whole pot."""
        for junk in ({"sessions": "x"}, {"sessions": 5}, {"sessions": ["x"]},
                     {"sessions": {"start": "now"}}, {"project": 1}, {"project": None},
                     {"project": ["a"]}, {"repo": 1}, {"uncommitted": "lots"},
                     {"path": 7}, {"commits": "none"}):
            with self.subTest(junk=junk):
                totals = self._totals(self._pot(junk))
                self.assertGreaterEqual(totals[0], 2,
                                        "the healthy slice's 2 commits must still be reported")

    def _pot_with_session(self, junk):
        """The same pot, but the junk is inside a session rather than beside it."""
        now = datetime.now(TZ).isoformat()
        s = {"start": now, "end": now, "title": "t", "prompts": 1, "active_min": 5}
        s.update(junk)
        return self._pot({"sessions": [s]})

    def _pot_with_machine(self, junk):
        """The same pot, plus a machine slice - which is read by the same consumers and was
        never cleaned at all, so it stopped every report from one field over."""
        pot = self._pot({})
        m = {"kind": "machine", "machine": "somebody-elses-pc"}
        m.update(junk)
        (Path(pot) / "slices" / "_machine__somebody-elses-pc.json").write_text(
            json.dumps(m), encoding="utf-8")
        return pot

    def test_no_bad_session_field_stops_the_healthy_slice_reporting(self):
        """A session is a slice one level in, and every one of these was measured raising out
        of build_report. `sessions` being the right type was never the whole of the claim."""
        for junk in ({"active_min": "lots"}, {"bursts": 5}, {"tokens": "none"}, {"tokens": 3},
                     {"agents": ["x"]}, {"agents": {"a": "x"}}, {"tools": "x"},
                     {"commands": 7}, {"tools": {"Read": "many"}},
                     {"tokens_by_model": ["x"]}, {"context_max": "big"},
                     # and the leaf below the fields, where the counts themselves live
                     {"tokens": {"in": "lots"}}, {"tokens_by_model": {"m": "x"}},
                     {"agents": {"a": {"runs": "two"}}},
                     {"tokens_by_day_by_model": {"2026-09-14": {"m": {"in": "x"}}}}):
            with self.subTest(junk=junk):
                totals = self._totals(self._pot_with_session(junk))
                self.assertGreaterEqual(totals[0], 2,
                                        "the healthy slice's 2 commits must still be reported")

    def test_a_token_count_that_is_a_count_is_still_added_up(self):
        """The guard at the leaf must not cost the ordinary case: a real count still counts."""
        self.assertEqual(wa.tok_of({"in": 12}, "in"), 12)
        self.assertEqual(wa.tok_of({"in": "twelve"}, "in"), 0)
        self.assertEqual(wa.tok_of("not a map", "in"), 0)
        self.assertEqual(wa.tok_of(None, "in"), 0)

    def test_a_number_too_large_to_be_a_count_reads_as_none(self):
        """json.load turns `Infinity` back into a float, and int() refuses it with
        OverflowError - which as_int() did not catch, so the guard raised from inside itself."""
        self.assertEqual(wa.as_int(float("inf")), 0)
        self.assertEqual(wa.as_int(float("nan")), 0)
        totals = self._totals(self._pot({"uncommitted": float("inf")}))
        self.assertGreaterEqual(totals[0], 2)

    def test_no_bad_machine_field_stops_every_report(self):
        """Desk time and presence come out of the same pot, written by the same agents on the
        same machines, and reach build_report on the same unprotected path."""
        for junk in ({"aw": "x"}, {"aw": ["x"]}, {"aw": {"days": "x"}}, {"aw": {"days": ["x"]}},
                     {"aw": {"days": {"2026-09-14": "all day"}}},
                     {"presence": "none"}, {"presence": 5}, {"presence": {"events": "x"}},
                     {"presence": {"events": ["x"]}},
                     {"presence": {"events": [{"event": "unlock"}]}}):
            with self.subTest(junk=junk):
                totals = self._totals(self._pot_with_machine(junk))
                self.assertGreaterEqual(totals[0], 3,
                                        "both healthy slices' commits must still be reported")

    def test_a_machine_slice_that_is_merely_odd_keeps_everything_it_holds(self):
        """The same rule as for a repo slice: normalising is not licence to drop good data."""
        day = datetime.now(TZ).date().isoformat()
        pot = self._pot_with_machine({"aw": {"ok": True, "days": {day: {"desk_s": 3600}}},
                                      "presence": {"events": [{"time": datetime.now(TZ).isoformat(),
                                                               "event": "unlock"}]}})
        _slices, machines = wa.load_slices(pot)
        self.assertEqual(machines[0]["aw"]["days"][day]["desk_s"], 3600)
        self.assertTrue(machines[0]["aw"]["ok"])
        self.assertEqual(len(machines[0]["presence"]["events"]), 1)

    def test_the_command_you_run_when_the_pot_looks_wrong_is_not_the_one_that_crashes(self):
        """cmd_status reads the raw file on purpose - it describes files, not work - so it is
        the one place a malformed slice is expected, and the one place it must not raise."""
        pot = Path(make_temp_dir(self, prefix="worklog-status-junk-"))
        (pot / "slices").mkdir(parents=True)
        root = Path(make_temp_dir(self, prefix="worklog-status-repo-"))
        sp = wa.slice_path(str(pot), wa.project_name(root), root.name)
        sp.write_text(json.dumps({"project": root.name, "repo": root.name,
                                  "commits": "none", "sessions": 5}), encoding="utf-8")
        (pot / "slices" / ("_machine__%s.json" % root.name)).write_text(
            json.dumps({"kind": "machine", "aw": ["x"], "presence": {"events": ["x"]}}),
            encoding="utf-8")
        said = []
        for name, stub in (("repo_root", lambda: root), ("say", said.append),
                           ("central_cfg", lambda: dict(CFG, pot=str(pot), aw_url="http://x")),
                           ("hooks_installed", lambda r: []),
                           ("global_hook_installed", lambda: False),
                           ("aw_reachable", lambda c: False)):
            saved = getattr(wa, name)
            setattr(wa, name, stub)
            self.addCleanup(lambda n=name, v=saved: setattr(wa, n, v))
        wa.cmd_status(None)
        self.assertTrue(any("slice" in line for line in said), said)

    def test_a_slice_with_no_usable_project_is_dropped_rather_than_guessed_at(self):
        """`project` is the bucket label every count hangs off; there is nothing to fall back
        to, so such a slice is dropped - and it is the only field whose type drops one."""
        slices, _machines = wa.load_slices(self._pot({"project": 1}))
        self.assertEqual([sl["project"] for sl in slices], ["Good"])

    def test_a_slice_that_is_merely_odd_keeps_everything_it_holds(self):
        """Normalising must not become quiet data loss: a slice whose fields are all the right
        type is passed through untouched, sessions and uncommitted count included."""
        pot = self._pot({"uncommitted": 3,
                         "sessions": [{"start": datetime.now(TZ).isoformat(),
                                       "end": datetime.now(TZ).isoformat(), "title": "t"}]})
        slices, _machines = wa.load_slices(pot)
        bad = [sl for sl in slices if sl["project"] == "Bad"][0]
        self.assertEqual(bad["uncommitted"], 3)
        self.assertEqual(len(bad["sessions"]), 1)
        self.assertEqual(len(bad["commits"]), 1)

    def test_the_slice_that_could_not_be_used_is_named_in_the_log(self):
        """Silence is how this bug survived three rounds of review: something has to say which
        file was unusable, or a dropped slice looks exactly like a quiet week."""
        said, real = [], wa.log
        wa.log = said.append
        try:
            wa.load_slices(self._pot({"project": 1}))
        finally:
            wa.log = real
        self.assertTrue(any("Bad__bad.json" in m for m in said),
                        "nothing said which file was dropped: %r" % (said,))


@unittest.skipUnless(GIT, "git is not on PATH")
class RefsThatAreNotWork(unittest.TestCase):
    """--all is `every ref under refs/`, and a stash lives under refs/ too.

    The same reading of "what does git answer for" that this release fixes on the directory side
    has a second edge on the ref side. `git stash -u` writes refs/stash, and hanging off it are
    two pseudo-commits - `index on <branch>` and `untracked files on <branch>` - which are not
    merges, so --no-merges does not filter them, and which are not work either: they are one
    shelved change, and it is counted again for real when it is unstashed and committed. In this
    machine's pot, 4 of 3,215 collected commits were these."""

    def _stashed(self):
        _base, repo = make_repo(self)
        commit(repo, "a.txt", "real work")
        (repo / "a.txt").write_text("changed but not committed\n", encoding="utf-8")
        (repo / "untracked.txt").write_text("not added\n", encoding="utf-8")
        run_git("-C", str(repo), "stash", "push", "-u", "-m", "shelved")
        refs = run_git("-C", str(repo), "for-each-ref", "--format=%(refname)", "refs/stash")
        self.assertIn("refs/stash", refs, "precondition: the stash ref exists")
        return repo

    def _noted(self):
        """A repo carrying one real commit and one git note about it."""
        _base, repo = make_repo(self)
        commit(repo, "a.txt", "real work")
        run_git("-C", str(repo), "-c", "commit.gpgsign=false", "notes", "add", "-m", "a note")
        refs = run_git("-C", str(repo), "for-each-ref", "--format=%(refname)", "refs/notes/")
        self.assertIn("refs/notes/", refs, "precondition: the notes ref exists")
        return repo

    def test_a_note_is_not_collected_as_a_commit(self):
        """refs/notes is the stash's twin: a ref under refs/, so --all walks it, and the commit
        it holds is single-parent, so --no-merges keeps it - and it is authored and dated by
        whoever wrote the note, so the diary's author filter keeps it too. Annotating a commit
        is not a second piece of work."""
        repo = self._noted()
        since = datetime.now(TZ) - timedelta(days=2)
        subjects = [c["subject"] for c in wa.collect_commits(repo, since)]
        self.assertIn("real work", subjects, "the real commit must still be collected")
        self.assertEqual([s for s in subjects if s.startswith("Notes added")], [],
                         "a git note was counted as a commit: %r" % (subjects,))

    def test_the_diary_does_not_put_a_note_in_the_day(self):
        repo = self._noted()
        subjects = [c["message"] for c in da.day_commits(repo, datetime.now(TZ).date(), set())]
        self.assertIn("real work", subjects)
        self.assertEqual([s for s in subjects if s.startswith("Notes added")], [],
                         "the diary put a git note in the day: %r" % (subjects,))

    def test_a_stash_is_not_collected_as_commits(self):
        repo = self._stashed()
        since = datetime.now(TZ) - timedelta(days=2)
        subjects = [c["subject"] for c in wa.collect_commits(repo, since)]
        self.assertIn("real work", subjects, "the real commit must still be collected")
        self.assertEqual([s for s in subjects if s.lower().startswith(
            ("index on", "untracked files on", "wip on"))], [],
            "a shelved change was counted as commits: %r" % (subjects,))

    def test_the_diary_does_not_put_a_stash_in_the_day(self):
        """The diary and the worklog have to answer with the same set of refs or they tell two
        different stories about one day - which is what --all was added to day_commits to fix."""
        repo = self._stashed()
        subjects = [c["message"] for c in da.day_commits(repo, datetime.now(TZ).date(), set())]
        self.assertIn("real work", subjects)
        self.assertEqual([s for s in subjects if s.lower().startswith(
            ("index on", "untracked files on", "wip on"))], [],
            "the diary put a shelved change in the day: %r" % (subjects,))


if __name__ == "__main__":
    unittest.main()
