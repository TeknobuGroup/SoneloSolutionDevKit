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
import subprocess
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

class AgentModelsDeclared(unittest.TestCase):
    """v4.3: every shipped agent declares the model it runs on, so a reviewer does not
    silently inherit the session's Opus. The three that gate correctness deliberately
    declare nothing and inherit - pinned here so nobody "tidies" them onto a cheap model."""

    SONNET = ("design-reviewer", "test-writer", "test-runner", "qa-runner", "Explore")
    HAIKU = ("changelog-scribe", "docs-maintainer", "uat-writer", "uat-plan-maintainer")
    INHERITS = ("code-reviewer", "security-reviewer", "impact-analyst")

    def body(self, name):
        rel = ".claude/agents/%s.md" % name
        self.assertIn(rel, rs.BUILTIN_PIPELINE, "%s must ship from BUILTIN_PIPELINE" % name)
        return rs.BUILTIN_PIPELINE[rel]

    def test_sonnet_agents(self):
        for name in self.SONNET:
            self.assertIn("\nmodel: sonnet\n", self.body(name), name)

    def test_haiku_agents(self):
        for name in self.HAIKU:
            self.assertIn("\nmodel: haiku\n", self.body(name), name)

    def test_gating_agents_inherit(self):
        for name in self.INHERITS:
            self.assertNotIn("\nmodel:", self.body(name),
                             "%s gates correctness and must inherit the session model" % name)


class DesignReviewerRefreshes(unittest.TestCase):
    """design-reviewer used to be carved out of the refresh path (design_files kept the body and
    rewrote only a hardcoded `tools:` line), so kit-wide frontmatter changes never reached a repo
    that already had the file. It now ships from BUILTIN_PIPELINE like every other agent."""

    REL = ".claude/agents/design-reviewer.md"

    def test_frontmatter_change_reaches_an_existing_repo(self):
        root = make_temp_dir(self)
        rs.copy_pipeline(root, rs.Report(False), update=False)
        agent = root / self.REL
        self.assertTrue(agent.exists(), "design-reviewer must ship on a plain apply")
        agent.write_text(agent.read_text(encoding="utf-8").replace("\nmodel: sonnet\n", "\n"),
                         encoding="utf-8")
        rs.copy_pipeline(root, rs.Report(False), update=True)
        self.assertIn("\nmodel: sonnet\n", agent.read_text(encoding="utf-8"),
                      "--update-pipeline must restore the kit's design-reviewer frontmatter")

    def test_design_contract_is_not_overwritten(self):
        """The per-repo brand file stays the repo's own - the real reason for the old carve-out.
        design_files() is the function that decides, so it is the one under test."""
        root = make_temp_dir(self)
        rules = root / ".claude" / "rules" / "design.md"
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text("# our brand\n", encoding="utf-8")
        rs.design_files(root, {}, rs.Report(False), update=True)
        self.assertEqual(rules.read_text(encoding="utf-8"), "# our brand\n")
        self.assertNotIn(".claude/rules/design.md", rs.BUILTIN_PIPELINE,
                         "the brand contract must never be a refreshable kit file")


