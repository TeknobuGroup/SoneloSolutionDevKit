"""Tests for the Lovable migration sweep (kit v4.11).

The defect these exist to prevent is not a crash. It is a migration that appears to have happened:
the code moves to a new repo, the app carries on working, and it carries on working because it is
still reading Lovable Cloud's database through a URL hardcoded in `src/integrations/supabase/client.ts`
that no env file controls. Nothing fails, so nobody looks - until the Lovable project lapses.

So the cases here pin three things: that the sweep names what still ties a repo to Lovable, that the
gate fails while any of it is left and passes once it is gone, and that a sweep which reads `.env`
files never puts a value from one in front of anyone.

Run from the repo root with:  python -m unittest discover -s tests
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import repo_setup as rs

KIT = Path(__file__).resolve().parents[1]

# A value that must never be echoed back by anything the sweep prints or writes. Built at run time
# so a key-shaped literal never sits in the source for the repo's own pre-commit scanner to find.
FAKE_SECRET = "sk" + "_live_" + "z9y8x7w6v5u4t3s2r1q0"
LOVABLE_REF = "pxqckcvyymppsrulnebb"

LOVABLE_FILES = {
    "index.html": (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" />\n'
        "<title>demo - Lovable Generated Project</title>\n"
        '<meta name="author" content="Lovable" />\n'
        '<meta name="description" content="Lovable Generated Project" />\n'
        '<meta property="og:image" content="https://lovable.dev/opengraph-image-p98pqg.png" />\n'
        '<meta name="twitter:site" content="@lovable_dev" />\n'
        '</head><body><div id="root"></div>\n'
        '<script src="https://cdn.gpteng.co/gptengineer.js" type="module"></script>\n'
        "</body></html>\n"
    ),
    "package.json": (
        '{"name": "vite_react_shadcn_ts", "dependencies": {"@supabase/supabase-js": "^2.45.0"},\n'
        ' "devDependencies": {"lovable-tagger": "^1.1.7"}}\n'
    ),
    "src/integrations/supabase/client.ts": (
        'import { createClient } from "@supabase/supabase-js";\n'
        'const SUPABASE_URL = "https://%s.supabase.co";\n'
        "export const supabase = createClient(SUPABASE_URL, \"anon\");\n" % LOVABLE_REF
    ),
    "src/lib/ai.ts": 'await fetch("https://ai.gateway.lovable.dev/v1/chat/completions");\n',
    "src/lib/odd.ts": 'await fetch("https://telemetry.some-vendor-nobody-knows.io/v1");\n',
    "supabase/functions/pay/index.ts": (
        'await fetch("https://api.stripe.com/v1/charges");\n'
        'await fetch("https://hooks.zapier.com/hooks/catch/1/2/");\n'
        'const k = Deno.env.get("STRIPE_SECRET_KEY");\n'
    ),
    "supabase/config.toml": 'project_id = "%s"\n' % LOVABLE_REF,
    ".env": (
        "VITE_SUPABASE_URL=https://%s.supabase.co\n"
        "VITE_SUPABASE_PUBLISHABLE_KEY=eyJhbGciOiJIUzI1NiJ9.notreal\n"  # sonelo:allow
        "STRIPE_SECRET_KEY=%s\n" % (LOVABLE_REF, FAKE_SECRET)
    ),
    "public/placeholder.svg": "<svg></svg>\n",
    "public/favicon.ico": "icon\n",
    "README.md": "# demo\n\nBuilt with [Lovable](https://lovable.dev/projects/x).\n",
}

MIGRATED_FILES = {
    "index.html": (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" />\n'
        "<title>Sonelo Solutions</title>\n"
        '<meta name="description" content="Field operations." />\n'
        '<meta property="og:title" content="Sonelo Solutions" />\n'
        '<meta property="og:description" content="Field operations." />\n'
        '<meta property="og:image" content="https://sonelo.co.uk/og.png" />\n'
        '<meta property="og:url" content="https://sonelo.co.uk/" />\n'
        '<meta name="twitter:card" content="summary_large_image" />\n'
        '</head><body><div id="root"></div></body></html>\n'
    ),
    "package.json": '{"name": "sonelo-solutions", "dependencies": {"@supabase/supabase-js": "^2.45.0"}}\n',
    "src/integrations/supabase/client.ts": (
        'import { createClient } from "@supabase/supabase-js";\n'
        "export const supabase = createClient(import.meta.env.VITE_SUPABASE_URL,\n"
        "                                     import.meta.env.VITE_SUPABASE_ANON_KEY);\n"
    ),
    "supabase/config.toml": 'project_id = "abcdefghijklmnopqrst"\n',
    ".env": "VITE_SUPABASE_URL=https://abcdefghijklmnopqrst.supabase.co\nVITE_SUPABASE_ANON_KEY=notreal\n",
    "README.md": "# sonelo-solutions\n",
    "robots.txt": "User-agent: *\n",
}


def build(root, files, remote="https://github.com/lovable-user/demo.git"):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if remote:
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", remote], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return root


class SweepFindsWhatTiesTheRepoToLovable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kit-lovable-")
        cls.root = build(Path(cls.tmp) / "demo", LOVABLE_FILES)
        cls.scan = rs.lovable_scan(cls.root)
        cls.blockers = rs.lovable_blockers(cls.scan)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_ai_gateway_and_the_tagger_script_are_both_found(self):
        joined = "\n".join(self.blockers)
        self.assertIn("ai.gateway.lovable.dev", joined)
        # The script tag outlives the dependency: removing lovable-tagger from package.json
        # leaves cdn.gpteng.co in the markup, still loading on every page view.
        self.assertIn("gpteng.co", joined)

    def test_every_external_host_is_reported_including_ones_we_cannot_name(self):
        self.assertIn("api.stripe.com", self.scan["hosts"])
        self.assertIn("hooks.zapier.com", self.scan["hosts"])
        self.assertEqual("Zapier", rs.service_of("hooks.zapier.com"))
        table = rs.lovable_connections_md(self.scan)
        # An unrecognised host must appear and must be marked as needing identification: dropping it
        # for not being in the table would be the sweep quietly deciding it is safe. It is pinned on a
        # host that is unknowable by construction, not on one the table may later learn to name.
        self.assertIn("telemetry.some-vendor-nobody-knows.io", self.scan["hosts"])
        self.assertEqual("", rs.service_of("telemetry.some-vendor-nobody-knows.io"))
        self.assertIn("telemetry.some-vendor-nobody-knows.io", table)
        self.assertIn("unrecognised", table)

    def test_the_automation_hosts_a_no_code_app_actually_carries_are_named(self):
        # A Lovable app is wired together with webhooks and integration platforms far more often than
        # with SDKs, so these are the connections a migration most often has to decide about - and the
        # table was silent on every one of them, which made the report noisiest in its commonest case.
        for host, name in (("hooks.zapier.com", "Zapier"), ("hook.eu1.make.com", "Make"),
                           ("teknobu.app.n8n.cloud", "n8n"), ("api.airtable.com", "Airtable"),
                           ("demo.firebaseio.com", "Firebase"), ("s3.eu-west-2.amazonaws.com", "AWS"),
                           ("api.clerk.dev", "Clerk"), ("api.paypal.com", "PayPal")):
            self.assertEqual(name, rs.service_of(host), host)
        # ...without swallowing a host an earlier, more specific entry already claims.
        self.assertEqual("CDN", rs.service_of("cdnjs.cloudflare.com"))

    def test_a_description_left_at_lovables_default_is_a_blocker(self):
        # Only the presence of a description was checked, so "Lovable Generated Project" passed the
        # sweep and went on appearing under the app's own name in every search result.
        found = [(n, b) for _, n, b in rs.lovable_branding(self.root, self.scan)
                 if "description" in n and "og:" not in n]
        self.assertTrue(found, "the meta description was not examined at all")
        self.assertTrue(any(b for _, b in found),
                        "a Lovable default description must block: %s" % found)

    def test_the_command_and_the_document_say_the_same_thing_about_a_connection(self):
        # The command is what a person runs; the document is what they follow afterwards. A Supabase
        # project labelled just "Supabase" in the command reads as theirs, which is the single
        # misreading this whole release exists to remove - so the two must not be able to disagree.
        host = "%s.supabase.co" % LOVABLE_REF
        self.assertIn("Lovable Cloud", rs.connection_origin(host, self.scan))
        out = subprocess.run([sys.executable, str(KIT / "repo_setup.py"), "lovable", "--repo", str(self.root)],
                             capture_output=True, text=True)
        self.assertIn("Lovable Cloud", out.stdout)
        self.assertIn(rs.connection_origin(host, self.scan), rs.lovable_connections_md(self.scan))

    def test_a_supabase_project_is_lovables_while_lovable_traces_remain(self):
        # The ref is in .env - but before the cutover that env file is Lovable's too.
        self.assertIn(LOVABLE_REF, self.scan["env_refs"])
        self.assertIn("Lovable Cloud", rs.lovable_connections_md(self.scan))

    def test_the_branding_findings_say_which_ones_block(self):
        blocking = [n for _, n, b in self.scan["branding"] if b]
        soft = [n for _, n, b in self.scan["branding"] if not b]
        self.assertTrue(any("tagger script tag" in n for n in blocking))
        self.assertTrue(any("still a default" in n for n in blocking))
        # A favicon cannot be judged from its bytes. It is work to confirm, never a failed gate.
        self.assertTrue(any("favicon" in p for p, _, b in self.scan["branding"] if not b))
        self.assertTrue(soft)

    def test_node_modules_is_not_swept(self):
        buried = self.root / "node_modules" / "some-pkg" / "index.js"
        buried.parent.mkdir(parents=True, exist_ok=True)
        buried.write_text('fetch("https://ai.gateway.lovable.dev/x");\n', encoding="utf-8")
        again = rs.lovable_scan(self.root)
        self.assertNotIn("node_modules/some-pkg/index.js",
                         set().union(*again["hosts"].values()) if again["hosts"] else set())

    def test_the_git_remote_is_reported_so_lovables_repo_can_be_spotted(self):
        self.assertEqual("lovable-user/demo", self.scan["remote"])


class TheSweepNeverPrintsAnEnvValue(unittest.TestCase):
    """It reads `.env` files, so this is the one thing it must be incapable of doing. A project ref is
    the deliberate exception: it is public and it is in the dashboard URL."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kit-lovable-sec-")
        cls.root = build(Path(cls.tmp) / "demo", LOVABLE_FILES)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_env_value_reaches_the_command_output(self):
        out = subprocess.run([sys.executable, str(KIT / "repo_setup.py"), "lovable", "--repo", str(self.root)],
                             capture_output=True, text=True)
        self.assertNotIn(FAKE_SECRET, out.stdout + out.stderr)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", out.stdout + out.stderr)
        # the key NAME is what a connections sweep is for
        self.assertIn("STRIPE_SECRET_KEY", out.stdout)

    def test_no_env_value_reaches_the_generated_migration_document(self):
        rs.lovable_notes(self.root, {}, rs.Report(False))
        md = (self.root / "MIGRATION.md").read_text(encoding="utf-8")
        self.assertNotIn(FAKE_SECRET, md)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", md)
        self.assertIn(LOVABLE_REF, md)

    def test_credentials_in_a_url_are_dropped_rather_than_reported(self):
        self.assertEqual("api.example.io", rs.host_of("admin:hunter2@api.example.io:8443"))


class TheGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit-lovable-gate-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_gate(self, root):
        return subprocess.run([sys.executable, str(KIT / "repo_setup.py"), "lovable", "--repo", str(root), "--strict"],
                              capture_output=True, text=True)

    def test_it_fails_while_lovable_is_still_in_the_tree(self):
        root = build(Path(self.tmp) / "dirty", LOVABLE_FILES)
        self.assertEqual(1, self.run_gate(root).returncode)

    def test_it_passes_once_the_migration_is_done(self):
        root = build(Path(self.tmp) / "clean", MIGRATED_FILES, remote="https://github.com/TeknobuGroup/demo.git")
        out = self.run_gate(root)
        self.assertEqual(0, out.returncode, out.stdout)
        # Passing the gate is not the same as nothing being left to do, and it must not claim otherwise.
        self.assertIn("still a person's decisions", out.stdout)

    def test_a_hardcoded_ref_that_no_env_file_names_blocks_on_its_own(self):
        files = dict(MIGRATED_FILES)
        files["src/integrations/supabase/client.ts"] = (
            'export const url = "https://qqqqwwwweeeerrrrtttt.supabase.co";\n')
        root = build(Path(self.tmp) / "stale", files, remote="https://github.com/TeknobuGroup/demo.git")
        out = self.run_gate(root)
        self.assertEqual(1, out.returncode)
        self.assertIn("qqqqwwwweeeerrrrtttt", out.stdout)

    def test_a_file_it_cannot_read_is_reported_rather_than_passed_over(self):
        # UTF-16 is routine on Windows (PowerShell redirection writes it). Failing closed matters:
        # a gate that silently skips what it cannot read reports "clean" for a repo it never swept.
        root = build(Path(self.tmp) / "utf16", MIGRATED_FILES, remote="https://github.com/TeknobuGroup/demo.git")
        (root / "src" / "odd.ts").write_bytes("const x = 1;\n".encode("utf-16"))
        out = self.run_gate(root)
        self.assertEqual(1, out.returncode)
        self.assertIn("could not be read", out.stdout)


