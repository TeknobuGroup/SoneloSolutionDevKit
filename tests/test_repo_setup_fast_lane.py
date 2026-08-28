"""Tests for the kit 4.7 fast lane: scoped checks, design-only diffs, and spike branches.

The tiering in CLAUDE.md relieved the cheap parts of a change (plan mode, the impact report) and
left the expensive ones (a reviewer verdict, the whole test suite) in place, so a stylesheet paid
almost what a migration paid. These cover the three things that changed.

The rule every case here defends: **the fast lane may only skip work it is certain is irrelevant.**
Every defect found in the previous release was a silent skip - a control that stopped working while
still reporting success - so an unknown changed set must run everything, and an existing repo's
hand-written check must never be quietly dropped.

Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-fastlane-fake-home-")
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

ZERO = "0" * 40


def make_temp_dir(testcase, prefix="repo-setup-fastlane-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def tools(testcase):
    git, sh = shutil.which("git"), shutil.which("sh")
    if not git or not sh:
        testcase.skipTest("git and sh needed")
    return git, sh


def git_env():
    return dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                GIT_CONFIG_NOSYSTEM="1")


class PrePushRepo:
    """A scratch repo with the generated pre-push hook and a checks file, driven by feeding ref
    updates on stdin the way git does."""

    def __init__(self, testcase, checks):
        self.git, self.sh = tools(testcase)
        self.env = git_env()
        self.root = make_temp_dir(testcase)
        self._run([self.git, "init", "-b", "prelive", str(self.root)])
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Tester")
        (self.root / ".githooks").mkdir()
        (self.root / ".githooks" / "checks").write_text(checks, encoding="utf-8", newline="\n")
        (self.root / ".githooks" / "pre-push").write_text(
            rs.fill(rs.PRE_PUSH, PROTECTED="main", WORK="prelive"), encoding="utf-8", newline="\n")

    def _run(self, cmd, **kw):
        return subprocess.run(cmd, capture_output=True, text=True, env=self.env, **rs.NOWIN, **kw)

    def _git(self, *a):
        return self._run([self.git, "-C", str(self.root)] + list(a))

    def commit(self, rel, body):
        f = self.root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8", newline="\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "chore: " + rel)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def push(self, remote_sha):
        """Returns the hook's stdout. remote_sha=ZERO models a branch the remote has never seen."""
        head = self._git("rev-parse", "HEAD").stdout.strip()
        line = "refs/heads/prelive %s refs/heads/prelive %s\n" % (head, remote_sha)
        # bytes, not text: on Windows Python would translate the LF to CRLF, and git feeds a hook
        # LF-delimited lines. The hook strips CR anyway - a CR made every sha unresolvable, which
        # the fail-safe correctly turned into "run everything".
        out = subprocess.run([self.sh, ".githooks/pre-push"], cwd=str(self.root),
                             capture_output=True, env=self.env, input=line.encode(), **rs.NOWIN)
        return out.stdout.decode("utf-8", "replace") + out.stderr.decode("utf-8", "replace")

    def ran(self, remote_sha):
        """The markers the checks actually printed. The hook's own narration quotes the command it
        is about to run or skip, so a substring test against the whole transcript matches the
        narration as well as the execution - which is not the same question."""
        out = self.push(remote_sha)
        return [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("pre-push:")]


CHECKS = """echo RAN-always
[tests/*] echo RAN-suite
[src/* *.css] echo RAN-ui
"""


class ScopedChecksRunTheRightLines(unittest.TestCase):
    def test_a_stylesheet_does_not_pay_for_the_back_end_suite(self):
        r = PrePushRepo(self, CHECKS)
        base = r.commit("src/app.css", "body{}\n")
        r.commit("src/app.css", "body{color:red}\n")
        self.assertEqual(sorted(r.ran(base)), ["RAN-always", "RAN-ui"])

    def test_a_test_change_does_not_pay_for_the_ui_checks(self):
        r = PrePushRepo(self, CHECKS)
        base = r.commit("tests/t.py", "x\n")
        r.commit("tests/t.py", "y\n")
        self.assertEqual(sorted(r.ran(base)), ["RAN-always", "RAN-suite"])

    def test_it_says_what_it_skipped(self):
        """A silent skip is indistinguishable from a pass. It has to be on the transcript."""
        r = PrePushRepo(self, CHECKS)
        base = r.commit("tests/t.py", "x\n")
        r.commit("tests/t.py", "y\n")
        self.assertIn("skipped", r.push(base))

    def test_an_unknown_changed_set_runs_everything(self):
        """The invariant: it may only skip work it is CERTAIN is irrelevant. A branch the remote has
        never seen has no computable range here, so nothing may be skipped on that basis."""
        r = PrePushRepo(self, CHECKS)
        r.commit("docs/x.md", "d\n")
        self.assertEqual(sorted(r.ran(ZERO)), ["RAN-always", "RAN-suite", "RAN-ui"])


