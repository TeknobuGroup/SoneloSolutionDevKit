"""Regression tests for the code-review findings on the UAT Hub wiring (kit v4.6).

Each case reproduces a defect the review found in v4.5/4.6 before it reached a repo. They are here
rather than in the feature tests because each one is a specific way the kit destroyed or silently
discarded something a repo owned.

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

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-regr-fake-home-")
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


def make_temp_dir(testcase, prefix="repo-setup-regr-test-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


class UnreadableMcpJsonIsNeverOverwritten(unittest.TestCase):
    """`read()` returns None for UnicodeDecodeError as well as for a missing file, so a `.mcp.json`
    that could not be decoded took the *create* branch: other servers replaced, no backup, reported
    as `created`. A UTF-16 file - what PowerShell 5.1 redirection produces on Windows - hit this
    exactly, on a kit whose first-class platform is Windows."""

    def test_utf16_file_survives(self):
        root = make_temp_dir(self)
        original = json.dumps({"mcpServers": {"postgres": {"command": "pg-mcp"}}})
        (root / ".mcp.json").write_bytes(original.encode("utf-16"))
        rep = rs.Report(False)
        rs.mcp_json(root, rep, "fortex-hub")
        self.assertEqual((root / ".mcp.json").read_bytes(), original.encode("utf-16"),
                         "a file the kit cannot decode must be left byte-identical")
        self.assertTrue(any("skipped" in str(a) for a, _ in rep.rows), rep.rows)

    def test_a_bom_is_not_a_broken_file(self):
        """utf-8-sig: a BOM-prefixed file is valid JSON, and reporting it as unparseable sent the
        operator looking for a syntax error that was not there."""
        root = make_temp_dir(self)
        (root / ".mcp.json").write_bytes(
            b"\xef\xbb\xbf" + json.dumps({"mcpServers": {"theirs": {"command": "x"}}}).encode("utf-8"))
        rs.mcp_json(root, rs.Report(False), "fortex-hub")
        data = json.loads((root / ".mcp.json").read_text(encoding="utf-8-sig"))
        self.assertIn("theirs", data["mcpServers"])
        self.assertIn(rs.UAT_MCP_NAME, data["mcpServers"])

    def test_a_redirected_server_path_self_heals(self):
        """Round 1 preserved a hand-edited `args` to stop the file churning between developers.
        The security re-review showed that turned an args hijack into a persistent one: `node` runs
        whatever that path names at session start, with UAT_HUB_KEY in its environment, and
        `mcp_ok` then reported the repo as standards-complete. Churn is the lesser problem, so the
        canonical path is rewritten every run and any tampering self-heals."""
        root = make_temp_dir(self)
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": {rs.UAT_MCP_NAME: {
            "command": "node", "args": ["./tools/evil.mcp/server.mjs"], "env": {}}}}),
            encoding="utf-8")
        rs.mcp_json(root, rs.Report(False), "fortex-hub")
        data = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(data["mcpServers"][rs.UAT_MCP_NAME]["args"],
                         [rs.UAT_HUB_SERVER_REF], "a redirected launch target must not survive")


class SpliceSurvivesDamagedMarkers(unittest.TestCase):
    """With `end` present before `start` - a botched merge, a hand-trimmed section - the splice
    re-emitted everything between them, so CLAUDE.md doubled on every run (435 bytes -> 8.8 KB ->
    16.3 KB) and duplicated the repo's own prose with it."""

    def test_orphaned_end_marker_does_not_grow_the_file(self):
        start, end = "<!-- x:start", "<!-- x:end -->"
        text = "KEEP ME\n\n%s\nstale\n" % end          # end without start
        sizes = []
        for _ in range(3):
            text = rs.splice(text, start, end, start + " -->\nfresh\n" + end)
            sizes.append(len(text))
        self.assertEqual(text.count(start), 1, text)
        self.assertEqual(sizes[1], sizes[2], "the file must stop growing: %s" % sizes)
        self.assertIn("KEEP ME", text)

    def test_crossed_markers_do_not_duplicate_the_repos_prose(self):
        start, end = "<!-- x:start", "<!-- x:end -->"
        text = "%s\nold\n%s -->\nKEEP ME\n" % (end, start)   # end before start
        first = rs.splice(text, start, end, start + " -->\nfresh\n" + end)
        second = rs.splice(first, start, end, start + " -->\nfresh\n" + end)
        self.assertEqual(len(first), len(second), "idempotent on damaged markers")
        self.assertEqual(second.count("KEEP ME"), 1)