class TheGeneratedChecklist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kit-lovable-md-")
        cls.root = build(Path(cls.tmp) / "demo", LOVABLE_FILES)
        rs.lovable_notes(cls.root, {}, rs.Report(False))
        cls.md = (cls.root / "MIGRATION.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_token_is_filled(self):
        self.assertEqual([], sorted(set(re.findall(r"\{[A-Z_]+\}", self.md))))

    def test_it_carries_all_three_sweeps(self):
        for heading in ("## 1. New instances", "## 2. Connections sweep", "## 4. SEO, branding"):
            self.assertIn(heading, self.md)

    def test_it_says_both_databases_and_never_to_reuse_lovables(self):
        self.assertIn("both databases", self.md)
        # The trap this whole change exists for: --only <work> is right for an app with a production
        # project of yours, and wrong for every Lovable repo. It may appear only as a prohibition.
        for line in self.md.splitlines():
            if "--only %s" % rs.WORK_BRANCH in line:
                self.assertRegex(line, r"[Dd]o not pass")

    def test_it_names_the_region_and_keeps_the_password_out_of_the_session(self):
        self.assertIn(rs.DEFAULT_SUPABASE_REGION, self.md)
        self.assertIn("project ref", self.md)
        self.assertIn("password manager", self.md)


class TheRepoSetupPrompt(unittest.TestCase):
    def test_question_three_tells_a_lovable_migration_to_create_both(self):
        q = [l for l in rs.COMMAND_MD.splitlines() if l.startswith("3. Supabase")]
        self.assertEqual(1, len(q))
        self.assertIn("create both", q[0])
        self.assertIn("Lovable", q[0])

    def test_both_command_prompts_forbid_the_password_coming_back(self):
        for prompt in (rs.COMMAND_MD, rs.NEW_COMMAND_MD):
            self.assertIn("never the database password", prompt)


if __name__ == "__main__":
    unittest.main()
