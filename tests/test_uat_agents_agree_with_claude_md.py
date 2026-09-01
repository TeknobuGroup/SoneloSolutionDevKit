"""The shipped agents must not contradict the shipped CLAUDE.md.

v4.5 put a "Writing UAT" block into every generated CLAUDE.md saying "Do NOT write them to a
Markdown file - the hub is where a human tester picks them up." The `uat-writer` agent shipped
alongside it still said "You write docs/uat/<branch>-<date>.md", and `/pr` plus `ci-gates.yml`
*require* that file or the pull request fails. So a session obeying CLAUDE.md pushed to the hub,
wrote no file, and then failed its own PR gate; a session obeying the agent wrote a file and never
pushed, leaving the hub empty. Two shipped instructions, mutually exclusive, both enforced.

These cases pin the resolution: the cases go to the hub, a short record goes to docs/uat/ so the
gate is satisfied and a reviewer can see scope, and the field contract lives in exactly one place.

Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-uatagents-fake-home-")
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

WRITER = rs.BUILTIN_PIPELINE[".claude/agents/uat-writer.md"]
PR = rs.BUILTIN_PIPELINE[".claude/commands/pr.md"]


class UatWriterPushesToTheHub(unittest.TestCase):
    def test_it_pushes_rather_than_only_writing_a_file(self):
        self.assertIn("UAT Hub", WRITER)
        self.assertIn("push", WRITER.lower())

    def test_it_defers_to_the_claude_md_block_for_the_contract(self):
        """The block is generated from the hub's docs/AGENT_PROMPT.md, merged with the two sections
        from its docs/toolkit-uat-block.md (v4.8), and states a contract
        the endpoint enforces. A second shipped copy would drift, and silently."""
        self.assertIn("Writing UAT", WRITER)
        self.assertIn("CLAUDE.md", WRITER)

    def test_the_field_contract_is_not_duplicated_in_the_agent(self):
        """If the agent restated the fields, a change to the endpoint would have to be made twice
        and nothing would notice when it was made once."""
        fields = ["expected_result", "test_url"]
        present = [f for f in fields if f in WRITER]
        self.assertEqual(present, [], "field contract restated in the agent: %s" % present)

    def test_it_still_leaves_a_record_for_the_pull_request(self):
        """ci-gates.yml fails a PR when code changed and docs/uat/ has no document. Pushing to the
        hub and writing nothing would fail the kit's own gate on every PR."""
        self.assertIn("docs/uat/", WRITER)
        self.assertIn("source_ref", WRITER)

    def test_it_does_not_duplicate_the_cases_into_that_record(self):
        self.assertIn("record, not a duplicate", WRITER)

    def test_a_repo_with_no_hub_project_still_gets_usable_uat(self):
        """Wiring is inert until a project exists - that must not mean a branch gets no UAT."""
        self.assertIn("not available", WRITER)
        self.assertIn("Never invent a project slug", WRITER)


class TheGateAndTheAgentAgree(unittest.TestCase):
    def test_pr_describes_the_document_as_a_record_of_the_push(self):
        self.assertIn("pushes the cases to UAT Hub", PR)

    def test_the_gate_still_requires_a_document(self):
        gates = rs.BUILTIN_PIPELINE[".github/workflows/ci-gates.yml"]
        self.assertIn("docs/uat/", gates)

    def test_claude_md_and_the_agent_do_not_contradict_each_other(self):
        """The exact sentence that made them mutually exclusive."""
        self.assertIn("Do NOT write them to a Markdown file", rs.UAT_SECTION)
        self.assertNotIn("You write `docs/uat/", WRITER)


if __name__ == "__main__":
    unittest.main()
