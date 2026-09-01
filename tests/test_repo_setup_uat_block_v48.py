"""Kit v4.8: the shipped "Writing UAT" block, re-synced with the hub and extended.

Two things happened here and both are pinned, because both are the kind of thing that goes
wrong silently in a block nobody diffs:

1. **The kit's copy had drifted from uat-hub's docs/AGENT_PROMPT.md and one line of it was
   wrong.** It told every client repo that pushing the same case twice with the same
   `source_ref` "updates nothing and creates nothing" - so a session that rebuilt a feature
   would not re-push, believing it pointless. The hub's own prompt says the opposite: the
   push *refreshes* that case. The copy was also 64 lines short, missing "Fixing what a
   tester found", "Order cases the way a tester must run them", "Push the whole module, not
   a subset", and the pointer to the read/update tools.

2. **Two new sections arrived from the hub** (its docs/toolkit-uat-block.md): name the login
   profile so a tester can batch a round by sign-in, and verify a push landed before
   reporting it. They were written to be dropped in unchanged, which would have shipped a
   second "If the push is refused" section and a second statement of the source_ref rule -
   so they are merged, and these cases pin that there is exactly one of each.

Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-uat48-fake-home-")
atexit.register(shutil.rmtree, _FAKE_HOME, ignore_errors=True)
_saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
os.environ["HOME"] = _FAKE_HOME
os.environ["USERPROFILE"] = _FAKE_HOME

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import repo_setup as rs

for _k, _v in _saved.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v

BLOCK = rs.fill(rs.UAT_SECTION, UAT_PROJECT="fortex-hub")
# A line-wrap-insensitive view. Asserting on text that spans a line break pins where the hub
# happened to wrap a paragraph, so the next legitimate sync fails for no behavioural reason.
FLAT = " ".join(BLOCK.split())


class SourceRefRuleIsCorrect(unittest.TestCase):
    """The drift that mattered. Everything else in this file is additive; this one was a
    shipped instruction that was false, and it contradicted the section above it telling a
    session to re-push after rebuilding a feature."""

    def test_a_repush_is_described_as_refreshing_the_case(self):
        self.assertIn("refreshes that one case", BLOCK)

    def test_the_wrong_claim_is_gone(self):
        self.assertNotIn("updates nothing and creates nothing", BLOCK,
                         "a session reading this would never re-push a rebuilt feature")

    def test_source_ref_is_stated_once(self):
        self.assertEqual(BLOCK.count("### Always set source_ref"), 1)
        # Counting the heading is not enough: the incoming block stated the rule again as bare
        # prose with no heading of its own, so a duplicate slips straight past a heading count.
        self.assertEqual(FLAT.count("refreshes that one case"), 1)


class NamingTheLogin(unittest.TestCase):
    """A round is slow because the tester keeps signing in as somebody else, not because the
    cases are hard. The block has to say so in both places a tester looks."""

    def test_the_module_carries_the_profile(self):
        self.assertIn("Put the profile first in the module name", BLOCK)
        self.assertIn('module: "Supplier', BLOCK)

    def test_numbering_and_the_profile_are_reconciled(self):
        """The block already told sessions to number modules ("01. Ops login"). Profile-first
        and numbering are both required, so the block says how they combine rather than
        leaving a session to pick one."""
        self.assertIn('"01. Supplier', BLOCK)

    def test_the_steps_name_the_login_as_the_first_instruction(self):
        self.assertIn("And name it again in the steps", BLOCK)
        self.assertIn("Sign in as a supplier user", BLOCK)

    def test_one_login_per_case(self):
        self.assertIn("One login per case", BLOCK)

    def test_credentials_never_go_in_a_case(self):
        self.assertIn("Do not put credentials in a test case", BLOCK)


class VerifyingThePush(unittest.TestCase):

    def test_the_block_says_to_read_the_module_back(self):
        self.assertIn("read_uat_test_cases", BLOCK)
        self.assertIn("Report the number the hub returned, not the number you sent", BLOCK)

    def test_the_created_field_trap_is_explained(self):
        """`created` counts inserts AND source_ref refreshes, so a clean re-push of twelve
        unchanged cases reports twelve and reads like twelve duplicates."""
        self.assertIn("rows it inserted", BLOCK)
        self.assertIn("rows it refreshed", BLOCK)

    def test_a_push_is_not_reported_unchecked(self):
        self.assertIn("never report one you have not checked", BLOCK)


class TheKeyIsNeverPrinted(unittest.TestCase):

    def test_the_block_forbids_printing_any_part_of_it(self):
        self.assertIn("### Never print the key", BLOCK)
        self.assertIn('not "the key starts with"', BLOCK)

    def test_the_registry_route_captures_rather_than_echoes(self):
        """reg query's raw output contains the key. The one-liner has to assign it and pass it
        as an environment variable; a version that echoed it would leak into every transcript."""
        line = [l for l in BLOCK.splitlines() if "K=$(reg query" in l]
        self.assertEqual(len(line), 1, "one registry recipe, not several")
        self.assertNotIn("echo", line[0])
        self.assertIn('UAT_HUB_KEY="$K"', BLOCK)

    def test_the_grep_binary_trap_is_called_out(self):
        """Without -a, grep treats reg query's output as binary and reports no match at all -
        which reads as "no key set" rather than as a grep problem."""
        self.assertIn("`grep` needs `-a`", FLAT)

    def test_the_tail_does_not_forbid_what_the_recipe_requires(self):
        """The kit-only tail said "never echo, print or interpolate" while the recipe above it
        captures the value into a variable - two shipped instructions in one document, mutually
        exclusive. That is the exact failure mode this whole change exists to remove."""
        self.assertNotIn("Never echo, print or interpolate", FLAT)
        self.assertIn("Capturing it into a variable is done only as the registry route", FLAT)

    def test_no_literal_key_is_shipped(self):
        for probe in ("uath_", "sk-", "Bearer uat"):
            self.assertNotIn(probe, BLOCK, probe)


class MergedNotAppended(unittest.TestCase):
    """toolkit-uat-block.md says "drop in unchanged"; the kit's block already had a refusal
    section, so dropping it in unchanged would have shipped two, with different advice."""

    def test_exactly_one_refusal_section(self):
        self.assertEqual(BLOCK.count("If the push is refused") + BLOCK.count("If a push is refused"), 1)

    def test_the_restart_and_the_registry_route_are_both_offered(self):
        self.assertIn("Restart Claude Code and try once more", FLAT)
        self.assertIn("without restarting anything", FLAT)

    def test_rotation_still_needs_more_than_one_401(self):
        self.assertIn("Do not rotate a key on the strength of one 401", FLAT)


class ResyncedSectionsAreBack(unittest.TestCase):
    """The four sections the kit's copy had lost. Each one changes what a session does, and
    their absence is why this was a re-sync rather than an append."""

    def test_fixing_what_a_tester_found(self):
        self.assertIn("### Fixing what a tester found", BLOCK)
        self.assertIn("update_uat_test_cases", BLOCK)
        self.assertIn("Only the fields you send change", BLOCK)

    def test_console_output_is_withheld_by_default(self):
        """It comes from the client's live system and routinely carries access tokens."""
        self.assertIn("include_console", BLOCK)
        self.assertIn("withheld by default", BLOCK)

    def test_ordering_and_numbering(self):
        self.assertIn("### Order cases the way a tester must run them", BLOCK)
        self.assertIn("the case that CREATES it comes first", BLOCK)

    def test_push_the_whole_module(self):
        self.assertIn("Push the whole module, not a subset", BLOCK)

    def test_the_read_and_update_tools_are_pointed_at(self):
        self.assertIn("Two more tools exist", BLOCK)


class StillRendersAsOneManagedBlock(unittest.TestCase):

    def test_the_slug_is_substituted_and_no_placeholder_survives(self):
        self.assertIn("fortex-hub", BLOCK)
        self.assertNotIn("{UAT_PROJECT}", BLOCK)
        self.assertNotIn("<project-slug>", BLOCK)

    def test_the_markers_still_wrap_it(self):
        self.assertTrue(BLOCK.lstrip().startswith("<!-- sonelo-devkit:uat:start"))
        self.assertIn("<!-- sonelo-devkit:uat:end -->", BLOCK)
        self.assertIn("v%s" % rs.VERSION, BLOCK.splitlines()[0])

    def test_the_repo_specific_tail_survived_the_resync(self):
        """The hub's prompt knows nothing about how a kit repo is wired; that tail is the
        kit's own and a re-sync must not drop it."""
        self.assertIn("### How this repo is wired", BLOCK)
        self.assertIn("testing.teknobugroup.com", BLOCK)


if __name__ == "__main__":
    unittest.main()
