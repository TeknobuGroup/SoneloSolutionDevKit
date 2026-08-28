"""Tests for what the kit tells an operator to type, and the commands it installs (kit v4.6).

The bug these exist for: `python ~/.claude/sonelo/repo_setup.py ...` shipped in every generated
PRELIVE.md/STAGING.md. PowerShell passes `~` through literally rather than expanding it, so python
resolves it against the working directory and the command dies with ENOENT - on a kit whose stated
first-class platform is Windows. `$HOME` is a variable in both PowerShell and sh, so one form works
in both, and NoTildeCommands scans the whole module so a new template cannot reintroduce it.

Import safety: same pattern as the other repo_setup tests - HOME/USERPROFILE point at a temp dir
around the import so the developer machine's config cannot leak in, which also means the command
files these tests create and delete are inside that temp dir, never the real ~/.claude.
Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-commands-fake-home-")
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

SOURCE = Path(rs.__file__).with_suffix(".py").read_text(encoding="utf-8")


class NoTildeCommands(unittest.TestCase):
    """A command the kit prints must run in PowerShell as well as sh."""

    def test_module_ships_no_python_tilde_command(self):
        offenders = [l.strip() for l in SOURCE.splitlines() if re.search(r"python\s+~/", l)]
        self.assertEqual(offenders, [], "PowerShell does not expand ~ for a native command; use \"$HOME/...\"")

    def test_the_generated_environment_doc_is_powershell_safe(self):
        doc = rs.fill(rs.PRELIVE_MD, REPO="app", WORK="prelive", WORKU="PRELIVE", MAIN="main",
                      UAT_HUB=rs.UAT_HUB_URL, DEPLOY_LINE="", SUPABASE_TODO="")
        self.assertNotIn("python ~/", doc)
        self.assertIn('python "$HOME/.claude/sonelo/repo_setup.py" protect', doc)

    def test_every_command_template_uses_the_portable_form(self):
        for name in ("COMMAND_MD", "NEW_COMMAND_MD", "LANDING_COMMAND_MD", "UPDATE_COMMAND_MD"):
            tpl = getattr(rs, name)
            self.assertNotIn("python ~/", tpl, name)

    def test_no_template_still_points_at_the_pre_v4_home(self):
        """~/.claude/teknobu was renamed to ~/.claude/sonelo in v4.0; a template left behind sends
        the operator to a path that has not existed for four releases."""
        self.assertNotIn(".claude/teknobu/repo_setup.py", SOURCE)


class UpdateCommand(unittest.TestCase):
    """The machine update was only reachable through a session-start nudge; dismiss it and there was
    nothing to type."""

    def test_the_template_is_a_valid_command_file(self):
        tpl = rs.UPDATE_COMMAND_MD
        self.assertTrue(tpl.startswith("---\n"), "a slash command needs frontmatter")
        self.assertIn("description:", tpl.split("---")[1])
        self.assertIn('repo_setup.py" update', tpl)

    def test_it_does_not_invent_a_manual_install(self):
        """The failure mode worth blocking: a session that cannot run update going off to download
        and unpack a release by hand."""
        self.assertIn("Do not fetch, unpack or install a release by hand.", rs.UPDATE_COMMAND_MD)

    def test_it_points_on_to_refresh(self):
        self.assertIn("refresh", rs.UPDATE_COMMAND_MD)

    def test_all_four_commands_are_owned(self):
        names = {p.name for p in rs.KIT_COMMAND_FILES}
        self.assertEqual(names, {"repo-setup.md", "new-repo.md", "landing.md", "update.md"})

    def test_uninstall_removes_every_one_of_them(self):
        """landing.md was written by install and never removed by uninstall - it outlived the kit."""
        import argparse
        for f in rs.KIT_COMMAND_FILES:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x", encoding="utf-8")
        rs.cmd_uninstall(argparse.Namespace())
        left = [f.name for f in rs.KIT_COMMAND_FILES if f.exists()]
        self.assertEqual(left, [], "uninstall must not leave a command behind")

    def test_the_nudge_names_something_the_user_can_type(self):
        self.assertIn("/update", SOURCE, "the release nudge should name the command, not only a path")


if __name__ == "__main__":
    unittest.main()
