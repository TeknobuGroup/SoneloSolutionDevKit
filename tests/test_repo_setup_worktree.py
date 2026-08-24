"""Tests for the repo_setup.py worktree feature: wt_dirname, wt_list, wt_state, cmd_worktree.

Import safety: importing repo_setup executes module-level configuration loading —
`CONFIG = load_config()` reads ~/.claude/sonelo/config.json (falling back to
~/.claude/teknobu/config.json) and derives WORK_BRANCH / PROTECTED from it.  That
code is read-only and wrapped in try/except, so the import itself cannot write or
spawn anything, but the developer machine's kit config would leak into the module
globals.  The paths are built with Path.expanduser() at import time, so this file
points HOME and USERPROFILE (Python 3.8+ on Windows resolves ~ via USERPROFILE,
not HOME) at an empty temp dir BEFORE the import, then restores them immediately
after — the functions under test never call expanduser again at run time.

wt_state and cmd_worktree read the module-global WORK_BRANCH; each test that needs
it sets repo_setup.WORK_BRANCH explicitly and restores it with addCleanup.

Stdlib only; hermetic: every repository lives in a per-test temp dir, and all git
invocations — both the tests' own and repo_setup's internal sh() calls — ignore the
user's global/system config (GIT_CONFIG_GLOBAL / GIT_CONFIG_SYSTEM point at
os.devnull; set in os.environ per test because sh() inherits the process env).
Git-backed tests skip if git is not on PATH.
Run from the repo root with:  python -m unittest discover -s tests
"""

import argparse
import atexit
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-worktree-fake-home-")
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

GIT = shutil.which("git")


def make_temp_dir(testcase, prefix="repo-setup-worktree-test-"):
    """A per-test temp dir, removed on cleanup; nothing outside it is touched."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def run_git(*args):
    """Run git with the user's global/system config neutralised; return stdout."""
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1")
    proc = subprocess.run([GIT] + [str(a) for a in args], capture_output=True, text=True,
                          env=env, check=True, **rs.NOWIN)
    return proc.stdout


def make_repo(testcase):
    """git init a repo on branch `work` with one commit; return (base, repo)."""
    base = make_temp_dir(testcase)
    repo = base / "repo"
    run_git("init", repo)
    run_git("-C", repo, "checkout", "-b", "work")
    run_git("-C", repo, "config", "user.name", "Repo Setup Test")
    run_git("-C", repo, "config", "user.email", "repo-setup-test@example.invalid")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    run_git("-C", repo, "add", "seed.txt")
    run_git("-C", repo, "-c", "commit.gpgsign=false", "commit", "-m", "seed commit")
    return base, repo


def set_work_branch(testcase, name):
    """Point the module-global WORK_BRANCH at `name`; restore the old value on cleanup."""
    testcase.addCleanup(setattr, rs, "WORK_BRANCH", rs.WORK_BRANCH)
    rs.WORK_BRANCH = name


def commit_in(worktree, filename, message):
    """Stage and commit one new file inside a worktree (repo config supplies the identity)."""
    (Path(worktree) / filename).write_text("content\n", encoding="utf-8")
    run_git("-C", worktree, "add", filename)
    run_git("-C", worktree, "-c", "commit.gpgsign=false", "commit", "-m", message)


def by_path(items, path):
    """The wt_list entry whose path resolves to `path`."""
    want = Path(path).resolve()
    for it in items:
        if Path(it["path"]).resolve() == want:
            return it
    raise AssertionError("no worktree entry for %s in %r" % (want, items))


class GitCase(unittest.TestCase):
    """Neutralise git's global/system config in os.environ, because repo_setup.sh()
    runs git with the inherited process environment."""

    def setUp(self):
        for k, v in (("GIT_CONFIG_GLOBAL", os.devnull), ("GIT_CONFIG_SYSTEM", os.devnull),
                     ("GIT_CONFIG_NOSYSTEM", "1")):
            prev = os.environ.get(k)
            os.environ[k] = v
            self.addCleanup(self._put_env, k, prev)

    @staticmethod
    def _put_env(key, value):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class WtDirname(unittest.TestCase):
    """Folder name for a worktree: <repo>-wt-<branch>, sanitised."""

    def test_simple_branch_becomes_repo_wt_branch(self):
        self.assertEqual(rs.wt_dirname("shop", "fix-nav"), "shop-wt-fix-nav")

    def test_slashes_in_the_branch_become_dashes(self):
        self.assertEqual(rs.wt_dirname("r", "feature/x"), "r-wt-feature-x")

    def test_runs_of_weird_characters_collapse_to_one_dash(self):
        self.assertEqual(rs.wt_dirname("r", "fix it!!now"), "r-wt-fix-it-now")

    def test_leading_and_trailing_dots_and_dashes_are_stripped(self):
        self.assertEqual(rs.wt_dirname("r", "-.-release-.-"), "r-wt-release")

    def test_empty_branch_falls_back_to_the_word_branch(self):
        self.assertEqual(rs.wt_dirname("r", ""), "r-wt-branch")

    def test_branch_of_only_junk_characters_falls_back_to_the_word_branch(self):
        self.assertEqual(rs.wt_dirname("r", "///"), "r-wt-branch")


