"""Tests for the diary classification the kit does at setup time (kit v4.13).

The diary reads a `diary` block out of every repo's own `.teknobu.json`. Until 4.13 that block was
written once, as `{"tier": "private"}`, and raising it meant hand-editing a file per repo - which is
why eighteen repos sat unclassified. These tests cover the three ways it can now be set:

  - `apply --diary-*` and `refresh --diary-*`, so a repo is classified when it is set up;
  - `repo_setup.py diary`, the sweep over every repo the worklog knows about;
  - the validators and the codename generator that both of those go through.

The load-bearing case is *agreement*: `repo_setup.py` writes this block and `diary_agent.py` reads
it, and the kit's one-file-per-tool rule means neither can import the other. So the normalisation is
duplicated, and the first class here compares the two implementations directly on the same inputs.
The worklog's `session_day_minutes` drifted between copies once and nobody noticed for weeks.

Stdlib only, hermetic: HOME is redirected before repo_setup is imported, and every pot is a temp
directory, so nothing here reads or writes the developer's real repos, worklog or settings.
Run from the repo root with:  python -m unittest discover -s tests
"""

import argparse
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-diary-fake-home-")
atexit.register(shutil.rmtree, _FAKE_HOME, ignore_errors=True)
_saved_home = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
os.environ["HOME"] = _FAKE_HOME
os.environ["USERPROFILE"] = _FAKE_HOME

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import diary_agent as da
import repo_setup as rs

for _k, _v in _saved_home.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v


