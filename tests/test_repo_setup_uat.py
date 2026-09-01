"""Tests for the UAT Hub wiring in repo_setup.py (kit v4.5): the .mcp.json merge, slug
resolution, UAT_HUB_KEY in .env.example (and deliberately not in .env.<work>), and the managed
"Writing UAT" block in CLAUDE.md.

The rule these exist to protect: the kit must never write the literal key. .mcp.json is committed
into client repos that may be handed over, and one key covers every project - so a literal in one
repo's history would expose push access for the whole estate. NoLiteralKeyEverWritten puts a real
key in the environment and greps everything the kit produces.

Import safety: same pattern as test_repo_setup_pipeline.py - HOME/USERPROFILE point at a temp dir
around the repo_setup import so the developer machine's config cannot leak in.
Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-uat-fake-home-")
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

# Built at run time, not written as a literal: a key-shaped string in source would trip the
# repo's own pre-commit scanner forever - and a test suite that can only be committed with
# SONELO_SKIP teaches the habit the scanner exists to prevent.
REAL_KEY = "uath" + "_" + "a1b2c3d4" * 8


def make_temp_dir(testcase, prefix="repo-setup-uat-test-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def servers(root):
    return json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


class McpJsonMerge(unittest.TestCase):
    """.mcp.json is committed, may already hold the repo's own servers, and must never carry a key."""

    def test_created_with_the_placeholder_not_a_value(self):
        root = make_temp_dir(self)
        rs.mcp_json(root, rs.Report(False), "fortex-hub")
        env = servers(root)[rs.UAT_MCP_NAME]["env"]
        self.assertEqual(env["UAT_HUB_KEY"], "${UAT_HUB_KEY}",
                         "the key stays a placeholder expanded from the environment")
        self.assertEqual(env["UAT_HUB_URL"], rs.UAT_HUB_URL)
        self.assertEqual(env["UAT_HUB_PROJECT"], "fortex-hub")
        self.assertEqual(servers(root)[rs.UAT_MCP_NAME]["command"], "node")

    def test_second_call_merges_rather_than_duplicating(self):
        root = make_temp_dir(self)
        rs.mcp_json(root, rs.Report(False), "fortex-hub")
        first = (root / ".mcp.json").read_text(encoding="utf-8")
        rep = rs.Report(False)
        rs.mcp_json(root, rep, "fortex-hub")
        self.assertEqual((root / ".mcp.json").read_text(encoding="utf-8"), first,
                         "a second apply must change nothing")
        self.assertEqual([a for a, _ in rep.rows], ["unchanged"])
        self.assertEqual(len(servers(root)), 1)

    def test_another_server_and_other_keys_survive(self):
        """A repo may have its own MCP servers. Only the uat-hub entry is ours."""
        root = make_temp_dir(self)
        (root / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"theirs": {"command": "node", "args": ["./tools/theirs.mjs"]}},
            "someOtherKey": {"kept": True},
        }, indent=2) + "\n", encoding="utf-8")
        rs.mcp_json(root, rs.Report(False), "fortex-hub")
        data = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(data["mcpServers"]["theirs"], {"command": "node", "args": ["./tools/theirs.mjs"]})
        self.assertEqual(data["someOtherKey"], {"kept": True})
        self.assertIn(rs.UAT_MCP_NAME, data["mcpServers"])

    def test_unparseable_file_is_reported_not_replaced(self):
        root = make_temp_dir(self)
        (root / ".mcp.json").write_text("not json at all {{{", encoding="utf-8")
        rep = rs.Report(False)
        rs.mcp_json(root, rep, "fortex-hub")
        self.assertEqual((root / ".mcp.json").read_text(encoding="utf-8"), "not json at all {{{",
                         "a file the kit cannot understand is never overwritten")
        self.assertTrue(any("skipped" in a for a, _ in rep.rows), rep.rows)

    def test_mcp_servers_that_is_not_an_object_does_not_crash(self):
        root = make_temp_dir(self)
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": ["wrong shape"]}) + "\n", encoding="utf-8")
        rs.mcp_json(root, rs.Report(False), "fortex-hub")
        self.assertIn(rs.UAT_MCP_NAME, servers(root))

    def test_replacing_an_existing_file_leaves_a_backup(self):
        root = make_temp_dir(self)
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"theirs": {}}}, indent=2) + "\n",
                                        encoding="utf-8")
        saved = rs.mcp_json(root, rs.Report(False), "fortex-hub")
        self.assertIsNotNone(saved, "a replaced file must leave a copy")
        self.assertIn("theirs", (saved / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual((root / ".claude" / ".backup" / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_dry_run_writes_nothing(self):
        root = make_temp_dir(self)
        rs.mcp_json(root, rs.Report(True), "fortex-hub")
        self.assertFalse((root / ".mcp.json").exists(), "--dry-run must not write")


class UatSlugResolution(unittest.TestCase):
    """The hub fixes a slug at creation and it cannot change, so it is asked for, then remembered."""

    def test_explicit_wins(self):
        root = make_temp_dir(self)
        (root / ".teknobu.json").write_text(json.dumps({"uat_project": "recorded"}), encoding="utf-8")
        self.assertEqual(rs.uat_slug(root, "asked-for"), "asked-for")

    def test_recorded_wins_over_the_folder_name(self):
        root = make_temp_dir(self)
        (root / ".teknobu.json").write_text(json.dumps({"uat_project": "recorded"}), encoding="utf-8")
        self.assertEqual(rs.uat_slug(root), "recorded",
                         "a later apply without the flag must not silently re-slug the repo")

    def test_folder_name_is_the_fallback(self):
        """Sanitised since v4.6: a folder name is not guaranteed to be a legal slug, and the
        slug is spliced into CLAUDE.md."""
        root = make_temp_dir(self)
        self.assertRegex(rs.uat_slug(root), rs.SLUG_RE)

    def test_blank_answers_fall_through(self):
        root = make_temp_dir(self)
        (root / ".teknobu.json").write_text(json.dumps({"uat_project": "   "}), encoding="utf-8")
        self.assertRegex(rs.uat_slug(root, "  "), rs.SLUG_RE)

    def test_survives_a_teknobu_json_that_is_not_an_object(self):
        root = make_temp_dir(self)
        (root / ".teknobu.json").write_text('["not", "an", "object"]\n', encoding="utf-8")
        self.assertRegex(rs.uat_slug(root), rs.SLUG_RE)


class EnvExampleDocumentsTheKey(unittest.TestCase):
    """UAT_HUB_KEY appears wherever the kit documents configuration - with an empty value."""

    def keys(self, path):
        return re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", path.read_text(encoding="utf-8"), re.M)

    def test_written_even_when_there_is_no_env_to_derive_from(self):
        root = make_temp_dir(self)
        rs.env_example(root, rs.Report(False))
        example = root / ".env.example"
        self.assertTrue(example.exists(), "the kit's own keys are documented regardless of a .env")
        self.assertIn("UAT_HUB_KEY", self.keys(example))
        self.assertIn("UAT_HUB_KEY=\n", example.read_text(encoding="utf-8"))

    def test_derived_keys_still_come_from_env(self):
        root = make_temp_dir(self)
        (root / ".env").write_text("VITE_SUPABASE_URL=https://real.example\nOTHER=x\n", encoding="utf-8")
        rs.env_example(root, rs.Report(False))
        text = (root / ".env.example").read_text(encoding="utf-8")
        self.assertEqual(self.keys(root / ".env.example"), ["VITE_SUPABASE_URL", "OTHER", "UAT_HUB_KEY"])
        self.assertNotIn("real.example", text, "values are stripped")

    def test_not_added_twice(self):
        root = make_temp_dir(self)
        rs.env_example(root, rs.Report(False))
        first = (root / ".env.example").read_text(encoding="utf-8")
        rep = rs.Report(False)
        rs.env_example(root, rep)
        self.assertEqual((root / ".env.example").read_text(encoding="utf-8"), first)
        self.assertEqual([a for a, _ in rep.rows], ["unchanged"])

    def test_added_to_an_env_example_that_predates_the_kit(self):
        root = make_temp_dir(self)
        (root / ".env.example").write_text("EXISTING=\n", encoding="utf-8")
        rs.env_example(root, rs.Report(False))
        self.assertEqual(self.keys(root / ".env.example"), ["EXISTING", "UAT_HUB_KEY"])

    def test_env_work_branch_does_not_carry_it(self):
        """.env.<work> is pushed to the hosting provider. UAT_HUB_KEY is a session variable with no
        use in a deployed environment, so spreading it there buys nothing and costs blast radius."""
        root = make_temp_dir(self)
        (root / ".env").write_text("VITE_API_URL=\n", encoding="utf-8")
        rs.env_example(root, rs.Report(False))
        rs.env_prelive(root, rs.Report(False))
        work = root / (".env.%s" % rs.WORK_BRANCH)
        self.assertTrue(work.exists())
        self.assertIn("VITE_API_URL", work.read_text(encoding="utf-8"))
        self.assertNotIn("UAT_HUB_KEY", work.read_text(encoding="utf-8"))


class ClaudeMdUatSection(unittest.TestCase):
    """The block is assembled from uat-hub's docs/AGENT_PROMPT.md plus the two sections it
    handed over in docs/toolkit-uat-block.md (v4.8): it states a field contract the endpoint
    enforces, so the field names are pinned rather than left to a future paraphrase."""

    def test_written_into_a_fresh_claude_md_with_the_slug(self):
        root = make_temp_dir(self)
        rs.claude_md(root, rs.Report(False), "fortex-hub")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("## Writing UAT", text)
        self.assertIn("fortex-hub", text)
        self.assertIn("<!-- sonelo-devkit:uat:start", text)
        self.assertIn("<!-- sonelo-devkit:uat:end -->", text)

    def test_the_field_contract_is_present(self):
        root = make_temp_dir(self)
        rs.claude_md(root, rs.Report(False), "fortex-hub")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        for required in ("push_uat_test_cases", "title", "steps", "expected_result", "test_url",
                         "source_ref", "https://testing.teknobugroup.com/api/uat/test-cases"):
            self.assertIn(required, text, required)

    def test_says_a_push_cannot_create_a_project(self):
        root = make_temp_dir(self)
        rs.claude_md(root, rs.Report(False), "fortex-hub")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("create it in UAT Hub first", text)
        self.assertIn("A push cannot create a project", text)

    def test_rerun_replaces_in_place_and_keeps_the_repos_own_text(self):
        root = make_temp_dir(self)
        rs.claude_md(root, rs.Report(False), "fortex-hub")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        (root / "CLAUDE.md").write_text(text + "\n## House rules\n\nOurs, keep.\n", encoding="utf-8")
        rs.claude_md(root, rs.Report(False), "fortex-hub")
        after = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(after.count("<!-- sonelo-devkit:uat:start"), 1, "no duplicate block")
        self.assertEqual(after.count("## Writing UAT"), 1)
        self.assertIn("## House rules", after)
        self.assertIn("Ours, keep.", after)

    def test_a_changed_slug_is_rewritten_not_appended(self):
        root = make_temp_dir(self)
        rs.claude_md(root, rs.Report(False), "old-slug")
        rs.claude_md(root, rs.Report(False), "new-slug")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("<!-- sonelo-devkit:uat:start"), 1)
        self.assertIn("new-slug", text)
        self.assertNotIn("old-slug", text)

    def test_added_to_a_claude_md_that_predates_the_kit(self):
        root = make_temp_dir(self)
        (root / "CLAUDE.md").write_text("# App\n\nHouse policy, no markers.\n", encoding="utf-8")
        rs.claude_md(root, rs.Report(False), "fortex-hub")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("House policy, no markers.", text)
        self.assertIn("## Writing UAT", text)

    def test_dry_run_writes_nothing(self):
        root = make_temp_dir(self)
        rs.claude_md(root, rs.Report(True), "fortex-hub")
        self.assertFalse((root / "CLAUDE.md").exists())


class NoLiteralKeyEverWritten(unittest.TestCase):
    """The one rule with an estate-wide blast radius: a real key in the environment must not reach
    any file the kit creates."""

    def setUp(self):
        self.saved = os.environ.get(rs.UAT_HUB_KEY_VAR)
        os.environ[rs.UAT_HUB_KEY_VAR] = REAL_KEY
        self.addCleanup(self.restore)

    def restore(self):
        if self.saved is None:
            os.environ.pop(rs.UAT_HUB_KEY_VAR, None)
        else:
            os.environ[rs.UAT_HUB_KEY_VAR] = self.saved

    def test_nothing_the_writers_produce_contains_it(self):
        root = make_temp_dir(self)
        (root / ".env").write_text("%s=%s\n" % (rs.UAT_HUB_KEY_VAR, REAL_KEY), encoding="utf-8")
        rep = rs.Report(False)
        rs.mcp_json(root, rep, "fortex-hub")
        rs.claude_md(root, rep, "fortex-hub")
        rs.env_example(root, rep)
        rs.env_prelive(root, rep)
        offenders = []
        for f in root.rglob("*"):
            if f.is_file() and f.name != ".env":          # the developer's own .env is theirs
                try:
                    if REAL_KEY in f.read_text(encoding="utf-8"):
                        offenders.append(str(f.relative_to(root)))
                except (OSError, UnicodeDecodeError):
                    pass
        self.assertEqual(offenders, [], "the kit wrote the literal key")

    def test_a_key_already_in_env_is_documented_by_name_only(self):
        root = make_temp_dir(self)
        (root / ".env").write_text("%s=%s\n" % (rs.UAT_HUB_KEY_VAR, REAL_KEY), encoding="utf-8")
        rs.env_example(root, rs.Report(False))
        text = (root / ".env.example").read_text(encoding="utf-8")
        self.assertIn("UAT_HUB_KEY=\n", text)
        self.assertNotIn(REAL_KEY, text)
        self.assertEqual(text.count("UAT_HUB_KEY="), 1, "derived and kit-owned must not both add it")


class RefreshTakesTheSlug(unittest.TestCase):
    """`refresh` is the rollout verb for a repo that already has the pipeline, so it has to be able
    to set the hub slug. Without the flag it wired the repo to its folder name, and the only way to
    correct that was `apply` - which also rewrites CI, the environment doc and the design contract
    and checks out the work branch. Far too much blast radius for one string."""

    def args(self, root, **kw):
        import argparse
        kw.setdefault("dry_run", False)
        kw.setdefault("uat_project", None)
        return argparse.Namespace(repo=str(root), **kw)

    def make_repo(self):
        import subprocess
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
        (root / ".teknobu.json").write_text(
            json.dumps({"kit": "4.5", "work_branch": "prelive"}) + "\n", encoding="utf-8")
        return root

    def test_flag_sets_the_slug_everywhere_at_once(self):
        root = self.make_repo()
        rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        self.assertEqual(servers(root)[rs.UAT_MCP_NAME]["env"]["UAT_HUB_PROJECT"], "fortex-hub")
        self.assertIn("fortex-hub", (root / "CLAUDE.md").read_text(encoding="utf-8"))
        cfg = json.loads((root / ".teknobu.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["uat_project"], "fortex-hub")

    def test_the_slug_survives_a_later_plain_refresh(self):
        """The reason it is recorded: otherwise the next refresh reverts to the folder name."""
        root = self.make_repo()
        rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        rs.cmd_refresh(self.args(root))
        self.assertEqual(servers(root)[rs.UAT_MCP_NAME]["env"]["UAT_HUB_PROJECT"], "fortex-hub")

    def test_without_the_flag_refresh_still_owns_no_repo_keys(self):
        root = self.make_repo()
        rs.cmd_refresh(self.args(root))
        cfg = json.loads((root / ".teknobu.json").read_text(encoding="utf-8"))
        self.assertNotIn("uat_project", cfg, "refresh must not invent a key it was not handed")
        self.assertEqual(cfg["work_branch"], "prelive")
        self.assertEqual(cfg["kit"], rs.VERSION)

    def test_a_blank_flag_is_not_a_slug(self):
        root = self.make_repo()
        rs.cmd_refresh(self.args(root, uat_project="   "))
        cfg = json.loads((root / ".teknobu.json").read_text(encoding="utf-8"))
        self.assertNotIn("uat_project", cfg)

    def test_the_flag_can_correct_a_wrong_slug(self):
        root = self.make_repo()
        rs.cmd_refresh(self.args(root, uat_project="typo-hub"))
        rs.cmd_refresh(self.args(root, uat_project="fortex-hub"))
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("fortex-hub", text)
        self.assertNotIn("typo-hub", text)
        self.assertEqual(servers(root)[rs.UAT_MCP_NAME]["env"]["UAT_HUB_PROJECT"], "fortex-hub")

    def test_dry_run_records_nothing(self):
        root = self.make_repo()
        rs.cmd_refresh(self.args(root, uat_project="fortex-hub", dry_run=True))
        cfg = json.loads((root / ".teknobu.json").read_text(encoding="utf-8"))
        self.assertNotIn("uat_project", cfg)
        self.assertFalse((root / ".mcp.json").exists())


class CheckReportsTheWiring(unittest.TestCase):
    def test_status_lists_the_mcp_server(self):
        root = make_temp_dir(self)
        names = [n for n, _ in rs.status(root)[0]]
        self.assertTrue(any(".mcp.json" in n for n in names), names)

    def test_status_flags_it_missing_then_present(self):
        root = make_temp_dir(self)
        before = dict((n, ok) for n, ok in rs.status(root)[0])
        rs.mcp_json(root, rs.Report(False), "fortex-hub")
        after = dict((n, ok) for n, ok in rs.status(root)[0])
        key = [n for n in before if ".mcp.json" in n][0]
        self.assertFalse(before[key])
        self.assertTrue(after[key])


if __name__ == "__main__":
    unittest.main()
