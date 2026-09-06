"""`doctor` must check the variable the repo's own .mcp.json names, not the one this platform writes.

4.14 fixed the nested `${HOME:-${USERPROFILE}}` reference that never resolved, and made `mcp_json`
preserve whichever canonical reference a file already carries so a mixed-platform team sees no
churn. Those two together opened a narrower version of the same hole: a repo set up on macOS keeps
`${HOME}/uat-hub/mcp/server.mjs`, a Windows developer clones it, and HOME is not a Windows
environment variable - so Claude Code cannot resolve the reference and the server never starts.

Every check reported that repo healthy. `mcp_ok` accepts either reference by design, doctor's
existence check resolves `~` through Python's expanduser (USERPROFILE on Windows) and finds the
file, and doctor's guard read `"USERPROFILE" if os.name == "nt" else "HOME"` - the variable the
*platform* would write, which is always set on the platform that writes it. A check that cannot
fail is not a check, one level along from the release that said so.

Run from the repo root with:  python -m unittest discover -s tests
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_FAKE_HOME = tempfile.mkdtemp(prefix="repo-setup-doctor-var-fake-home-")
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

WINDOWS_REF = "${USERPROFILE}/uat-hub/mcp/server.mjs"
POSIX_REF = "${HOME}/uat-hub/mcp/server.mjs"

# The pair below is what the *other* platform writes - the case the no-churn exception in
# `mcp_json` creates, and the one the round-1 doctor defect was about. Naming it relative to the
# machine matters: hardcoding POSIX_REF passes here and takes the same-platform branch on CI's
# ubuntu-latest, where the assertion it exists to make is silently not made.
FOREIGN_REF = POSIX_REF if os.name == "nt" else WINDOWS_REF
FOREIGN_VAR = "HOME" if os.name == "nt" else "USERPROFILE"
NATIVE_VAR = "USERPROFILE" if os.name == "nt" else "HOME"


class DoctorReadsTheVariableTheRepoActuallyNames(unittest.TestCase):

    def repo(self, ref):
        """A repo whose .mcp.json carries `ref` as the launch target. None writes no file at all."""
        root = Path(tempfile.mkdtemp(prefix="repo-setup-doctor-var-"))
        self.addCleanup(shutil.rmtree, str(root), ignore_errors=True)
        if ref is not None:
            (root / ".mcp.json").write_text(json.dumps({"mcpServers": {rs.UAT_MCP_NAME: {
                "command": "node", "args": [ref],
                "env": {"UAT_HUB_URL": rs.UAT_HUB_URL, "UAT_HUB_KEY": "${UAT_HUB_KEY}"}}}},
                indent=2), encoding="utf-8")
        return root

    def set_env(self, **values):
        """Set or unset environment variables for one test."""
        for name, value in values.items():
            old = os.environ.get(name)
            self.addCleanup(os.environ.__setitem__, name, old) if old is not None \
                else self.addCleanup(os.environ.pop, name, None)
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_a_mac_written_reference_is_checked_against_HOME(self):
        """The case the no-churn exception created. On Windows HOME is absent, so this must warn -
        the old guard checked USERPROFILE, which is set, and said nothing."""
        self.assertEqual(rs.mcp_ref_var(self.repo(POSIX_REF)), "HOME")

    def test_a_windows_written_reference_is_checked_against_USERPROFILE(self):
        """The mirror case, which is live in this repo now: .mcp.json was rewritten to
        ${USERPROFILE}, so every macOS clone of the kit hits it."""
        self.assertEqual(rs.mcp_ref_var(self.repo(WINDOWS_REF)), "USERPROFILE")

    def test_with_no_repo_it_falls_back_to_what_this_platform_would_write(self):
        expected = "USERPROFILE" if os.name == "nt" else "HOME"
        self.assertEqual(rs.mcp_ref_var(None), expected)

    def test_with_no_mcp_json_it_falls_back_the_same_way(self):
        expected = "USERPROFILE" if os.name == "nt" else "HOME"
        self.assertEqual(rs.mcp_ref_var(self.repo(None)), expected)

    def test_a_redirected_reference_falls_back_rather_than_raising(self):
        """Drift is mcp_ok's business and it reports it. This must not raise or invent a variable -
        a doctor that dies reports nothing at all."""
        self.assertIn(rs.mcp_ref_var(self.repo("./tools/uat-hub/mcp/server.mjs")),
                      ("HOME", "USERPROFILE"))

    def test_it_warns_when_the_named_variable_is_missing_from_this_machine(self):
        self.set_env(HOME=None)
        line = rs.mcp_var_warning(self.repo(POSIX_REF))
        self.assertIsNotNone(line, "HOME is unset and .mcp.json names it - this must warn")
        self.assertIn("HOME", line)
        self.assertNotIn("USERPROFILE is not set", line or "")

    def test_it_stays_silent_when_the_named_variable_is_set(self):
        self.set_env(HOME="/home/someone")
        self.assertIsNone(rs.mcp_var_warning(self.repo(POSIX_REF)))

    def test_the_warning_says_the_reference_came_from_another_platform(self):
        """Without this the reader is told to set HOME on Windows, which is the wrong fix: the
        reference is what is wrong, and `refresh` rewrites it."""
        self.set_env(**{FOREIGN_VAR: None})
        line = rs.mcp_var_warning(self.repo(FOREIGN_REF)) or ""
        self.assertIn("refresh", line)
        self.assertIn(rs.UAT_HUB_SERVER_REF, line)

    def test_the_platform_variable_being_set_does_not_excuse_the_named_one(self):
        """The whole defect in one assertion."""
        self.set_env(**{FOREIGN_VAR: None, NATIVE_VAR: "/somewhere/that/exists"})
        self.assertIsNotNone(rs.mcp_var_warning(self.repo(FOREIGN_REF)))


if __name__ == "__main__":
    unittest.main()