class RefreshRecordsTheSlugWithoutAConfigFile(unittest.TestCase):
    """`if isinstance(cfg, dict) and cfg and (...)` short-circuited on an empty or absent
    `.teknobu.json`, so `refresh --uat-project` wired .mcp.json and CLAUDE.md to the slug, recorded
    nothing, said nothing, and the next plain refresh reverted both to the folder name - the exact
    regression the flag was added to prevent. The feature tests all seeded a config file."""

    def args(self, root, **kw):
        import argparse
        kw.setdefault("dry_run", False)
        kw.setdefault("uat_project", None)
        return argparse.Namespace(repo=str(root), **kw)

    def make_repo(self, seed_config):
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
        subprocess.run([git, "init", str(root)], capture_output=True, env=env, check=True, **rs.NOWIN)
        if seed_config is not None:
            (root / ".teknobu.json").write_text(json.dumps(seed_config), encoding="utf-8")
        return root

    def slug_in_mcp(self, root):
        data = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        return data["mcpServers"][rs.UAT_MCP_NAME]["env"]["UAT_HUB_PROJECT"]

    def test_no_config_file_at_all(self):
        root = self.make_repo(None)
        rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        rs.cmd_refresh(self.args(root))
        self.assertEqual(self.slug_in_mcp(root), "fortex-hub")

    def test_empty_config_file(self):
        root = self.make_repo({})
        rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        rs.cmd_refresh(self.args(root))
        self.assertEqual(self.slug_in_mcp(root), "fortex-hub")

    def test_still_no_key_when_none_was_asked_for(self):
        root = self.make_repo({"kit": "4.5", "work_branch": "prelive"})
        rs.cmd_refresh(self.args(root))
        cfg = json.loads((root / ".teknobu.json").read_text(encoding="utf-8"))
        self.assertNotIn("uat_project", cfg)


class RepoSetupCommandUsesTheFlagItAsksFor(unittest.TestCase):
    def test_the_refresh_path_carries_the_slug(self):
        """Question 5 collects the slug; the existing-repo path recommends `refresh`. Naming refresh
        without the flag threw the answer away on exactly the repos refresh is recommended for."""
        self.assertIn("repo_setup.py refresh --uat-project <slug>", rs.COMMAND_MD)


class UnreadableTeknobuJsonIsNeverReplaced(unittest.TestCase):
    """The fix for "refresh discards the slug with no .teknobu.json" reintroduced the .mcp.json bug
    one file over: read_json returns {} for unparseable and absent alike, so refresh --uat-project
    rewrote a config it could not read, losing work_branch, protected and stack with no backup and
    no message. use_repo_config reads that file, so the next apply would regenerate hooks and CI
    against this machine's work branch instead of the repo's."""

    def args(self, root, **kw):
        import argparse
        kw.setdefault("dry_run", False)
        kw.setdefault("uat_project", None)
        return argparse.Namespace(repo=str(root), **kw)

    def make_repo(self, raw):
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
        subprocess.run([git, "init", str(root)], capture_output=True, env=env, check=True, **rs.NOWIN)
        (root / ".teknobu.json").write_bytes(raw)
        return root

    def test_a_config_with_a_syntax_error_stops_the_command(self):
        raw = b'{"kit":"4.5","work_branch":"prelive","protected":["main"],}'
        root = self.make_repo(raw)
        with self.assertRaises(SystemExit):
            rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        self.assertEqual((root / ".teknobu.json").read_bytes(), raw)
        self.assertFalse((root / ".mcp.json").exists(), "nothing may be written on the way out")

    def test_a_utf16_config_stops_the_command(self):
        raw = json.dumps({"kit": "4.5", "work_branch": "prelive"}).encode("utf-16")
        root = self.make_repo(raw)
        with self.assertRaises(SystemExit):
            rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        self.assertEqual((root / ".teknobu.json").read_bytes(), raw)

    def test_the_message_says_what_to_do(self):
        """Stopping is only better than guessing if the operator knows why and what fixes it."""
        root = self.make_repo(b'{"broken",}')
        with self.assertRaises(SystemExit) as e:
            rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        msg = str(e.exception)
        self.assertIn(".teknobu.json", msg)
        self.assertIn("not readable JSON", msg)
        self.assertIn("Fix the file", msg)


class AnInvalidSlugFailsBeforeAnythingIsWritten(unittest.TestCase):
    """refresh --uat-project 'Bad Slug' used to replace the whole pipeline - 34 files - and then
    exit on the slug, printing neither its summary nor where the backups went."""

    def test_argparse_rejects_it(self):
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--uat-project", type=rs.slug_arg)
        with self.assertRaises(SystemExit):
            ap.parse_args(["--uat-project", "Bad Slug"])
        self.assertEqual(ap.parse_args(["--uat-project", "fortex-hub"]).uat_project, "fortex-hub")