class ExistingChecksFilesAreNotMangled(unittest.TestCase):
    """Regression. `[ -f package.json ] && npm test` is one of the commonest lines in a checks file,
    and the prefix parser ate it: glob `-f package.json`, command `&& npm test`. The check was
    SILENTLY SKIPPED and the hook still reported success, so a repo that upgraded would quietly stop
    running its tests. POSIX `[` is a command, so a space always follows it; a glob list never has
    one - that is the disambiguation."""

    LEGACY = """[ -f package.json ] && echo RAN-conditional
[ -d nope ] || echo RAN-fallback
echo RAN-plain
[tests/*] echo RAN-scoped
"""

    def test_a_conditional_check_still_runs(self):
        r = PrePushRepo(self, self.LEGACY)
        base = r.commit("package.json", "{}\n")
        r.commit("tests/t.py", "x\n")
        self.assertEqual(sorted(r.ran(base)),
                         ["RAN-conditional", "RAN-fallback", "RAN-plain", "RAN-scoped"])

    def test_it_is_not_treated_as_a_glob_prefix(self):
        r = PrePushRepo(self, self.LEGACY)
        base = r.commit("package.json", "{}\n")
        r.commit("tests/t.py", "x\n")
        out = r.push(base)
        self.assertNotIn("nothing matching [ -f package.json ]", out,
                         "a test command must never be parsed as a path filter")

    def test_scoping_still_works_alongside_it(self):
        r = PrePushRepo(self, self.LEGACY)
        base = r.commit("package.json", "{}\n")
        r.commit("docs/x.md", "d\n")
        got = sorted(r.ran(base))
        self.assertIn("RAN-conditional", got)
        self.assertNotIn("RAN-scoped", got)

    def test_a_double_bracket_line_is_left_alone(self):
        r = PrePushRepo(self, "[[ -f package.json ]] && echo RAN-bashism\necho RAN-plain\n")
        base = r.commit("package.json", "{}\n")
        r.commit("tests/t.py", "x\n")
        out = r.push(base)
        self.assertNotIn("nothing matching", out)


