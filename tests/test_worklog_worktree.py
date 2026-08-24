"""Failing-test-first reproduction: install_git_hook breaks in a linked git worktree.

The bug: worklog_agent.install_git_hook(root) builds the hook path as
root/".git"/"hooks"/"post-commit".  In a linked worktree, <worktree>/.git is a
FILE (a "gitdir: ..." pointer), not a directory, so the write raises an OSError
(NotADirectoryError on POSIX, FileNotFoundError on Windows) instead of
installing the hook — which kills `worklog install` in any worktree.

The real hooks directory is what `git -C <worktree> rev-parse --git-path hooks`
resolves to; in a linked worktree that lives under the parent repository's
.git directory.  The reproducing test asserts the hook lands there without
raising; the companion test guards the ordinary main-repo path against
regressing when the fix goes in.

Stdlib only; hermetic: every repository lives in a per-test temp dir, and all
git invocations ignore the user's global/system config (GIT_CONFIG_GLOBAL /
GIT_CONFIG_SYSTEM point at os.devnull) so settings such as core.hooksPath or
init.templateDir cannot leak in.  Both tests skip if git is not on PATH.
Run from the repo root with:  python -m unittest discover -s tests
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worklog_agent as wa

GIT = shutil.which("git")


def make_temp_dir(testcase, prefix="worklog-worktree-test-"):
    """A per-test temp dir, removed on cleanup; nothing outside it is touched."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def run_git(*args):
    """Run git with the user's global/system config neutralised; return stdout."""
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1")
    proc = subprocess.run([GIT] + list(args), capture_output=True, text=True,
                          env=env, check=True, **wa.NOWIN)
    return proc.stdout


def make_repo(testcase):
    """git init a repo in a per-test temp dir with one commit; return (base, repo)."""
    base = make_temp_dir(testcase)
    repo = base / "repo"
    run_git("init", str(repo))
    run_git("-C", str(repo), "config", "user.name", "Worklog Test")
    run_git("-C", str(repo), "config", "user.email", "worklog-test@example.invalid")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    run_git("-C", str(repo), "add", "seed.txt")
    run_git("-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-m", "seed commit")
    return base, repo


def add_worktree(base, repo):
    """A linked worktree beside the repo; its .git entry is a pointer FILE."""
    worktree = base / "wt"
    run_git("-C", str(repo), "worktree", "add", str(worktree), "-b", "t-branch")
    return worktree


def real_hooks_dir(worktree):
    """Where git actually looks for hooks, as git itself resolves it.
    The output can be relative to the worktree, so anchor and resolve it."""
    out = run_git("-C", str(worktree), "rev-parse", "--git-path", "hooks").strip()
    p = Path(out)
    if not p.is_absolute():
        p = Path(worktree) / p
    return p.resolve()


@unittest.skipUnless(GIT, "git is not on PATH")
class InstallGitHookInWorktree(unittest.TestCase):
    """install_git_hook must work from a linked worktree, where .git is a file."""

    def test_install_in_linked_worktree_puts_hook_in_real_hooks_dir(self):
        base, repo = make_repo(self)
        worktree = add_worktree(base, repo)
        self.assertTrue((worktree / ".git").is_file(),
                        "precondition: a linked worktree's .git entry is a pointer file")
        try:
            wa.install_git_hook(worktree)
        except OSError as exc:
            self.fail("install_git_hook raised %r in a linked worktree: it builds "
                      "root/.git/hooks, but <worktree>/.git is a file, not a directory"
                      % (exc,))
        hooks = real_hooks_dir(worktree)
        self.assertTrue((hooks / "post-commit").is_file(),
                        "post-commit hook was not installed in the repository's real "
                        "hooks directory (%s)" % hooks)


@unittest.skipUnless(GIT, "git is not on PATH")
class InstallGitHookInMainRepo(unittest.TestCase):
    """The ordinary main-repo path must keep working once the worktree fix goes in."""

    def test_install_in_main_repo_writes_post_commit_under_dot_git_hooks(self):
        _base, repo = make_repo(self)
        wa.install_git_hook(repo)
        self.assertTrue((repo / ".git" / "hooks" / "post-commit").is_file(),
                        "post-commit hook was not installed in <repo>/.git/hooks")


if __name__ == "__main__":
    unittest.main()
