"""Tests for kit v4.2 wiring in repo_setup.py: merge_settings_hooks (four hooks, idempotent,
worklog entries untouched), claude_md pipeline-marker replacement under --update-pipeline,
merge_gitattributes, and the update-aware nudge (update_available: daily throttle, cached
tag, silent failure, ask-don't-auto).

Import safety: same pattern as test_repo_setup_worktree.py — HOME/USERPROFILE point at a
temp dir around the repo_setup import so the developer machine's config cannot leak in.
Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-pipeline-fake-home-")
atexit.register(shutil.rmtree, _FAKE_HOME, ignore_errors=True)
_saved_home = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
os.environ["HOME"] = _FAKE_HOME
os.environ["USERPROFILE"] = _FAKE_HOME

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import repo_setup as rs

for _k, _v in _saved_home.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v

WORKLOG_CMD = 'C:/py/python.exe "$CLAUDE_PROJECT_DIR/.worklog/worklog_agent.py" run'


def make_temp_dir(testcase, prefix="repo-setup-pipeline-test-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def hook_commands(data, event):
    return [h.get("command") for e in data.get("hooks", {}).get(event, [])
            for h in (e.get("hooks") or [])]


class MergeSettingsHooks(unittest.TestCase):
    """Four hooks registered, twice-applied stays identical, other tools' entries survive."""

    def test_registers_four_hooks_idempotently(self):
        root = make_temp_dir(self)
        rs.merge_settings_hooks(root, rs.Report(False))
        path = root / ".claude" / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for event, script in (("PreToolUse", "guard-migrations.sh"), ("PostToolUse", "post-edit.sh"),
                              ("Stop", "stop-gate.sh"), ("SessionStart", "session-brief.sh")):
            cmds = hook_commands(data, event)
            self.assertEqual(len([c for c in cmds if script in c]), 1, "%s -> %s" % (event, cmds))
        first = path.read_text(encoding="utf-8")
        rs.merge_settings_hooks(root, rs.Report(False))
        self.assertEqual(path.read_text(encoding="utf-8"), first, "second apply must change nothing")

    def test_worklog_entries_survive(self):
        root = make_temp_dir(self)
        path = root / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": WORKLOG_CMD, "timeout": 20}]}]}}), encoding="utf-8")
        rs.merge_settings_hooks(root, rs.Report(False))
        cmds = hook_commands(json.loads(path.read_text(encoding="utf-8")), "SessionStart")
        self.assertIn(WORKLOG_CMD, cmds)
        self.assertTrue(any("session-brief.sh" in c for c in cmds))
        self.assertEqual(len(cmds), 2)


class ClaudeMdMarkers(unittest.TestCase):
    """--update-pipeline replaces only the marker block; hand-written text survives."""

    def test_pipeline_block_replaced_text_outside_kept(self):
        root = make_temp_dir(self)
        hand = "### Reviewers run on their own\n\nHand-written; must survive.\n"
        (root / "CLAUDE.md").write_text(
            "# My repo\n\nintro prose\n\n"
            "<!-- sonelo-devkit:pipeline:start -->\n## Change pipeline\n\nOLD CONTENT\n"
            "<!-- sonelo-devkit:pipeline:end -->\n\n" + hand, encoding="utf-8")
        rs.claude_md(root, rs.Report(False), update=True)
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertNotIn("OLD CONTENT", text)
        self.assertIn("| Changed | Reviewer due |", text)
        self.assertIn(hand, text)
        self.assertIn("intro prose", text)

    def test_without_update_flag_block_is_kept(self):
        root = make_temp_dir(self)
        (root / "CLAUDE.md").write_text(
            "# My repo\n\n<!-- sonelo-devkit:pipeline:start -->\nOLD CONTENT\n"
            "<!-- sonelo-devkit:pipeline:end -->\n", encoding="utf-8")
        rs.claude_md(root, rs.Report(False), update=False)
        self.assertIn("OLD CONTENT", (root / "CLAUDE.md").read_text(encoding="utf-8"))


