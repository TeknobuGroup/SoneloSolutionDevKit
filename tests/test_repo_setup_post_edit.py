"""Tests for the PostToolUse hook shipped as .claude/hooks/post-edit.sh (kit 4.10).

Failing-test-first: every test here was written red against the 4.2-4.9 template, which ran
`tsc --noEmit -p tsconfig.json` on every single edit and reported every lint error in the
edited file. Both were measured defects rather than style objections:

  * A Vite/React `tsconfig.json` is a solution file ("files": [], "references": [...]), so
    that command compiles the empty file list. It cost seconds per edit for no signal, on
    1,411 edits in one repo alone.
  * A repo with an eslint ratchet carries hundreds of accepted errors, so the hook exited 2
    on more than half of all edits and sent the session off fixing debt it had not written.

What is pinned: no whole-project type check, silence when the change added nothing, and a
report naming the rise when it did. Whole-project type checking belongs to .githooks/checks
and CI, which is where the removed check went - not nowhere.

Import safety and hermetic subprocesses follow test_pipeline_state.py.
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

_FAKE_HOME = tempfile.mkdtemp(prefix="post-edit-fake-home-")
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
SH = shutil.which("sh")
NODE = shutil.which("node")

HOOK_REL = ".claude/hooks/post-edit.sh"
FILL_VARS = dict(NAME="t", WORK="work", MAIN="main",
                 TYPES="src/types/database.ts", GEN_TYPES="npx supabase gen types")

# A fake eslint: prints whatever report the test put in .eslint-fixture.json, so the number
# of errors in a file is controlled by the test rather than by a real lint run.
FAKE_ESLINT = (
    "var fs = require('fs');\n"
    "process.stdout.write(fs.readFileSync('.eslint-fixture.json', 'utf8'));\n"
)


def hook_env():
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1")
    for k in ("SONELO_SKIP_HOOKS", "TEKNOBU_SKIP_HOOKS", "SONELO_SKIP", "GIT_LITERAL_PATHSPECS"):
        env.pop(k, None)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def run_git(*args):
    return subprocess.run([GIT] + [str(a) for a in args], capture_output=True, text=True,
                          env=hook_env(), check=True, **rs.NOWIN).stdout


def report(n):
    """An eslint JSON report carrying n severity-2 messages (and one warning, ignored)."""
    msgs = [{"severity": 2, "line": i + 1, "column": 1,
             "message": "error %d" % (i + 1), "ruleId": "rule/%d" % (i + 1)} for i in range(n)]
    msgs.append({"severity": 1, "line": 99, "column": 1, "message": "just a warning",
                 "ruleId": "rule/warn"})
    return [{"filePath": "x", "messages": msgs}]


@unittest.skipUnless(GIT and SH and NODE, "git, sh and node are required")
class PostEditReportsOnlyWhatTheChangeAdded(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix="post-edit-test-"))
        self.addCleanup(shutil.rmtree, str(base), ignore_errors=True)
        self.repo = base / "repo"
        run_git("init", self.repo)
        run_git("-C", self.repo, "checkout", "-b", "work")
        run_git("-C", self.repo, "config", "user.name", "Post Edit Test")
        run_git("-C", self.repo, "config", "user.email", "post-edit@example.invalid")
        self.write("eslint.config.js", "export default [];\n")
        self.write("node_modules/eslint/bin/eslint.js", FAKE_ESLINT)
        self.write("src/a.ts", "export const a = 1;\n")
        run_git("-C", self.repo, "add", "-A")
        run_git("-C", self.repo, "-c", "commit.gpgsign=false", "commit", "-m", "seed")
        hook = self.repo / HOOK_REL
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(rs.fill(rs.BUILTIN_PIPELINE[HOOK_REL], **FILL_VARS),
                        encoding="utf-8", newline="\n")

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        return p

    def errors(self, n):
        self.write(".eslint-fixture.json", json.dumps(report(n)))

    def run_hook(self, rel="src/a.ts"):
        payload = json.dumps({"tool_input": {"file_path": rel}})
        proc = subprocess.run([SH, HOOK_REL], input=payload, capture_output=True, text=True,
                              cwd=str(self.repo), env=hook_env(), **rs.NOWIN)
        return proc.returncode, (proc.stderr or "") + (proc.stdout or "")

    def test_pre_existing_errors_are_silent(self):
        """A tracked file arrived with whatever it has. The session did not write it."""
        self.errors(2)
        rc, out = self.run_hook()
        self.assertEqual(rc, 0, "pre-existing lint debt must not stop an edit: %s" % out)
        self.assertEqual(out.strip(), "")

    def test_errors_the_change_added_are_reported(self):
        self.errors(2)
        self.run_hook()                      # records 2 as the accepted level for this file
        self.errors(4)
        rc, out = self.run_hook()
        self.assertEqual(rc, 2, "an added lint error must be fed back to the session")
        self.assertIn("from 2 to 4", out)
        self.assertIn("added 2", out)

    def test_going_back_down_is_silent_again(self):
        self.errors(4)
        self.run_hook()
        self.errors(2)
        rc, out = self.run_hook()
        self.assertEqual(rc, 0, "fixing errors must not keep reporting: %s" % out)

    def test_a_file_this_session_created_owns_every_error_in_it(self):
        """Untracked: nothing accepted it before, so there is no debt to inherit."""
        self.write("src/new.ts", "export const b = 2;\n")
        self.errors(3)
        rc, out = self.run_hook("src/new.ts")
        self.assertEqual(rc, 2)
        self.assertIn("from 0 to 3", out)

    def test_ratchet_baseline_is_the_accepted_level(self):
        """A repo with a baseline has an authoritative accepted count per file."""
        self.write("scripts/eslint-baseline.json", json.dumps({"counts": {"src/a.ts": 5}}))
        self.errors(5)
        rc, out = self.run_hook()
        self.assertEqual(rc, 0, "at the baseline the hook says nothing: %s" % out)
        self.errors(6)
        rc, out = self.run_hook()
        self.assertEqual(rc, 2)
        self.assertIn("added 1", out)

    def test_a_file_absent_from_the_baseline_accepts_zero(self):
        self.write("scripts/eslint-baseline.json", json.dumps({"counts": {"src/other.ts": 9}}))
        self.errors(1)
        rc, out = self.run_hook()
        self.assertEqual(rc, 2, "a baseline that does not list the file accepts none: %s" % out)

    def git_root(self):
        return run_git("-C", self.repo, "rev-parse", "--show-toplevel").strip()

    def test_an_absolute_path_is_resolved_against_the_baseline(self):
        """Claude passes file_path however the tool got it, and that is often absolute. If the
        repo root does not get stripped, no baseline key matches and accepted silently falls to
        zero - every pre-existing error is then reported as one this change added."""
        self.write("scripts/eslint-baseline.json", json.dumps({"counts": {"src/a.ts": 5}}))
        self.errors(5)
        rc, out = self.run_hook(self.git_root() + "/src/a.ts")
        self.assertEqual(rc, 0, "an absolute path must find its own baseline entry: %s" % out)

    @unittest.skipUnless(os.name == "nt", "drive letters are a Windows concern")
    def test_a_drive_letter_case_mismatch_still_resolves(self):
        """Windows hands back "C:/..." where Python's getcwd() reports "c:/...". A case-sensitive
        prefix strip leaves the path absolute and re-reports the whole file."""
        root = self.git_root()
        flipped = root[0].swapcase() + root[1:]
        self.assertNotEqual(flipped, root, "test needs a drive letter to flip")
        self.write("scripts/eslint-baseline.json", json.dumps({"counts": {"src/a.ts": 5}}))
        self.errors(5)
        rc, out = self.run_hook(flipped + "/src/a.ts")
        self.assertEqual(rc, 0, "drive-letter case must not decide whether debt is reported: %s" % out)

    def test_the_lint_report_leaves_nothing_shared_behind(self):
        """The report file is scratch. Anything left under a fixed name is state two concurrent
        sessions in one repo would fight over."""
        self.errors(2)
        self.run_hook()
        stray = [q.name for q in (self.repo / ".claude/state/lint").glob("*.json")]
        self.assertEqual(stray, [], "the eslint report must be cleaned up, not left to be read "
                                    "by another session's hook: %s" % stray)


class NoWholeProjectWorkPerEdit(unittest.TestCase):
    """The hook runs on every Edit/Write/MultiEdit. Anything whole-project in it is paid for
    on every keystroke-sized change, and belongs on push instead."""

    def test_the_hook_does_not_typecheck_the_whole_project(self):
        body = rs.BUILTIN_PIPELINE[HOOK_REL]
        self.assertNotIn("tsc --noEmit -p tsconfig.json", body,
                         "a per-edit whole-project typecheck compiles nothing in a solution-style "
                         "tsconfig and costs seconds on every edit - it belongs in .githooks/checks")
        self.assertNotIn("[typecheck]", body)

    def test_the_managed_claude_section_does_not_claim_a_per_edit_typecheck(self):
        """Shipped prose is a contract: nine repos read it as the truth about their hooks."""
        self.assertNotIn("The type checker and linter run on every edit",
                         rs.PIPELINE_CLAUDE_SECTION)

    def test_the_managed_claude_section_still_forbids_disabling_a_rule(self):
        """Reporting less must not mean permitting more: the escape hatches stay shut."""
        self.assertIn("never disable a rule", rs.PIPELINE_CLAUDE_SECTION)
        self.assertIn("never raise the lint baseline", rs.PIPELINE_CLAUDE_SECTION)

    def test_lint_still_runs_on_the_edited_file(self):
        body = rs.BUILTIN_PIPELINE[HOOK_REL]
        self.assertIn("eslint", body)
        self.assertIn("[lint]", body)

    def test_the_impact_report_nudge_survives(self):
        self.assertIn("impact.json", rs.BUILTIN_PIPELINE[HOOK_REL])

    def test_the_lint_report_path_is_per_process(self):
        """This user runs several Claude sessions at once, and worktrees share nothing but a repo
        can hold two sessions. A fixed report path lets one session's hook read the report another
        session's hook just wrote, and score a file against a different file's error count."""
        body = rs.BUILTIN_PIPELINE[HOOK_REL]
        self.assertIn(".report-$$.json", body)
        self.assertNotIn(".last-report.json", body)


if __name__ == "__main__":
    unittest.main()