@unittest.skipUnless(GIT, "git is not on PATH")
class WtList(GitCase):
    """wt_list parses `git worktree list --porcelain` into [{path, branch, main}]."""

    def test_main_worktree_is_listed_first_and_flagged_main(self):
        base, repo = make_repo(self)
        run_git("-C", repo, "worktree", "add", "-b", "side", base / "side-wt")
        items = rs.wt_list(repo)
        self.assertTrue(items[0]["main"], "git lists the main worktree first; it must carry main=True")
        self.assertEqual(Path(items[0]["path"]).resolve(), repo.resolve())
        self.assertEqual(items[0].get("branch"), "work")
        self.assertFalse(any(it["main"] for it in items[1:]),
                         "only the first (main) worktree may be flagged main")

    def test_added_worktree_reports_its_branch_and_a_path_with_a_space_parses(self):
        base, repo = make_repo(self)
        spaced = base / "wt with space"
        run_git("-C", repo, "worktree", "add", "-b", "side", spaced)
        entry = by_path(rs.wt_list(repo), spaced)
        self.assertEqual(entry.get("branch"), "side")
        self.assertFalse(entry["main"])

    def test_detached_worktree_has_branch_none(self):
        base, repo = make_repo(self)
        detached = base / "wt-detached"
        run_git("-C", repo, "worktree", "add", "--detach", detached)
        entry = by_path(rs.wt_list(repo), detached)
        self.assertIsNone(entry.get("branch"))


@unittest.skipUnless(GIT, "git is not on PATH")
class WtState(GitCase):
    """wt_state reports (dirty, merged-into-WORK_BRANCH) for one worktree."""

    def _repo_with_side_worktree(self):
        base, repo = make_repo(self)
        set_work_branch(self, "work")
        side = base / "side-wt"
        run_git("-C", repo, "worktree", "add", "-b", "side", side)
        return repo, side

    def test_an_untracked_file_marks_the_worktree_dirty(self):
        repo, side = self._repo_with_side_worktree()
        (side / "scratch.txt").write_text("wip\n", encoding="utf-8")
        dirty, _merged = rs.wt_state(repo, {"path": str(side), "branch": "side", "main": False})
        self.assertTrue(dirty)

    def test_a_clean_worktree_is_not_dirty(self):
        repo, side = self._repo_with_side_worktree()
        dirty, _merged = rs.wt_state(repo, {"path": str(side), "branch": "side", "main": False})
        self.assertFalse(dirty)

    def test_a_branch_at_the_work_branch_tip_reads_merged(self):
        repo, side = self._repo_with_side_worktree()
        _dirty, merged = rs.wt_state(repo, {"path": str(side), "branch": "side", "main": False})
        self.assertTrue(merged, "a branch pointing at (or under) the work branch tip is merged")

    def test_a_branch_with_an_extra_commit_reads_unmerged(self):
        repo, side = self._repo_with_side_worktree()
        commit_in(side, "extra.txt", "extra commit on side")
        _dirty, merged = rs.wt_state(repo, {"path": str(side), "branch": "side", "main": False})
        self.assertFalse(merged)

    def test_a_missing_work_branch_ref_reads_unmerged_without_raising(self):
        repo, side = self._repo_with_side_worktree()
        set_work_branch(self, "no-such-branch")
        _dirty, merged = rs.wt_state(repo, {"path": str(side), "branch": "side", "main": False})
        self.assertFalse(merged)

    def test_a_tag_named_like_the_branch_at_the_work_tip_does_not_make_it_read_merged(self):
        """Regression: wt_state used to pass unqualified names to
        `git merge-base --is-ancestor`; git resolves refs/tags/ before refs/heads/,
        so a TAG `feat` at the work branch's tip shadowed the unmerged branch `feat`,
        it read as merged, and `worktree clean` deleted the worktree.  The refs must
        be qualified as refs/heads/ so the branch, not the tag, is consulted."""
        base, repo = make_repo(self)
        set_work_branch(self, "work")
        side = base / "feat-wt"
        run_git("-C", repo, "worktree", "add", side, "-b", "feat")
        commit_in(side, "ahead.txt", "commit that puts feat ahead of work")
        run_git("-C", repo, "tag", "feat", "work")
        _dirty, merged = rs.wt_state(repo, {"path": str(side), "branch": "feat", "main": False})
        self.assertFalse(merged,
                         "branch feat is one commit ahead of work; the tag feat at work's tip "
                         "must not shadow it in the merged check")