class MergeGitattributes(unittest.TestCase):
    def test_created_then_unchanged_then_merged(self):
        root = make_temp_dir(self)
        rs.merge_gitattributes(root, rs.Report(False))
        text = (root / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", text)
        rs.merge_gitattributes(root, rs.Report(False))
        self.assertEqual((root / ".gitattributes").read_text(encoding="utf-8"), text)
        (root / ".gitattributes").write_text("*.png binary\n", encoding="utf-8")
        rs.merge_gitattributes(root, rs.Report(False))
        text = (root / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.png binary", text)
        self.assertIn(".githooks/* text eol=lf", text)


class UpdateAvailable(unittest.TestCase):
    """Daily-throttled release check: network at most once a day, cached tag keeps speaking,
    failure is silent and still throttled, non-version tags are ignored."""

    def setUp(self):
        self.stamp = make_temp_dir(self) / "latest-release"
        self._old = rs.UPDATE_STAMP
        rs.UPDATE_STAMP = self.stamp
        self.addCleanup(setattr, rs, "UPDATE_STAMP", self._old)

    def test_newer_tag_is_reported_and_cached(self):
        tag = rs.update_available(now=1000.0, fetch=lambda: "v99.9")
        self.assertEqual(tag, "v99.9")
        self.assertEqual(self.stamp.read_text(encoding="utf-8").strip(), "v99.9")

    def test_fresh_stamp_skips_the_network(self):
        self.stamp.write_text("v99.9\n", encoding="utf-8")

        def explode():
            raise AssertionError("network must not be asked while the stamp is fresh")
        self.assertEqual(rs.update_available(fetch=explode), "v99.9")

    def test_stale_stamp_refetches(self):
        self.stamp.write_text("v99.9\n", encoding="utf-8")
        old = self.stamp.stat().st_mtime - 90000
        os.utime(self.stamp, (old, old))
        self.assertIsNone(rs.update_available(fetch=lambda: "v" + rs.VERSION))
        self.assertEqual(self.stamp.read_text(encoding="utf-8").strip(), "v" + rs.VERSION)

    def test_current_or_older_returns_none(self):
        self.assertIsNone(rs.update_available(fetch=lambda: "v" + rs.VERSION))
        self.assertIsNone(rs.update_available(now=1e12, fetch=lambda: "v0.1"))

    def test_failure_is_silent_and_still_throttled(self):
        def explode():
            raise OSError("offline")
        self.assertIsNone(rs.update_available(fetch=explode))
        self.assertTrue(self.stamp.exists(), "a failed check must still stamp (retry tomorrow)")
        self.assertIsNone(rs.update_available(fetch=lambda: "v99.9"),
                          "throttle applies after a failure too")

    def test_garbage_tags_are_ignored(self):
        for bad in ("main", "vHEAD", "v1.2.x", ""):
            if self.stamp.exists():
                self.stamp.unlink()
            self.assertIsNone(rs.update_available(fetch=lambda b=bad: b))

    def test_latest_tag_accepts_timeout(self):
        import inspect
        self.assertIn("to", inspect.signature(rs.latest_tag).parameters)


class SeedDocsNeverRefreshed(unittest.TestCase):
    """docs/ entries in BUILTIN_PIPELINE are seed templates: created when missing, never
    overwritten by --update-pipeline - a repo's STATUS/ARCHITECTURE/UAT_PLAN are living
    documents. (Caught dogfooding v4.2: the kit's own STATUS.md was wiped to template.)"""

    DOCS = ("docs/STATUS.md", "docs/ARCHITECTURE.md", "docs/UAT_PLAN.md")

    def test_update_pipeline_keeps_living_docs_but_refreshes_hooks(self):
        root = make_temp_dir(self)
        rs.copy_pipeline(root, rs.Report(False), update=False)
        for rel in self.DOCS:
            (root / rel).write_text("# living content\n", encoding="utf-8")
        (root / ".claude/hooks/stop-gate.sh").write_text("# stale hook\n", encoding="utf-8")
        rs.copy_pipeline(root, rs.Report(False), update=True)
        for rel in self.DOCS:
            self.assertEqual((root / rel).read_text(encoding="utf-8"), "# living content\n", rel)
        self.assertNotEqual((root / ".claude/hooks/stop-gate.sh").read_text(encoding="utf-8"),
                            "# stale hook\n", "shipped hooks must still refresh")


if __name__ == "__main__":
    unittest.main()