class DesignLaneStillWakesCodeReviewer(unittest.TestCase):
    """4.7 briefly made a diff that was entirely design-lane yield `design` only, on the reasoning
    that CLAUDE.md forbids logic changes in the design lane. That reasoning is circular - the
    reviewer is what catches the rule being broken - and the measured consequences were bad:
    `useAuth.tsx`, `AuthProvider.tsx`, `supabaseAdmin.tsx` and a `tailwind.config.js` running
    `child_process.execSync` all classified as design-only, so code-reviewer never woke.

    Reverted. `.tsx` is application code, and file extension is the wrong axis to gate on. If the
    goal is to spare the reviewer trivial diffs, gate on the content of the diff instead."""

    def due(self, files):
        git, sh = tools(self)
        env = git_env()
        root = make_temp_dir(self)
        subprocess.run([git, "init", "-b", "prelive", str(root)], capture_output=True, env=env,
                       check=True, **rs.NOWIN)
        script = root.parent / ("ps-%s.sh" % root.name)   # outside the repo: not a changed file
        script.write_text(rs.fill(rs.PIPELINE_STATE_SH), encoding="utf-8", newline="\n")
        self.addCleanup(script.unlink, missing_ok=True)
        for rel, body in files.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8", newline="\n")
        subprocess.run([git, "-C", str(root), "add", "-A"], capture_output=True, env=env, **rs.NOWIN)
        out = subprocess.run([sh, str(script), "due"], cwd=str(root), capture_output=True,
                             text=True, env=env, **rs.NOWIN)
        return sorted(out.stdout.split())

    def test_a_stylesheet_still_wakes_code_reviewer(self):
        self.assertEqual(self.due({"src/a.css": "body{}"}), ["code", "design"])

    def test_a_component_is_application_code(self):
        """The measured case: an auth component is not a styling change."""
        self.assertEqual(self.due({"src/hooks/useAuth.tsx": "x"}), ["code", "design", "security"])

    def test_tailwind_config_is_executable_and_wakes_security(self):
        """It runs on every build, in CI and on every machine. It is not a stylesheet."""
        self.assertIn("security", self.due({"tailwind.config.js": "module.exports={}"}))

    def test_the_security_trigger_catches_ordinary_react_auth_naming(self):
        """The pattern was case-sensitive and path-shaped, so AuthProvider.tsx missed it."""
        for rel in ("src/components/AuthProvider.tsx", "src/lib/auth.ts", "src/hooks/useAuth.tsx"):
            self.assertIn("security", self.due({rel: "x"}), rel)

    def test_the_file_that_decides_which_checks_run_wakes_security(self):
        self.assertIn("security", self.due({".githooks/checks": "npm test"}))

    def test_docs_still_make_nothing_due(self):
        self.assertEqual(self.due({"README.md": "x"}), [])


class SpikeBranchesReportInsteadOfBlocking(unittest.TestCase):
    """The gate exists because this kit has shipped destructive bugs that review caught. It is not
    relaxed for real work - only on a branch that cannot reach main except through a pull request,
    where the CI gates and a full pipeline pass still apply."""

    def gate(self, branch):
        git, sh = tools(self)
        env = git_env()
        root = make_temp_dir(self)
        subprocess.run([git, "init", "-b", "prelive", str(root)], capture_output=True, env=env,
                       check=True, **rs.NOWIN)
        for a in (("config", "user.email", "t@example.com"), ("config", "user.name", "Tester"),
                  ("commit", "-q", "--allow-empty", "-m", "chore: seed")):
            subprocess.run([git, "-C", str(root)] + list(a), capture_output=True, env=env, **rs.NOWIN)
        if branch != "prelive":
            subprocess.run([git, "-C", str(root), "checkout", "-q", "-b", branch],
                           capture_output=True, env=env, **rs.NOWIN)
        (root / "src").mkdir()
        (root / "src" / "a.ts").write_text("x\n", encoding="utf-8", newline="\n")
        subprocess.run([git, "-C", str(root), "add", "-A"], capture_output=True, env=env, **rs.NOWIN)
        script = root / "sg.sh"
        script.write_text(rs.fill(rs.STOP_GATE_SH), encoding="utf-8", newline="\n")
        out = subprocess.run([sh, "sg.sh"], cwd=str(root), capture_output=True, text=True,
                             input="{}", env=env, **rs.NOWIN)
        return out.returncode, (out.stdout or "") + (out.stderr or "")

    def test_a_real_branch_still_blocks(self):
        for branch in ("prelive", "feature/normal", "spikes-not-a-spike"):
            code, _ = self.gate(branch)
            self.assertEqual(code, 2, branch)

    def test_a_spike_branch_reports_and_allows(self):
        for branch in ("spike/ui", "draft/x", "proto/y"):
            code, out = self.gate(branch)
            self.assertEqual(code, 0, branch)
            self.assertIn("not blocking", out)

    def test_the_disclosure_goes_to_stdout_not_stderr(self):
        """A Stop hook's stderr reaches the session only when it exits 2. Writing the disclosure to
        stderr on the exit-0 path meant the one thing making this defensible never happened - and
        the first version of this test could not see that, because it merged both streams."""
        git, sh = tools(self)
        env = git_env()
        root = make_temp_dir(self)
        subprocess.run([git, "init", "-b", "prelive", str(root)], capture_output=True, env=env,
                       check=True, **rs.NOWIN)
        for a in (("config", "user.email", "t@example.com"), ("config", "user.name", "Tester"),
                  ("commit", "-q", "--allow-empty", "-m", "chore: seed"),
                  ("checkout", "-q", "-b", "spike/ui")):
            subprocess.run([git, "-C", str(root)] + list(a), capture_output=True, env=env, **rs.NOWIN)
        (root / "src").mkdir()
        (root / "src" / "a.ts").write_text("x\n", encoding="utf-8", newline="\n")
        subprocess.run([git, "-C", str(root), "add", "-A"], capture_output=True, env=env, **rs.NOWIN)
        (root / "sg.sh").write_text(rs.fill(rs.STOP_GATE_SH), encoding="utf-8", newline="\n")
        out = subprocess.run([sh, "sg.sh"], cwd=str(root), capture_output=True, text=True,
                             input="{}", env=env, **rs.NOWIN)
        self.assertEqual(out.returncode, 0)
        self.assertIn("CHANGELOG", out.stdout, "the disclosure must be on stdout")
        self.assertIn("UNREVIEWED", out.stdout)

    def test_it_says_the_debt_is_not_recorded_anywhere(self):
        """It claimed the full pipeline runs on promotion. Nothing enforces that: pipeline-state
        sees only uncommitted work, so committing hides the debt, and ci-gates fires only on PRs
        into main. The claim was removed rather than left standing."""
        _, out = self.gate("spike/ui")
        self.assertIn("nothing downstream recomputes it", out)