@unittest.skipUnless(GIT, "git is not on PATH")
class CmdWorktreeNew(GitCase):
    """cmd_worktree new <branch>: sibling dir, branch checked out, worklog stamped."""

    def _run_new(self, repo, branch):
        ns = argparse.Namespace(verb="new", branch=branch, repo=str(repo))
        with redirect_stdout(io.StringIO()):
            rs.cmd_worktree(ns)
        return repo.parent / rs.wt_dirname(repo.name, branch)

    def test_new_creates_the_sibling_directory(self):
        _base, repo = make_repo(self)
        set_work_branch(self, "work")
        dest = self._run_new(repo, "topic")
        self.assertTrue(dest.is_dir(), "expected the worktree at %s" % dest)

    def test_new_checks_out_the_requested_branch_in_the_worktree(self):
        _base, repo = make_repo(self)
        set_work_branch(self, "work")
        dest = self._run_new(repo, "topic")
        head = run_git("-C", dest, "rev-parse", "--abbrev-ref", "HEAD").strip()
        self.assertEqual(head, "topic")

    def test_new_stamps_the_worklog_project_with_the_repo_name_by_default(self):
        _base, repo = make_repo(self)
        set_work_branch(self, "work")
        dest = self._run_new(repo, "topic")
        stamp = json.loads((dest / ".worklog" / "worklog.json").read_text(encoding="utf-8"))
        self.assertEqual(stamp, {"project": repo.name})

    def test_new_carries_over_the_parent_repos_configured_project_name(self):
        _base, repo = make_repo(self)
        set_work_branch(self, "work")
        (repo / ".worklog").mkdir()
        (repo / ".worklog" / "worklog.json").write_text(
            json.dumps({"project": "Sonelo Solution"}), encoding="utf-8")
        dest = self._run_new(repo, "topic")
        stamp = json.loads((dest / ".worklog" / "worklog.json").read_text(encoding="utf-8"))
        self.assertEqual(stamp.get("project"), "Sonelo Solution")

    def test_new_twice_exits_because_the_destination_already_exists(self):
        _base, repo = make_repo(self)
        set_work_branch(self, "work")
        self._run_new(repo, "topic")
        with self.assertRaises(SystemExit) as cm:
            self._run_new(repo, "topic")
        self.assertIn("already exists", str(cm.exception.code))


@unittest.skipUnless(GIT, "git is not on PATH")
class CmdWorktreeClean(GitCase):
    """cmd_worktree clean: removes merged+clean worktrees, keeps dirty ones."""

    def test_clean_removes_the_merged_clean_worktree_and_keeps_the_dirty_one(self):
        base, repo = make_repo(self)
        set_work_branch(self, "work")
        merged_dir = base / "repo-wt-merged"
        run_git("-C", repo, "worktree", "add", "-b", "merged-side", merged_dir)
        dirty_dir = base / "repo-wt-dirty"
        run_git("-C", repo, "worktree", "add", "-b", "dirty-side", dirty_dir)
        (dirty_dir / "scratch.txt").write_text("wip\n", encoding="utf-8")
        ns = argparse.Namespace(verb="clean", branch=None, repo=str(repo))
        with redirect_stdout(io.StringIO()):
            rs.cmd_worktree(ns)
        self.assertFalse(merged_dir.exists(),
                         "a clean worktree whose branch is merged into the work branch must be removed")
        self.assertTrue(dirty_dir.exists(),
                        "a worktree with uncommitted changes must be kept")


if __name__ == "__main__":
    unittest.main()