class ApplyAlsoLeavesAnUnreadableConfigAlone(unittest.TestCase):
    """The guard went into cmd_refresh and not cmd_apply, so fixing one of two writers fixed
    nothing on the heavier command. An unreadable .teknobu.json was replaced with this machine's
    defaults - work_branch, protected, generated_types and any key of the repo's own, gone, no
    backup, report row reading "updated" - and use_repo_config reads the same file the same way, so
    the branch model silently became this machine's and was then written out as fact. A protected
    branch quietly stops being protected by the generated pre-push hook."""

    RAW = (b'{"kit":"4.5","work_branch":"prelive","protected":["main","release"],'
           b'"generated_types":"src/db.ts","vercel_project":"mine",}')   # one trailing comma

    def make_repo(self, raw):
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
        subprocess.run([git, "init", str(root)], capture_output=True, env=env, check=True, **rs.NOWIN)
        (root / ".teknobu.json").write_bytes(raw)
        return root

    def args(self, root, dry_run=False):
        import argparse
        return argparse.Namespace(repo=str(root), dry_run=dry_run, force=False,
                                  update_pipeline=False, uat_project=None)

    def test_apply_stops_and_writes_nothing(self):
        """The narrow guard saved .teknobu.json but WORK_BRANCH and PROTECTED had already fallen
        back to this machine's, and apply then regenerated pre-push, ci.yml and the environment doc
        from them - so a repo protecting `production` quietly stopped protecting it. The guard moved
        one file along rather than closing."""
        root = self.make_repo(self.RAW)
        with self.assertRaises(SystemExit):
            rs.cmd_apply(self.args(root))
        self.assertEqual((root / ".teknobu.json").read_bytes(), self.RAW)
        for rel in (".githooks/pre-push", ".github/workflows/ci.yml", "PRELIVE.md", ".mcp.json"):
            self.assertFalse((root / rel).exists(), rel)

    def test_apply_dry_run_stops_too(self):
        root = self.make_repo(self.RAW)
        with self.assertRaises(SystemExit):
            rs.cmd_apply(self.args(root, dry_run=True))
        self.assertEqual((root / ".teknobu.json").read_bytes(), self.RAW)

    def test_use_repo_config_says_so_rather_than_substituting_in_silence(self):
        """Falling back to this machine's branch model is survivable; doing it without saying so is
        how a repo's protected branches stop being protected with nobody told."""
        root = self.make_repo(self.RAW)
        lines = []
        self.addCleanup(setattr, rs, "say", rs.say)
        rs.say = lambda msg="": lines.append(str(msg))
        rs.use_repo_config(root)
        out = "\n".join(lines)
        self.assertIn("cannot be parsed", out)
        self.assertIn(".teknobu.json", out)

    def test_a_readable_config_is_still_honoured(self):
        root = self.make_repo(json.dumps({"kit": "4.5", "work_branch": "prelive",
                                          "protected": ["main", "release"]}).encode())
        rs.use_repo_config(root)
        self.assertEqual(rs.WORK_BRANCH, "prelive")
        self.assertEqual(rs.PROTECTED, ["main", "release"])


class ProtectedIsValidatedBeforeItReachesGeneratedShell(unittest.TestCase):
    """`work_branch` was regex-filtered in kit 4.1 with the comment "option-shaped values from a
    cloned repo's config never reach git argv". `protected` sat on the next line, unfiltered, and
    lands inside double quotes in .githooks/pre-push and inside a YAML list in ci.yml - so `apply`
    on a cloned repo executed whatever was in it, on every push."""

    def setUp(self):
        self.saved = list(rs.PROTECTED)
        self.addCleanup(setattr, rs, "PROTECTED", self.saved)

    def config(self, value):
        root = make_temp_dir(self)
        (root / ".teknobu.json").write_text(json.dumps({"protected": value}), encoding="utf-8")
        rs.use_repo_config(root)
        return rs.PROTECTED

    def test_an_injected_entry_is_dropped(self):
        got = self.config(['main"; touch /tmp/PWNED; echo owned; #', "release"])
        self.assertEqual(got, ["release"])

    def test_a_string_is_not_exploded_into_characters(self):
        self.assertEqual(self.config("main"), ["main"])

    def test_ordinary_branch_names_survive(self):
        self.assertEqual(self.config(["main", "production", "release/2024"]),
                         ["main", "production", "release/2024"])

    def test_an_all_bad_list_leaves_the_default_alone(self):
        self.assertEqual(self.config(["; rm -rf /"]), self.saved)


if __name__ == "__main__":
    unittest.main()