class RefreshIsNarrow(unittest.TestCase):
    """`refresh` exists so a repo can take the current agents/commands/hooks without the rest of
    `apply`. Anything it touches beyond the pipeline is a bug."""

    def args(self, root, dry_run=False):
        import argparse
        return argparse.Namespace(repo=str(root), dry_run=dry_run)

    def make_repo(self):
        """cmd_refresh resolves its root through git, so the fixture has to be a real repo.

        ensure_installed() and use_repo_config() are neutralised: a unit test must not install
        the kit onto the machine running it, and use_repo_config mutates module globals that
        would otherwise leak into every later test in the process."""
        git = shutil.which("git")
        if not git:
            self.skipTest("git not on PATH")
        self.addCleanup(setattr, rs, "ensure_installed", rs.ensure_installed)
        rs.ensure_installed = lambda: False
        self.addCleanup(setattr, rs, "WORK_BRANCH", rs.WORK_BRANCH)
        self.addCleanup(setattr, rs, "PROTECTED", list(rs.PROTECTED))
        root = make_temp_dir(self)
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                   GIT_CONFIG_NOSYSTEM="1")
        subprocess.run([git, "init", str(root)], capture_output=True, text=True, env=env,
                       check=True, **rs.NOWIN)
        return root

    def test_leaves_non_pipeline_files_alone(self):
        root = self.make_repo()
        rs.copy_pipeline(root, rs.Report(False), update=False)
        untouched = {
            ".githooks/checks": "# my own checks\n",
            ".github/workflows/ci.yml": "# my ci\n",          # ci-gates.yml IS refreshed; this is not
            ".env.example": "MY_VAR=\n",
            rs.env_doc(): "# mine\n",                          # PRELIVE.md or STAGING.md per config
            ".claude/rules/design.md": "# our brand\n",
        }
        for rel, text in untouched.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        (root / ".claude" / "hooks" / "stop-gate.sh").write_text("# stale\n", encoding="utf-8")
        rs.cmd_refresh(self.args(root))
        for rel, text in untouched.items():
            self.assertEqual((root / rel).read_text(encoding="utf-8"), text, rel)
        self.assertNotEqual((root / ".claude" / "hooks" / "stop-gate.sh").read_text(encoding="utf-8"),
                            "# stale\n", "the pipeline itself must refresh")

    def test_replaced_files_are_backed_up_and_the_backup_is_ignored(self):
        """A refresh overwrites kit-owned files, including a GitHub workflow. Every replacement
        must leave a copy, and the copies must not appear as untracked work in the repo - refresh
        does not touch .gitignore, so a repo set up before v4.3 has no line for them."""
        root = self.make_repo()
        rs.copy_pipeline(root, rs.Report(False), update=False)
        agent = root / ".claude" / "agents" / "code-reviewer.md"
        agent.write_text("# our own reviewer\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("# house policy, no markers\n", encoding="utf-8")
        rs.cmd_refresh(self.args(root))
        backups = sorted((root / ".claude" / ".backup").glob("*/"))
        self.assertTrue(backups, "a replacement must leave a backup")
        saved = {p.name for b in backups for p in b.iterdir()}
        self.assertIn("claude__agents__code-reviewer.md", saved)
        self.assertIn("CLAUDE.md", saved, "CLAUDE.md is rewritten in place and must be saved too")
        self.assertEqual((root / ".claude" / ".backup" / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_ci_gates_refresh_but_the_repos_own_workflow_does_not(self):
        """ci-gates.yml is the pipeline's half of .github and is meant to refresh; ci.yml is the
        repo's own and is not. The command's output claims exactly this, so it is pinned."""
        root = self.make_repo()
        rs.copy_pipeline(root, rs.Report(False), update=False)
        gates = root / ".github" / "workflows" / "ci-gates.yml"
        own = root / ".github" / "workflows" / "ci.yml"
        gates.write_text("# stale gates\n", encoding="utf-8")
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text("# my ci\n", encoding="utf-8")
        rs.cmd_refresh(self.args(root))
        self.assertNotEqual(gates.read_text(encoding="utf-8"), "# stale gates\n")
        self.assertEqual(own.read_text(encoding="utf-8"), "# my ci\n")

    def test_the_github_files_refresh_claims_are_the_only_ones(self):
        """cmd_refresh's Refreshed/Untouched summary names the two .github files in prose. Add a
        third BUILTIN_PIPELINE key under .github/ and that prose becomes the same class of false
        claim this release removed - so the set is pinned here rather than left to memory."""
        github = {rel for rel in rs.BUILTIN_PIPELINE if rel.startswith(".github/")}
        self.assertEqual(github, {".github/workflows/ci-gates.yml", ".github/pull_request_template.md"},
                         "refresh's output names these two by hand - update it before adding another")

    def test_apply_and_refresh_do_not_fight_over_the_same_file(self):
        """cmd_apply used to write its own pull_request_template.md while BUILTIN_PIPELINE held a
        different one, so apply and refresh replaced each other's copy on every run. A second
        producer for any pipeline path is the bug; this pins that there is only one."""
        self.assertFalse(hasattr(rs, "PR_TEMPLATE"),
                         "a second template for a BUILTIN_PIPELINE path is how the flip-flop started")
        root = self.make_repo()
        rs.copy_pipeline(root, rs.Report(False), update=False)
        rep = rs.Report(False)
        rs.copy_pipeline(root, rep, update=True)
        replaced = [w for a, w in rep.rows if str(a).startswith("replaced")]
        self.assertEqual(replaced, [], "a freshly written pipeline must have nothing to replace")

    def test_stops_on_a_teknobu_json_that_is_not_an_object(self):
        """Until v4.6 this ran to completion on a config it could not use. That is the same silent
        substitution as an unparseable one: a JSON list carries no branch model, so the generated
        pre-push hook and CI would be built from this machine's answers and written into the repo as
        if they were the repo's. The kit now stops and says so."""
        root = self.make_repo()
        (root / ".teknobu.json").write_text('["not", "an", "object"]\n', encoding="utf-8")
        with self.assertRaises(SystemExit):
            rs.cmd_refresh(self.args(root))
        self.assertFalse((root / ".claude" / "agents" / "code-reviewer.md").exists())

    def test_dry_run_writes_nothing(self):
        root = self.make_repo()

        def tree():   # .git churns on any git call; the question is what the kit writes
            return sorted(str(q.relative_to(root)) for q in root.rglob("*")
                          if ".git" not in q.relative_to(root).parts)

        before = tree()
        rs.cmd_refresh(self.args(root, dry_run=True))
        self.assertEqual(before, tree(), "--dry-run must not write")

    def test_marks_the_repo_as_current(self):
        """cmd_nudge compares .teknobu.json's kit against VERSION; a refreshed repo that does not
        record the new version nags every session and points back at the heavy command."""
        root = self.make_repo()
        (root / ".teknobu.json").write_text(
            json.dumps({"kit": "0.1", "work_branch": "prelive"}) + "\n", encoding="utf-8")
        rs.cmd_refresh(self.args(root))
        cfg = json.loads((root / ".teknobu.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["kit"], rs.VERSION)
        self.assertEqual(cfg["work_branch"], "prelive", "refresh must not rewrite the repo's own keys")



if __name__ == "__main__":
    unittest.main()
