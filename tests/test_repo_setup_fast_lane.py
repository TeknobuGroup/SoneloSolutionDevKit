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

    def push_many(self, lines):
        """Several ref updates in one push. Nothing reached this path before, and it is the only
        path on which the invariant this file defends actually broke."""
        body = "".join("%s %s %s %s\n" % l for l in lines)
        out = subprocess.run([self.sh, ".githooks/pre-push"], cwd=str(self.root),
                             capture_output=True, env=self.env, input=body.encode(), **rs.NOWIN)
        text = out.stdout.decode("utf-8", "replace") + out.stderr.decode("utf-8", "replace")
        return [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("pre-push:")]

    def sha(self, ref="HEAD"):
        return self._git("rev-parse", ref).stdout.strip()

    def branch(self, name):
        self._git("checkout", "-q", "-b", name)

    def mv(self, a, b):
        self._git("mv", a, b)
        self._git("commit", "-q", "-m", "chore: move %s" % a)
        return self.sha()

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


class TheChangedSetIsAllOrNothing(unittest.TestCase):
    """A range that cannot be resolved emitted nothing and was unioned with the ranges that could,
    leaving a PARTIAL set - which still looks non-empty, so scoping engaged against a set missing
    whole branches. Measured: a first push of `prelive` alongside a spike branch skipped the
    migrations suite and the hook exited 0. The invariant held per-range, not per-push."""

    def test_a_multi_ref_push_with_one_unresolvable_range_runs_everything(self):
        r = PrePushRepo(self, CHECKS)
        r.commit("tests/t.py", "x\n")
        prelive = r.sha()
        r.branch("spike/x")
        r.commit("src/b.css", "c\n")
        got = sorted(r.push_many([
            ("refs/heads/prelive", prelive, "refs/heads/prelive", ZERO),        # never seen: unresolvable
            ("refs/heads/spike/x", r.sha(), "refs/heads/spike/x", prelive),     # resolvable
        ]))
        self.assertEqual(got, ["RAN-always", "RAN-suite", "RAN-ui"])

    def test_a_resolvable_multi_ref_push_still_scopes(self):
        """All-or-nothing must not mean never: two good ranges still scope."""
        r = PrePushRepo(self, CHECKS)
        base = r.commit("src/a.css", "x\n")
        r.commit("src/a.css", "y\n")
        got = sorted(r.push_many([("refs/heads/prelive", r.sha(), "refs/heads/prelive", base)]))
        self.assertEqual(got, ["RAN-always", "RAN-ui"])