def temp_dir(testcase, prefix="repo-setup-diary-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(shutil.rmtree, str(d), ignore_errors=True)
    return d


def write_config(root, data):
    (root / ".teknobu.json").write_text(json.dumps(data), encoding="utf-8")
    return root


class TheTwoToolsNormaliseTheBlockTheSameWay(unittest.TestCase):
    """`repo_setup.read_diary_block` writes what `diary_agent.repo_diary_cfg` reads. One file per
    tool means the logic cannot be shared, so it is compared instead. A disagreement here is a repo
    classified as one thing by the tool that sets it and another by the tool that publishes it."""

    CASES = [
        ("no config file at all", None),
        ("config with no diary block", {"kit": "4.13"}),
        ("diary block is not an object", {"diary": "own"}),
        ("diary block is null", {"diary": None}),
        ("tier the tools do not know", {"diary": {"tier": "public"}}),
        ("tier empty", {"diary": {"tier": ""}}),
        ("tier in capitals", {"diary": {"tier": "OWN"}}),
        ("tier padded with spaces", {"diary": {"tier": "  nickname  ", "nickname": "Kestrel"}}),
        ("nickname full of whitespace", {"diary": {"tier": "nickname", "nickname": " Kes  trel \n"}}),
        ("description over two lines", {"diary": {"tier": "own", "description": "a scheduling\ntool"}}),
        ("nickname is a number", {"diary": {"tier": "nickname", "nickname": 7}}),
        ("private with leftovers", {"diary": {"tier": "private", "nickname": "Kestrel",
                                              "description": "a scheduling tool"}}),
        ("the whole config is a list", ["not", "an", "object"]),
    ]

    def test_every_shape_normalises_identically(self):
        for label, data in self.CASES:
            root = temp_dir(self)
            if data is not None:
                (root / ".teknobu.json").write_text(json.dumps(data), encoding="utf-8")
            mine, theirs = rs.read_diary_block(root), da.repo_diary_cfg(root)
            self.assertEqual(mine, theirs, "%s: repo_setup says %r, diary_agent says %r"
                             % (label, mine, theirs))

    def test_an_unparseable_config_is_private_in_both(self):
        root = temp_dir(self)
        (root / ".teknobu.json").write_text('{"diary": {"tier": "own",}', encoding="utf-8")
        self.assertEqual(rs.read_diary_block(root), da.repo_diary_cfg(root))
        self.assertEqual(rs.read_diary_block(root)["tier"], "private")

    def test_the_tiers_and_the_default_are_the_same_set(self):
        self.assertEqual(sorted(rs.DIARY_TIERS), sorted(da.TIERS))
        self.assertEqual(da.DEFAULT_TIER, "private")
        self.assertEqual(rs.read_diary_block(temp_dir(self))["tier"], da.DEFAULT_TIER)
        self.assertEqual(rs.DIARY_PRIVATE_LABEL, da.PRIVATE_LABEL)

    def test_the_label_shown_at_setup_is_the_label_the_day_file_will_use(self):
        """The setup command prints what the day-file will call the repo, so the operator sees the
        consequence of the tier at the moment they pick it. It has to be the same string."""
        for block in ({"tier": "private"},
                      {"tier": "private", "nickname": "Kestrel"},
                      {"tier": "nickname", "nickname": "Kestrel"},
                      {"tier": "own", "description": "a scheduling tool"},
                      {"tier": "own"}):
            cfg = dict({"nickname": "", "description": "", "declared": True}, **block)
            self.assertEqual(rs.diary_label(block), da.label_for(cfg), "block %r" % (block,))

    def test_nickname_with_no_codename_is_the_one_case_they_differ_and_it_cannot_be_written(self):
        """`label_for` raises on it and the collect downgrades the project to private for the day.
        repo_setup shows the private label rather than raising - and, more to the point, refuses to
        record the combination at all (see TheTierAndTheDescriptionStayTheOperators)."""
        with self.assertRaises(da.TierError):
            da.label_for({"tier": "nickname", "nickname": "", "description": "", "declared": True})
        self.assertEqual(rs.diary_label({"tier": "nickname"}), rs.DIARY_PRIVATE_LABEL)
        block, _notes = rs.diary_block(rs.read_diary_block(temp_dir(self)), tier="nickname")
        self.assertTrue(block["nickname"], "a tier that cannot work must never be recorded")


class OnlyTheCodenameIsEverGenerated(unittest.TestCase):
    """docs/decisions/0011: classification is an act, never an omission. A tier or a description this
    tool inferred would be a classification nobody made, and the default is private precisely so
    that silence is the closed answer. The codename is the one thing that may be invented, because
    it carries no information about the project by design."""

    def test_a_codename_is_not_derived_from_anything_about_the_repo(self):
        root = temp_dir(self, prefix="acme-holdings-crm-")
        names = set()
        for _ in range(40):
            block, _n = rs.diary_block(rs.read_diary_block(root), tier="nickname", nickname="auto")
            names.add(block["nickname"])
            self.assertIn(block["nickname"], rs.CODENAMES)
        self.assertNotIn("acme", " ".join(names).lower())
        self.assertGreater(len(names), 1, "a fixed answer would be derived from something")

    def test_no_codename_reads_as_a_product_or_a_client(self):
        for word in rs.CODENAMES:
            self.assertTrue(word.isalpha() and word[0].isupper(), word)

    def test_a_generated_codename_avoids_the_ones_in_use(self):
        taken = list(rs.CODENAMES[:-1])
        self.assertEqual(rs.codename(taken), rs.CODENAMES[-1])

    def test_taken_is_matched_regardless_of_case_and_padding(self):
        taken = ["  %s  " % w.upper() for w in rs.CODENAMES[:-1]]
        self.assertEqual(rs.codename(taken), rs.CODENAMES[-1])

    def test_when_every_codename_is_in_use_it_still_returns_a_distinct_one(self):
        got = rs.codename(list(rs.CODENAMES))
        self.assertNotIn(got, rs.CODENAMES)
        self.assertRegex(got, r"^[A-Z][a-z]+ [1-9][0-9]$")

    def test_no_tier_given_keeps_the_one_the_repo_already_has(self):
        root = write_config(temp_dir(self), {"diary": {"tier": "own", "description": "a kit"}})
        block, _n = rs.diary_block(rs.read_diary_block(root), description="a developer kit")
        self.assertEqual(block, {"tier": "own", "description": "a developer kit"})

    def test_nothing_asked_for_means_nothing_written(self):
        root = write_config(temp_dir(self), {"diary": {"tier": "own", "description": "a kit"}})
        args = argparse.Namespace(diary_tier=None, diary_nickname=None, diary_description=None)
        self.assertEqual(rs.diary_from_args(root, args), (None, []))


class TheTierAndTheDescriptionStayTheOperators(unittest.TestCase):
    def test_tier_own_without_a_description_says_what_that_costs(self):
        root = temp_dir(self)
        block, notes = rs.diary_block(rs.read_diary_block(root), tier="own")
        self.assertEqual(block, {"tier": "own"})
        self.assertTrue(any("a project" in n for n in notes), notes)

    def test_tier_nickname_without_a_codename_generates_one_and_says_so(self):
        root = temp_dir(self)
        block, notes = rs.diary_block(rs.read_diary_block(root), tier="nickname")
        self.assertIn(block["nickname"], rs.CODENAMES)
        self.assertTrue(any("codename" in n for n in notes), notes)

    def test_a_key_the_new_tier_does_not_use_is_kept(self):
        """A codename that changed every time a repo was raised and lowered would make the diary
        incoherent between posts - the reader cannot know two names are one project."""
        root = write_config(temp_dir(self), {"diary": {"tier": "nickname", "nickname": "Kestrel"}})
        block, _n = rs.diary_block(rs.read_diary_block(root), tier="private")
        self.assertEqual(block, {"tier": "private", "nickname": "Kestrel"})
        back, _n = rs.diary_block(block, tier="nickname")
        self.assertEqual(back["nickname"], "Kestrel", "the codename must survive the round trip")


class TheValuesAreValidatedBeforeAnythingIsWritten(unittest.TestCase):
    """The description is written into a committed file and printed verbatim into a day-file whose
    whole purpose is to be safe to publish. Same reasoning as `uat_slug`, which is spliced into
    CLAUDE.md: an unchecked string here is a way to write text into a published artefact."""

    def parser(self):
        ap = argparse.ArgumentParser()
        rs.add_diary_args(ap)
        return ap

    def test_an_empty_description_is_refused(self):
        with self.assertRaises(SystemExit):
            self.parser().parse_args(["--diary-description", "   "])

    def test_a_description_longer_than_the_limit_is_refused(self):
        with self.assertRaises(SystemExit):
            self.parser().parse_args(["--diary-description", "x" * (rs.DIARY_LIMITS["description"] + 1)])

    def test_a_control_character_is_refused(self):
        with self.assertRaises(SystemExit):
            self.parser().parse_args(["--diary-nickname", "Kes\x1b[31mtrel"])

    def test_a_tier_the_diary_does_not_know_is_refused(self):
        with self.assertRaises(SystemExit):
            self.parser().parse_args(["--diary-tier", "public"])

    def test_newlines_and_tabs_are_folded_rather_than_refused(self):
        """A pasted sentence with a line break in it is a typing accident, not an attack. It is
        normalised to one line - what must not happen is that the break reaches the day-file."""
        got = self.parser().parse_args(["--diary-description", "a scheduling\n\ttool"])
        self.assertEqual(got.diary_description, "a scheduling tool")

    def test_auto_is_the_one_reserved_nickname(self):
        self.assertEqual(self.parser().parse_args(["--diary-nickname", "AUTO"]).diary_nickname, "auto")
        self.assertEqual(self.parser().parse_args(["--diary-nickname", "Auto Trader"]).diary_nickname,
                         "Auto Trader")


class WritingABlockTouchesNothingElse(unittest.TestCase):
    def test_the_rest_of_the_config_survives(self):
        root = write_config(temp_dir(self), {"kit": "4.10", "work_branch": "prelive",
                                             "protected": ["main"], "uat_project": "fortex-hub"})
        rs.write_diary_block(root, {"tier": "own", "description": "a developer kit"})
        cfg = json.loads((root / ".teknobu.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["work_branch"], "prelive")
        self.assertEqual(cfg["uat_project"], "fortex-hub")
        self.assertEqual(cfg["kit"], "4.10", "the sweep is not a kit upgrade")
        self.assertEqual(cfg["diary"], {"tier": "own", "description": "a developer kit"})

    def test_a_config_it_cannot_parse_stops_it(self):
        """The sweep writes into repos other than the one the session is in. Replacing a config it
        could not read would lose the branch model and the slug with no backup - the v4.6 bug."""
        root = temp_dir(self)
        raw = b'{"kit":"4.10","work_branch":"prelive",}'
        (root / ".teknobu.json").write_bytes(raw)
        with self.assertRaises(SystemExit):
            rs.write_diary_block(root, {"tier": "own"})
        self.assertEqual((root / ".teknobu.json").read_bytes(), raw)

    def test_a_repo_with_no_config_gets_one_holding_only_the_block(self):
        root = temp_dir(self)
        rs.write_diary_block(root, {"tier": "private"})
        self.assertEqual(json.loads((root / ".teknobu.json").read_text(encoding="utf-8")),
                         {"diary": {"tier": "private"}})

    def test_a_dry_run_writes_nothing(self):
        root = write_config(temp_dir(self), {"kit": "4.13"})
        self.assertTrue(rs.write_diary_block(root, {"tier": "own"}, dry=True))
        self.assertNotIn("diary", json.loads((root / ".teknobu.json").read_text(encoding="utf-8")))

    def test_recording_the_same_block_twice_reports_no_change(self):
        root = write_config(temp_dir(self), {"diary": {"tier": "own"}})
        self.assertFalse(rs.write_diary_block(root, {"tier": "own"}))


class TheSweepReadsThePot(unittest.TestCase):
    def pot(self, *slices):
        pot = temp_dir(self)
        (pot / "slices").mkdir()
        for i, s in enumerate(slices):
            (pot / "slices" / ("s%02d.json" % i)).write_text(json.dumps(s), encoding="utf-8")
        return pot

    def test_a_machine_row_is_not_a_repo(self):
        pot = self.pot({"kind": "machine", "name": "DESKTOP"},
                       {"project": "Fortex", "repo": "Fortex", "path": str(temp_dir(self))})
        self.assertEqual([r["project"] for r in rs.pot_repos(pot)], ["Fortex"])

    def test_a_slice_with_no_path_is_skipped_rather_than_read_as_the_current_directory(self):
        self.assertEqual(rs.pot_repos(self.pot({"project": "Fortex", "repo": "Fortex"})), [])

    def test_two_checkouts_of_one_project_are_two_rows_named_apart(self):
        a, b = temp_dir(self), temp_dir(self)
        rows = rs.pot_repos(self.pot({"project": "flex", "repo": "flex", "path": str(a)},
                                     {"project": "flex", "repo": "flex-wt-codex", "path": str(b)}))
        self.assertEqual([r["name"] for r in rows], ["flex", "flex/flex-wt-codex"])

    def test_the_same_path_twice_is_one_row(self):
        a = temp_dir(self)
        rows = rs.pot_repos(self.pot({"project": "flex", "repo": "flex", "path": str(a)},
                                     {"project": "flex", "repo": "flex", "path": str(a)}))
        self.assertEqual(len(rows), 1)

    def test_it_reports_each_repos_own_classification(self):
        a = write_config(temp_dir(self), {"diary": {"tier": "own", "description": "a kit"}})
        b = temp_dir(self)
        rows = rs.pot_repos(self.pot({"project": "kit", "repo": "kit", "path": str(a)},
                                     {"project": "zed", "repo": "zed", "path": str(b)}))
        self.assertEqual([(r["project"], r["tier"], r["declared"]) for r in rows],
                         [("kit", "own", True), ("zed", "private", False)])

    def test_a_repo_that_is_no_longer_on_disk_is_shown_and_marked(self):
        gone = temp_dir(self)
        shutil.rmtree(str(gone), ignore_errors=True)
        rows = rs.pot_repos(self.pot({"project": "old", "repo": "old", "path": str(gone)}))
        self.assertEqual([(r["project"], r["on_disk"]) for r in rows], [("old", False)])

    def test_a_pot_that_does_not_exist_is_empty_not_an_error(self):
        self.assertEqual(rs.pot_repos(temp_dir(self) / "nope"), [])

    def test_a_generated_codename_avoids_the_ones_other_repos_use(self):
        used = temp_dir(self)
        write_config(used, {"diary": {"tier": "nickname", "nickname": rs.CODENAMES[0]}})
        pot = self.pot({"project": "used", "repo": "used", "path": str(used)})
        self.assertEqual(rs.taken_codenames(pot), [rs.CODENAMES[0]])
        self.assertNotEqual(rs.codename(rs.taken_codenames(pot)), rs.CODENAMES[0])

    def test_a_repos_own_codename_does_not_count_against_it(self):
        """Re-running `--nickname auto` on a repo must be able to give it its own name back."""
        used = temp_dir(self)
        write_config(used, {"diary": {"tier": "nickname", "nickname": rs.CODENAMES[0]}})
        pot = self.pot({"project": "used", "repo": "used", "path": str(used)})
        self.assertEqual(rs.taken_codenames(pot, excluding=used), [])

    def test_an_unreadable_pot_never_fails_a_setup(self):
        self.assertEqual(rs.taken_codenames(temp_dir(self) / "missing"), [])


class TheCommandsAskForWhatTheyPass(unittest.TestCase):
    """Kit v4.5 asked question 5 and then ran the command without the flag, so every answer was
    thrown away silently. The question and the flag are checked against each other here."""

    def test_the_setup_command_passes_the_tier_it_asks_for(self):
        self.assertIn("--diary-tier", rs.COMMAND_MD)
        self.assertIn("--diary-tier", rs.NEW_COMMAND_MD)
        self.assertIn("apply --uat-project <slug> --diary-tier <tier>", rs.COMMAND_MD)

    def test_the_refresh_path_carries_the_tier_too(self):
        """The existing-repo path recommends refresh, and refresh is where an already-set-up repo
        gets classified. Naming it without the flags repeats the 4.5 mistake one release later."""
        self.assertIn("refresh --uat-project <slug> --diary-tier <tier>", rs.COMMAND_MD)

    def test_both_commands_say_private_is_the_default_and_must_not_be_guessed(self):
        for md in (rs.COMMAND_MD, rs.NEW_COMMAND_MD, rs.DIARY_COMMAND_MD):
            self.assertIn("[private]" if md is not rs.DIARY_COMMAND_MD else "private", md)
            self.assertRegex(md, r"[Nn]ever (choose for them|choose for the user|infer)")

    def test_the_diary_command_is_installed_and_uninstalled_with_the_rest(self):
        self.assertIn(rs.DIARY_COMMAND_FILE, rs.KIT_COMMAND_FILES)
        self.assertEqual(rs.DIARY_COMMAND_FILE.name, "diary.md")

    def test_the_diary_command_only_ever_runs_the_diary_subcommand(self):
        """It walks other people's repos. It writes one key through one command; it does not edit
        their files, and it does not commit in a repo the session is not in."""
        self.assertIn("diary --repo", rs.DIARY_COMMAND_MD)
        self.assertIn("do not commit them yourself", rs.DIARY_COMMAND_MD)
        self.assertNotIn("git commit", rs.DIARY_COMMAND_MD)


class ApplyAndRefreshRecordTheTier(unittest.TestCase):
    """End to end through the real commands, on a real git repo, because the bug this guards
    against is not in the block-building - it is in the condition around the write."""

    def args(self, root, **kw):
        for k, v in (("dry_run", False), ("uat_project", None), ("force", False),
                     ("update_pipeline", False), ("diary_tier", None),
                     ("diary_nickname", None), ("diary_description", None)):
            kw.setdefault(k, v)
        return argparse.Namespace(repo=str(root), **kw)

    def make_repo(self, seed=None):
        git = shutil.which("git")
        if not git:
            self.skipTest("git not on PATH")
        self.addCleanup(setattr, rs, "ensure_installed", rs.ensure_installed)
        rs.ensure_installed = lambda: False
        self.addCleanup(setattr, rs, "WORK_BRANCH", rs.WORK_BRANCH)
        self.addCleanup(setattr, rs, "PROTECTED", list(rs.PROTECTED))
        root = temp_dir(self)
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                   GIT_CONFIG_NOSYSTEM="1")
        subprocess.run([git, "init", str(root)], capture_output=True, env=env, check=True, **rs.NOWIN)
        if seed is not None:
            write_config(root, seed)
        return root

    def block(self, root):
        return json.loads((root / ".teknobu.json").read_text(encoding="utf-8")).get("diary")

    def test_apply_with_no_flags_still_defaults_to_private(self):
        root = self.make_repo()
        rs.cmd_apply(self.args(root))
        self.assertEqual(self.block(root), {"tier": "private"})

    def test_apply_records_the_tier_it_was_given(self):
        root = self.make_repo()
        rs.cmd_apply(self.args(root, diary_tier="own", diary_description="a scheduling tool"))
        self.assertEqual(self.block(root), {"tier": "own", "description": "a scheduling tool"})

    def test_apply_with_no_flags_never_lowers_a_repo_that_is_already_classified(self):
        """`private` is the safe default for a repo nobody has classified. Re-applying the kit to a
        repo whose tier is `own` must not quietly take it back down to hours-only."""
        root = self.make_repo({"diary": {"tier": "own", "description": "a developer kit"}})
        rs.cmd_apply(self.args(root))
        self.assertEqual(self.block(root), {"tier": "own", "description": "a developer kit"})

    def test_refresh_records_a_tier_on_a_repo_that_is_already_on_this_version(self):
        """The v4.6 regression, exactly: the condition around the write short-circuited when there
        was nothing else to record, so the flag was accepted, reported and thrown away."""
        root = self.make_repo({"kit": rs.VERSION, "work_branch": "prelive"})
        rs.cmd_refresh(self.args(root, diary_tier="nickname", diary_nickname="Kestrel"))
        self.assertEqual(self.block(root), {"tier": "nickname", "nickname": "Kestrel"})

    def test_refresh_with_no_flags_records_no_diary_block_at_all(self):
        root = self.make_repo({"kit": "4.5", "work_branch": "prelive"})
        rs.cmd_refresh(self.args(root))
        self.assertIsNone(self.block(root))

    def test_a_dry_run_apply_writes_no_tier(self):
        root = self.make_repo()
        rs.cmd_apply(self.args(root, dry_run=True, diary_tier="own"))
        self.assertFalse((root / ".teknobu.json").exists())


if __name__ == "__main__":
    unittest.main()
