"""Tests for the shipped pipeline hooks: pipeline-state.sh and the rewritten stop-gate.sh.

These pin the ADR-0003 contract: the working-set filter, the due-reviewer mapping, the
content signature ("sig") of the reviewable work, the verdict states, and the Stop
gate's count-based valve (block at most twice per work-state, then allow with a
disclosure demand — never an infinite loop, whatever stdin contains).

Failing-test-first: ValveTwoBlocksThenAllow and LegacyAndGarbageStdin reproduce the
v4.1 bug — a missing review verdict passed the Stop gate silently — and were written
red against the old template before the rewrite.

Import safety: same pattern as test_repo_setup_worktree.py — HOME/USERPROFILE point at
a temp dir around the repo_setup import. Shell-executing tests skip unless both git
and sh are on PATH; every subprocess gets git's global/system config neutralised, the
kit's skip vars removed, and the running Python's directory prepended to PATH (the
hooks call `python`).
Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="pipeline-state-fake-home-")
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

FILL_VARS = dict(NAME="t", WORK="work", MAIN="main",
                 TYPES="src/types/database.ts", GEN_TYPES="npx supabase gen types")

STATE_REL = ".claude/hooks/pipeline-state.sh"
GATE_REL = ".claude/hooks/stop-gate.sh"

STDIN_OK = '{"stop_hook_active": false}'


def hook_env():
    """Environment for running the shipped sh hooks hermetically."""
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1")
    for k in ("SONELO_SKIP_HOOKS", "TEKNOBU_SKIP_HOOKS", "SONELO_SKIP", "GIT_LITERAL_PATHSPECS"):
        env.pop(k, None)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def make_temp_dir(testcase, prefix="pipeline-state-test-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def run_git(*args):
    proc = subprocess.run([GIT] + [str(a) for a in args], capture_output=True, text=True,
                          env=hook_env(), check=True, **rs.NOWIN)
    return proc.stdout


def make_repo(testcase):
    """git init on branch `work` with one commit; materialise the shipped hooks; return repo path."""
    base = make_temp_dir(testcase)
    repo = base / "repo"
    run_git("init", repo)
    run_git("-C", repo, "checkout", "-b", "work")
    run_git("-C", repo, "config", "user.name", "Pipeline Test")
    run_git("-C", repo, "config", "user.email", "pipeline-test@example.invalid")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    run_git("-C", repo, "add", "seed.txt")
    run_git("-C", repo, "-c", "commit.gpgsign=false", "commit", "-m", "seed commit")
    for rel in (STATE_REL, GATE_REL):
        if rel in rs.BUILTIN_PIPELINE:
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(rs.fill(rs.BUILTIN_PIPELINE[rel], **FILL_VARS),
                           encoding="utf-8", newline="\n")
    return repo


def commit_files(repo, *relpaths):
    for rel in relpaths:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("content of %s\n" % rel, encoding="utf-8")
    run_git("-C", repo, "add", "--", *relpaths)
    run_git("-C", repo, "-c", "commit.gpgsign=false", "commit", "-m", "add files")


def put(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def append(repo, rel, text):
    with open(repo / rel, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def state(repo, subcmd, *args):
    """Run pipeline-state.sh <subcmd>; return stdout stripped."""
    proc = subprocess.run([SH, str(repo / STATE_REL), subcmd] + list(args), cwd=str(repo),
                          capture_output=True, text=True, env=hook_env(), **rs.NOWIN)
    return proc.stdout.strip()


def gate(repo, stdin=STDIN_OK):
    """Run stop-gate.sh with the given stdin; return (returncode, stderr)."""
    proc = subprocess.run([SH, str(repo / GATE_REL)], cwd=str(repo), input=stdin,
                          capture_output=True, text=True, env=hook_env(), **rs.NOWIN)
    return proc.returncode, proc.stderr


def write_verdict(repo, branch, sig, reviewers, verdict="clear", tests="green"):
    put(repo, ".claude/state/%s/review.json" % branch, json.dumps(
        {"branch": branch, "at": "2026-08-25T00:00:00", "sig": sig, "verdict": verdict,
         "blocking": [], "reviewers": reviewers, "tests": tests}))


@unittest.skipUnless(GIT and SH, "git and sh are required")
class CodeChangedFilter(unittest.TestCase):
    """`changed` lists everything; `code-changed` drops docs, changelog and .claude state."""

    def test_code_changed_excludes_docs_changelog_and_state(self):
        repo = make_repo(self)
        commit_files(repo, "src/app.ts", "CHANGELOG.md", "docs/x.md")
        append(repo, "src/app.ts", "edit\n")
        append(repo, "CHANGELOG.md", "entry\n")
        append(repo, "docs/x.md", "docs edit\n")
        put(repo, ".claude/state/work/review.json", "{}")
        changed = state(repo, "changed").splitlines()
        for rel in ("src/app.ts", "CHANGELOG.md", "docs/x.md", ".claude/state/work/review.json"):
            self.assertIn(rel, changed)
        code = state(repo, "code-changed").splitlines()
        self.assertEqual(code, ["src/app.ts"])


@unittest.skipUnless(GIT and SH, "git and sh are required")
class DueReviewers(unittest.TestCase):
    """Fixed-order mapping from the changed set to due reviewers; auth needs a boundary."""

    def test_due_order_and_mapping(self):
        repo = make_repo(self)
        put(repo, "src/Button.tsx", "x\n")
        self.assertEqual(state(repo, "due"), "code design")
        put(repo, "supabase/functions/f/index.ts", "x\n")
        self.assertEqual(state(repo, "due"), "code design security")

    def test_auth_boundary_and_plain_code(self):
        repo = make_repo(self)
        put(repo, "src/author.ts", "x\n")
        self.assertEqual(state(repo, "due"), "code")
        put(repo, "src/auth.ts", "x\n")
        self.assertEqual(state(repo, "due"), "code security")

    def test_empty_when_only_docs_changed(self):
        repo = make_repo(self)
        put(repo, "docs/x.md", "x\n")
        self.assertEqual(state(repo, "due"), "")


@unittest.skipUnless(GIT and SH, "git and sh are required")
class SigExcludesNonReviewable(unittest.TestCase):
    """The deadlock pin: docs/changelog/state writes by the tail agents must not move the sig."""

    def test_sig_ignores_excluded_paths_and_moves_on_code(self):
        repo = make_repo(self)
        commit_files(repo, "src/app.ts", "CHANGELOG.md", "docs/x.md")
        append(repo, "src/app.ts", "edit\n")
        sig_a = state(repo, "sig")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40,64}", sig_a), "sig should be a hash: %r" % sig_a)
        append(repo, "CHANGELOG.md", "entry\n")
        append(repo, "docs/x.md", "docs edit\n")
        put(repo, ".claude/state/work/review.json", "{}")
        self.assertEqual(state(repo, "sig"), sig_a)
        append(repo, "src/app.ts", "more\n")
        self.assertNotEqual(state(repo, "sig"), sig_a)


@unittest.skipUnless(GIT and SH, "git and sh are required")
class SigCoverage(unittest.TestCase):
    """Sig covers index, worktree and untracked work — including names with spaces."""

    def test_index_worktree_untracked_and_spaces(self):
        repo = make_repo(self)
        commit_files(repo, "src/app.ts")
        append(repo, "src/app.ts", "staged\n")
        run_git("-C", repo, "add", "src/app.ts")
        sig1 = state(repo, "sig")
        append(repo, "src/app.ts", "unstaged\n")
        sig2 = state(repo, "sig")
        self.assertNotEqual(sig1, sig2)
        put(repo, "src/my file.ts", "spaced\n")
        sig3 = state(repo, "sig")
        self.assertNotEqual(sig2, sig3)

    def test_two_untracked_files_differ_from_one_concatenation(self):
        repo_a = make_repo(self)
        put(repo_a, "x.ts", "x\n")
        put(repo_a, "y.ts", "y\n")
        repo_b = make_repo(self)
        put(repo_b, "x.ts", "x\ny\n")
        self.assertNotEqual(state(repo_a, "sig"), state(repo_b, "sig"))


@unittest.skipUnless(GIT and SH, "git and sh are required")
class VerdictStates(unittest.TestCase):
    """none | stale | blocked | clear-partial <keys> | clear — and old files never crash."""

    def test_verdict_states(self):
        repo = make_repo(self)
        put(repo, "src/Button.tsx", "x\n")           # due: code design
        self.assertEqual(state(repo, "verdict"), "none")
        put(repo, ".claude/state/work/review.json",
            json.dumps({"verdict": "clear", "reviewers": {"code": "clear"}}))  # v4.1 shape, no sig
        self.assertEqual(state(repo, "verdict"), "stale")
        sig = state(repo, "sig")
        write_verdict(repo, "work", sig, {"code": "clear"})
        self.assertEqual(state(repo, "verdict"), "clear-partial design")
        write_verdict(repo, "work", sig, {"code": "clear", "design": "skipped"})
        self.assertEqual(state(repo, "verdict"), "clear-partial design")
        write_verdict(repo, "work", sig, {"code": "clear", "design": "clear"})
        self.assertEqual(state(repo, "verdict"), "clear")
        write_verdict(repo, "work", sig, {"code": "clear", "design": "clear"}, verdict="blocked")
        self.assertEqual(state(repo, "verdict"), "blocked")
        write_verdict(repo, "work", sig, {"code": "clear", "design": "clear"}, tests="red")
        self.assertEqual(state(repo, "verdict"), "blocked")
        write_verdict(repo, "work", sig, {"code": "clear", "design": "blocked"})
        self.assertEqual(state(repo, "verdict"), "blocked")
        put(repo, ".claude/state/work/review.json", "not json {")
        self.assertEqual(state(repo, "verdict"), "none")


@unittest.skipUnless(GIT and SH, "git and sh are required")
class ValveTwoBlocksThenAllow(unittest.TestCase):
    """THE v4.1 BUG, reproduced: code changed, changelog present, no verdict — the old gate
    exited 0. The rewritten gate blocks (twice, the second time demanding disclosure),
    then allows; a sig change re-arms it."""

    def test_missing_verdict_blocks_then_discloses_then_allows(self):
        repo = make_repo(self)
        commit_files(repo, "src/app.ts")
        append(repo, "src/app.ts", "edit\n")
        put(repo, "CHANGELOG.md", "- src/app.ts: edited\n")   # changelog reason satisfied
        rc1, err1 = gate(repo)
        self.assertEqual(rc1, 2, "gate must block when no review verdict covers the work")
        self.assertIn("review", err1.lower())
        self.assertIn("/post-change", err1)
        rc2, err2 = gate(repo)
        self.assertEqual(rc2, 2)
        self.assertIn("state plainly to the user", err2)
        rc3, _ = gate(repo)
        self.assertEqual(rc3, 0, "third stop on the same work-state must be allowed")
        sig = state(repo, "sig")
        marker = (repo / ".claude/state/work/disclosed").read_text(encoding="utf-8").split()
        self.assertEqual(marker, [sig, "2"])
        append(repo, "src/app.ts", "more work\n")             # sig moves: gate re-arms
        rc4, _ = gate(repo)
        self.assertEqual(rc4, 2)
        marker = (repo / ".claude/state/work/disclosed").read_text(encoding="utf-8").split()
        self.assertEqual(marker[1], "1")

    def test_fresh_clear_verdict_passes_and_clears_marker(self):
        repo = make_repo(self)
        commit_files(repo, "src/app.ts")
        append(repo, "src/app.ts", "edit\n")
        put(repo, "CHANGELOG.md", "- entry\n")
        self.assertEqual(gate(repo)[0], 2)                    # arms the marker
        sig = state(repo, "sig")
        write_verdict(repo, "work", sig, {"code": "clear"})
        rc, _ = gate(repo)
        self.assertEqual(rc, 0)
        self.assertFalse((repo / ".claude/state/work/disclosed").exists())


@unittest.skipUnless(GIT and SH, "git and sh are required")
class LegacyAndGarbageStdin(unittest.TestCase):
    """Mixed-version repos fall back to v4.1 behaviour; unparseable stdin can never loop."""

    def test_legacy_fallback_without_pipeline_state(self):
        repo = make_repo(self)
        (repo / STATE_REL).unlink()
        commit_files(repo, "src/app.ts")
        append(repo, "src/app.ts", "edit\n")
        put(repo, "CHANGELOG.md", "- entry\n")
        rc, err = gate(repo)
        self.assertEqual(rc, 0, "no pipeline-state.sh: gate keeps v4.1 semantics")
        self.assertFalse((repo / ".claude/state/work/disclosed").exists())
        put(repo, ".claude/state/work/review.json", json.dumps({"verdict": "blocked"}))
        rc, err = gate(repo)
        self.assertEqual(rc, 2)
        self.assertIn("blocked", err)

    def test_garbage_stdin_blocks_twice_then_allows(self):
        repo = make_repo(self)
        commit_files(repo, "src/app.ts")
        append(repo, "src/app.ts", "edit\n")
        put(repo, "CHANGELOG.md", "- entry\n")
        self.assertEqual(gate(repo, stdin="not-json")[0], 2)
        self.assertEqual(gate(repo, stdin="not-json")[0], 2)
        self.assertEqual(gate(repo, stdin="not-json")[0], 0)


@unittest.skipUnless(GIT and SH, "git and sh are required")
class BranchShapesAndDetached(unittest.TestCase):
    """Branch names with '/' nest cleanly; detached HEAD gets legacy checks and no state."""

    def test_branch_with_slash(self):
        repo = make_repo(self)
        run_git("-C", repo, "checkout", "-b", "feat/x")
        commit_files(repo, "src/app.ts")
        append(repo, "src/app.ts", "edit\n")
        put(repo, "CHANGELOG.md", "- entry\n")
        sig = state(repo, "sig")
        write_verdict(repo, "feat/x", sig, {"code": "clear"})
        rc, err = gate(repo)
        self.assertEqual(rc, 0, "stderr: %s" % err)

    def test_detached_head_is_legacy_only(self):
        repo = make_repo(self)
        commit_files(repo, "src/app.ts")
        run_git("-C", repo, "checkout", "--detach")
        append(repo, "src/app.ts", "edit\n")                  # no CHANGELOG: legacy reason fires
        self.assertEqual(state(repo, "verdict"), "none")
        rc, err = gate(repo)
        self.assertEqual(rc, 2)
        self.assertIn("CHANGELOG", err)
        self.assertNotIn("review", err.lower().replace("changelog", ""))
        found = list((repo / ".claude").rglob("disclosed"))
        self.assertEqual(found, [], "detached HEAD must not write state markers")


class TemplatesTokenSafe(unittest.TestCase):
    """fill() does raw substring replacement of {TOKEN}s: the sh templates must contain no
    uppercase ${...} shell expansions, and no {TOKEN} may survive rendering."""

    TOKENS = ("MARK", "VERSION", "NAME", "WORK", "MAIN", "TYPES", "GEN_TYPES")

    def test_sh_templates_have_no_uppercase_brace_expansions(self):
        for rel, tpl in rs.BUILTIN_PIPELINE.items():
            if not rel.endswith(".sh"):
                continue
            hit = re.search(r"\$\{(%s)\}" % "|".join(self.TOKENS), tpl)
            self.assertIsNone(hit, "%s uses %s — fill() would corrupt it" % (rel, hit and hit.group(0)))

    def test_no_tokens_survive_fill(self):
        for rel, tpl in rs.BUILTIN_PIPELINE.items():
            rendered = rs.fill(tpl, **FILL_VARS)
            for tok in self.TOKENS:
                self.assertNotIn("{%s}" % tok, rendered, "%s leaves {%s} unfilled" % (rel, tok))


@unittest.skipUnless(GIT and SH, "git and sh are required")
class WorkflowsAreCode(unittest.TestCase):
    """.github/workflows/ is deploy surface: reviewable, sig-covered, security due -
    while the rest of .github/ and all of .claude/ stay excluded (ADR-0003)."""

    def test_workflow_edits_are_reviewable_and_security_due(self):
        repo = make_repo(self)
        put(repo, ".github/workflows/deploy.yml", "on: push" + chr(10))
        put(repo, ".github/pull_request_template.md", "template" + chr(10))
        code = state(repo, "code-changed").splitlines()
        self.assertIn(".github/workflows/deploy.yml", code)
        self.assertNotIn(".github/pull_request_template.md", code)
        self.assertEqual(state(repo, "due"), "code security")
        sig_a = state(repo, "sig")
        append(repo, ".github/workflows/deploy.yml", "  branches: [main]" + chr(10))
        self.assertNotEqual(state(repo, "sig"), sig_a, "workflow edits must move the sig")


if __name__ == "__main__":
    unittest.main()
