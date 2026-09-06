"""The generated types gate must be satisfiable by a migration that genuinely changes no types.

The gate fires when anything under `supabase/migrations/` changed and the generated types file did
not. That is right for a schema migration and impossible for a policy, grant or data-only one: the
regeneration produces no diff by definition, so the pull request could never go green and the only
ways out were editing the workflow or not shipping. It shipped in that state from the release that
introduced it; a downstream repo hit it on a policy-only migration and stopped.

4.14 adds the escape hatch the kit already uses elsewhere - an explicit act, recorded in git
history, in the same spirit as "`SONELO_SKIP=1` exists for false positives only; say so in the
commit message". The trailer `Types-not-affected: <reason>` waives the gate, the reason is
mandatory, and CI echoes it so a reviewer who never opens the commits still sees it.

These cases run the gate's own shell out of the generated workflow against real git history,
because a substring assertion on the YAML cannot tell a satisfiable gate from an unsatisfiable one.

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

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-typesgate-fake-home-")
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

TYPES = "src/types/database.ts"


def gate_script(base_ref="main"):
    """The gate's `run:` block, lifted out of the generated workflow and made runnable.

    Read out of BUILTIN_PIPELINE rather than restated here: a copy of the shell in the test is a
    test of the copy. `${{ github.base_ref }}` is Actions templating, not shell, so it is the one
    thing substituted - everything else runs exactly as CI runs it."""
    gates = rs.fill(rs.BUILTIN_PIPELINE[".github/workflows/ci-gates.yml"], TYPES=TYPES)
    marker = "- name: Types regenerated after migrations"
    lines = gates.split("\n")
    i = next(n for n, line in enumerate(lines) if marker in line)
    assert lines[i + 1].strip() == "run: |", lines[i + 1]
    indent = len(lines[i + 2]) - len(lines[i + 2].lstrip())
    body = []
    for line in lines[i + 2:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:] if line.strip() else "")
    script = "\n".join(body)
    assert "grep" in script and "changed.txt" in script, script
    return script.replace("${{ github.base_ref }}", base_ref)


class TheTypesGateCanBeSatisfied(unittest.TestCase):

    def setUp(self):
        self.git, self.sh = shutil.which("git"), shutil.which("sh")
        if not self.git or not self.sh:
            self.skipTest("git and sh needed")
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                        GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")

    def run_git(self, root, *args):
        out = subprocess.run([self.git, "-C", str(root)] + list(args), capture_output=True,
                             text=True, env=self.env, **rs.NOWIN)
        self.assertEqual(out.returncode, 0, " ".join(args) + ": " + out.stdout + out.stderr)
        return out.stdout

    def temp_dir(self, prefix):
        d = Path(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
        return d

    def branch(self, messages, changed=("supabase/migrations/0001_policy.sql",)):
        """A clone whose `main` is behind a feature branch carrying `messages`, one per commit,
        plus the `changed.txt` CI writes from the diff. Returns the working repo."""
        origin = self.temp_dir("types-gate-origin-")
        self.run_git(origin, "init", "-b", "main", ".")
        (origin / "README.md").write_text("x\n", encoding="utf-8")
        self.run_git(origin, "add", "-A")
        self.run_git(origin, "commit", "-m", "chore: base")
        work = self.temp_dir("types-gate-work-")
        shutil.rmtree(str(work), ignore_errors=True)
        out = subprocess.run([self.git, "clone", str(origin), str(work)], capture_output=True,
                             text=True, env=self.env, **rs.NOWIN)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.run_git(work, "checkout", "-b", "feature")
        for n, message in enumerate(messages):
            (work / ("f%d.txt" % n)).write_text("x\n", encoding="utf-8")
            self.run_git(work, "add", "-A")
            self.run_git(work, "commit", "-m", message)
        (work / "changed.txt").write_text("\n".join(changed) + "\n", encoding="utf-8", newline="\n")
        self.work, self.origin = work, origin
        return work

    def run_gate(self, root=None):
        root = root or self.work
        out = subprocess.run([self.sh, "-c", gate_script()], cwd=str(root), capture_output=True,
                             text=True, env=self.env, **rs.NOWIN)
        return out.returncode, out.stdout + out.stderr

    def test_a_migration_without_regenerated_types_fails(self):
        """Unchanged behaviour, and the reason the gate exists: a schema migration whose types were
        not regenerated leaves the repo's types lying about the database."""
        self.branch(["feat: add a column"])
        code, out = self.run_gate()
        self.assertEqual(code, 1, out)
        self.assertIn("::error::", out)
        self.assertIn("Types-not-affected:", out, "the error must name the way out")

    def test_a_trailer_with_a_reason_waives_it_and_the_reason_is_printed(self):
        self.branch(["feat: tighten the read policy",
                     "chore: note why",
                     ])
        self.run_git(self.work, "commit", "--allow-empty", "-m",
                     "chore: declare\n\nTypes-not-affected: policy-only migration")
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)
        self.assertIn("policy-only migration", out,
                      "a reviewer who never opens the commits must see the reason in the log")

    def test_a_bare_trailer_with_no_reason_does_not_waive_it(self):
        """The whole value of the hatch is the reason. A trailer anyone can paste without thinking
        is the unsatisfiable gate again, only silent."""
        for message in ("chore: declare\n\nTypes-not-affected:",
                        "chore: declare\n\nTypes-not-affected:    ",
                        "chore: declare\n\nTypes-not-affected"):
            self.branch(["feat: policy", message])
            code, out = self.run_gate()
            self.assertEqual(code, 1, message + " -> " + out)

    def test_the_trailer_is_matched_however_it_is_cased(self):
        self.branch(["feat: policy",
                     "chore: declare\n\ntypes-not-affected: grants only"])
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)

    def test_a_trailer_on_the_base_branch_cannot_waive_this_pull_request(self):
        """`..HEAD`, not `...HEAD`. With three dots the range is symmetric and any commit that ever
        landed on main carrying the trailer would waive every later pull request - a waiver nobody
        on this branch wrote."""
        self.branch(["feat: policy"])
        self.run_git(self.origin, "commit", "--allow-empty", "-m",
                     "chore: someone else\n\nTypes-not-affected: not this branch's business")
        self.run_git(self.work, "fetch", "origin")
        code, out = self.run_gate()
        self.assertEqual(code, 1, out)

    def test_regenerated_types_pass_with_no_trailer_at_all(self):
        self.branch(["feat: add a column"],
                    changed=("supabase/migrations/0001_add.sql", TYPES))
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)

    def test_a_change_with_no_migration_is_not_the_gate_s_business(self):
        self.branch(["feat: a button"], changed=("src/App.tsx",))
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)


class TheDocumentedTrailerIsTheOneTheGateReads(unittest.TestCase):
    """A hatch documented with one spelling and implemented with another is no hatch: the author
    follows the document, CI fails anyway, and the next person edits the workflow."""

    def test_claude_md_and_the_gate_agree(self):
        gates = rs.BUILTIN_PIPELINE[".github/workflows/ci-gates.yml"]
        self.assertIn("Types-not-affected:", gates)
        self.assertIn("Types-not-affected:", rs.PIPELINE_CLAUDE_SECTION)

    def test_the_gate_reads_the_whole_message_not_just_the_subject(self):
        """A trailer belongs in the body. `--format=%s` would read subjects only and never match
        one, which fails in the direction that looks like the gate working."""
        gates = rs.BUILTIN_PIPELINE[".github/workflows/ci-gates.yml"]
        self.assertIn("--format=%B", gates)


if __name__ == "__main__":
    unittest.main()