class ARenameOutOfAScopedTreeStillCounts(unittest.TestCase):
    """`git diff --name-only` reports only a rename's destination, so moving a file OUT of a scoped
    tree hid that the tree had changed. Both scoped checks were skipped by a single `git mv`, which
    is the commonest way a UI or migration suite actually breaks."""

    def test_moving_a_file_out_of_the_tree_runs_the_check(self):
        r = PrePushRepo(self, CHECKS)
        base = r.commit("src/a.css", "x\n")
        r.mv("src/a.css", "a.css")
        self.assertIn("RAN-ui", r.ran(base))

    def test_moving_a_file_into_the_tree_runs_the_check(self):
        r = PrePushRepo(self, CHECKS)
        r.commit("top.css", "x\n")
        base = r.commit("tests/keep.py", "x\n")
        r.mv("top.css", "src/top.css")
        self.assertIn("RAN-ui", r.ran(base))


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

    def test_a_spike_branch_states_the_debt_once_then_allows(self):
        """stdout on an exit-0 Stop hook is transcript-only and never reaches the model, so simply
        allowing the stop meant the disclosure was never actually made. It now uses the valve the
        gate already had: block once with the debt on stderr, then allow."""
        for branch in ("spike/ui", "draft/x", "proto/y"):
            code, out = self.gate(branch)
            self.assertEqual(code, 2, branch)
            self.assertIn("UNREVIEWED", out)
            self.assertIn("state it to", out)

    def test_the_disclosure_reaches_the_model_and_then_stops_blocking(self):
        """A Stop hook's stderr is fed back only on exit 2 and its stdout is transcript-only, so
        the disclosure has to ride an exit 2. The second stop is allowed - it is a spike lane, not
        a wall. An earlier version of this test could not see the difference: it merged the streams."""
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
        first = subprocess.run([sh, "sg.sh"], cwd=str(root), capture_output=True, text=True,
                               input="{}", env=env, **rs.NOWIN)
        self.assertEqual(first.returncode, 2, "the disclosure must ride an exit 2 to be seen")
        self.assertIn("CHANGELOG", first.stderr)
        self.assertIn("UNREVIEWED", first.stderr)
        second = subprocess.run([sh, "sg.sh"], cwd=str(root), capture_output=True, text=True,
                                input="{}", env=env, **rs.NOWIN)
        self.assertEqual(second.returncode, 0, "said once; a spike lane is not a wall")

    def test_refresh_carries_the_release_into_an_existing_repo(self):
        """4.3 kept the git hooks and ci.yml out of `refresh`. 4.7's feature lives in pre-push and
        in the CI step, so under that scoping `refresh` recorded a repo as 4.7 while shipping none
        of it - and `check` then called the repo current. See docs/decisions/0007."""
        import argparse, json as _json
        git = shutil.which("git")
        if not git:
            self.skipTest("git not on PATH")
        self.addCleanup(setattr, rs, "ensure_installed", rs.ensure_installed)
        rs.ensure_installed = lambda: False
        self.addCleanup(setattr, rs, "WORK_BRANCH", rs.WORK_BRANCH)
        self.addCleanup(setattr, rs, "PROTECTED", list(rs.PROTECTED))
        root = make_temp_dir(self)
        subprocess.run([git, "init", "-b", "prelive", str(root)], capture_output=True,
                       env=git_env(), check=True, **rs.NOWIN)
        (root / ".teknobu.json").write_text(
            _json.dumps({"kit": "4.6", "work_branch": "prelive", "protected": ["main"]}), encoding="utf-8")
        (root / ".githooks").mkdir()
        (root / ".githooks" / "pre-push").write_text(
            "#!/bin/sh\n# sonelo-devkit v4.6 - old\nexit 0\n", encoding="utf-8", newline="\n")
        mine = "# mine\nnpm test\n"
        (root / ".githooks" / "checks").write_text(mine, encoding="utf-8", newline="\n")
        rs.cmd_refresh(argparse.Namespace(repo=str(root), dry_run=False, uat_project=None))
        self.assertIn("nothing matching", (root / ".githooks" / "pre-push").read_text(encoding="utf-8"))
        self.assertEqual((root / ".githooks" / "checks").read_text(encoding="utf-8"), mine,
                         "the checks file is the repo's own and is never rewritten")

    def test_it_says_the_debt_is_not_recorded_anywhere(self):
        """It claimed the full pipeline runs on promotion. Nothing enforces that: pipeline-state
        sees only uncommitted work, so committing hides the debt, and ci-gates fires only on PRs
        into main. The claim was removed rather than left standing."""
        _, out = self.gate("spike/ui")
        self.assertIn("nothing downstream recomputes it", out)
        self.assertIn("/post-change on the branch you merge into", out)


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

    def test_apply_makes_ci_read_the_checks_file(self):
        """Baking the list at apply time meant editing the file - which its own header invites -
        left a line running nowhere until someone re-ran apply. CI reads the file instead."""
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
        self.assertIn(".githooks/checks", ci, "CI must read the same list pre-push runs")
        self.assertNotIn("- run: npm run test:ui", ci,
                         "a baked line goes stale the moment the checks file is edited")
        # and the step strips the prefix, so CI runs the line it would otherwise skip
        self.assertIn("line=${line#*]}", ci)


if __name__ == "__main__":
    unittest.main()