class CiRunsEveryLineTheChecksFileHas(unittest.TestCase):
    """The shipped checks file says scoping "trades local speed for nothing" because CI runs every
    line regardless. That was false: ci.yml was generated from detect()'s list and never read
    .githooks/checks, which the file's own header invites you to edit. So a [glob]-scoped line was
    by construction absent from CI - it could be skipped on every local push and never run anywhere.
    This is the claim, pinned."""

    def checks(self, body):
        root = make_temp_dir(self)
        (root / ".githooks").mkdir()
        (root / ".githooks" / "checks").write_text(body, encoding="utf-8", newline="\n")
        return rs.checks_lines(root)

    def test_a_scoped_line_reaches_ci_with_its_prefix_stripped(self):
        got = self.checks("npm run typecheck\n[src/* *.css] npm run test:ui\n")
        self.assertEqual(got, ["npm run typecheck", "npm run test:ui"])

    def test_a_test_command_is_not_mistaken_for_a_prefix(self):
        got = self.checks("[ -f package.json ] && npm test\n[[ -d x ]] && echo b\n")
        self.assertEqual(got, ["[ -f package.json ] && npm test", "[[ -d x ]] && echo b"])

    def test_comments_and_blank_lines_are_dropped(self):
        self.assertEqual(self.checks("# header\n\n  npm test  \n"), ["npm test"])

    def test_no_checks_file_yields_nothing_so_detection_still_applies(self):
        root = make_temp_dir(self)
        self.assertEqual(rs.checks_lines(root), [])

    def test_apply_puts_those_lines_into_ci(self):
        """End to end: the generated workflow contains the scoped line, unscoped."""
        import argparse
        git = shutil.which("git")
        if not git:
            self.skipTest("git not on PATH")
        self.addCleanup(setattr, rs, "ensure_installed", rs.ensure_installed)
        rs.ensure_installed = lambda: False
        self.addCleanup(setattr, rs, "WORK_BRANCH", rs.WORK_BRANCH)
        self.addCleanup(setattr, rs, "PROTECTED", list(rs.PROTECTED))
        root = make_temp_dir(self)
        subprocess.run([git, "init", str(root)], capture_output=True, env=git_env(),
                       check=True, **rs.NOWIN)
        (root / ".githooks").mkdir()
        (root / ".githooks" / "checks").write_text(
            "npm run typecheck\n[src/*] npm run test:ui\n", encoding="utf-8", newline="\n")
        rs.cmd_apply(argparse.Namespace(repo=str(root), dry_run=False, force=False,
                                        update_pipeline=False, uat_project=None))
        ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("- run: npm run typecheck", ci)
        self.assertIn("- run: npm run test:ui", ci)
        self.assertNotIn("[src/*]", ci, "the prefix is local-only; CI has no push to scope against")


if __name__ == "__main__":
    unittest.main()
