#!/usr/bin/env python3
"""
repo_setup.py  (v3.2)  -  Teknobu repo standards kit

One file, standard library only. Lives at ~/.claude/sonelo/repo_setup.py and is driven by the
/repo-setup command in Claude Code (or run by hand from a repo root).
  `refresh` takes a new kit release's agents, commands, hooks and CI gates into an existing
  repo - and nothing else; `apply` is the full lay-down.

  python repo_setup.py install          # once per machine: copies itself to ~/.claude/sonelo/, writes the
                                        #   /repo-setup command, registers the session-start nudge
  python repo_setup.py apply            # in a repo: lay down the standards (idempotent; --dry-run to preview)
  python repo_setup.py check            # in a repo: what's in place, what's missing
  python repo_setup.py protect          # in a repo: GitHub branch protection for main via the gh CLI
  python repo_setup.py vercel --domain <work>.example.com
                                        # in a repo: assign the domain to the work branch on Vercel, check DNS,
                                        #   push .env.<work> as branch-scoped Preview variables
  python repo_setup.py nudge            # what the session-start hook calls (prints one line if standards are missing)
  python repo_setup.py github --org TeknobuGroup
                                        # in a repo: create the GitHub repo (gh), push main + work branch, protect main
  python repo_setup.py supabase --create [--only <work>] [--database separate|branching]
                                        # in a repo: create the work (and production) databases, write
                                        #   .env / .env.<work> / .env.production, set the GitHub deploy secrets
  python repo_setup.py vercel --create --domain <work>.example.com
                                        # also creates the Vercel project from the GitHub repo if it doesn't exist
  python repo_setup.py uninstall        # remove the commands and the nudge (repos keep their files)

What apply lays down (adapted to what it finds: package.json, supabase/, pubspec.yaml, tests), plus the worklog agent
(bundled; .worklog/ in the repo, git-ignored locally) and anything in ~/.claude/sonelo/pipeline/:
  .githooks/commit-msg                  Conventional Commits, enforced
  .githooks/pre-commit                  blocks .env files, key material, files over 5 MB, secrets in added lines
  .githooks/pre-push                    refuses direct pushes to main and force-pushes to main/<work>, runs .githooks/checks
  .githooks/checks                      the checks pre-push and CI share (typecheck, lint, test); edit freely
  .github/workflows/ci.yml              the same checks plus a secrets scan on every push and PR
  .github/workflows/deploy-supabase.yml migrations + edge functions to the work or production database (Supabase repos)
  .github/pull_request_template.md
  .teknobu.json                         branch model and kit version
  <WORK>.md (PRELIVE.md, STAGING.md)    the manual wiring left to do (staging project, secrets, Vercel branch domain)
  CLAUDE.md                             a standards section so Claude Code follows the rules
  .gitignore / .env.example             housekeeping
  git: core.hooksPath=.githooks, work branch created if missing

Branch model: work on the work branch (its own URL and database), pull request into main (production).
Escape hatches: SONELO_SKIP=1 disables the hooks for one command; SONELO_ALLOW_MAIN=1 allows one direct push to main (TEKNOBU_* still honoured).
"""

import argparse
import json
import os
import re
import secrets as _secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

VERSION = "4.5"
KIT_NAME = "Sonelo Solution DevKit"
MARK = "sonelo-devkit"                                 # marker line in every generated file we own
OLD_MARKS = ("teknobu-kit",)                           # earlier releases' marker; files carrying it are still ours
ALL_MARKS = (MARK,) + OLD_MARKS
HOME_DIR = Path("~/.claude/sonelo").expanduser()
OLD_HOME_DIR = Path("~/.claude/teknobu").expanduser()
INSTALLED = HOME_DIR / "repo_setup.py"
PIPELINE_DIR = HOME_DIR / "pipeline"                    # optional: files here are copied into every repo (your Claude pipeline)
WORKLOG = HOME_DIR / "worklog_agent.py"                 # the worklog agent, bundled with the kit
COMMAND_FILE = Path("~/.claude/commands/repo-setup.md").expanduser()
NEW_COMMAND_FILE = Path("~/.claude/commands/new-repo.md").expanduser()
USER_SETTINGS = Path("~/.claude/settings.json").expanduser()
HOOK_MARK = "repo_setup.py"
CONFIG_FILE = HOME_DIR / "config.json"
UPDATE_STAMP = HOME_DIR / "latest-release"          # newest release tag seen; mtime = last check (daily throttle for the nudge)

# UAT Hub: one internal deployment, one checkout location, so these are constants rather than
# configuration - a knob nobody turns is one more thing to fall out of step. The only value that
# genuinely differs per repo is the project slug, and that is asked for (see uat_slug).
UAT_HUB_URL = "https://testing.teknobugroup.com"
UAT_HUB_KEY_VAR = "UAT_HUB_KEY"                         # read from the environment; never written into a file
UAT_MCP_NAME = "uat-hub"                                # the server's key in .mcp.json
UAT_HUB_SERVER = Path("~/uat-hub/mcp/server.mjs").expanduser()   # the checkout every Teknobu machine has
KIT_ENV_KEYS = ("UAT_HUB_KEY",)                         # keys .env.example documents because the kit needs them,
                                                        # not because a .env in the repo mentioned them

DEFAULTS = {
    "mode": "full",                       # full: standards + agents + infrastructure | worklog: the worklog only
    "work_branch": "staging",             # the branch you work on; it gets its own URL and database
    "main_branch": "main",                # production; moves only by pull request
    "github_org": "",                     # organisation or user for new repos (empty = your gh user)
    "vercel_team": "",                    # Vercel team id (team_...) when you have several
    "domain_pattern": "{name}.example.com",   # production domain for a new project; staging is {work}.<that>
    "supabase_org": "",                   # organisation id/slug (empty = the only one, or asked)
    "supabase_region": "us-east-1",
    "database": "separate",               # separate: two projects | branching: one project + a persistent Supabase branch
    "stack_default": "Vite + React + TypeScript + Supabase",
    "source": "TeknobuGroup/SoneloSolutionDevKit",    # GitHub repo the `update` command pulls releases from
    "brand": {"PRIMARY": "one accent token (`--primary`); the only call-to-action colour", "FONTS": "one sans for UI, one mono for code and metadata",
              "RADIUS": "4px", "LINT": "none yet; the reviewer reads source"},
}
PRESETS = {
    "sonelo": {"work_branch": "prelive", "github_org": "TeknobuGroup", "domain_pattern": "{name}.co.uk", "supabase_region": "eu-west-2",
               "database": "separate", "stack_default": "TanStack Start + React + TypeScript + Supabase",
               "brand": {"PRIMARY": "Teknobu teal `#00AF9F` (token `--primary`)", "FONTS": "Manrope (UI, 400/500/600), JetBrains Mono (code, metadata)",
                         "RADIUS": "4px", "LINT": "none yet; the reviewer reads source"}},
    "teknobu": {"work_branch": "prelive", "github_org": "TeknobuGroup", "domain_pattern": "{name}.co.uk", "supabase_region": "eu-west-2",
                "database": "separate", "stack_default": "TanStack Start + React + TypeScript + Supabase",
                "brand": {"PRIMARY": "Teknobu teal `#00AF9F` (token `--primary`)", "FONTS": "Manrope (UI, 400/500/600), JetBrains Mono (code, metadata)",
                          "RADIUS": "4px", "LINT": "none yet; the reviewer reads source"}},
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    data = {}
    src = CONFIG_FILE if CONFIG_FILE.exists() else (OLD_HOME_DIR / "config.json")
    try:
        data = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
    except (OSError, ValueError):
        data = {}
    for k, v in (data or {}).items():
        if k == "brand" and isinstance(v, dict):
            cfg["brand"].update(v)
        else:
            cfg[k] = v
    return cfg


CONFIG = load_config()
WORK_BRANCH = CONFIG["work_branch"]
PROTECTED = [CONFIG["main_branch"]]
DEFAULT_GITHUB_ORG = CONFIG["github_org"]
DEFAULT_SUPABASE_REGION = CONFIG["supabase_region"]


def use_repo_config(root):
    """A repo set up with other branch names keeps them (e.g. prelive) whatever the machine config says now."""
    global WORK_BRANCH, PROTECTED
    rc = read_json(root / ".teknobu.json", {}) if root else {}
    if rc.get("work_branch") and re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]*\Z", str(rc["work_branch"])):
        WORK_BRANCH = str(rc["work_branch"])   # option-shaped values from a cloned repo's config never reach git argv
    if rc.get("protected"):
        PROTECTED = list(rc["protected"])


def env_doc():
    return WORK_BRANCH.upper() + ".md"      # PRELIVE.md, STAGING.md: the per-repo wiring checklist


# ----------------------------------------------------------------------------- helpers

NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW
BIN_DIR = HOME_DIR / "bin"                                          # CLIs the kit downloads itself (supabase, gh)
USER_AGENT = "sonelo-devkit/%s (+python-urllib)" % VERSION            # Supabase's API rejects urllib's default User-Agent with 403
LOVABLE_MARKERS = ("lovable-tagger", "VITE_SUPABASE_PUBLISHABLE_KEY", "lovable.dev", "ai.gateway.lovable.dev")


def tool(name):
    """Path to a CLI: on PATH, else the kit's own bin/ (where install downloads it), else None."""
    found = shutil.which(name)
    if found:
        return found
    for base in (BIN_DIR, OLD_HOME_DIR / "bin"):
        for cand in (base / name, base / (name + ".exe"), base / (name + ".cmd")):
            if cand.exists():
                return str(cand)
    return None


def sh(args, cwd=None, check=False, timeout=120):
    out = subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=timeout, **NOWIN)
    if check and out.returncode != 0:
        raise RuntimeError("%s failed: %s" % (" ".join(args), out.stderr.strip()))
    return out


def say(msg=""):
    try:
        print(msg)
    except Exception:
        pass


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write(path, text, executable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, str(path))
    if executable:
        try:
            path.chmod(path.stat().st_mode | 0o111)
        except OSError:
            pass


def read_json(path, default):
    """Every caller wants a JSON object. A file holding a valid list, string or number is as
    unusable as a malformed one, so it takes the same path - otherwise the .get() is a crash
    several writes into a command."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, dict) else default


def repo_root(start=None):
    start = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    out = sh(["git", "-C", str(start), "rev-parse", "--show-toplevel"])
    if out.returncode == 0 and out.stdout.strip():
        return Path(out.stdout.strip())
    return None


def version_of(path):
    try:
        m = re.search(r'^VERSION\s*=\s*"([0-9.]+)"', Path(path).read_text(encoding="utf-8", errors="replace"), re.M)
        return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)
    except (OSError, ValueError):
        return (0,)


def github_slug(root):
    out = sh(["git", "-C", str(root), "config", "--get", "remote.origin.url"])
    if out.returncode != 0:
        out = sh(["git", "-C", str(root), "remote", "get-url", "origin"])
    m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", out.stdout.strip()) if out.returncode == 0 else None
    return (m.group(1), m.group(2)) if m else None


# ----------------------------------------------------------------------------- detection

def detect(root):
    d = {"node": False, "pm": "npm", "lockfile": None, "scripts": {}, "tsconfig": False, "supabase": False,
         "flutter": False, "python": False, "pytest": False, "vercel": False, "node_version": "20", "checks": []}
    pkg = read_json(root / "package.json", None)
    if isinstance(pkg, dict):
        d["node"] = True
        d["scripts"] = pkg.get("scripts") or {}
        eng = (pkg.get("engines") or {}).get("node") or ""
        m = re.search(r"(\d\d)", eng)
        if m:
            d["node_version"] = m.group(1)
        nvmrc = read(root / ".nvmrc")
        if nvmrc and re.search(r"\d+", nvmrc):
            d["node_version"] = re.search(r"\d+", nvmrc).group(0)
        for lock, pm in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"), ("bun.lockb", "bun")):
            if (root / lock).exists():
                d["pm"], d["lockfile"] = pm, lock
                break
    d["tsconfig"] = (root / "tsconfig.json").exists()
    d["supabase"] = (root / "supabase" / "config.toml").exists() or (root / "supabase" / "migrations").is_dir() or (root / "supabase" / "functions").is_dir()
    d["flutter"] = (root / "pubspec.yaml").exists()
    d["python"] = (root / "pyproject.toml").exists() or (root / "requirements.txt").exists()
    d["pytest"] = d["python"] and ((root / "tests").is_dir() or (root / "test").is_dir())
    d["vercel"] = (root / "vercel.json").exists() or (root / ".vercel").is_dir()

    run = {"npm": "npm run", "pnpm": "pnpm run", "yarn": "yarn", "bun": "bun run"}[d["pm"]]
    checks = []
    if d["node"]:
        s = d["scripts"]
        if "typecheck" in s:
            checks.append("%s typecheck" % run)
        elif "type-check" in s:
            checks.append("%s type-check" % run)
        elif d["tsconfig"]:
            checks.append("npx tsc --noEmit")
        if "lint" in s:
            checks.append("%s lint" % run)
        if "test" in s and "no test specified" not in s["test"]:
            checks.append("%s test" % run if d["pm"] != "npm" else "npm test")
    if d["flutter"]:
        checks += ["flutter analyze", "flutter test"]
    if d["pytest"]:
        checks.append("python -m pytest -q")
    d["checks"] = checks
    return d


# ----------------------------------------------------------------------------- templates

COMMIT_MSG = r'''#!/bin/sh
# {MARK} v{VERSION} - commit message format (Conventional Commits). Regenerated by repo_setup.py apply.
{ [ "$SONELO_SKIP" = "1" ] || [ "$TEKNOBU_SKIP" = "1" ]; } && exit 0
msg_file="$1"
first=$(grep -v '^#' "$msg_file" | sed '/^[[:space:]]*$/d' | head -n 1)
case "$first" in
  "Merge "*|"Revert "*|"fixup!"*|"squash!"*|"Initial commit"*) exit 0 ;;
esac
if printf '%s\n' "$first" | grep -Eq '^(feat|fix|chore|docs|refactor|perf|test|build|ci|style|revert)(\([A-Za-z0-9._/ -]+\))?!?: [^ ].{0,99}$'; then
  exit 0
fi
cat >&2 <<EOF

  Commit message rejected:
    $first

  Format:  type(scope)?: summary        (summary up to 100 chars, imperative, no trailing full stop)
  Types:   feat fix chore docs refactor perf test build ci style revert
  e.g.     feat(webhooks): validate Twilio signature per tenant
           fix: handle empty rate card on work order create

  One-off override: SONELO_SKIP=1 git commit ...
EOF
exit 1
'''

PRE_COMMIT = r'''#!/bin/sh
# {MARK} v{VERSION} - blocks env files, key material, large files and secrets in added lines. Regenerated by repo_setup.py apply.
{ [ "$SONELO_SKIP" = "1" ] || [ "$TEKNOBU_SKIP" = "1" ]; } && exit 0
fail=0
files=$(git diff --cached --name-only --diff-filter=ACMR)
[ -z "$files" ] && exit 0
old_ifs=$IFS
IFS='
'
for f in $files; do
  case "$f" in
    *.example|*.sample|*.template|*.dist) ;;
    .env|.env.*|*/.env|*/.env.*) echo "blocked: $f (environment file - keep secrets out of git; commit .env.example instead)"; fail=1 ;;
    *.pem|*.key|*.p12|*.pfx|*.jks|*.keystore|*id_rsa*|*id_ed25519*|*id_ecdsa*|*serviceAccount*.json|*service-account*.json|*service_account*.json)
      echo "blocked: $f (key material)"; fail=1 ;;
  esac
  size=$(git cat-file -s ":$f" 2>/dev/null || echo 0)
  if [ "$size" -gt 5242880 ]; then
    echo "blocked: $f is larger than 5 MB (use storage or git-lfs)"; fail=1
  fi
done
patterns='AKIA[0-9A-Z]{16}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|sk_live_[0-9A-Za-z]{16,}|AIza[0-9A-Za-z_-]{35}|SK[0-9a-f]{32}|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|(api[_-]?key|secret|token|password)["'"'"'[:space:]]*[:=]["'"'"'[:space:]]*[A-Za-z0-9_/+=-]{20,}'
for f in $files; do
  case "$f" in
    package-lock.json|pnpm-lock.yaml|yarn.lock|bun.lockb|*.min.js|*.map|*.svg|*.lock|*.example) continue ;;
  esac
  hits=$(git diff --cached -U0 -- "$f" | grep -E '^\+' | grep -Ev '^\+\+\+' | grep -Ei "$patterns" | head -n 3)
  if [ -n "$hits" ]; then
    echo "blocked: $f looks like it contains a secret:"
    printf '%s\n' "$hits" | cut -c1-80 | sed 's/^/    /'
    fail=1
  fi
done
IFS=$old_ifs
if [ "$fail" = "1" ]; then
  echo ""
  echo "  Nothing was committed. Move secrets to environment variables (.env, listed in .env.example),"
  echo "  then stage again. If this is a false positive: SONELO_SKIP=1 git commit ..."
  exit 1
fi
exit 0
'''

PRE_PUSH = r'''#!/bin/sh
# {MARK} v{VERSION} - protects {PROTECTED} and {WORK}, then runs the checks in .githooks/checks. Regenerated by repo_setup.py apply.
{ [ "$SONELO_SKIP" = "1" ] || [ "$TEKNOBU_SKIP" = "1" ]; } && exit 0
protected="{PROTECTED}"
work="{WORK}"
zero=0000000000000000000000000000000000000000
fail=0
updates=0
while read local_ref local_sha remote_ref remote_sha; do
  [ -z "$remote_ref" ] && continue
  [ "$local_sha" = "$zero" ] && continue          # deleting a remote branch: not our business
  updates=$((updates + 1))
  branch=${remote_ref#refs/heads/}
  for p in $protected; do
    if [ "$branch" = "$p" ] && [ "$SONELO_ALLOW_MAIN" != "1" ] && [ "$TEKNOBU_ALLOW_MAIN" != "1" ]; then
      echo "blocked: direct push to '$p'. Push '$work' and open a pull request:"
      echo "    gh pr create --base $p --head $work --fill"
      echo "  (one-off override: SONELO_ALLOW_MAIN=1 git push ...)"
      fail=1
    fi
  done
  if [ "$remote_sha" != "$zero" ]; then
    git merge-base --is-ancestor "$remote_sha" "$local_sha" 2>/dev/null
    rc=$?
    if [ "$rc" = "1" ]; then
      case " $protected $work " in
        *" $branch "*) echo "blocked: force-push to '$branch' would rewrite shared history"; fail=1 ;;
      esac
    fi
  fi
done
[ "$fail" = "1" ] && exit 1
[ "$updates" = "0" ] && exit 0
hooks_dir=$(dirname "$0")
checks="$hooks_dir/checks"
[ -f "$checks" ] || exit 0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  echo "pre-push: $line"
  if ! sh -c "$line"; then
    echo ""
    echo "  pre-push: FAILED: $line"
    echo "  Fix it and push again, or skip once with SONELO_SKIP=1 git push ..."
    exit 1
  fi
done < "$checks"
exit 0
'''

CHECKS = '''# {MARK} v{VERSION} - commands run by .githooks/pre-push (one per line). CI runs the same list.
# Edit freely; keep them fast enough to run before every push.
{CHECKS}
'''

CI_YML = '''# {MARK} v{VERSION} - generated by repo_setup.py apply; edit if you like, re-apply overwrites only if this header is intact.
name: CI
on:
  push:
    branches: [{BRANCHES}]
  pull_request:
    branches: [{PROTECTED_LIST}]
jobs:
  checks:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - name: Secrets scan (gitleaks, working tree)
        run: |
          curl -sSfL https://github.com/gitleaks/gitleaks/releases/download/v8.21.2/gitleaks_8.21.2_linux_x64.tar.gz | tar -xz gitleaks
          ./gitleaks dir . --no-banner --redact
{NODE_STEPS}{FLUTTER_STEPS}{PYTHON_STEPS}{CHECK_STEPS}'''

NODE_STEPS = '''      - uses: actions/setup-node@v4
        with:
          node-version: "{NODE_VERSION}"
{CACHE}      - run: {INSTALL}
'''

PNPM_SETUP = '''      - uses: pnpm/action-setup@v4
'''

FLUTTER_STEPS = '''      - uses: subosito/flutter-action@v2
        with:
          channel: stable
      - run: flutter pub get
'''

PYTHON_STEPS = '''      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: |
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          if [ -f pyproject.toml ]; then pip install -e . || true; fi
'''

DEPLOY_YML = '''# {MARK} v{VERSION} - Supabase migrations and edge functions. {WORK} -> {WORK} database, {MAIN} -> production.
# Needs repository secrets (Settings -> Secrets and variables -> Actions): SUPABASE_ACCESS_TOKEN,
# SUPABASE_{WORKU}_PROJECT_REF + SUPABASE_{WORKU}_DB_PASSWORD, SUPABASE_PROJECT_REF + SUPABASE_DB_PASSWORD.
# Until they exist the job explains itself and exits green. See {ENVDOC}.
name: Deploy Supabase
on:
  push:
    branches: [{WORK}, {PROTECTED_LIST}]
jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}
      PROJECT_REF: ${{ github.ref_name == '{MAIN}' && secrets.SUPABASE_PROJECT_REF || secrets.SUPABASE_{WORKU}_PROJECT_REF }}
      DB_PASSWORD: ${{ github.ref_name == '{MAIN}' && secrets.SUPABASE_DB_PASSWORD || secrets.SUPABASE_{WORKU}_DB_PASSWORD }}
    steps:
      - uses: actions/checkout@v4
      - name: Secrets present?
        id: gate
        run: |
          if [ -z "$SUPABASE_ACCESS_TOKEN" ] || [ -z "$PROJECT_REF" ]; then
            echo "Supabase secrets for '${{ github.ref_name }}' are not set yet - see {ENVDOC}. Skipping deploy."
            echo "ready=false" >> "$GITHUB_OUTPUT"
          else
            echo "ready=true" >> "$GITHUB_OUTPUT"
          fi
      - uses: supabase/setup-cli@v1
        if: steps.gate.outputs.ready == 'true'
        with:
          version: latest
      - name: Link project
        if: steps.gate.outputs.ready == 'true'
        run: supabase link --project-ref "$PROJECT_REF" --password "$DB_PASSWORD"
      - name: Push migrations
        if: steps.gate.outputs.ready == 'true'
        run: supabase db push --password "$DB_PASSWORD"
      - name: Deploy edge functions
        if: steps.gate.outputs.ready == 'true' && hashFiles('supabase/functions/**') != ''
        run: supabase functions deploy --project-ref "$PROJECT_REF"
'''

# The pull-request template lives in BUILTIN_PIPELINE, which is its only producer. cmd_apply used
# to write a second, different version of the same path, so `apply` and a pipeline refresh each
# replaced the other's copy on every run - flip-flop, with a spurious backup each time (v4.3).

PRELIVE_MD = '''<!-- {MARK} v{VERSION} -->
# Prelive setup for {REPO}

Branch model: work on **{WORK}**, which deploys to its own URL and database. **{MAIN}** is production and only moves by pull request.

```
git checkout {WORK}                  # day to day
git push -u origin {WORK}            # first time; CI runs, {WORK} deploys
gh pr create --base {MAIN} --head {WORK} --fill   # when it's ready for production; merge on GitHub
```

What the kit wired automatically: git hooks (commit format, secrets, protected branches, pre-push checks), CI on every push and PR,
{DEPLOY_LINE}a CLAUDE.md section so Claude Code follows the same rules.

## Left to do by hand (once per repo)

{SUPABASE_TODO}### Hosting (Vercel)
- [ ] Fill `.env.{WORK}` (created next to `.env.example`, git-ignored) with the {WORK} values: Supabase URL and anon key of the {WORK} database, API URLs, anything that differs from production.
- [ ] `python ~/.claude/sonelo/repo_setup.py vercel --domain {WORK}.<your-domain>` - links the project, assigns the domain to the `{WORK}` branch, checks DNS, pushes `.env.{WORK}` as Preview variables scoped to `{WORK}`. Uses your Vercel CLI login or a `VERCEL_TOKEN` (vercel.com/account/tokens).
- [ ] If it reports DNS as misconfigured: add the CNAME it prints at your DNS provider (GoDaddy), then re-run.
- [ ] By hand instead: Settings -> Domains (add domain, Git branch `{WORK}`); Settings -> Environment Variables (Preview, scoped to `{WORK}`); production branch stays `{MAIN}`.

### UAT Hub
- [ ] The project must exist at {UAT_HUB} before anything can be pushed: a push never creates one, so an unknown slug is refused (which is what stops a typo inventing a phantom client). Until then the wiring is inert, not broken.
- [ ] Set `UAT_HUB_KEY` in your environment - not in `.env`, not in `.mcp.json`, which is committed. `repo_setup.py doctor` reports whether it is set, never its value.
- [ ] `.mcp.json` records the slug and the path to the uat-hub checkout as `~/uat-hub/mcp/server.mjs` resolved on the machine that ran the kit. On a machine that keeps the checkout elsewhere, edit the `args` path there; sessions without the server fall back to the HTTP endpoint.

### GitHub
- [ ] `python ~/.claude/sonelo/repo_setup.py protect` (needs the `gh` CLI logged in) - or Settings -> Branches -> add rule for `{MAIN}`: require a pull request, require the `checks` status, block force pushes and deletions.
- [ ] Actions -> Secrets: see the list at the top of `.github/workflows/deploy-supabase.yml` (Supabase repos only).

### Escape hatches
- `SONELO_SKIP=1 git commit ...` / `SONELO_SKIP=1 git push ...` disables the hooks for one command.
- `SONELO_ALLOW_MAIN=1 git push origin {MAIN}` allows one direct push (hotfix, first push).
'''

SUPABASE_TODO = '''### Database (Supabase)
- [ ] A database for {WORK}: `repo_setup.py supabase --create --only {WORK}` makes `<project>-{WORK}` (or a persistent Supabase branch with `--database branching`).
- [ ] Copy the production schema into it once: `supabase db dump --linked -f schema.sql` against production, then apply to {WORK}. Seed only what you need - no client data.
- [ ] Edge function secrets are per database: set them for {WORK} (Project -> Edge Functions -> Secrets) as well as production.
- [ ] Auth: add the {WORK} URL to Site URL / Redirect URLs for {WORK}.
- [ ] GitHub secrets: `SUPABASE_ACCESS_TOKEN` (account token), `SUPABASE_{WORKU}_PROJECT_REF`, `SUPABASE_{WORKU}_DB_PASSWORD`, `SUPABASE_PROJECT_REF`, `SUPABASE_DB_PASSWORD`.

'''

CLAUDE_SECTION = '''<!-- {MARK}:start v{VERSION} (managed by repo_setup.py; edit outside these markers) -->
## Sonelo standards

**Branches.** Work on `{WORK}`; it deploys to its own URL and database. `{MAIN}` is production and only changes through a pull request from `{WORK}` (`gh pr create --base {MAIN} --head {WORK} --fill`). Never push to `{MAIN}` directly and never force-push `{WORK}` or `{MAIN}`. If you find yourself on `{MAIN}` with uncommitted work, switch to `{WORK}` first.

**Commits.** Conventional Commits, enforced by a hook: `type(scope)?: summary`, types `feat fix chore docs refactor perf test build ci style revert`, summary imperative and under 100 characters. One logical change per commit; run the pre-push checks before pushing (`.githooks/checks`).

**Secrets.** Never commit `.env` files, keys, tokens or certificates; the pre-commit hook blocks them. Config comes from environment variables, documented in `.env.example` with empty values. Prelive and production have separate values; set them in the hosting provider, not in code.

**Before pushing.** Typecheck, lint and tests must pass locally (the pre-push hook runs `.githooks/checks`); CI runs the same on GitHub. Database or edge-function changes go to {WORK} first and are verified there before the pull request. Migrations are files under `supabase/migrations`, never hand edits in a dashboard.

**If a hook blocks you**, fix the cause. `SONELO_SKIP=1` exists for false positives only; say so in the commit message if you use it.
<!-- {MARK}:end -->
'''

UAT_SECTION = '''<!-- {MARK}:uat:start v{VERSION} (managed by repo_setup.py; edit outside these markers) -->
## Writing UAT

When you finish building a feature, write its UAT test cases and push them to UAT Hub.
Do NOT write them to a Markdown file — the hub is where a human tester picks them up.

Push with the `push_uat_test_cases` MCP tool. If that tool is unavailable, POST the same
shape to `https://testing.teknobugroup.com/api/uat/test-cases` with
`Authorization: Bearer $UAT_HUB_KEY`.

    project:    {UAT_PROJECT}          (omit if UAT_HUB_PROJECT is set for this repo)
    module:     the feature area, e.g. "Auth", "Checkout", "Patrols"
    test_cases: a list, each with
                  title            required, one line, the thing being checked
                  steps            how to carry it out
                  expected_result  what should happen if it works
                  test_url         the page to open — must be http(s)
                  source_ref       a stable id you choose, e.g. "auth-login-invalid"

### Write for the tester, not for yourself

The person running these has not read the code and may not know the feature. Assume
nothing.

- **One check per case.** If the title needs "and", it is two cases.
- **Steps are what to do, in order** — "Enter a valid email and a wrong password, submit",
  not "test invalid credentials".
- **Expected result must be decidable.** Someone has to be able to say pass or fail without
  asking you. "Shows an error" is not decidable; "Inline error under the password field,
  and the page does not navigate" is.
- **Name real things** — the actual button text, the actual field label, the actual URL.
- **No jargon from the codebase.** No component names, no function names, no ticket numbers.

### Cover what actually breaks

A list of happy paths is close to worthless. For each feature include:

- the normal case
- the empty case — no data, first use, nothing configured yet
- the invalid case — wrong input, wrong format, wrong order
- the permission case — someone who should not be able to do this, if roles apply
- anything you know is fragile, or that you had to think hard about while building it

If something cannot be tested through the interface, say so in the steps rather than
writing a case nobody can run.

### Always set source_ref

Give every case a stable id derived from what it tests, e.g. `checkout-discount-invalid`.
Pushing the same case twice with the same `source_ref` updates nothing and creates nothing,
so a retry after a timeout is safe and re-running you is safe. Without it, every push
duplicates.

### Batching

Up to 200 cases per push, one module per push. Several modules means several pushes.

### If the push is refused

Read the message; it is specific.

- _"no project with slug X; create it in UAT Hub first"_ — the slug is wrong, or the project
  has not been created. Do not invent one. Stop and report it.
- _"invalid or revoked api key"_ — `UAT_HUB_KEY` is missing, wrong, or has been revoked.
  Stop and report it. Do not put a key in any committed file.

Report what you pushed, to which project and module, and how many cases.

### How this repo is wired

- The MCP server is registered in `.mcp.json`. `UAT_HUB_KEY` is expanded from the environment of
  the machine running the session and is never written into a file in this repo - `.mcp.json` is
  committed, and one key covers every project. `repo_setup.py doctor` reports whether it is set.
- This repo pushes to the UAT Hub project `{UAT_PROJECT}`. A push cannot create a project: if the
  hub has no project with that slug, every push is refused until someone creates it in UAT Hub.
  That is correct behaviour, not a fault to work around - do not invent a slug.
<!-- {MARK}:uat:end -->
'''

# the sh hooks break under a CRLF checkout; merge_gitattributes writes its own header
GITATTRIBUTES_LINES = ["*.sh text eol=lf", ".githooks/* text eol=lf"]

GITIGNORE_LINES = [
    "# sonelo standards", ".env", ".env.*", "!.env.example", ".claude/settings.local.json", ".claude/state/", ".claude/.backup/", ".worklog/",
    "node_modules/", "dist/", "build/", ".vercel/", "supabase/.temp/", "supabase/.branches/",
    ".DS_Store", "Thumbs.db", "*.log", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
]

DESIGN_REVIEWER_MD = r"""---
name: design-reviewer
model: sonnet
description: Reviews UI work as a user would meet it - can they finish the task, can they read it, does it hold up in the states that actually occur - and checks it against this repo's design contract in .claude/rules/design.md. Use before finishing any change that alters what appears on screen. Reports; never edits.
tools: Read, Grep, Glob, Bash(git status:*), Bash(git ls-files:*), Bash(git diff:*), Bash(git log:*)
---

You review interface work. You **report and recommend - you never edit**. You have no Write or Edit
tool on purpose: bulk automated restyling is how design regressions ship, so the reviewer is
deliberately not the thing holding the pen.

The brand facts for this repo live in `.claude/rules/design.md`. Read it first. Everything below is
method; that file is the contract you judge against.

## Judge it in this order. The order is the point.

Work down this list and stop escalating once something fails: a beautiful screen the user cannot
finish a task on is a failed screen, and no amount of spacing fixes it.

**1. Can they finish the task?** Name the one job this screen is for. Is the action that does that job
the most prominent thing on screen, or is it competing with a toolbar, three filters and a banner?
Count the steps and the decisions. A second primary button means there is no primary button.

**2. Can they read it?** Hierarchy comes from size, weight and space - not from colour, and not from
boxes. Body text floors at 13px in dense admin tables, 15px elsewhere; 10-11px is for eyebrow labels
only, never for anything the user must act on. Line length tops out around 75 characters. Contrast is
4.5:1 for text, 3:1 for large text and for anything non-text that carries meaning: a focus ring, a
status dot, a chart series, a border between regions.

**3. Does it survive reality?** For every list, form and panel ask what happens with: nothing yet ·
one item · two hundred items · a 60-character name with no spaces · a null · a four-second load · a
failed request. "No data" wastes the one moment the user was ready to be told what to do. A failure
with nowhere to surface is a finding, not a nitpick.

**4. Can everyone use it?** Reachable and operable by keyboard, in a sensible order, with a visible
focus ring at 3:1. Targets at least 24x24px, 44px for anything primary or touch-first. Real labels,
not placeholders posing as labels. Never colour alone to carry meaning. Icon-only controls need an
accessible name.

**5. Is it consistent with everything else?** Same job, same component. If this screen invents a
card, badge or button that already exists elsewhere, that is the finding. Divergence is the disease;
pixel values are symptoms.

## The contract

Apply `.claude/rules/design.md` literally: its tokens, its type families and allowed weights, its
radius, its rule on borders versus shadows, which colour is the only call to action, and its off-brand
list. Any hex, `rgb()`, `hsl()` literal or palette utility in a component where the contract says
colour comes from tokens is a finding. If a genuine need has no token, say which token should be
added and where. Never propose a local value.

## Reject these on sight

decorative gradients · glassmorphism and backdrop blur · drop shadows doing a border's job · fully
round pills on everything · emoji standing in for icons · a centred hero above three equal feature
cards · tinted status boxes · bold weights for emphasis · placeholders as labels · full-page spinners
where a skeleton belongs · a modal for something that could be inline · animation that is not
communicating state · icon-only buttons with no accessible name · "click here" links · fixed pixel
heights that clip when text wraps. Restraint reads as considered. Decoration reads as filler.

## What you cannot see, and must say so

You are reading source, not pixels. You can prove a token is used; you cannot prove the result is
legible, that a label is not clipped, or that a grid holds at 1100px. End every review by naming the
specific screens a human should open and what to look at on each. If the repo has a design lint
command (see the contract), run it and report, but treat a clean result as the floor, not the verdict.

## Reporting

Findings ordered by user cost, not by how easy they are to describe. For each: `file.tsx:line` and
one sentence naming the defect · who it costs and how · the specific fix, in tokens · severity:
**blocks the task** · **hurts the task** · **inconsistency** · **polish**. If it is genuinely fine,
say so in a line. Manufacturing findings to look thorough trains people to stop reading you.
"""

DESIGN_RULE_MD = """# Design contract - {NAME}

<!-- {MARK} v{VERSION}. The design-reviewer agent judges against this file. Replace the facts below with the
product's brand guidelines (docs/BRAND.md if present); keep the shape. -->

## Colour
- Colour comes only from semantic tokens (CSS custom properties -> semantic Tailwind classes). No hex, rgb(), hsl()
  literals or palette utilities (`bg-slate-100`, `text-white`) in components.
- Primary / call to action: {PRIMARY}. It is the only call-to-action colour.
- Status colours carry meaning only (success, warning, error, neutral); never decorative.

## Type
- Families: {FONTS}.
- Weights: 400 running text, 500-600 headings and actions. Nothing heavier.
- Body 14-16px; eyebrow/meta 11-13px; never below 11px.

## Surface
- Radius: {RADIUS}.
- Borders over shadows: 1px hairlines for separation; shadows only for genuinely floating elements.
- Put colour on the value, not behind it.

## Motion
- Only to communicate state; short (<= 300ms), ease-out; no parallax, no bounce.

## Explicitly off-brand
- Default AI aesthetics: Inter/Poppins-by-default, purple-indigo gradients on white, glassmorphism, emoji in UI copy,
  stock futuristic imagery, drop shadows as primary depth.

## Design lint
- {LINT}
"""

LOVABLE_MD = """<!-- {MARK} v{VERSION} -->
# Migrating {REPO} off Lovable

This repo was built on Lovable ({MARKERS}). The standards, {WORK} branch and deploy workflow are in place;
this is the order for moving the running app onto your own Supabase, Vercel and OpenRouter. Keep the Lovable
project alive until {WORK} has proven out.

## Found in the code
- Routes: {ROUTES}. Router: {ROUTER}.
- Lovable AI Gateway call sites: {AI_SITES} (each becomes an OpenRouter call with the same model name).
- Browser-only touches (`window`, `localStorage`, `document` at render time): {BROWSER}. Relevant only if you later
  move to TanStack Start; a plain Vite SPA does not care.
- Supabase client: {CLIENT}.

## In order
1. [ ] `repo_setup.py supabase --create` - new {WORK} and production databases; `.env` / `.env.{WORK}` / `.env.production` written.
2. [ ] Rename env usage: `VITE_SUPABASE_PUBLISHABLE_KEY` -> `VITE_SUPABASE_ANON_KEY`, `VITE_SUPABASE_PROJECT_ID` -> `VITE_SUPABASE_PROJECT_REF` (the kit writes the new names; grep for the old ones).
3. [ ] Database: from the Lovable project, `supabase db dump --db-url <lovable-db-url> -f schema.sql` and `--data-only -f data.sql`; restore into {WORK} first (`psql` with the {WORK} DB password from `.env.{WORK}`), then production when {WORK} is proven.
4. [ ] Storage buckets: recreate with the same names and policies; copy objects.
5. [ ] Auth: providers, redirect URLs (`https://{WORK}.<domain>`, `https://<domain>`), email templates, SMTP.
6. [ ] Edge functions: `supabase functions deploy` to {WORK} (the deploy workflow does this from the {WORK} branch once `supabase/` is committed); set their secrets with `supabase secrets set`.
7. [ ] AI Gateway -> OpenRouter: replace each call site listed above; `OPENROUTER_API_KEY` as an edge-function secret, never in the client.
8. [ ] Webhooks and third parties (Twilio, Stripe, Zoho, Meta): repoint to the new function URLs.
9. [ ] `repo_setup.py vercel --create --domain {WORK}.<domain>`; custom domains move last, after {WORK} is proven.
10. [ ] Rotate every key that ever lived in this repo's git history (Lovable projects usually have at least one).
11. [ ] Remove `lovable-tagger` from package.json and `vite.config.ts`.
"""


# The shipped pipeline hooks. Shell rule (ADR-0003): lowercase, unbraced variables only —
# fill() rewrites {TOKEN} substrings, so an uppercase ${...} would be silently corrupted
# (pinned by tests/test_pipeline_state.py::TemplatesTokenSafe).

PIPELINE_STATE_SH = r'''#!/bin/sh
# sonelo-devkit pipeline: shared state helper for stop-gate.sh, session-brief.sh and /post-change.
# Subcommands: changed | code-changed | due | sig | verdict [sig]. Always exits 0; empty output means
# "cannot compute" and callers fall back. See docs/decisions/0003 in the kit repo for the contract.
py=python
command -v python >/dev/null 2>&1 || py=python3
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
changed() { { git -c core.quotePath=false diff --name-only; git -c core.quotePath=false diff --name-only --cached; git -c core.quotePath=false ls-files --others --exclude-standard; } 2>/dev/null | sort -u; }
codechanged() { { changed | grep -Ev '^(docs/|CHANGELOG\.md|README|\.claude/|\.github/|PRELIVE\.md|STAGING\.md|[A-Z]+\.md|.*\.md$)' | grep -Ev '^\.(env|teknobu)'; changed | grep -E '^\.github/workflows/'; } | sort -u; }
case "$1" in
  changed) changed ;;
  code-changed) codechanged ;;
  due)
    files=$(codechanged)
    [ -z "$files" ] && exit 0
    out="code"
    printf '%s\n' "$files" | grep -Eq '\.(tsx|jsx|css|scss)$|(^|/)tailwind\.config\.' && out="$out design"
    printf '%s\n' "$files" | grep -Eq '^supabase/|(^|/)functions/|(^|/)auth(/|\.)|^\.github/workflows/' && out="$out security"
    printf '%s\n' "$out"
    ;;
  sig)
    # Content signature of the reviewable work: diffs of only the code-changed list plus a
    # hash line per untracked member. Docs/changelog/state writes cannot move it.
    files=$(codechanged)
    {
      printf 'v1\n'
      if [ -n "$files" ]; then
        oldifs=$IFS
        IFS='
'
        set -f
        set -- $files
        IFS=$oldifs
        GIT_LITERAL_PATHSPECS=1 git diff --cached --no-color --no-ext-diff -- "$@" 2>/dev/null
        GIT_LITERAL_PATHSPECS=1 git diff --no-color --no-ext-diff -- "$@" 2>/dev/null
        set +f
        others=$(git ls-files --others --exclude-standard 2>/dev/null | sort -u)
        printf '%s\n' "$files" | while IFS= read -r f; do
          [ -f "$f" ] || continue
          printf '%s\n' "$others" | grep -Fxq "$f" || continue
          printf '== %s %s\n' "$f" "$(git hash-object -- "$f" 2>/dev/null)"
        done
      fi
    } | git hash-object --stdin 2>/dev/null
    ;;
  verdict)
    branch=$(git branch --show-current 2>/dev/null)
    [ -z "$branch" ] && { echo none; exit 0; }
    vf=".claude/state/$branch/review.json"
    [ -f "$vf" ] || { echo none; exit 0; }
    cur=$2
    [ -n "$cur" ] || cur=$(sh "$0" sig)
    due=$(sh "$0" due)
    $py - "$vf" "$cur" "$due" <<'PYEOF' 2>/dev/null || echo none
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("none"); raise SystemExit
cur = sys.argv[2]
due = sys.argv[3].split() if len(sys.argv) > 3 else []
if not d.get("sig") or d.get("sig") != cur:
    print("stale"); raise SystemExit
rev = d.get("reviewers") or {}
if d.get("verdict") == "blocked" or d.get("tests") == "red" or any(rev.get(k) == "blocked" for k in due):
    print("blocked"); raise SystemExit
missing = [k for k in due if rev.get(k) in (None, "skipped")]
print("clear-partial " + " ".join(missing) if missing else "clear")
PYEOF
    ;;
esac
exit 0
'''

STOP_GATE_SH = r'''#!/bin/sh
# sonelo-devkit pipeline: Stop hook. Blocks the session from stopping while "done" is not true.
# Checks: (1) code changed -> CHANGELOG.md entry; (2) migrations changed -> generated types regenerated;
# (3) a review verdict exists for this branch, covers the reviewers the diff makes due, and matches the
# current work (sig from pipeline-state.sh). Blocks at most twice per work-state (marker in
# .claude/state/<branch>/disclosed), then demands plain disclosure to the user and allows the stop.
{ [ -n "$SONELO_SKIP_HOOKS" ] || [ -n "$TEKNOBU_SKIP_HOOKS" ]; } && exit 0
input=$(cat)
py=python
command -v python >/dev/null 2>&1 || py=python3
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
active=$(printf '%s' "$input" | $py -c "import json,sys; print(1 if json.load(sys.stdin).get('stop_hook_active') else 0)" 2>/dev/null)
[ "$active" = "1" ] || active=0
branch=$(git branch --show-current 2>/dev/null)
types=$($py -c "import json,sys,re; v=json.load(open(sys.argv[1])).get('generated_types') or ''; print(v if re.fullmatch(r'[A-Za-z0-9._/-]+', v) else '')" .teknobu.json 2>/dev/null)
[ -n "$types" ] || types=src/types/database.ts
ps=.claude/hooks/pipeline-state.sh
changed=$( { git diff --name-only 2>/dev/null; git diff --name-only --cached 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | sort -u)
mfile=""
[ -n "$branch" ] && mfile=".claude/state/$branch/disclosed"
if [ -z "$changed" ]; then [ -n "$mfile" ] && rm -f "$mfile" 2>/dev/null; exit 0; fi
if [ -f "$ps" ]; then
  code=$(sh "$ps" code-changed | head -1)
else
  code=$(printf '%s\n' "$changed" | grep -Ev '^(docs/|CHANGELOG\.md|README|\.claude/|\.github/|PRELIVE\.md|STAGING\.md|[A-Z]+\.md|.*\.md$)' | grep -Ev '^\.(env|teknobu)' | head -1)
fi
reasons=""
if [ -n "$code" ] && ! printf '%s\n' "$changed" | grep -q '^CHANGELOG\.md$'; then
  reasons="$reasons
- Code changed but CHANGELOG.md has no entry for it. Run changelog-scribe (or /post-change)."
fi
if printf '%s\n' "$changed" | grep -q '^supabase/migrations/' && ! printf '%s\n' "$changed" | grep -Fxq "$types"; then
  reasons="$reasons
- A migration changed but $types was not regenerated. Run the types generation command from .claude/rules/supabase.md and commit it."
fi
sig=""
if [ -f "$ps" ] && [ -n "$branch" ] && [ -n "$code" ]; then
  sig=$(sh "$ps" sig)
  due=$(sh "$ps" due)
  v=$(sh "$ps" verdict "$sig")
  word=${v%% *}
  case "$word" in
    none|stale) reasons="$reasons
- No fresh review covers this work (reviewers due: $due). Run /post-change." ;;
    blocked) reasons="$reasons
- The pipeline verdict for $branch is blocked (see .claude/state/$branch/review.json). Fix the blocking findings and re-run /post-change." ;;
    clear-partial) reasons="$reasons
- Reviewers still due for this work: ${v#clear-partial }. Run /post-change." ;;
  esac
elif [ -n "$branch" ] && [ -f ".claude/state/$branch/review.json" ]; then
  old=$($py -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict',''))" ".claude/state/$branch/review.json" 2>/dev/null)
  [ "$old" = "blocked" ] && reasons="$reasons
- The pipeline verdict for $branch is blocked (see .claude/state/$branch/review.json). Fix the blocking findings and re-run /post-change."
fi
if [ -z "$reasons" ]; then [ -n "$mfile" ] && rm -f "$mfile" 2>/dev/null; exit 0; fi
if [ -z "$sig" ]; then printf '%s\n' "Not done yet:$reasons" >&2; exit 2; fi
msig=""
mcount=0
if [ -f "$mfile" ]; then read -r msig mcount < "$mfile" 2>/dev/null; fi
case "$mcount" in ''|*[!0-9]*) mcount=0 ;; esac
if [ "$msig" = "$sig" ] && [ "$mcount" -ge 2 ]; then exit 0; fi
if [ "$msig" = "$sig" ]; then n=$((mcount+1)); else n=1; fi
mkdir -p "$(dirname "$mfile")" 2>/dev/null
if ! printf '%s %s\n' "$sig" "$n" > "$mfile" 2>/dev/null; then
  [ "$active" = "1" ] && exit 0
fi
extra=""
[ "$n" -ge 2 ] && extra="
If these gates cannot be met now, state plainly to the user which are unmet and why, then stop."
printf '%s\n' "Not done yet:$reasons$extra" >&2
exit 2
'''

SESSION_BRIEF_SH = r'''#!/bin/sh
# sonelo-devkit pipeline: SessionStart hook. One line of review debt so the session starts
# knowing what the Stop gate will require; silent when there is nothing to say. stdout
# becomes session context.
{ [ -n "$SONELO_SKIP_HOOKS" ] || [ -n "$TEKNOBU_SKIP_HOOKS" ]; } && exit 0
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
ps=.claude/hooks/pipeline-state.sh
[ -f "$ps" ] || exit 0
branch=$(git branch --show-current 2>/dev/null)
[ -n "$branch" ] || exit 0
files=$(sh "$ps" code-changed)
[ -n "$files" ] || exit 0
n=$(printf '%s\n' "$files" | grep -c .)
due=$(sh "$ps" due)
v=$(sh "$ps" verdict)
word=${v%% *}
[ "$word" = "clear" ] && exit 0
printf '%s\n' "$n changed code file(s) on $branch; reviewers due: $due; verdict: $word. The Stop gate will require a fresh /post-change verdict before this session can end."
exit 0
'''

POST_EDIT_SH = r'''#!/bin/sh
# sonelo-devkit pipeline: PostToolUse hook on Edit/Write/MultiEdit.
# Type-checks and lints the edited file's project so errors surface immediately, and nudges
# once per branch when a full-pipeline path is edited without an impact report on record.
# Exit 2 feeds the output back to Claude.
{ [ -n "$SONELO_SKIP_HOOKS" ] || [ -n "$TEKNOBU_SKIP_HOOKS" ]; } && exit 0
input=$(cat)
py=python
command -v python >/dev/null 2>&1 || py=python3
file=$(printf '%s' "$input" | $py -c "import json,sys; d=json.load(sys.stdin); print((d.get('tool_input') or {}).get('file_path') or '')" 2>/dev/null)
[ -z "$file" ] && exit 0
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
out=""
p=$(printf '%s' "$file" | tr '\\' '/')
branch=$(git branch --show-current 2>/dev/null)
case "$p" in
  *.md) ;;
  */supabase/*|supabase/*|*/functions/*|functions/*|*/auth/*|auth/*|*/auth.*|auth.*)
    if [ -n "$branch" ] && [ ! -f ".claude/state/$branch/impact.json" ] && [ ! -f ".claude/state/$branch/impact-nudged" ]; then
      mkdir -p ".claude/state/$branch" 2>/dev/null
      : > ".claude/state/$branch/impact-nudged" 2>/dev/null
      out="$out
[pipeline]
Full-pipeline path touched ($p). The impact-analyst report is due for this change - run it and record .claude/state/$branch/impact.json before continuing."
    fi
    ;;
esac
case "$p" in
  *.ts|*.tsx|*.js|*.jsx|*.mts|*.cts)
    if [ -f tsconfig.json ]; then
      tsc_out=$(timeout 90 npx --no-install tsc --noEmit -p tsconfig.json 2>&1 | grep -v '^$' | head -40)
      [ -n "$tsc_out" ] && out="$out
[typecheck]
$tsc_out"
    fi
    if [ -f eslint.config.js ] || [ -f eslint.config.mjs ] || [ -f eslint.config.ts ] || [ -f .eslintrc.json ] || [ -f .eslintrc.cjs ] || [ -f .eslintrc.js ]; then
      es_out=$(timeout 60 npx --no-install eslint -- "$file" 2>&1 | grep -v '^$' | head -40)
      [ -n "$es_out" ] && out="$out
[lint]
$es_out"
    fi
    ;;
esac
if [ -n "$out" ]; then
  printf '%s\n' "Fix or act on these before continuing (from the post-edit hook on $file):$out" >&2
  exit 2
fi
exit 0
'''


BUILTIN_PIPELINE = {
    '.claude/agents/design-reviewer.md': DESIGN_REVIEWER_MD,
    '.claude/agents/impact-analyst.md': '---\nname: impact-analyst\ndescription: Before any full-pipeline change, maps what the change touches and what depends on it. Use in plan mode, before editing. Reports; never edits.\ntools: Read, Grep, Glob, Bash(git log:*), Bash(git diff:*)\n---\n\nYou map blast radius. The user is about to change something; your job is to say what else moves.\n\n1. From the request, name the files and symbols that will change.\n2. For each, find every importer and caller (`Grep` for the symbol and the module path). List them with file:line.\n3. Find shared contracts the change crosses: database tables and columns, RLS policies, edge-function request/response shapes, shared types, environment variables, routes.\n4. Name the tests that cover the touched code, and the touched code that has no tests.\n5. Name what could break that nobody asked about: callers with different assumptions, a null that becomes possible, an ordering that matters, a migration that needs a backfill.\n\nReport as: **Touches** (files) · **Depends on it** (callers, with file:line) · **Contracts crossed** · **Test coverage** (covered / uncovered) · **Risks** (one line each, most likely first) · **Recommended order of edits**. Short lines. If the change is genuinely local, say so in two lines and stop.\n',
    '.claude/agents/code-reviewer.md': '---\nname: code-reviewer\ndescription: Reviews a change for correctness - logic errors, unhandled states, regressions in neighbouring code, and whether it does what was asked and nothing else. Use after implementing, before tests. Reports; never edits.\ntools: Read, Grep, Glob, Bash(git status:*), Bash(git ls-files:*), Bash(git diff:*), Bash(git log:*)\n---\n\nYou review the diff (`git diff` against the base branch, plus any untracked files - `git status` and `git ls-files --others --exclude-standard` list them) for whether it is *right*, not whether it is pretty. You never edit.\n\nBudget your reading. The diff is the source, not the repo: read the files it touches, and follow callers only as far as the change actually reaches. Do not sweep the repo by reading it - grep to find callers, then read only the ones the change reaches. Do not read unrelated modules, and do not open a file you have no reason to suspect. Breadth is what costs; depth where the change lands is the job.\n\nWork through, in order, and stop escalating once something fails:\n\n1. **Does it do what was asked, and only that?** Compare the change to the request. Anything extra is a finding; anything missing is a finding.\n2. **Logic.** Off-by-ones, inverted conditions, wrong operator, async not awaited, a promise whose rejection goes nowhere, state updated from stale values, a loop that mutates what it iterates.\n3. **States the code does not handle.** Null, empty, one, many, duplicate, concurrent, slow, failed. For every external call: what happens when it fails, and does the user see it?\n4. **Neighbours.** Read the callers of anything whose signature or behaviour changed. A regression in a file the diff does not touch is the finding that matters most.\n5. **Data.** Migrations append-only; RLS on new tables; types regenerated; no secret in code; no `service_role` in a client path.\n6. **Tests.** Is the changed behaviour tested? Would the tests fail if the change were reverted? A test that cannot fail is not a test.\n\nReport findings ordered by user cost. For each: `file:line` · one sentence naming the defect · who it costs and how · the specific fix · severity **blocks the task** / **hurts the task** / **inconsistency** / **polish**. End with one line: `VERDICT: clear` or `VERDICT: blocked (<n> blocking)`. If it is genuinely fine, say so in a line; do not manufacture findings.\n',
    '.claude/agents/security-reviewer.md': '---\nname: security-reviewer\ndescription: Reviews a change for security - RLS and policies, auth paths, secrets, input handling, edge-function exposure. Use after implementing any change that touches data, auth, edge functions or user input. Reports; never edits.\ntools: Read, Grep, Glob, Bash(git status:*), Bash(git ls-files:*), Bash(git diff:*)\n---\n\nYou review the diff (plus untracked files - `git status` and `git ls-files --others --exclude-standard` list them) for how it could be abused. You never edit.\n\nBudget your reading. The diff is the source, not the repo: read the files it touches, and follow callers only as far as the change actually reaches. Do not sweep the repo by reading it - grep to find callers, then read only the ones the change reaches. Do not read unrelated modules, and do not open a file you have no reason to suspect. Breadth is what costs; depth where the change lands is the job. Two things are always in scope even though the diff does not name them: the migration that created a table you alter, and both sides of an import you change.\n\nCheck, in order:\n1. **Row Level Security.** Every new or altered table has RLS enabled and policies for each operation that is meant to be allowed, scoped to the owner or tenant. Policies that use `true`, or that trust a client-supplied id, are findings.\n2. **Auth.** Protected routes and edge functions verify the session server-side. Roles are checked on the server, never only in the UI.\n3. **Secrets.** No keys, tokens or passwords in code, config, logs or client bundles. `service_role` only inside edge functions, never in anything shipped to a browser.\n4. **Input.** Everything from a request, form, webhook or file is validated before use; SQL and shell built from input are findings; uploads have type and size limits.\n5. **Exposure.** New edge functions: CORS, rate limits, what happens on malformed input, what is returned in errors (no stack traces, no internal ids that enable enumeration).\n6. **Third parties.** Webhooks verify signatures; outbound calls have timeouts; retries are bounded.\n\nReport as `file:line` · the hole · what an attacker does with it · the fix · severity **blocks the task** / **hurts the task** / **polish**. End with `VERDICT: clear` or `VERDICT: blocked (<n> blocking)`. Two lines if it is fine.\n',
    '.claude/agents/test-writer.md': "---\nname: test-writer\ndescription: Writes or extends tests for changed code - unit and integration - and a failing test first for every bug fix. The only agent that writes files, and only test files. Use after a change is implemented, before test-runner.\nmodel: sonnet\ntools: Read, Grep, Glob, Write, Edit, Bash(git diff:*)\n---\n\nYou write tests. You write nothing else: only files under the project's test locations (`tests/`, `__tests__/`, `*.test.*`, `*.spec.*`, `e2e/`). If a test needs a change to source code, report it; do not make it.\n\n1. Read the diff. For every changed behaviour, decide the smallest test that would fail if the change were reverted.\n2. For a bug fix: write the reproducing test first and confirm it fails on the old behaviour (reason from the code if you cannot run it), then that it passes.\n3. Cover the states: empty, one, many, null, failure of any external call. Prefer one assertion per test and names that read as sentences.\n4. Use the project's existing test framework and conventions; look at a neighbouring test before writing one. Never hit production data; use the local or work-branch database, fixtures, or mocks at the boundary.\n5. Do not write tests that cannot fail, tests of the framework, or tests of private details that would break on a harmless refactor.\n\nReport: files written, what each test proves, and any source change a test would need (as a request, not an edit).\n",
    '.claude/agents/test-runner.md': '---\nname: test-runner\ndescription: Runs the project\'s checks and tests and reports the truth of them - what ran, what failed, and why. Use after implementation and after fixes. Never edits.\nmodel: sonnet\ntools: Read, Bash(npm:*), Bash(npx:*), Bash(pnpm:*), Bash(yarn:*), Bash(bun:*), Bash(flutter:*), Bash(python:*), Bash(pytest:*), Bash(git diff:*)\n---\n\nYou run the checks and report what actually happened. You never edit and never "fix" a test by weakening it.\n\n1. Run, in order, stopping at the first red: the type check, the linter, the unit/integration tests, using the commands in `.githooks/checks` (the same list the pre-push hook and CI run). Never against production; the work-branch database or local only.\n2. For every failure: the test name, the assertion, the first relevant line of the stack, and your reading of the cause in one sentence. Do not paste whole logs.\n3. Say what did not run and why (no tests for this area, a missing service, a timeout).\n\nEnd with `TESTS: green (<n> passed)` or `TESTS: red (<n> failed of <m>)`, then the failures. Three lines if everything is green.\n',
    '.claude/agents/qa-runner.md': "---\nname: qa-runner\ndescription: Exercises the running app the way a user would, on the work-branch URL, through Playwright - the flows in docs/UAT_PLAN.md and the ones the change touches - and reports what a user would hit. Use after tests are green and the branch is deployed. Never edits.\nmodel: sonnet\ntools: Read, Grep, Glob, Bash(npx playwright:*), Bash(npx:*), Bash(curl:*)\n---\n\nYou are the tester of what was built, as opposed to the code. You never edit.\n\n1. Find the base URL: `QA_BASE_URL` in the environment, else the work-branch URL in `.teknobu.json` or the work-branch `.env` file. If none, say so and stop.\n2. If the repo has Playwright (`@playwright/test` in package.json, or `e2e/`), run the end-to-end suite against that URL and report as test-runner would. If it has none, say so once and recommend `npm init playwright@latest` with a smoke suite of the UAT plan's top flows; then do the walkthrough below with `curl` for what can be checked without a browser (routes respond, auth redirects, API errors are shaped).\n3. Walk the flows in `docs/UAT_PLAN.md` that the change touches, and the three most important flows regardless. For each: the steps, what happened, what a user would think. Look specifically at empty states, a failed request, a slow request, a refresh mid-flow, a deep link.\n4. Never create data in production. Never use real customer data.\n\nReport per flow: **pass** / **fail** / **could not test** with one line of why, ordered by user cost. End with `QA: pass` or `QA: fail (<n> flows)`.\n",
    '.claude/agents/uat-writer.md': '---\nname: uat-writer\ndescription: Writes the UAT document for the current branch\'s pull request from the diff and the changelog - preconditions, test data, cases with steps and expected results, sign-off. Use before creating a PR. Haiku; formatting work.\nmodel: haiku\ntools: Read, Grep, Glob, Write, Bash(git diff:*), Bash(git log:*), Bash(git branch:*)\n---\n\nYou write `docs/uat/<branch>-<YYYY-MM-DD>.md` for the current branch, for a tester who did not build the feature. Plain English; no code.\n\nFrom `git diff <base>...HEAD`, the CHANGELOG.md entry, and docs/UAT_PLAN.md:\n\n```\n# UAT - <feature or branch> - <date>\n\n**Branch:** <branch>   **Environment:** <work-branch URL>   **Prepared by:** Claude Code   **Status:** awaiting sign-off\n\n## What changed\nTwo to five sentences a client understands.\n\n## Preconditions\nAccounts, roles, data that must exist, feature flags.\n\n## Test data\nExactly what to type or upload, so two testers get the same result.\n\n| ID | Area | Steps | Expected | Result | Tester | Date |\n|----|------|-------|----------|--------|--------|------|\n| UAT-1 | ... | 1. ... 2. ... | ... | | | |\n\n## Not covered here\nWhat this change does not touch and why it is out of scope.\n\n## Sign-off\nName / role / date / decision (accept, accept with notes, reject).\n```\n\nOne row per behaviour a user can observe, including the failure paths. Number steps. Expected results are specific ("the row shows Verified in green", not "it works"). Also add the new cases to docs/UAT_PLAN.md so the master plan stays current. Report the path of the file written.\n',
    '.claude/agents/changelog-scribe.md': '---\nname: changelog-scribe\ndescription: Adds or updates the CHANGELOG.md entry for the current branch from the diff. Use after a change, before the Stop gate. Haiku; formatting work. Writes only CHANGELOG.md.\nmodel: haiku\ntools: Read, Edit, Write, Bash(git diff:*), Bash(git log:*), Bash(git branch:*)\n---\n\nYou maintain CHANGELOG.md (Keep a Changelog shape: `## [Unreleased]` with Added / Changed / Fixed / Removed / Security). From `git diff <base>...HEAD` write one line per user-visible or operator-visible change, in plain language, with the area in front: `- Case search: results now deduplicate across BAILII and the National Archives.` Migrations get a line under Changed naming the table. No internal refactor chatter unless it changes behaviour. Edit only CHANGELOG.md; report the lines added.\n',
    '.claude/agents/docs-maintainer.md': '---\nname: docs-maintainer\ndescription: Keeps docs/STATUS.md current and updates docs/ARCHITECTURE.md when the shape of the system changed. Use at the end of a work block. Haiku; formatting work. Writes only under docs/.\nmodel: haiku\ntools: Read, Edit, Write, Grep, Glob, Bash(git diff:*), Bash(git log:*)\n---\n\nYou keep two documents truthful, editing nothing else.\n\n- `docs/STATUS.md`: what is being worked on now, what was finished in this block (one line each, dated), what is blocked and on whom, the next three things. Delete what is stale; keep it to one screen.\n- `docs/ARCHITECTURE.md`: only when the diff adds or removes a service, table, edge function, integration, route group, or environment variable. Update the relevant section; never rewrite the document.\n\nReport what you changed in two lines.\n',
    '.claude/agents/uat-plan-maintainer.md': '---\nname: uat-plan-maintainer\ndescription: Updates docs/UAT_PLAN.md after a change - flags invalidated scenarios, adds new ones, marks what needs client-side re-testing. Use as part of /post-change.\ntools: Read, Grep, Glob, Write, Edit, Bash(git diff:*)\nmodel: haiku\n---\n\nYou maintain `docs/UAT_PLAN.md` only - do not modify any other file.\n\nGiven the current branch\'s diff (`git diff` against the base branch), changelog entry, and impact report:\n\n1. Mark existing UAT scenarios touched by this change as **RE-TEST REQUIRED**, with the\n   reason and date.\n2. Add scenarios for any new behaviour: ID, preconditions, steps, expected result,\n   tenant/role to test as.\n3. Flag anything that needs **client-side verification** (real accounts, live\n   integrations, third-party services) separately from internal testing.\n4. Keep a short "Changed in this cycle" list at the top so a human can brief UAT in\n   two minutes.\n\nScenario IDs are stable - never renumber existing ones. Retired scenarios are moved to\nan Archive section, not deleted.\n',
    '.claude/commands/post-change.md': '---\ndescription: Run the change pipeline on the current work block - parallel review, fix loop (max 2), tests, verdict, docs. Once per block, not per edit.\n---\nRun the pipeline on everything changed since the last commit on this branch (plus any uncommitted work). Do not ask questions; report each stage in a line or two.\n\n1. **Tier.** Decide fast lane or full pipeline per CLAUDE.md. Say which and why in one line.\n2. **Review, in parallel.** Launch `code-reviewer` and `security-reviewer` together (and `design-reviewer` if anything under the UI changed). Wait for all three.\n3. **Fix loop.** Fix every finding marked *blocks the task* or *hurts the task*. Re-run only the reviewer(s) that reported them. At most two rounds; if a blocker survives two rounds, stop and ask the user with the finding quoted.\n4. **Tests.** Run `test-writer` for the changed behaviour (and the failing-test-first rule for any bug fix), then `test-runner`. Red means fix and re-run; same two-round cap.\n5. **Verdict.** After the last code or test edit of the block, run `sh .claude/hooks/pipeline-state.sh sig` from the repo root, then write `.claude/state/<branch>/review.json`: `{"branch": "...", "at": "<ISO time>", "sig": "<the sig output>", "verdict": "clear" | "blocked", "blocking": ["..."], "reviewers": {"code": "clear|blocked", "security": "clear|blocked", "design": "clear|blocked|skipped"}, "tests": "green|red"}`. The Stop gate blocks until this exists, covers the reviewers the diff makes due, and matches the current sig - any later code edit makes it stale.\n6. **Tail, in parallel.** `changelog-scribe`, `docs-maintainer` and `uat-plan-maintainer` together. Then, if this block is heading for a pull request, `uat-writer`.\n7. **Summary.** Five lines: tier, findings fixed, tests, what is in the changelog, what is still open.\n\nRules: reviewers never edit; only the lead (you) and test-writer write. Never weaken a test to pass it. Never print secrets or env values.\n',
    '.claude/commands/design-pass.md': "---\ndescription: Design-led polish of a screen within the design contract - applies the design-reviewer's polish and consistency findings in the fast lane; leaves anything that blocks or hurts the task for a human.\nargument-hint: <screen or component path>\n---\nRun `design-reviewer` on $ARGUMENTS (or on the screens touched since the last commit if no argument).\n\nThen, in the fast lane and without asking:\n- Apply every finding marked **polish** or **inconsistency**: spacing, hierarchy by size/weight/space, empty/loading/error states, reuse of the existing component for the same job, tokens instead of literals, accessible names, focus rings.\n- Do not touch data flow, contracts, handlers, or logic. If a finding needs any of those, leave it and list it.\n- Do not apply findings marked **blocks the task** or **hurts the task**; list them for the user with the reviewer's wording.\n\nRe-run `design-reviewer` once on the result. Report: what was applied (file:line), what was left and why, and the screens a human should open to see the result. Commit message if asked: `style: design pass on <screen>`.\n",
    '.claude/commands/worktree.md': '---\ndescription: Manage git worktrees for parallel sessions - new <branch> creates a sibling worktree wired for the worklog, list shows state, clean removes merged ones\nargument-hint: new <branch> | list | clean\n---\nRun `python "$HOME/.claude/sonelo/repo_setup.py" worktree $ARGUMENTS` from the repo root (default to `list` when no argument was given) and relay its output plainly.\n- `new <branch>`: report the created path and tell the user to open their next Claude Code session there; the worklog is pre-stamped to report under this repo\'s project.\n- `clean`: a "kept" line is information for the user - uncommitted work, or a branch git cannot prove merged (squash merges look unmerged). Never force-remove a worktree and never delete branches to make clean succeed.\n',
    '.claude/commands/pr.md': '---\ndescription: Create the pull request for this branch into production - pipeline verdict must be clear, UAT document required, PR body is the UAT document.\n---\n1. Confirm `.claude/state/<branch>/review.json` exists with `"verdict": "clear"` and `"tests": "green"` from this branch\'s latest work. If not, run `/post-change` first.\n2. Run `uat-writer` if `docs/uat/` has no document for this branch dated today. Commit it: `docs: UAT for <branch>`.\n3. Push the branch. Create the PR with `gh pr create --base <production branch> --head <branch> --title "<conventional summary>" --body-file docs/uat/<the document>`. Add the changelog lines under a "## Changes" heading in the body if the PR template asks for them.\n4. Report the PR URL, the gates that must pass, and the UAT document path. Never print secrets.\n',
    '.claude/hooks/post-edit.sh': POST_EDIT_SH,
    '.claude/hooks/guard-migrations.sh': '#!/bin/sh\n# sonelo-devkit pipeline: PreToolUse hook on Edit/Write/MultiEdit. Migrations are append-only.\n{ [ -n "$SONELO_SKIP_HOOKS" ] || [ -n "$TEKNOBU_SKIP_HOOKS" ]; } && exit 0\ninput=$(cat)\nfile=$(printf \'%s\' "$input" | python -c "import json,sys; d=json.load(sys.stdin); print((d.get(\'tool_input\') or {}).get(\'file_path\') or \'\')" 2>/dev/null)\ncase "$file" in\n  *supabase/migrations/*|*supabase\\\\migrations\\\\*) ;;\n  *) exit 0 ;;\nesac\nif [ -f "$file" ]; then\n  echo "Blocked: $file is an existing migration. Migrations are append-only - create a new file under supabase/migrations/ instead. (SONELO_SKIP_HOOKS=1 overrides, say why in the commit.)" >&2\n  exit 2\nfi\nexit 0\n',
    '.claude/hooks/stop-gate.sh': STOP_GATE_SH,
    '.claude/hooks/pipeline-state.sh': PIPELINE_STATE_SH,
    '.claude/hooks/session-brief.sh': SESSION_BRIEF_SH,
    '.claude/rules/supabase.md': '---\npaths: ["supabase/**", "src/integrations/supabase/**", "src/lib/supabase*"]\n---\n# Supabase rules\n- Migrations are append-only files under `supabase/migrations/`; never edit an existing one, never change schema in a dashboard. After any migration change regenerate types: `{GEN_TYPES}` and commit the result.\n- Every table has RLS enabled with a policy per allowed operation, scoped to the owner or tenant. No `using (true)` outside intentionally public reads.\n- `service_role` only in edge functions. Clients use the publishable/anon key.\n- Edge functions validate input, return shaped errors (no stack traces), set CORS explicitly, and read secrets from `Deno.env.get`, never from code.\n- Local development and tests point at the work-branch database or `supabase start`; never at production.\n',
    '.github/workflows/ci-gates.yml': '# sonelo-devkit pipeline - pull-request gates: changelog entry, UAT document, types regenerated after migrations.\nname: CI gates\non:\n  pull_request:\n    branches: [{MAIN}]\npermissions:\n  contents: read\njobs:\n  gates:\n    name: gates\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n      - name: Changed files\n        id: files\n        run: |\n          git diff --name-only "origin/${{ github.base_ref }}"...HEAD > changed.txt\n          echo "code=$(grep -Ev \'^(docs/|CHANGELOG\\.md|\\.claude/|\\.github/|.*\\.md$|\\.env)\' changed.txt | head -1)" >> "$GITHUB_OUTPUT"\n      - name: Changelog entry present\n        if: steps.files.outputs.code != \'\'\n        run: grep -q \'^CHANGELOG\\.md$\' changed.txt || { echo "::error::Code changed but CHANGELOG.md has no entry. Run /post-change."; exit 1; }\n      - name: UAT document present\n        if: steps.files.outputs.code != \'\'\n        run: grep -q \'^docs/uat/\' changed.txt || { echo "::error::Code changed but no docs/uat/ document was added for this PR. Run /pr (uat-writer)."; exit 1; }\n      - name: Types regenerated after migrations\n        run: |\n          if grep -q \'^supabase/migrations/\' changed.txt && ! grep -q \'^{TYPES}$\' changed.txt; then\n            echo "::error::Migration changed but {TYPES} was not regenerated."; exit 1; fi\n',
    '.github/pull_request_template.md': '<!-- sonelo-devkit -->\n## Summary\n\n## UAT\nDocument: docs/uat/<file>\n\n## Checklist\n- [ ] Pipeline verdict clear (/post-change)\n- [ ] Tests green\n- [ ] CHANGELOG.md updated\n- [ ] Tried on the {WORK} URL\n- [ ] Migrations applied to the {WORK} database (if any)\n\n## Risk\n<!-- fast lane (docs/copy/styling) or full pipeline (db, auth, edge functions, shared types) -->\n',
    'docs/STATUS.md': '# STATUS - {NAME}\n\n## Now\n- <the one thing being worked on>\n\n## Done recently\n\n## Blocked\n\n## Next\n1.\n2.\n3.\n',
    'docs/ARCHITECTURE.md': '# ARCHITECTURE - {NAME}\n\n## Services and hosting\n<services, hosting, domains - five to ten lines>\n\n## Data\n<core tables, tenancy model, where RLS lives>\n\n## Edge functions\n<one line each>\n\n## Frontend\n<stack, routing, state, key screens>\n\n## Integrations\n<each third party and its auth model>\n\n## Environments\n<local, {WORK}, production - how they differ>\n',
    'docs/UAT_PLAN.md': '# UAT PLAN - {NAME}\n\nMaster list of user-observable behaviours, kept current by uat-writer. Per-PR documents live in docs/uat/.\n\n| ID | Area | Flow | Expected |\n|----|------|------|----------|\n',
}
PIPELINE_CLAUDE_SECTION = '## Change pipeline\n\nEvery change goes through: plan -> implement -> review -> test -> verdict -> docs. The lead is this session; the agents are its specialists. Run `/post-change` once per work block - before reporting the work done, not per edit.\n\n### Risk tiers\n- **Fast lane**: docs, copy, styling, comments, and design-lane changes (below). No plan mode, no impact report. Reviewers, hooks, the Stop gate and CI still apply.\n- **Full pipeline**: anything touching the database or migrations, auth, edge functions, shared types or contracts, or code used in more than one place. Plan mode and the impact-analyst report are mandatory before editing; after the report, record `.claude/state/<branch>/impact.json` (`{"at": "<ISO time>", "touches": ["..."]}`) - the post-edit hook nudges once per branch until it exists.\n- If unsure which tier a change is, it is full pipeline.\n\n### Reviewers are triggered by the diff, not by memory\nThe hooks compute what is due from the changed files (`sh .claude/hooks/pipeline-state.sh due`), the session is briefed at start, and the Stop gate requires a fresh verdict covering:\n\n| Changed | Reviewer due |\n|---|---|\n| any code | `code-reviewer` |\n| *.tsx, *.jsx, *.css, *.scss, tailwind.config.* | `design-reviewer` |\n| supabase/, functions/, auth paths, .github/workflows/ | `security-reviewer` |\n\nRun the due reviewers in one message, in parallel; `/post-change` does this and records the verdict. If something blocks a reviewer from running - a missing tool, a worktree, a session instruction - say so in the same message as the work: after two blocked stops the gate lets the session end so the gap is reported, never hidden.\n\n### Rules that prevent bugs\n- Any bug fix starts with a failing test that reproduces it, then the fix, then the test goes green. No exceptions.\n- Migrations are append-only: never edit an existing file under `supabase/migrations/`; add a new one. After any migration change, regenerate types and commit them.\n- Errors must surface: a request that can fail has a visible failure state in the interface and a logged error on the server. A silent catch is a bug.\n- The type checker and linter run on every edit (PostToolUse hook). Fix what they report before moving on; never disable a rule to pass.\n- Never report a visual change as done on the strength of type checks, lint, tests and the build alone - none of them can see the screen. Render it, or run `design-reviewer`.\n- "Done" means: reviewers\' verdict clear, tests green, CHANGELOG.md entry, UAT document for the PR, STATUS.md current.\n\n### Design-led, build-safe\n- When building or changing a screen, make the design decisions yourself, within `.claude/rules/design.md`: hierarchy, empty/loading/error states, spacing, reuse of the existing component for the same job. Do not ask; decide and say what you decided.\n- A design decision may never change data flow, contracts, or logic. If it would, it is a full-pipeline change and is planned first.\n- `/design-pass <screen>` applies the design-reviewer\'s polish and consistency findings in the fast lane and leaves anything that blocks or hurts the task for a human.\n\n### Loop cap\n- Review -> fix -> re-review runs at most twice. If a reviewer still reports a blocker after two rounds, stop and ask the user. The Stop gate blocks at most twice per work-state, then requires plain disclosure of what is unmet.\n'

LANDING_COMMAND_MD = '''---
description: Open this repo's landing page - commands, agents, state, environments, docs, worklog - in the browser
---
Run `python "$HOME/.claude/sonelo/repo_setup.py" landing` and report in one line that the page opened (the command prints its path). Do nothing else.
'''

LANDING_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{NAME} &mdash; Sonelo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,500;1,9..144,300;1,9..144,400&family=Manrope:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--paper:#f6f4ee;--ink:#14161a;--ink2:#3a3d44;--mute:#7a7e87;--rule:rgba(20,22,26,.14);--rule2:rgba(20,22,26,.07);--accent:{ACCENT};--ok:#2a6f4e;--no:#a8422f;
--serif:"Fraunces","Iowan Old Style","Palatino Linotype",Georgia,serif;--sans:"Manrope",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"JetBrains Mono",ui-monospace,"SF Mono",Consolas,monospace}
*{box-sizing:border-box}html{background:var(--paper)}body{margin:0;color:var(--ink);font:15px/1.6 var(--sans);-webkit-font-smoothing:antialiased;font-feature-settings:"tnum" 1}
.page{max-width:1280px;margin:0 auto;padding:56px 56px 72px}
.eyebrow{font:500 11px/1 var(--sans);letter-spacing:.18em;text-transform:uppercase;color:var(--mute)}
.masthead{display:grid;grid-template-columns:1fr auto;gap:32px;align-items:end;padding-bottom:28px;border-bottom:1px solid var(--ink)}
.masthead h1{margin:10px 0 6px;font:300 64px/1.02 var(--serif);letter-spacing:-.02em;font-variation-settings:"opsz" 144}
.masthead .lede{margin:0;font:italic 300 20px/1.4 var(--serif);color:var(--ink2)}
.masthead .lede code{font:500 15px var(--mono);font-style:normal;color:var(--ink);background:rgba(20,22,26,.05);padding:2px 7px;border-radius:3px}
.lockup{text-align:right;font-size:13px;color:var(--mute);line-height:1.9}.lockup b{display:block;font:400 34px/1 var(--serif);color:var(--ink);letter-spacing:-.01em}.lockup .ok{color:var(--ok)}.lockup .no{color:var(--no)}
.grid{display:grid;grid-template-columns:repeat(12,1fr);column-gap:40px;row-gap:0}
section{padding:34px 0 30px;border-top:1px solid var(--rule);grid-column:span 6}section.wide{grid-column:1/-1}section.third{grid-column:span 4}
section h2{display:flex;align-items:baseline;gap:14px;margin:0 0 18px;font:400 24px/1.2 var(--serif);letter-spacing:-.01em}
section h2 .n{font:500 11px var(--mono);color:var(--mute);letter-spacing:.1em}
.flow{counter-reset:step;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0 18px;margin:4px 0 14px}
.flow .s{counter-increment:step;padding:12px 0 14px;border-top:1px solid var(--rule2);position:relative}
.flow .s:before{content:counter(step,decimal-leading-zero);display:block;font:500 11px var(--mono);color:var(--mute);letter-spacing:.1em;margin-bottom:6px}
.flow .s b{display:block;font:500 15px var(--sans);color:var(--ink)}.flow .s span{display:block;font-size:13px;color:var(--mute);margin-top:2px}.flow .s.key b{color:var(--accent)}
.lane{font:italic 300 16px/1.5 var(--serif);color:var(--ink2);max-width:900px}
.row{display:grid;grid-template-columns:168px 1fr auto auto;gap:14px;align-items:baseline;padding:10px 0;border-top:1px solid var(--rule2)}
.row:first-of-type{border-top:0}.row .k{font:500 13px var(--mono);color:var(--ink);word-break:break-all}.row .d{color:var(--ink2);font-size:14px}
.row .m{font:500 10px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--mute)}
button.copy{font:500 10px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--mute);background:none;border:0;border-bottom:1px solid var(--rule);padding:0 0 2px;cursor:pointer;transition:color .15s,border-color .15s}
button.copy:hover{color:var(--accent);border-color:var(--accent)}button.copy.done{color:var(--ok);border-color:var(--ok)}
.state{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:2px 28px}.state div{padding:7px 0;font-size:14px;color:var(--ink2);border-top:1px solid var(--rule2)}
.tick{display:inline-block;width:8px;height:8px;border-radius:50%;margin:0 10px 1px 0;background:var(--ok)}.tick.no{background:var(--no)}
a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule);transition:border-color .15s}a:hover{border-color:var(--accent)}
.muted{color:var(--mute);font-size:14px}.mono{font:500 13px var(--mono)}
footer{margin-top:40px;padding-top:18px;border-top:1px solid var(--ink);display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap;font-size:12.5px;color:var(--mute)}
@media (max-width:900px){.page{padding:32px 22px 48px}.masthead{grid-template-columns:1fr}.lockup{text-align:left}.masthead h1{font-size:44px}section,section.third{grid-column:1/-1}.row{grid-template-columns:1fr;gap:4px}}
</style></head><body><div class="page">
<header class="masthead">
  <div><div class="eyebrow">Sonelo Solution DevKit &middot; v{VERSION} &middot; {WHEN}</div><h1>{NAME}</h1>
  <p class="lede">Work on <code>{WORK}</code>, pull request into <code>{MAIN}</code>. Currently on <code>{BRANCH}</code>.</p></div>
  <div class="lockup"><b>{OKCOUNT}<span style="color:var(--mute);font-size:20px"> / {TOTAL}</span></b>standards in place{STATE_NOTE}</div>
</header>
<div class="grid">
<section class="wide"><h2><span class="n">01</span>The pipeline</h2>
<div class="flow">
<div class="s"><b>Plan</b><span>plan mode, impact-analyst maps the blast radius</span></div>
<div class="s"><b>Implement</b><span>type check and lint after every edit; migrations append-only</span></div>
<div class="s key"><b>/post-change</b><span>code, security and design reviewers in parallel</span></div>
<div class="s"><b>Fix</b><span>two rounds at most, then it asks</span></div>
<div class="s"><b>Test</b><span>test-writer, then test-runner; failing test first for bugs</span></div>
<div class="s"><b>Verdict</b><span>written per branch; the Stop gate reads it</span></div>
<div class="s"><b>Record</b><span>changelog, STATUS, architecture</span></div>
<div class="s key"><b>/pr</b><span>UAT document required; it becomes the pull request</span></div>
<div class="s"><b>Gates</b><span>CI: changelog, UAT, types; then {MAIN}</span></div>
</div>
<p class="lane">Fast lane for docs, copy, styling and design-lane changes. Full pipeline for anything touching data, auth, edge functions, shared types, or code used in more than one place. When unsure, it is full pipeline.</p></section>
<section><h2><span class="n">02</span>Commands</h2>{COMMANDS}</section>
<section><h2><span class="n">03</span>Agents</h2>{AGENTS}</section>
<section class="wide"><h2><span class="n">04</span>Repo state</h2><div class="state">{STATE}</div></section>
<section class="third"><h2><span class="n">05</span>Environments</h2>{ENVS}</section>
<section class="third"><h2><span class="n">06</span>Documents</h2>{DOCS}</section>
<section class="third"><h2><span class="n">07</span>Worklog</h2>{WORKLOG}</section>
<section class="wide"><h2><span class="n">08</span>Escape hatches</h2>
<div class="row"><span class="k">SONELO_SKIP=1</span><span class="d">in front of a git command: hooks off for that one command</span></div>
<div class="row"><span class="k">SONELO_ALLOW_MAIN=1</span><span class="d">one direct push to {MAIN}</span></div>
<div class="row"><span class="k">SONELO_SKIP_HOOKS=1</span><span class="d">Claude Code hooks (type check, migrations guard, Stop gate) off for the session</span></div>
<div class="row"><span class="k">.nokit &middot; .noworklog</span><span class="d">files in the repo root: no session nudge &middot; no worklog here</span></div></section>
</div>
<footer><span>Regenerate with <span class="mono">/landing</span>. Nothing on this page is a secret; keys live in git-ignored env files and are never shown.</span><span>Sonelo &middot; Teknobu Group Ltd</span></footer>
</div>
<script>
document.querySelectorAll('button.copy').forEach(function(b){b.addEventListener('click',function(){navigator.clipboard.writeText(b.getAttribute('data-copy')).then(function(){b.textContent='copied';b.classList.add('done');setTimeout(function(){b.textContent='copy';b.classList.remove('done')},1200)})})});
</script></body></html>
"""

COMMAND_MD = '''---
description: Apply the Teknobu standards to this repo (existing, new project, or Lovable migration) - asks everything first, then does it all
---
Start with one question: "Existing repo, new project, or migrating a Lovable project?" If the folder is empty or not a git repo, suggest new project. New project -> read ~/.claude/commands/new-repo.md and follow it. Otherwise continue here.

Gather everything before doing anything, in one message, defaults in brackets; the user can answer "defaults":
1. Brand and product guidelines: paste them, name a file, or say "defaults" / "none yet". [defaults]
2. Deploys on Vercel? If yes, {WORK} domain [{WORK}.<production domain>] and production domain [{DOMAIN_EXAMPLE}].
3. Supabase: already has a production project [yes for an existing app] - then create only the {WORK} database; or create both.
4. GitHub branch protection on main [yes].
5. UAT Hub project slug, so sessions can push UAT test cases to {UAT_HUB} instead of writing a Markdown file [the repo folder name]. The project must already exist in the hub - a push to an unknown slug is refused rather than creating one, so ask the user rather than guessing. "skip" leaves the default in place; the wiring stays inert until the project exists.
Confirm the plan in four lines, including that Supabase projects may be billable. Then run without further questions.

Do, reporting each step's output:
1. `python "$HOME/.claude/sonelo/repo_setup.py" doctor` - stop and tell the user if a login the plan needs is missing; don't work around it.
2. `python "$HOME/.claude/sonelo/repo_setup.py" apply --uat-project <slug>` (drop the flag to keep whatever the repo already recorded). It lays down hooks, CI, {ENVDOC}, CLAUDE.md and its "Writing UAT" section, `.mcp.json` registering the UAT Hub MCP server (merged into any that exists; the key stays the `${UAT_HUB_KEY}` placeholder and is never written out), `UAT_HUB_KEY` in `.env.example`, the pipeline (agents, /post-change, /design-pass, /pr, the three Claude Code hooks, CI gates, rules), the design contract, the worklog, creates `{WORK}` from `{MAIN}` and checks it out, and for a Lovable project writes MIGRATION.md. On a repo that already has an older pipeline, prefer `repo_setup.py refresh`: it takes the kit's current agents, commands, hooks and CI *gates* (ci-gates.yml, pull_request_template.md), keeps a backup of everything it replaces, and touches nothing else - not the repo's own ci.yml, env files, design contract or branches. Never pass `--force` unless asked.
3. Brand: write the guidelines verbatim to `docs/BRAND.md` if given, and rewrite `.claude/rules/design.md` from them (tokens and roles, type families and weights, radius, borders vs shadows, the one call-to-action colour, the off-brand list, the design lint command if any). Put the product's one-line description and voice rules into CLAUDE.md and the pipeline's ARCHITECTURE/STATUS/UAT placeholders. Take the stack from the repo, not from the guidelines; if they disagree (e.g. the document still says Lovable Cloud), say so in the summary.
4. Fill every remaining `TODO` in the pipeline files from what is true of the repo. Ask nothing; leave a TODO only if it is genuinely unknowable.
5. Stage the generated files, `git update-index --chmod=+x .githooks/commit-msg .githooks/pre-commit .githooks/pre-push .claude/hooks/*.sh`, commit `chore: apply sonelo repo standards` on `{WORK}`.
6. If wanted: `repo_setup.py protect` (requires `checks` and the pipeline's gates job). Then `supabase --create [--only {WORK}]` and `vercel --create --domain <{WORK} domain> --production-domain <prod>` as answered. Commit `.env.example` and `vercel.json` if created.
7. `git push -u origin {WORK}`.
8. Summary: branch model, what is enforced, what was created, DNS records outstanding, and anything that differed from the plan. Keep it short.

Rules: never print secrets, tokens, or the contents of `.env*` files, and never inspect environment variables with shell echo - `repo_setup.py doctor` reports presence without values. If a step fails, stop, show the error, ask before retrying. These are the user's standards; do not reinterpret them.
'''

NEW_COMMAND_MD = '''---
description: Create a new Teknobu project from scratch - one set of questions, then scaffold, agents and rules, standards, GitHub, Supabase, Vercel
---
Ask everything in ONE message, defaults in brackets. The user can reply "defaults" or change any item:

1. Project name, kebab-case. [required]
2. Location. [a new folder named after the project inside the current folder, unless the current folder is empty or holds only the kit - then the current folder]
3. Stack. [{STACK}] (or TanStack Start + React + TypeScript + Supabase / Vite + React + TypeScript + Supabase / Flutter / empty)
4. GitHub. [{ORG_OR_USER}, private]
5. Supabase. [{DB_PLAN}, region {REGION}]
6. Vercel. [create the project; {WORK}.{DOMAIN_PATTERN} for {WORK}, {DOMAIN_PATTERN} for production]
7. Brand and product guidelines: paste, name a file, or "defaults" / "none yet". [defaults]

Confirm the plan in a few lines, including that the Supabase projects may be billable, and that it will run to the end without further questions. Then do all of this, reporting each step briefly:

a. `python "$HOME/.claude/sonelo/repo_setup.py" doctor`. If a login the plan needs is missing, STOP and tell the user what to do; do not work around it.
b. Create the folder. `git init -b main`. Commit nothing yet.
c. Agents and rules FIRST: `python "$HOME/.claude/sonelo/repo_setup.py" apply`. It lays down the pipeline (agents, /post-change, stop gate, CI gates, rules, docs), the design-reviewer, `.claude/rules/design.md`, CLAUDE.md, hooks and CI before any application code exists. If brand guidelines were given: write them verbatim to `docs/BRAND.md`, rewrite `.claude/rules/design.md` from them (tokens and roles, type families and weights, radius, borders vs shadows, the single call-to-action colour, the off-brand list), and put the one-line description and voice rules into CLAUDE.md. The stack comes from the plan, not from the guidelines.
d. Scaffold the chosen stack into the folder with its current official scaffolding command (check the docs if unsure; non-interactive flags; keep the existing files). For "empty", a README.md. Make sure `.gitignore` exists.
e. `apply` again (now it detects the stack and fills the pipeline's build/test/types placeholders; it also creates `{WORK}` from `{MAIN}` and checks it out). Fill any remaining TODOs from what is true of the repo; leave none unless genuinely unknowable.
f. Stage everything, `git update-index --chmod=+x .githooks/commit-msg .githooks/pre-commit .githooks/pre-push .claude/hooks/*.sh`, commit `chore: scaffold <stack> with sonelo standards and pipeline` on {MAIN}, then `git checkout {WORK}` (or create it from {MAIN} if apply could not).
g. `repo_setup.py github --org <org>` (add `--public` only if asked). Creates the repository, pushes {MAIN} and {WORK}, protects {MAIN} with `checks` and the pipeline's gates job.
h. `repo_setup.py supabase --create` (plus `--org` if doctor listed more than one). Creates the database(s) per the configured strategy ({DATABASE}), runs `supabase init` if the CLI is present so the deploy workflow exists, writes the env files, sets the five GitHub secrets. Then `apply` once more so the deploy workflow is generated, and commit it.
i. `repo_setup.py vercel --create --domain <{WORK} domain> --production-domain <production domain>`. Creates the project from the GitHub repo, binds the {WORK} domain to the {WORK} branch, pushes `.env.{WORK}` to Preview and `.env.production` to Production, prints any DNS records.
j. Commit anything new (`.env.example`, `vercel.json`, the deploy workflow) on {WORK} and push.
k. Summary: where it lives, the URLs, DNS records outstanding, and the first three things to do next. Short.

Rules: never print secrets, tokens, or the contents of `.env*` files; never inspect environment variables with shell echo - `repo_setup.py doctor` reports presence without values. Ask before anything billable beyond the confirmed plan. If a step fails, stop, show the error, ask before retrying. These are the user's standards; do not reinterpret them.
'''



# ----------------------------------------------------------------------------- apply

def fill(tpl, **kw):
    out = tpl.replace("{MARK}", MARK).replace("{VERSION}", VERSION)
    for k, v in kw.items():
        out = out.replace("{%s}" % k, v)
    return out


def ours(path):
    text = read(path)
    return text is not None and any(m in text for m in ALL_MARKS)


class Report:
    def __init__(self, dry):
        self.dry = dry
        self.rows = []

    def put(self, path, text, executable=False, owned=True, force=False):
        """Create or update a generated file. Files we own (marker present) are refreshed; others are left alone unless force."""
        existing = read(path)
        if existing is None:
            action = "created"
        elif existing == text:
            action = "unchanged"
        elif force or (owned and any(m in existing for m in ALL_MARKS)):
            action = "updated"
        else:
            action = "skipped (exists without kit marker; use --force to replace)"
        if action in ("created", "updated") and not self.dry:
            write(path, text, executable=executable)
        self.rows.append((action, path))
        return action

    def note(self, action, what):
        self.rows.append((action, what))


def merge_gitattributes(root, rep):
    path = root / ".gitattributes"
    existing = read(path) or ""
    have = set(l.strip() for l in existing.splitlines())
    missing = [l for l in GITATTRIBUTES_LINES if l not in have and not l.startswith("#")]
    if not missing:
        rep.note("unchanged", path)
        return
    text = existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + "# sonelo standards\n" + "\n".join(missing) + "\n"
    if not rep.dry:
        write(path, text)
    rep.note("updated" if existing else "created", path)


def merge_gitignore(root, rep):
    path = root / ".gitignore"
    existing = read(path) or ""
    have = set(l.strip() for l in existing.splitlines())
    missing = [l for l in GITIGNORE_LINES if l not in have and not l.startswith("#")]
    text = existing
    if missing:
        text = existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + "# sonelo standards\n" + "\n".join(missing) + "\n"
    # .env.example must stay visible: a later `.env*` line (Vercel appends one) re-ignores it unless the negation comes after
    lines = text.splitlines()
    neg = [i for i, l in enumerate(lines) if l.strip() == "!.env.example"]
    ign = [i for i, l in enumerate(lines) if re.match(r"^\s*\.env(\*|\.\*)?\s*$", l)]
    moved = bool(ign) and (not neg or max(neg) < max(ign))
    if moved:
        lines = [l for l in lines if l.strip() != "!.env.example"] + ["!.env.example"]
        text = "\n".join(lines) + "\n"
    if text == existing:
        rep.note("unchanged", path)
        return
    if not rep.dry:
        write(path, text)
    rep.note("updated (%d lines added%s)" % (len(missing), "; !.env.example moved last" if moved else ""), path)


def kit_env_lines(keys):
    """The kit's own .env.example entries: what the variable is for, then an empty value. A value is
    never written here - .env.example is committed."""
    doc = {UAT_HUB_KEY_VAR: ("# UAT Hub (%s): create-only key for pushing UAT test cases from a Claude\n"
                             "# Code session. Set it in your environment - it is not a deploy variable, and a\n"
                             "# literal key never belongs in a committed file.\n" % UAT_HUB_URL)}
    return "".join(doc.get(k, "") + "%s=\n" % k for k in keys)


def env_example(root, rep):
    env, example = root / ".env", root / ".env.example"
    keys = []
    for src in (env, root / ".env.local"):
        for line in (read(src) or "").splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if m and m.group(1) not in keys:
                keys.append(m.group(1))
    kit = [k for k in KIT_ENV_KEYS if k not in keys]   # the kit needs these whether or not a .env mentions them
    existing = read(example)
    if existing is None:
        text = ("# Copy to .env and fill in. Prelive and production use different values.\n"
                + "".join("%s=\n" % k for k in keys) + kit_env_lines(kit))
        if not rep.dry:
            write(example, text)
        rep.note("created (%d keys, values stripped)" % (len(keys) + len(kit)), example)
        return
    have = set(re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", existing, re.M))
    add = [k for k in keys if k not in have]
    add_kit = [k for k in kit if k not in have]
    if add or add_kit:
        if not rep.dry:
            write(example, existing.rstrip("\n") + "\n" + "".join("%s=\n" % k for k in add) + kit_env_lines(add_kit))
        rep.note("updated (%d keys added)" % (len(add) + len(add_kit)), example)
    else:
        rep.note("unchanged", example)


def env_prelive(root, rep):
    path = root / (".env.%s" % WORK_BRANCH)
    if path.exists():
        rep.note("unchanged (yours)", path)
        return
    # KIT_ENV_KEYS are session/machine variables - UAT_HUB_KEY is read by the MCP server on the
    # machine running Claude Code. Pushing them to a hosting provider spreads a secret for no gain.
    keys = [k for k in re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=",
                                  read(root / ".env.example") or "", re.M) if k not in KIT_ENV_KEYS]
    if not keys:
        rep.note("skipped (no .env.example keys to start from)", path)
        return
    text = ("# %s values, pushed to Vercel (Preview, branch %s) by: repo_setup.py vercel --domain %s.<domain>\n"
            "# Git-ignored. Leave a value empty to skip it; the general Preview value (or nothing) applies then.\n" % (WORK_BRANCH, WORK_BRANCH, WORK_BRANCH)
            + "".join("%s=\n" % k for k in keys))
    if not rep.dry:
        write(path, text)
    rep.note("created (%d keys, fill in)" % len(keys), path)


def uat_slug(root, explicit=None):
    """This repo's UAT Hub project slug.

    The hub fixes a slug when the project is created there and it cannot change afterwards, so it is
    not derivable - hence: what was asked for, else what the repo already recorded, else the folder
    name. A guessed default is safe to write because a push to a slug the hub does not know is
    refused with a message saying so; the wiring is inert, not broken, until the project exists."""
    for value in (explicit, read_json(root / ".teknobu.json", {}).get("uat_project"), root.name):
        if value and str(value).strip():
            return str(value).strip()
    return root.name


def backup_copy(root, name, text, into=None):
    """Keep a copy of a file the kit is about to replace, under .claude/.backup/<stamp>/.

    Not named `backup`: copy_pipeline has a local of that name for the same directory, and a
    function shadowed inside the one place most likely to want it is a trap."""
    into = into or (root / ".claude" / ".backup" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    into.mkdir(parents=True, exist_ok=True)
    if not (into.parent / ".gitignore").exists():
        write(into.parent / ".gitignore", "*\n")
    write(into / name, text)
    return into


def mcp_json(root, rep, slug, into=None):
    """Register the UAT Hub MCP server, merging into whatever .mcp.json the repo already has.

    The key is written as the literal "${UAT_HUB_KEY}", expanded from the environment when Claude
    Code starts the server. It is never resolved here: .mcp.json is committed into client repos that
    may be handed over or shared, and one key covers every project - a literal in one repo's history
    would expose push access for the whole estate.

    Only the uat-hub entry is ours. Any other server in the file is left exactly as it is, and a
    .mcp.json that will not parse is reported rather than replaced."""
    path = root / ".mcp.json"
    server = {"command": "node", "args": [UAT_HUB_SERVER.as_posix()],
              "env": {"UAT_HUB_URL": UAT_HUB_URL, "UAT_HUB_KEY": "${%s}" % UAT_HUB_KEY_VAR,
                      "UAT_HUB_PROJECT": slug}}
    existing = read(path)
    if existing is None:
        data, action = {"mcpServers": {UAT_MCP_NAME: server}}, "created"
    else:
        data = read_json(path, None)
        if data is None:
            rep.note("skipped (not a JSON object; add the %s server by hand)" % UAT_MCP_NAME, path)
            return
        servers = data.get("mcpServers")
        data["mcpServers"] = servers if isinstance(servers, dict) else {}
        data["mcpServers"][UAT_MCP_NAME] = server
        action = "updated"
    text = json.dumps(data, indent=2) + "\n"
    if existing == text:
        rep.note("unchanged", path)
        return
    saved = None
    if not rep.dry:
        if existing is not None:
            saved = backup_copy(root, ".mcp.json", existing, into)
        write(path, text)
    rep.note("%s (%s -> project %s)" % (action, UAT_MCP_NAME, slug), path)
    return saved


def splice(text, start, end, block, before=None):
    """Replace a marked block in place, or add it - immediately before `before` when that marker is
    present, otherwise at the end."""
    if start in text and end in text:
        a, b = text.index(start), text.index(end) + len(end)
        return text[:a] + block.rstrip("\n") + text[b:]
    if before and before in text:
        a = text.index(before)
        return text[:a] + block.rstrip("\n") + "\n\n" + text[a:]
    return text.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n"


def claude_md(root, rep, slug=None, update=False):
    path = root / "CLAUDE.md"
    section = fill(CLAUDE_SECTION, WORK=WORK_BRANCH, MAIN=PROTECTED[0])
    existing = read(path)

    def marker(fmt):
        for m in ALL_MARKS:
            if existing and fmt % m in existing:
                return fmt % m
        return fmt % MARK
    ustart, uend = marker("<!-- %s:uat:start"), marker("<!-- %s:uat:end -->")
    uat = fill(UAT_SECTION, UAT_PROJECT=uat_slug(root, slug))
    pstart, pend = marker("<!-- %s:pipeline:start -->"), marker("<!-- %s:pipeline:end -->")
    pipeline = ("<!-- %s:pipeline:start -->" % MARK) + "\n" + fill(PIPELINE_CLAUDE_SECTION, WORK=WORK_BRANCH, MAIN=PROTECTED[0]).rstrip("\n") + "\n" + ("<!-- %s:pipeline:end -->" % MARK) + "\n"
    start, end = marker("<!-- %s:start"), marker("<!-- %s:end -->")
    if existing is None:
        text, action = ("# %s\n\n<one line: what this product is and who it is for>\n\n" % root.name
                        + pipeline + "\n" + uat + "\n" + section), "created"
    else:
        text = existing
        if pstart in text and pend in text:
            if update:
                a, b = text.index(pstart), text.index(pend) + len(pend)
                text = text[:a] + pipeline.rstrip("\n") + text[b:]
        elif "## Change pipeline" in text and not update:
            pass                                    # the starter's own pipeline section is in charge
        else:
            if "## Change pipeline" in text and update:
                a = text.index("## Change pipeline")
                m = re.search(r"\n(## |<!-- (?:%s))" % "|".join(ALL_MARKS), text[a + 5:])
                b = a + 5 + m.start() + 1 if m else len(text)
                text = text[:a] + text[b:]
            if start in text:
                text = text[:text.index(start)] + pipeline + "\n" + text[text.index(start):]
            else:
                text = text.rstrip("\n") + "\n\n" + pipeline
        text = splice(text, ustart, uend, uat, before=start)   # between the pipeline and the standards
        if start in text and end in text:
            a, b = text.index(start), text.index(end) + len(end)
            text = text[:a] + section.rstrip("\n") + text[b:]
        else:
            text = text.rstrip("\n") + "\n\n" + section
        action = "unchanged" if text == existing else "updated"
    if action != "unchanged" and not rep.dry:
        write(path, text)
    rep.note(action, path)


def find_pipeline_zip():
    here = Path(__file__).resolve().parent
    for folder in (here, here.parent, Path("~/Downloads").expanduser(), Path.cwd()):
        try:
            hits = sorted(folder.glob("claude-pipeline-starter*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            hits = []
        if hits:
            return hits[0]
    return None


def pipeline_present():
    return PIPELINE_DIR.is_dir() and any(p.is_file() for p in PIPELINE_DIR.rglob("*"))


def install_pipeline_zip(zip_path):
    """Extract the pipeline starter into PIPELINE_DIR, flattening a single top-level folder."""
    import zipfile
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        tops = {n.split("/")[0] for n in names}
        strip = (tops.pop() + "/") if len(tops) == 1 and "CLAUDE.md" not in names else ""
        for n in names:
            rel = n[len(strip):] if strip and n.startswith(strip) else n
            if not rel or rel.startswith("__MACOSX"):
                continue
            dst = PIPELINE_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
    return sum(1 for p in PIPELINE_DIR.rglob("*") if p.is_file())


def fill_placeholders(root, d, rep):
    """Fill the pipeline's mechanical TODOs from what the repo tells us; prose TODOs stay for the setup command."""
    name = root.name
    pm = d.get("pm") or "npm"
    run = {"npm": "npm run %s", "pnpm": "pnpm %s", "yarn": "yarn %s", "bun": "bun run %s"}.get(pm, "npm run %s")
    scripts = {}
    try:
        scripts = json.loads(read(root / "package.json") or "{}").get("scripts") or {}
    except ValueError:
        pass
    # only fill what is actually known; an unknown stays a TODO for a later apply (new projects get scaffolded after the first apply)
    build = (run % "build") if "build" in scripts else ("flutter build apk" if d.get("flutter") else None)
    test = (run % "test") if "test" in scripts else ("flutter test" if d.get("flutter") else None)
    ref = ""
    for envf in (".env", ".env.%s" % WORK_BRANCH):
        m = re.search(r"^(?:VITE_)?SUPABASE_PROJECT_REF=(\w+)", read(root / envf) or "", re.M)
        if m:
            ref = m.group(1)
            break
    subs = [(r"<TODO: project name>", name)]
    if build:
        subs += [(r"<TODO: build command>", build), (r"npm run build\s+# TODO: real build command", build)]
    if test:
        subs += [(r"<TODO: test command>", test),
                 (r"npm test\s+# TODO: real test command \(against ephemeral/local DB, never prod\)", test + "   # against ephemeral/local DB, never prod")]
    if ref:
        subs += [(r"<TODO: gen:types command>", "npx supabase gen types typescript --project-id %s --schema public > src/types/database.ts" % ref),
                 (r"<TODO: local Supabase / staging project ref>", "%s database %s" % (WORK_BRANCH, ref))]
    n_files = n_subs = 0
    targets = list((root / ".claude").rglob("*.md")) + list((root / ".claude").rglob("*.sh")) + list((root / "docs").glob("*.md")) + list((root / ".github" / "workflows").glob("*.yml"))
    for path in targets:
        text = read(path)
        if not text or "TODO" not in text:
            continue
        new = text
        for pat, val in subs:
            new, k = re.subn(pat, lambda m, v=val: v, new)
            n_subs += k
        if new != text:
            n_files += 1
            if not rep.dry:
                write(path, new)
    if n_subs:
        rep.note("%d placeholder%s filled in %d file%s (prose TODOs left for the setup command)" % (n_subs, "" if n_subs == 1 else "s", n_files, "" if n_files == 1 else "s"), "pipeline")


def pipeline_vars(root, d):
    cfg = read_json(root / ".teknobu.json", {})
    types = cfg.get("generated_types") or "src/types/database.ts"
    ref = ""
    for envf in (".env", ".env.%s" % WORK_BRANCH):
        m = re.search(r"^(?:VITE_)?SUPABASE_PROJECT_REF=(\w+)", read(root / envf) or "", re.M)
        if m:
            ref = m.group(1)
            break
    gen = "npx supabase gen types typescript --project-id %s --schema public > %s" % (ref or "$SUPABASE_PROJECT_REF", types)
    return dict(NAME=root.name, WORK=WORK_BRANCH, MAIN=PROTECTED[0], TYPES=types, GEN_TYPES=gen)


def copy_pipeline(root, rep, d=None, update=False):
    """The starter folder (your own pipeline) first, then the kit's built-in pipeline fills whatever is missing.
    --update-pipeline rewrites the built-in-named files from the kit (backup kept), keeping everything else."""
    d = d or detect(root)
    n_starter = 0
    if pipeline_present():
        for src in PIPELINE_DIR.rglob("*"):
            if src.is_dir():
                continue
            dst = root / src.relative_to(PIPELINE_DIR)
            if dst.exists():
                continue
            if not rep.dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(src), str(dst))
            n_starter += 1
        rep.note("starter: %d file%s copied" % (n_starter, "" if n_starter == 1 else "s"), PIPELINE_DIR)
    vars_ = pipeline_vars(root, d)
    seed_only = {"docs/STATUS.md", "docs/ARCHITECTURE.md", "docs/UAT_PLAN.md"}   # living documents: created once, never refreshed
    n_new = n_upd = 0
    replaced = []
    backup = root / ".claude" / ".backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
    for rel, tpl in BUILTIN_PIPELINE.items():
        dst = root / rel
        text = fill(tpl, **vars_)
        if dst.exists():
            if not update or rel in seed_only or (read(dst) or "") == text:
                continue
            if not rep.dry:
                backup.mkdir(parents=True, exist_ok=True)
                # self-ignoring: refresh does not touch .gitignore, and a repo set up before
                # v4.3 has no .claude/.backup/ line in it
                if not (backup.parent / ".gitignore").exists():
                    write(backup.parent / ".gitignore", "*\n")
                shutil.copyfile(str(dst), str(backup / rel.replace("/", "__").lstrip(".")))
                write(dst, text, executable=rel.endswith(".sh"))
            replaced.append(rel)
            n_upd += 1
            continue
        if not rep.dry:
            write(dst, text, executable=rel.endswith(".sh"))
        n_new += 1
    if not rep.dry:
        cl = root / "CHANGELOG.md"
        if not cl.exists():
            write(cl, "# Changelog\n\nAll notable changes, kept by changelog-scribe.\n\n## [Unreleased]\n\n### Added\n\n### Changed\n\n### Fixed\n")
        (root / "docs" / "uat").mkdir(parents=True, exist_ok=True)
        keep = root / "docs" / "uat" / ".gitkeep"
        if not keep.exists():
            write(keep, "")
    rep.note("built-in pipeline: %d file%s added%s (agents, /post-change, /design-pass, /pr, hooks, gates)" % (
        n_new, "" if n_new == 1 else "s", (", %d refreshed (backup in .claude/.backup/)" % n_upd) if n_upd else ""), "pipeline")
    for rel in replaced:              # named, not counted: a replaced workflow or agent must be visible
        rep.note("would be replaced (original kept)" if rep.dry else "replaced (yours backed up)", root / rel)
    merge_settings_hooks(root, rep)
    return backup if (replaced and not rep.dry) else None


def merge_settings_hooks(root, rep):
    """Register the four hooks in the repo's .claude/settings.json without disturbing anything else in it."""
    path = root / ".claude" / "settings.json"
    data = read_json(path, None) if path.exists() else {}
    if data is None:
        rep.note("NOT updated (cannot parse; add the hooks by hand)", path)
        return
    hooks = data.setdefault("hooks", {})
    wanted = {
        "PreToolUse": ("Edit|Write|MultiEdit", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/guard-migrations.sh"', 10),
        "PostToolUse": ("Edit|Write|MultiEdit", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/post-edit.sh"', 120),
        "Stop": ("", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/stop-gate.sh"', 30),
        "SessionStart": ("", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session-brief.sh"', 15),
    }
    changed = False
    for event, (matcher, cmd, timeout) in wanted.items():
        entries = hooks.setdefault(event, [])
        script = cmd.split("/.claude/hooks/")[1].split('"')[0]
        kept = []
        for e in entries:
            cmds = " ".join((h.get("command") or "") for h in (e.get("hooks") or []))
            if script in cmds and cmd not in cmds:
                changed = True          # an older registration of the same script: replaced below
                continue
            kept.append(e)
        if not any(cmd in " ".join((h.get("command") or "") for h in (e.get("hooks") or [])) for e in kept):
            entry = {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
            if matcher:
                entry["matcher"] = matcher
            kept.append(entry)
            changed = True
        hooks[event] = kept
    if changed:
        if not rep.dry:
            write(path, json.dumps(data, indent=2) + "\n")
        rep.note("hooks registered (PreToolUse migrations guard, PostToolUse typecheck+lint, Stop gate, SessionStart brief)", path)
    else:
        rep.note("unchanged (hooks present)", path)


def deploy_workflow(root, rep, force=False):
    rep.put(root / ".github" / "workflows" / "deploy-supabase.yml",
            fill(DEPLOY_YML, WORK=WORK_BRANCH, WORKU=WORK_BRANCH.upper(), ENVDOC=env_doc(), PROTECTED_LIST=", ".join(PROTECTED), MAIN=PROTECTED[0]), force=force)


def has_supabase_project(root):
    for f in (".env", ".env.%s" % WORK_BRANCH, ".env.production"):
        if re.search(r"^(?:VITE_)?SUPABASE_PROJECT_REF=\w+", read(root / f) or "", re.M):
            return True
    return False


def supabase_init(root):
    if (root / "supabase" / "config.toml").exists():
        return False
    exe = tool("supabase")
    if not exe:
        return False
    subprocess.run([exe, "init"], cwd=str(root), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120, **NOWIN)
    return (root / "supabase" / "config.toml").exists()


def design_files(root, d, rep, update=False):
    """The design contract only. design-reviewer.md ships from BUILTIN_PIPELINE like every other
    agent (v4.3): it used to be carved out here so a repo could edit the body, but the brand facts
    live in design.md, and the carve-out meant kit-wide frontmatter changes - the model it runs on,
    a new tool - never reached a repo that already had the file."""
    rule = root / ".claude" / "rules" / "design.md"
    if not rule.exists():
        if not rep.dry:
            write(rule, fill(DESIGN_RULE_MD, NAME=root.name, **CONFIG["brand"]))
        rep.note("created (config defaults; replace from the brand guidelines)", rule)
    else:
        rep.note("unchanged (yours)", rule)


def spa_rewrites(root, d, rep):
    """A Vite single-page app on Vercel needs every route rewritten to index.html, or deep links 404 on refresh."""
    pkg = read(root / "package.json") or ""
    if not d.get("node") or "vite" not in pkg or "@tanstack/react-start" in pkg or '"next"' in pkg:
        return
    path = root / "vercel.json"
    if path.exists():
        rep.note("unchanged (yours)", path)
        return
    if "react-router" in pkg or "@tanstack/react-router" in pkg:
        if not rep.dry:
            write(path, json.dumps({"rewrites": [{"source": "/(.*)", "destination": "/index.html"}]}, indent=2) + "\n")
        rep.note("created (SPA rewrite so client routes survive refresh)", path)


def lovable_audit(root):
    """Counts for the migration checklist; all by grep, nothing executed."""
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix in (".ts", ".tsx", ".js", ".jsx") and "node_modules" not in p.parts and ".git" not in p.parts]
    ai = routes = browser = 0
    router = "none found"
    client = "none found"
    for f in files:
        t = read(f) or ""
        ai += len(re.findall(r"ai\.gateway\.lovable\.dev|LOVABLE_API_KEY|lovable-ai|/v1/chat/completions", t))
        routes += len(re.findall(r"<Route\b|createRoute\(|createFileRoute\(", t))
        browser += len(re.findall(r"\b(?:window|localStorage|sessionStorage|document)\.", t))
        if "react-router" in t:
            router = "react-router"
        elif "@tanstack/react-router" in t and router == "none found":
            router = "TanStack Router"
        if "createClient(" in t and "supabase" in t.lower():
            client = str(f.relative_to(root)).replace("\\", "/")
    return {"AI_SITES": ai, "ROUTES": routes, "BROWSER": browser, "ROUTER": router, "CLIENT": client}


def lovable_notes(root, d, rep):
    pkg = read(root / "package.json") or ""
    envs = (read(root / ".env") or "") + (read(root / ".env.example") or "")
    readme = read(root / "README.md") or ""
    hits = [m for m in LOVABLE_MARKERS if m in pkg or m in envs or m in readme]
    if not hits:
        return
    path = root / "MIGRATION.md"
    if path.exists() and not ours(path):
        rep.note("unchanged (yours)", path)
        return
    a = lovable_audit(root)
    if not rep.dry:
        write(path, fill(LOVABLE_MD, REPO=root.name, WORK=WORK_BRANCH, MARKERS=", ".join(hits), **{k: str(v) for k, v in a.items()}))
    rep.note("Lovable project detected: migration checklist (%s AI gateway call sites, %s routes)" % (a["AI_SITES"], a["ROUTES"]), path)


def install_worklog(root, rep):
    if not WORKLOG.exists():
        return
    target = root / ".worklog" / "worklog_agent.py"
    if target.exists() and version_of(target) >= version_of(WORKLOG):
        rep.note("unchanged (v%s)" % ".".join(map(str, version_of(target))), "worklog agent")
        return
    if rep.dry:
        rep.note("would install v%s" % ".".join(map(str, version_of(WORKLOG))), "worklog agent")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(WORKLOG), str(target))
    out = subprocess.run([sys.executable, str(target), "install", "--quiet"], cwd=str(root),
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, **NOWIN)
    rep.note("installed v%s%s" % (".".join(map(str, version_of(WORKLOG))), "" if out.returncode == 0 else " (install reported an error; see .worklog/agent.log)"),
             "worklog agent (.worklog/, hooks in .claude/settings.local.json)")


def git_setup(root, rep):
    # hooks path (local config, per clone)
    cur = sh(["git", "-C", str(root), "config", "--get", "core.hooksPath"]).stdout.strip()
    if cur == ".githooks":
        rep.note("unchanged", "git config core.hooksPath = .githooks")
    else:
        if not rep.dry:
            sh(["git", "-C", str(root), "config", "core.hooksPath", ".githooks"])
        rep.note("set", "git config core.hooksPath = .githooks")
    # work branch
    branches = sh(["git", "-C", str(root), "branch", "--list", WORK_BRANCH]).stdout.strip()
    remote = sh(["git", "-C", str(root), "branch", "-r", "--list", "origin/" + WORK_BRANCH]).stdout.strip()
    created = False
    if branches:
        rep.note("unchanged", "branch %s exists" % WORK_BRANCH)
    elif remote:
        if not rep.dry:
            sh(["git", "-C", str(root), "branch", "--track", WORK_BRANCH, "origin/" + WORK_BRANCH])
        rep.note("created (tracking origin)", "branch " + WORK_BRANCH)
        created = True
    else:
        has_commits = sh(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"]).returncode == 0
        if has_commits:
            main = PROTECTED[0]
            base = main if sh(["git", "-C", str(root), "rev-parse", "--verify", main]).returncode == 0 else "HEAD"
            current = sh(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
            if not rep.dry:
                if current == main:
                    sh(["git", "-C", str(root), "checkout", "-q", "-b", WORK_BRANCH, base])
                else:
                    sh(["git", "-C", str(root), "branch", WORK_BRANCH, base])
            rep.note("created from %s%s" % (base, " and checked out" if current == main else " (you are on %s; switch when ready)" % current),
                     "branch " + WORK_BRANCH)
            created = True
        else:
            rep.note("skipped (no commits yet; create it after the first commit)", "branch " + WORK_BRANCH)
    return created


def ensure_installed():
    """Running from a copy that isn't the installed one (first use, or a newer zip): install first."""
    me = Path(__file__).resolve()
    if me == INSTALLED.resolve():
        return False
    if INSTALLED.exists() and version_of(INSTALLED) >= version_of(me) and COMMAND_FILE.exists():
        return False
    class A:                        # a silent bootstrap: never fetch CLIs, log in, or ask
        no_presence = True
        no_cli = True
        no_login = True
        yes = True
        mode = None
        preset = None
        set = None
    say("kit not installed on this machine yet (or this copy is newer): installing first")
    say("(CLIs and logins skipped - run `install` for gh / supabase / vercel.)")
    cmd_install(A())
    say("")
    return True


def exclude_locally(root, rel):
    ex = root / ".git" / "info" / "exclude"
    try:
        ex.parent.mkdir(parents=True, exist_ok=True)
        text = read(ex) or ""
        if rel not in text.splitlines():
            write(ex, text.rstrip("\n") + ("\n" if text else "") + rel + "\n")
    except OSError:
        pass


def cmd_apply(args):
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository (run from the repo, or pass --repo)")
    use_repo_config(root)
    if not args.dry_run:
        ensure_installed()
        me = Path(__file__).resolve()
        try:
            rel = me.parent.relative_to(root)
            exclude_locally(root, str(rel).replace("\\", "/") + "/")  # the kit folder dropped into this repo stays out of git
        except ValueError:
            pass
    if CONFIG.get("mode") == "worklog":
        rep = Report(args.dry_run)
        install_worklog(root, rep)
        for action, what in rep.rows:
            say("  %s  %s" % (action, what))
        say("(worklog-only mode; run install --mode full for standards, agents and infrastructure)")
        return
    d = detect(root)
    rep = Report(args.dry_run)
    main = PROTECTED[0]
    prot = " ".join(PROTECTED)

    # hooks
    rep.put(root / ".githooks" / "commit-msg", fill(COMMIT_MSG), executable=True, force=args.force)
    rep.put(root / ".githooks" / "pre-commit", fill(PRE_COMMIT), executable=True, force=args.force)
    rep.put(root / ".githooks" / "pre-push", fill(PRE_PUSH, PROTECTED=prot, WORK=WORK_BRANCH), executable=True, force=args.force)
    checks_path = root / ".githooks" / "checks"
    if checks_path.exists() and not args.force:
        rep.note("unchanged (yours to edit)", checks_path)
    else:
        rep.put(checks_path, fill(CHECKS, CHECKS="\n".join(d["checks"]) if d["checks"] else "# (nothing detected - add your typecheck / lint / test commands here)"), force=args.force)

    # CI
    node_steps = ""
    if d["node"]:
        if d["pm"] == "pnpm":
            node_steps += PNPM_SETUP
        install = {"npm": "npm ci" if d["lockfile"] else "npm install", "pnpm": "pnpm install --frozen-lockfile",
                   "yarn": "yarn install --frozen-lockfile", "bun": "bun install"}[d["pm"]]
        if d["pm"] == "bun":
            node_steps += "      - uses: oven-sh/setup-bun@v2\n      - run: bun install\n"
        else:
            cache = ("          cache: %s\n" % d["pm"]) if d["lockfile"] and d["pm"] in ("npm", "pnpm", "yarn") else ""
            node_steps += fill(NODE_STEPS, NODE_VERSION=d["node_version"], CACHE=cache, INSTALL=install)
    check_steps = "".join("      - run: %s\n" % c for c in d["checks"]) or "      - run: echo 'no checks configured - see .githooks/checks'\n"
    ci = fill(CI_YML, BRANCHES=", ".join(PROTECTED + [WORK_BRANCH]), PROTECTED_LIST=", ".join(PROTECTED),
              NODE_STEPS=node_steps, FLUTTER_STEPS=FLUTTER_STEPS if d["flutter"] else "",
              PYTHON_STEPS=PYTHON_STEPS if d["python"] else "", CHECK_STEPS=check_steps)
    rep.put(root / ".github" / "workflows" / "ci.yml", ci, force=args.force)
    if not d["supabase"] and has_supabase_project(root) and tool("supabase") and not args.dry_run:
        if supabase_init(root):
            rep.note("created (supabase init - the project has a Supabase backend, so the deploy workflow can exist)", root / "supabase" / "config.toml")
            d = detect(root)
    if d["supabase"]:
        deploy_workflow(root, rep, args.force)
    # pull_request_template.md is a BUILTIN_PIPELINE file; copy_pipeline below is its only writer.

    # docs + config
    rep.put(root / env_doc(), fill(PRELIVE_MD, REPO=root.name, WORK=WORK_BRANCH, WORKU=WORK_BRANCH.upper(), MAIN=main, UAT_HUB=UAT_HUB_URL,
                                   DEPLOY_LINE="Supabase migrations and edge functions deployed per branch, " if d["supabase"] else "",
                                   SUPABASE_TODO=fill(SUPABASE_TODO, WORK=WORK_BRANCH, WORKU=WORK_BRANCH.upper()) if d["supabase"] else ""), force=args.force)
    cfg = read_json(root / ".teknobu.json", {})
    slug = uat_slug(root, getattr(args, "uat_project", None))   # asked for once, then remembered here
    cfg.update({"kit": VERSION, "work_branch": WORK_BRANCH, "protected": PROTECTED, "commit_format": "conventional",
                "applied": datetime.now().strftime("%Y-%m-%d"), "uat_project": slug,
                "stack": {k: d[k] for k in ("node", "pm", "supabase", "flutter", "python", "vercel")}})
    cfg.setdefault("generated_types", "src/types/database.ts")
    text = json.dumps(cfg, indent=2) + "\n"
    existed = (root / ".teknobu.json").exists()
    if read(root / ".teknobu.json") == text:
        rep.note("unchanged", root / ".teknobu.json")
    else:
        if not rep.dry:
            write(root / ".teknobu.json", text)
        rep.note("updated" if existed else "created", root / ".teknobu.json")
    copy_pipeline(root, rep, d, update=args.update_pipeline)   # starter first, built-ins fill the gaps
    claude_md(root, rep, slug, update=args.update_pipeline)
    mcp_json(root, rep, slug)                                  # the tool the CLAUDE.md UAT section names
    merge_gitignore(root, rep)
    merge_gitattributes(root, rep)
    env_example(root, rep)
    env_prelive(root, rep)
    design_files(root, d, rep, update=args.update_pipeline)
    fill_placeholders(root, d, rep)
    spa_rewrites(root, d, rep)
    lovable_notes(root, d, rep)
    install_worklog(root, rep)
    created = git_setup(root, rep)

    say("Sonelo standards %s%s: %s" % ("(dry run) " if args.dry_run else "", "applied to", root))
    say("stack: %s" % ", ".join(k for k in ("node", "supabase", "flutter", "python", "vercel") if d[k]) or "stack: (nothing detected)")
    say("checks: %s" % ("; ".join(d["checks"]) if d["checks"] else "none detected"))
    say("")
    width = max(len(a) for a, _ in rep.rows)
    for action, what in rep.rows:
        w = str(what)
        try:
            w = str(Path(what).relative_to(root))
        except (ValueError, TypeError):
            pass
        say("  %-*s  %s" % (width, action, w))
    say("")
    if created:
        say("PRELIVE_BRANCH_CREATED")
    say("Next: read %s for the manual wiring, commit these files on %s, then `git push -u origin %s`." % (env_doc(), WORK_BRANCH, WORK_BRANCH))


def cmd_refresh(args):
    """Take the current kit's pipeline and nothing else.

    `apply --update-pipeline` refreshes the pipeline too, but it is a flag on a command that also
    rewrites CI, the environment doc, .gitignore, .env.example and the design contract, and ends by
    creating and checking out the work branch. On a repo that only wants this release's agents,
    commands and hooks, that is a lot of blast radius for a small want - so this is the narrow verb.

    It does exactly four things: the built-in pipeline files (backups kept in .claude/.backup/),
    the hook registrations in .claude/settings.json, the managed sections of CLAUDE.md, and the
    uat-hub entry in .mcp.json - the MCP server the managed UAT section tells sessions to use, which
    would otherwise be named by a refreshed CLAUDE.md in a repo that does not have it. It also
    records the kit version in .teknobu.json - without that the session-start nudge would keep
    reporting the repo as out of date and pointing back at the heavy command.

    "The pipeline" includes the two kit-owned files under .github/: ci-gates.yml and
    pull_request_template.md. They are the gates half of the pipeline, so refreshing them is the
    point - but a workflow is the highest-privilege thing this command rewrites, so every replaced
    file is named in the output rather than counted, and the repo's own ci.yml is never touched."""
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository (run from the repo, or pass --repo)")
    use_repo_config(root)                      # WORK_BRANCH/PROTECTED from this repo, not this machine
    dry = getattr(args, "dry_run", False)
    if not dry:
        ensure_installed()
        me = Path(__file__).resolve()
        try:
            rel = me.parent.relative_to(root)
            exclude_locally(root, str(rel).replace("\\", "/") + "/")
        except ValueError:
            pass
    if CONFIG.get("mode") == "worklog":
        say("worklog-only mode: there is no pipeline in this repo. Run `install --mode full` first.")
        return
    rep = Report(dry)
    backups = copy_pipeline(root, rep, update=True)   # also registers the hooks in .claude/settings.json
    # claude_md writes in place. Only BUILTIN_PIPELINE files get backed up by copy_pipeline, so a
    # repo whose CLAUDE.md carries hand-written policy outside the markers would lose it with no
    # copy anywhere - and refresh, unlike --update-pipeline, is now the recommended path.
    before = read(root / "CLAUDE.md")
    claude_md(root, rep, uat_slug(root), update=True)   # read-only on .teknobu.json: refresh owns no repo keys
    if before is not None and not dry and read(root / "CLAUDE.md") != before:
        backups = backups or (root / ".claude" / ".backup" / datetime.now().strftime("%Y%m%d-%H%M%S"))
        backups.mkdir(parents=True, exist_ok=True)
        if not (backups.parent / ".gitignore").exists():
            write(backups.parent / ".gitignore", "*\n")
        write(backups / "CLAUDE.md", before)
        rep.note("replaced (yours backed up)", root / "CLAUDE.md")
    backups = mcp_json(root, rep, uat_slug(root), into=backups or None) or backups
    cfg_path = root / ".teknobu.json"
    cfg = read_json(cfg_path, {})
    if isinstance(cfg, dict) and cfg and (cfg.get("kit") != VERSION):
        cfg["kit"] = VERSION                    # only these two keys: the rest is the repo's own
        cfg["applied"] = datetime.now().strftime("%Y-%m-%d")
        if not dry:
            write(cfg_path, json.dumps(cfg, indent=2) + "\n")
        rep.note("kit version recorded (v%s)" % VERSION, cfg_path)

    say("Pipeline %srefreshed from kit v%s: %s" % ("(dry run) " if dry else "", VERSION, root))
    say("")
    if rep.rows:
        width = max(len(a) for a, _ in rep.rows)
        for action, what in rep.rows:
            w = str(what)
            try:
                w = str(Path(what).relative_to(root))
            except (ValueError, TypeError):
                pass
            say("  %-*s  %s" % (width, action, w))
        say("")
    say("Refreshed: .claude/agents, .claude/commands, .claude/hooks, the CI *gates* "
        "(.github/workflows/ci-gates.yml, pull_request_template.md), the managed CLAUDE.md sections "
        "and the %s entry in .mcp.json (any other MCP server in it is left alone)." % UAT_MCP_NAME)
    say("Untouched: your CI workflow (ci.yml), the deploy workflow, %s, .githooks/, .env*, "
        ".claude/rules/design.md, branches, the worklog." % env_doc())
    if backups:
        say("Replaced files are backed up in %s (self-ignoring)." % backups)
    if dry:
        say("Dry run: nothing was written. Files that differ would be replaced, the original kept "
            "under .claude/.backup/ - CLAUDE.md included, which is rewritten in place.")


# ----------------------------------------------------------------------------- check / nudge / protect

def status(root):
    items = []
    hooks_ok = all((root / ".githooks" / h).exists() for h in ("commit-msg", "pre-commit", "pre-push"))
    items.append(("git hooks (.githooks/)", hooks_ok))
    path_ok = sh(["git", "-C", str(root), "config", "--get", "core.hooksPath"]).stdout.strip() == ".githooks"
    items.append(("hooks active in this clone (core.hooksPath)", path_ok))
    items.append(("CI workflow", (root / ".github" / "workflows" / "ci.yml").exists()))
    d = detect(root)
    if d["supabase"]:
        items.append(("Supabase deploy workflow", (root / ".github" / "workflows" / "deploy-supabase.yml").exists()))
    items.append(("branch %s" % WORK_BRANCH, bool(sh(["git", "-C", str(root), "branch", "--list", WORK_BRANCH]).stdout.strip())))
    items.append(("CLAUDE.md standards section", MARK in (read(root / "CLAUDE.md") or "")))
    items.append((".mcp.json (%s server)" % UAT_MCP_NAME, UAT_MCP_NAME in (read(root / ".mcp.json") or "")))
    if (root / ".env").exists() or (root / ".env.example").exists():
        items.append((".env.example", (root / ".env.example").exists()))
    items.append((".claude/rules/design.md (design contract)", (root / ".claude" / "rules" / "design.md").exists()))
    items.append((env_doc(), (root / env_doc()).exists()))
    cfg = read_json(root / ".teknobu.json", {})
    items.append((".teknobu.json (kit v%s)" % cfg.get("kit", "?"), bool(cfg)))
    items.append(("pipeline (agents, /post-change, /pr, hooks)", (root / ".claude" / "agents" / "code-reviewer.md").exists() and (root / ".claude" / "hooks" / "stop-gate.sh").exists() and (root / ".claude" / "hooks" / "pipeline-state.sh").exists()))
    if WORKLOG.exists():
        items.append(("worklog agent", (root / ".worklog" / "worklog_agent.py").exists()))
    return items, cfg


def cmd_check(args):
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository")
    use_repo_config(root)
    items, cfg = status(root)
    say("Teknobu standards in %s" % root)
    for name, ok in items:
        say("  %s  %s" % ("ok     " if ok else "missing", name))
    if cfg.get("kit") and tuple(map(int, str(cfg["kit"]).split("."))) < tuple(map(int, VERSION.split("."))):
        say("  kit v%s applied, v%s available: run apply to refresh the generated files" % (cfg["kit"], VERSION))
    missing = [n for n, ok in items if not ok]
    sys.exit(0 if not missing else 1)


def update_available(now=None, fetch=None):
    """The newest released kit tag when it is newer than this install, else None.
    The network is asked at most once a day (UPDATE_STAMP mtime is the throttle); the last
    seen tag is cached in the stamp so every session start can still speak without a
    request. Silent on every failure - the nudge must never delay or break a session."""
    try:
        now = time.time() if now is None else now
        if UPDATE_STAMP.exists() and now - UPDATE_STAMP.stat().st_mtime < 86400:
            tag = UPDATE_STAMP.read_text(encoding="utf-8").strip()
        else:
            if fetch is None:
                fetch = lambda: latest_tag(CONFIG.get("source") or DEFAULTS["source"], to=3)
            try:
                tag = (fetch() or "").strip()
            except Exception:
                tag = ""                          # failed check still stamps: retry tomorrow, not every session
            write(UPDATE_STAMP, tag + "\n")
        ver = tag.lstrip("v")
        if ver and re.fullmatch(r"[0-9]+(\.[0-9]+)*", ver) and tuple(map(int, ver.split("."))) > tuple(map(int, VERSION.split("."))):
            return tag
    except Exception:
        pass
    return None


def cmd_nudge(args):
    """User-level SessionStart hook. Prints one line only when something is worth saying; stdout becomes session context."""
    try:
        root = repo_root()
        if not root or (root / ".nokit").exists() or CONFIG.get("mode") == "worklog":
            return
        use_repo_config(root)
        has_hooks = (root / ".githooks" / "pre-push").exists()
        cfg = read_json(root / ".teknobu.json", {})
        if has_hooks:
            cur = sh(["git", "-C", str(root), "config", "--get", "core.hooksPath"]).stdout.strip()
            if cur != ".githooks":
                sh(["git", "-C", str(root), "config", "core.hooksPath", ".githooks"])  # fresh clone: activate the committed hooks
            tag = update_available()
            if tag:
                say("Sonelo kit %s is released; this machine has v%s. Ask the user: update now? If yes, run `python \"%s\" update`, then offer `refresh` in this repo." % (tag, VERSION, INSTALLED.as_posix()))
                return
            if cfg.get("kit") and tuple(map(int, str(cfg["kit"]).split("."))) < tuple(map(int, VERSION.split("."))):
                say("Teknobu standards kit v%s is installed but this repo was set up with v%s. Offer to run /repo-setup to refresh the generated files." % (VERSION, cfg["kit"]))
            return
        say("This repo does not have the Sonelo standards (git hooks, CI, %s branch). Offer the user /repo-setup; do not apply it without asking. Add a .nokit file to the repo root to silence this." % WORK_BRANCH)
    except Exception:
        return


def cmd_protect(args):
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository")
    use_repo_config(root)
    slug = github_slug(root)
    if not slug:
        sys.exit("no GitHub remote named origin")
    if not tool("gh"):
        sys.exit("the gh CLI is not installed (run repo_setup.py install, it downloads it); or set branch protection in Settings -> Branches")
    if sh([tool("gh"), "auth", "status"]).returncode != 0:
        sys.exit("gh is not logged in: run `gh auth login`")
    contexts = ["checks"]
    gates = read(root / ".github" / "workflows" / "ci-gates.yml") or ""
    if gates:
        m = re.search(r"^jobs:\s*\n\s+([A-Za-z0-9_-]+):\s*\n(?:\s+name:\s*(.+))?", gates, re.M)
        contexts.append((m.group(2) or m.group(1)).strip().strip("\"'") if m else "gates")
    body = json.dumps({
        "required_status_checks": {"strict": True, "contexts": contexts},
        "enforce_admins": False,
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "restrictions": None,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_linear_history": False,
    })
    for branch in PROTECTED:
        out = subprocess.run([tool("gh"), "api", "--method", "PUT", "repos/%s/%s/branches/%s/protection" % (slug[0], slug[1], branch),
                              "--input", "-"], input=body, capture_output=True, text=True, **NOWIN)
        if out.returncode == 0:
            say("protected %s/%s:%s - pull request required, %s must pass, no force-push, no deletion" % (slug[0], slug[1], branch, " and ".join("'%s'" % c for c in contexts)))
        else:
            err = out.stderr.strip() or out.stdout.strip()
            hint = " (branch protection on private repos needs a paid GitHub plan; use a ruleset or rely on the local hook)" if "403" in err or "Upgrade" in err else ""
            say("could not protect %s: %s%s" % (branch, err[:300], hint))


# ----------------------------------------------------------------------------- github (gh CLI)

def gh_ready():
    if not tool("gh"):
        return "the gh CLI is not installed (run repo_setup.py install, it downloads it)"
    if sh([tool("gh"), "auth", "status"]).returncode != 0:
        return "gh is not logged in: run `gh auth login`"
    return None


def gh_secret(root, name, value):
    out = subprocess.run([tool("gh"), "secret", "set", name, "--body", value], cwd=str(root), capture_output=True, text=True, **NOWIN)
    return out.returncode == 0, (out.stderr or out.stdout).strip()


def cmd_github(args):
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository")
    use_repo_config(root)
    err = gh_ready()
    if err:
        sys.exit(err)
    if sh(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"]).returncode != 0:
        sys.exit("make the first commit before creating the GitHub repository")
    slug = github_slug(root)
    if slug:
        say("remote     origin already points at github.com/%s/%s" % slug)
    else:
        name = args.name or root.name
        full = "%s/%s" % (args.org, name) if args.org else name
        vis = "--public" if args.public else "--private"
        out = subprocess.run([tool("gh"), "repo", "create", full, vis, "--source=.", "--remote=origin"], cwd=str(root),
                             capture_output=True, text=True, **NOWIN)
        if out.returncode != 0:
            sys.exit("gh repo create failed: %s" % (out.stderr or out.stdout).strip()[:400])
        say("created    github.com/%s (%s)" % (full, "public" if args.public else "private"))
        slug = github_slug(root)
    # push main, then the work branch, with the hooks' consent for the initial push
    env = dict(os.environ, TEKNOBU_ALLOW_MAIN="1")
    for branch in [PROTECTED[0], WORK_BRANCH]:
        if not sh(["git", "-C", str(root), "branch", "--list", branch]).stdout.strip():
            say("push       %s: no local branch, skipped" % branch)
            continue
        out = subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(root), capture_output=True, text=True, env=env, **NOWIN)
        say("push       %s %s" % (branch, "ok" if out.returncode == 0 else "FAILED: " + (out.stderr or out.stdout).strip()[:300]))
    class A:  # reuse protect
        pass
    a = A(); a.repo = str(root)
    cmd_protect(a)
    say("")
    say("https://github.com/%s/%s" % slug)


# ----------------------------------------------------------------------------- supabase (management API)

SUPABASE_API = "https://api.supabase.com"


def credential_manager_token(prefix="Supabase CLI"):
    """`supabase login` on Windows stores the token in Credential Manager as a generic credential 'Supabase CLI:<key>'."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        adv = ctypes.windll.advapi32

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
        count = wintypes.DWORD()
        pcreds = ctypes.POINTER(ctypes.POINTER(CREDENTIAL))()
        adv.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(CREDENTIAL)))]
        adv.CredEnumerateW.restype = wintypes.BOOL
        if not adv.CredEnumerateW(prefix + "*", 0, ctypes.byref(count), ctypes.byref(pcreds)):
            return None
        try:
            best = None
            for i in range(count.value):
                c = pcreds[i].contents
                blob = bytes(bytearray(c.CredentialBlob[j] for j in range(c.CredentialBlobSize)))
                text = blob.decode("utf-8", "ignore").strip("\x00 \r\n")
                if "\x00" in text or not text.isprintable():
                    text = blob.decode("utf-16-le", "ignore").strip("\x00 \r\n")
                if text.startswith("sbp_"):
                    return text
                if "access-token" in (c.TargetName or "") and text:
                    best = text
            return best
        finally:
            adv.CredFree(pcreds)
    except Exception:
        return None


def supabase_token(explicit=None, want_source=False):
    order = []
    if explicit:
        order.append((explicit, "--token"))
    if os.environ.get("SUPABASE_ACCESS_TOKEN"):
        order.append((os.environ["SUPABASE_ACCESS_TOKEN"], "SUPABASE_ACCESS_TOKEN env var (this overrides `supabase login` for the CLI too)"))
    cm = credential_manager_token()
    if cm:
        order.append((cm, "supabase login (Windows Credential Manager)"))
    f = Path("~/.supabase/access-token").expanduser()
    tok = (read(f) or "").strip().lstrip("\ufeff")
    if tok:
        order.append((tok, "supabase login (%s)" % f))
    if not order:
        return (None, None) if want_source else None
    return order[0] if want_source else order[0][0]


def sapi(token, method, path, body=None, base=None):
    url = (base or SUPABASE_API) + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
            msg = err.get("message") or err.get("error") or str(err)
        except Exception:
            msg = "HTTP %s" % e.code
        raise VercelError("%s %s -> %s" % (method, path, msg))
    except (urllib.error.URLError, OSError) as e:
        raise VercelError("%s %s -> cannot reach %s (%s)" % (method, path, base or SUPABASE_API, getattr(e, "reason", e)))


def supabase_keys(token, ref, base):
    """(publishable_or_anon, secret_or_service_role) - prefers the new key types, creates a publishable key if none exists."""
    keys = sapi(token, "GET", "/v1/projects/%s/api-keys?reveal=true" % ref, base=base) or []
    by_type = {}
    for k in keys:
        t = k.get("type") or ("legacy" if k.get("name") in ("anon", "service_role") else "")
        by_type.setdefault((t, k.get("name")), k.get("api_key"))
    pub = next((v for (t, n), v in by_type.items() if t == "publishable"), None)
    sec = next((v for (t, n), v in by_type.items() if t == "secret"), None)
    if not pub:
        try:
            created = sapi(token, "POST", "/v1/projects/%s/api-keys?reveal=true" % ref, {"type": "publishable", "name": "default"}, base=base)
            pub = created.get("api_key")
        except VercelError:
            pass
    anon = next((v for (t, n), v in by_type.items() if n == "anon"), None)
    service = next((v for (t, n), v in by_type.items() if n == "service_role"), None)
    return pub or anon, sec or service


def write_env_lines(path, pairs, header=None):
    """Set KEY=VALUE lines in an env file, replacing existing keys, keeping everything else."""
    lines = (read(path) or "").splitlines()
    done = set()
    out = []
    for line in lines:
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in pairs:
            out.append("%s=%s" % (m.group(1), pairs[m.group(1)]))
            done.add(m.group(1))
        else:
            out.append(line)
    rest = [k for k in pairs if k not in done]
    if rest:
        if not out and header:
            out.append(header)
        out += ["%s=%s" % (k, pairs[k]) for k in rest]
    write(path, "\n".join(out).rstrip("\n") + "\n")


def cmd_supabase(args):
    base = args.api or SUPABASE_API
    token = supabase_token(args.token)
    if not token:
        sys.exit("no Supabase access token: run `supabase login` (repo_setup.py install puts the CLI in place), or create a legacy token at supabase.com/dashboard/account/tokens and set SUPABASE_ACCESS_TOKEN")
    if args.list_orgs:
        try:
            for o in sapi(token, "GET", "/v1/organizations", base=base) or []:
                say("%-24s %s" % (o.get("id"), o.get("name")))
        except VercelError as e:
            sys.exit(str(e))
        return
    if not args.create:
        sys.exit("nothing to do: --create or --list-orgs")
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository")
    use_repo_config(root)
    try:
        orgs = sapi(token, "GET", "/v1/organizations", base=base) or []
    except VercelError as e:
        sys.exit(str(e))
    org = args.org
    if not org:
        if len(orgs) == 1:
            org = orgs[0]["id"]
        else:
            sys.exit("more than one Supabase organisation; pass --org <id>:\n" + "\n".join("  %-24s %s" % (o.get("id"), o.get("name")) for o in orgs))
    name = args.name or root.name
    work_env = ".env.%s" % WORK_BRANCH
    existing = {p["name"]: p for p in (sapi(token, "GET", "/v1/projects", base=base) or [])}
    created, passwords = {}, {}

    def create_project(env_name, pname):
        if pname in existing:
            created[env_name] = existing[pname]
            say("%-10s %s exists (%s), reusing" % (env_name, pname, existing[pname]["id"]))
            return
        pw = _secrets.token_urlsafe(24)
        try:
            pj = sapi(token, "POST", "/v1/projects", {"name": pname, "organization_id": org, "region": args.region, "db_pass": pw}, base=base)
        except VercelError as e:
            sys.exit("creating %s failed: %s" % (pname, e))
        created[env_name] = pj
        passwords[env_name] = pw
        say("%-10s %s created (%s, %s)" % (env_name, pname, pj.get("id"), args.region))

    def wait_healthy(env_name, ref, status=None):
        deadline = time.time() + 420
        while status != "ACTIVE_HEALTHY" and time.time() < deadline:
            time.sleep(args.poll)
            try:
                status = sapi(token, "GET", "/v1/projects/%s" % ref, base=base).get("status")
            except VercelError:
                status = "?"
        say("%-10s %s: %s" % (env_name, ref, status))

    if args.database == "branching":
        # one project; the work branch is a persistent Supabase branch (its own ref, keys and password) created from production
        create_project("production", name)
        wait_healthy("production", created["production"]["id"], created["production"].get("status"))
        prod_ref = created["production"]["id"]
        try:
            branches = sapi(token, "GET", "/v1/projects/%s/branches" % prod_ref, base=base) or []
        except VercelError as e:
            branches = []
            say("branching  cannot list branches: %s" % e)
        br = next((b for b in branches if b.get("name") == WORK_BRANCH or b.get("git_branch") == WORK_BRANCH), None)
        if br:
            say("%-10s branch exists (%s), reusing" % (WORK_BRANCH, br.get("project_ref") or br.get("ref") or br.get("id")))
        else:
            try:
                br = sapi(token, "POST", "/v1/projects/%s/branches" % prod_ref,
                          {"branch_name": WORK_BRANCH, "git_branch": WORK_BRANCH, "persistent": True, "region": args.region}, base=base)
                say("%-10s persistent branch created from production" % WORK_BRANCH)
            except VercelError as e:
                say("%-10s branch NOT created: %s" % (WORK_BRANCH, e))
                say("           Branching needs the Pro plan and must be enabled once on the project (dashboard -> Branches -> enable). Then re-run this command.")
                say("           Or switch the strategy: repo_setup.py supabase --create --database separate")
                br = None
        if br:
            bid = br.get("id")
            bref = br.get("project_ref") or br.get("ref")
            try:
                if bid:
                    detail = sapi(token, "GET", "/v1/branches/%s" % bid, base=base) or {}
                    bref = detail.get("ref") or bref
                    if detail.get("db_pass"):
                        passwords["work"] = detail["db_pass"]
            except VercelError:
                pass
            if bref:
                created["work"] = {"id": bref, "name": "%s (branch)" % WORK_BRANCH}
                wait_healthy(WORK_BRANCH, bref)
    else:
        create_project("work", "%s-%s" % (name, WORK_BRANCH))
        if not args.only:
            create_project("production", name)
        for env_name, pj in created.items():
            wait_healthy(WORK_BRANCH if env_name == "work" else env_name, pj["id"], pj.get("status"))
    # keys -> env files
    vite = (root / "package.json").exists() and "vite" in (read(root / "package.json") or "")
    def env_pairs(ref, pub, pw):
        pairs = {"SUPABASE_URL": "https://%s.supabase.co" % ref, "SUPABASE_ANON_KEY": pub or "", "SUPABASE_PROJECT_REF": ref}
        if vite:
            pairs["VITE_SUPABASE_URL"] = pairs["SUPABASE_URL"]; pairs["VITE_SUPABASE_ANON_KEY"] = pub or ""
        if pw:
            pairs["SUPABASE_DB_PASSWORD"] = pw
        return pairs
    for env_name, pj in created.items():
        ref = pj["id"]
        try:
            pub, sec = supabase_keys(token, ref, base)
        except VercelError as e:
            say("%-10s keys not readable yet (%s); re-run later to fill the env files" % (env_name, e))
            pub = sec = None
        pairs = env_pairs(ref, pub, passwords.get(env_name))
        if env_name == "work":
            write_env_lines(root / work_env, pairs, "# %s values (pushed to Vercel Preview/%s by: repo_setup.py vercel)" % (WORK_BRANCH, WORK_BRANCH))
            write_env_lines(root / ".env", pairs, "# Local development points at the %s database" % WORK_BRANCH)
            say("%-10s -> .env and %s (%s)" % (WORK_BRANCH, work_env, ", ".join(pairs)))
        else:
            write_env_lines(root / ".env.production", pairs, "# Production values (pushed to Vercel Production by: repo_setup.py vercel)")
            say("%-10s -> .env.production" % env_name)
        if sec:
            say("%-10s secret key not written anywhere; read it from the dashboard when an edge function needs it" % "")
    rep = Report(False)
    env_example(root, rep)
    env_prelive(root, rep)
    say("env        .env.example %s" % rep.rows[0][0])
    if supabase_init(root):
        say("supabase   `supabase init` run: supabase/config.toml created")
    if (root / "supabase").is_dir():
        rep2 = Report(False)
        deploy_workflow(root, rep2)
        say("workflow   .github/workflows/deploy-supabase.yml %s" % rep2.rows[0][0])
    else:
        say("workflow   deploy-supabase.yml not generated: no supabase/ folder and no Supabase CLI to run `supabase init`")
    # GitHub secrets for the deploy workflow
    if github_slug(root) and not gh_ready():
        pairs = {"SUPABASE_ACCESS_TOKEN": token}
        if "work" in created:
            pairs["SUPABASE_%s_PROJECT_REF" % WORK_BRANCH.upper()] = created["work"]["id"]
            if passwords.get("work"):
                pairs["SUPABASE_%s_DB_PASSWORD" % WORK_BRANCH.upper()] = passwords["work"]
        if "production" in created:
            pairs["SUPABASE_PROJECT_REF"] = created["production"]["id"]
            if passwords.get("production"):
                pairs["SUPABASE_DB_PASSWORD"] = passwords["production"]
        ok = [n for n, v in pairs.items() if gh_secret(root, n, v)[0]]
        say("github     secrets set: %s" % ", ".join(ok))
        missing = [n for n in ("SUPABASE_%s_DB_PASSWORD" % WORK_BRANCH.upper(), "SUPABASE_DB_PASSWORD") if n not in pairs and n.replace("_DB_PASSWORD", "_PROJECT_REF") in pairs]
        if missing:
            say("           set by hand (existing projects, password unknown to the kit): %s" % ", ".join(missing))
    else:
        say("github     not set (no GitHub remote or gh not ready); see the secret names in .github/workflows/deploy-supabase.yml")
    say("")
    say("Database passwords are in the env files (git-ignored). Store them in the password manager; the kit does not keep them.")


# ----------------------------------------------------------------------------- vercel

VERCEL_API = "https://api.vercel.com"


def vercel_auth_paths():
    cands = []
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]) / "com.vercel.cli" / "auth.json")
    for var in ("LOCALAPPDATA", "APPDATA"):
        if os.environ.get(var):
            base = Path(os.environ[var])
            cands += [base / "com.vercel.cli" / "Data" / "auth.json", base / "com.vercel.cli" / "auth.json",
                      base / "xdg.data" / "com.vercel.cli" / "auth.json", base / "xdg.config" / "com.vercel.cli" / "auth.json"]
    cands += [Path("~/.local/share/com.vercel.cli/auth.json").expanduser(), Path("~/.config/com.vercel.cli/auth.json").expanduser(),
              Path("~/Library/Application Support/com.vercel.cli/auth.json").expanduser()]
    return cands


def vercel_token(explicit=None, want_source=False):
    if explicit:
        return (explicit, "--token") if want_source else explicit
    if os.environ.get("VERCEL_TOKEN"):
        return (os.environ["VERCEL_TOKEN"], "VERCEL_TOKEN") if want_source else os.environ["VERCEL_TOKEN"]
    for c in vercel_auth_paths():
        tok = (read_json(c, {}) or {}).get("token")
        if tok:
            return (tok, "Vercel CLI login (%s)" % c) if want_source else tok
    return (None, None) if want_source else None


def vercel_slug(name):
    """Vercel project names: lowercase letters, digits, '.', '_', '-'; max 100 chars."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-")
    return slug[:100] or "project"


class VercelError(Exception):
    pass


def vapi(token, method, path, team=None, body=None, query=None, base=None):
    q = dict(query or {})
    if team:
        q["teamId"] = team
    url = (base or VERCEL_API) + path + (("?" + urllib.parse.urlencode(q)) if q else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error") or {}
            msg = "%s: %s" % (err.get("code", e.code), err.get("message", ""))
        except Exception:
            msg = "HTTP %s" % e.code
        raise VercelError("%s %s -> %s" % (method, path, msg))
    except (urllib.error.URLError, OSError) as e:
        raise VercelError("%s %s -> cannot reach %s (%s)" % (method, path, base or VERCEL_API, getattr(e, "reason", e)))


def parse_env_file(path):
    out = []
    for line in (read(path) or "").splitlines():
        m = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$', line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out.append((k, v))
    return out


def vercel_create(token, root, name, base, team):
    slug = github_slug(root)
    if not slug:
        raise VercelError("no GitHub remote to create the Vercel project from (run `repo_setup.py github` first)")
    body = {"name": vercel_slug(name), "gitRepository": {"type": "github", "repo": "%s/%s" % slug}}
    pkg = read(root / "package.json") or ""
    if "next" in pkg:
        body["framework"] = "nextjs"
    elif "vite" in pkg:
        body["framework"] = "vite"
    pj = vapi(token, "POST", "/v11/projects", team, body, base=base)
    (root / ".vercel").mkdir(exist_ok=True)
    write(root / ".vercel" / "project.json", json.dumps({"projectId": pj["id"], "orgId": team or pj.get("accountId", "")}, indent=2) + "\n")
    return pj


def vercel_project(token, root, name, base, create=False, team_hint=None):
    """Returns (project_id, team_id, project_json). Uses .vercel/project.json, else --project / repo name via the API."""
    link = read_json(root / ".vercel" / "project.json", {})
    if link.get("projectId"):
        team = link.get("orgId") if str(link.get("orgId", "")).startswith("team_") else None
        return link["projectId"], team, vapi(token, "GET", "/v9/projects/%s" % link["projectId"], team, base=base)
    wanted = vercel_slug(name or root.name)
    scopes = [None]
    try:
        scopes += [t["id"] for t in (vapi(token, "GET", "/v2/teams", base=base).get("teams") or [])]
    except VercelError:
        pass
    for team in scopes:
        try:
            pj = vapi(token, "GET", "/v9/projects/%s" % urllib.parse.quote(wanted), team, base=base)
            if pj.get("id"):
                (root / ".vercel").mkdir(exist_ok=True)
                write(root / ".vercel" / "project.json", json.dumps({"projectId": pj["id"], "orgId": team or pj.get("accountId", "")}, indent=2) + "\n")
                return pj["id"], team, pj
        except VercelError:
            continue
    if create:
        team = team_hint or (scopes[1] if len(scopes) == 2 else None)
        if team is None and len(scopes) > 2:
            raise VercelError("several Vercel teams; pass --team <team_id> so the project is created in the right one")
        pj = vercel_create(token, root, wanted, base, team)
        return pj["id"], team, dict(pj, _created=True)
    raise VercelError("no Vercel project called '%s' in your account or teams; pass --project <name>, or --create to make it" % wanted)


def cmd_vercel(args):
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository")
    use_repo_config(root)
    base = args.api or VERCEL_API
    token = vercel_token(args.token)
    if not token:
        sys.exit("no Vercel token: log in with the Vercel CLI (`vercel login`) or create one at vercel.com/account/tokens and set VERCEL_TOKEN")
    try:
        pid, team, pj = vercel_project(token, root, args.project, base, create=args.create, team_hint=args.team)
    except VercelError as e:
        sys.exit(str(e))
    say("project    %s (%s)%s%s" % (pj.get("name"), pid, ("  team " + team) if team else "", "  created from the GitHub repo" if pj.get("_created") else ""))
    prod = (pj.get("link") or {}).get("productionBranch") or "(repo default)"
    say("production branch on Vercel: %s%s" % (prod, "" if prod in ("(repo default)", PROTECTED[0]) else "  <- set it to %s in Settings -> Git" % PROTECTED[0]))

    # domain -> work branch
    if args.domain:
        domain = args.domain.lower().strip()
        try:
            existing = {d["name"]: d for d in (vapi(token, "GET", "/v9/projects/%s/domains" % pid, team, base=base).get("domains") or [])}
            if domain in existing:
                if existing[domain].get("gitBranch") != WORK_BRANCH:
                    vapi(token, "PATCH", "/v9/projects/%s/domains/%s" % (pid, domain), team, {"gitBranch": WORK_BRANCH}, base=base)
                    say("domain     %s: re-pointed at branch %s" % (domain, WORK_BRANCH))
                else:
                    say("domain     %s already on branch %s" % (domain, WORK_BRANCH))
                d = existing[domain]
            else:
                d = vapi(token, "POST", "/v10/projects/%s/domains" % pid, team, {"name": domain, "gitBranch": WORK_BRANCH}, base=base)
                say("domain     %s added, branch %s" % (domain, WORK_BRANCH))
            if d.get("verified") is False and d.get("verification"):
                say("           verification needed (the domain is claimed by another Vercel account):")
                for v in d["verification"]:
                    say("             %s record  %s = %s" % (v.get("type"), v.get("domain"), v.get("value")))
            cfg = vapi(token, "GET", "/v6/domains/%s/config" % domain, team, base=base)
            if cfg.get("misconfigured"):
                sub = domain.split(".")[0] if domain.count(".") >= 2 else "@"
                say("DNS        not pointing at Vercel yet. At your DNS provider add:")
                if sub == "@":
                    say("             A      @        76.76.21.21")
                else:
                    say("             CNAME  %-8s cname.vercel-dns.com" % sub)
                say("           then re-run this command; Vercel issues the certificate once it resolves.")
            else:
                say("DNS        ok - https://%s will serve the %s branch" % (domain, WORK_BRANCH))
            tcfg = read_json(root / ".teknobu.json", {})
            if tcfg.get("work_url") != "https://" + domain or (args.production_domain and tcfg.get("production_url") != "https://" + args.production_domain):
                tcfg["work_url"] = "https://" + domain
                if args.production_domain:
                    tcfg["production_url"] = "https://" + args.production_domain
                write(root / ".teknobu.json", json.dumps(tcfg, indent=2) + "\n")
        except VercelError as e:
            say("domain     FAILED: %s" % e)

    # env vars from .env.<work> -> Preview, scoped to the work branch
    env_file = Path(args.env_file) if args.env_file else root / (".env.%s" % WORK_BRANCH)
    pairs = [(k, v) for k, v in parse_env_file(env_file) if v != ""] if env_file.exists() else []
    skipped = [k for k, v in parse_env_file(env_file) if v == ""] if env_file.exists() else []
    if not env_file.exists():
        say("env        no %s - create it from .env.example with the %s values and re-run to push them" % (env_file.name, WORK_BRANCH))
    elif not pairs:
        say("env        %s has no values filled in yet (%d keys) - nothing pushed" % (env_file.name, len(skipped)))
    else:
        ok = 0
        for k, v in pairs:
            try:
                vapi(token, "POST", "/v10/projects/%s/env" % pid, team,
                     {"key": k, "value": v, "type": "encrypted", "target": ["preview"], "gitBranch": WORK_BRANCH},
                     query={"upsert": "true"}, base=base)
                ok += 1
            except VercelError as e:
                say("env        %s FAILED: %s" % (k, e))
        say("env        %d variable%s set for Preview deployments of %s%s" % (
            ok, "" if ok == 1 else "s", WORK_BRANCH, ("; %d left empty and skipped" % len(skipped)) if skipped else ""))
    if args.production_domain:
        pd = args.production_domain.lower().strip()
        try:
            have = {d["name"] for d in (vapi(token, "GET", "/v9/projects/%s/domains" % pid, team, base=base).get("domains") or [])}
            if pd not in have:
                vapi(token, "POST", "/v10/projects/%s/domains" % pid, team, {"name": pd}, base=base)
                say("domain     %s added for production" % pd)
            else:
                say("domain     %s already on the project" % pd)
            cfg = vapi(token, "GET", "/v6/domains/%s/config" % pd, team, base=base)
            if cfg.get("misconfigured"):
                sub = pd.split(".")[0] if pd.count(".") >= 2 else "@"
                say("DNS        %s not pointing at Vercel yet: %s" % (pd, ("A @ 76.76.21.21" if sub == "@" else "CNAME %s cname.vercel-dns.com" % sub)))
        except VercelError as e:
            say("domain     %s FAILED: %s" % (pd, e))
    prod_file = root / ".env.production"
    if prod_file.exists():
        prod_pairs = [(k, v) for k, v in parse_env_file(prod_file) if v != ""]
        ok = 0
        for k, v in prod_pairs:
            try:
                vapi(token, "POST", "/v10/projects/%s/env" % pid, team,
                     {"key": k, "value": v, "type": "sensitive" if "PASSWORD" in k or "SECRET" in k else "encrypted", "target": ["production"]},
                     query={"upsert": "true"}, base=base)
                ok += 1
            except VercelError as e:
                say("env        %s (production) FAILED: %s" % (k, e))
        if prod_pairs:
            say("env        %d variable%s set for Production from .env.production" % (ok, "" if ok == 1 else "s"))
    say("")
    say("Push %s and Vercel deploys it%s. Production deploys from %s%s." % (
        WORK_BRANCH, (" to https://" + args.domain.lower()) if args.domain else "", PROTECTED[0],
        (" to https://" + args.production_domain.lower()) if args.production_domain else ""))


# ----------------------------------------------------------------------------- install / uninstall

# ----------------------------------------------------------------------------- doctor / CLI bootstrap

def http_get(url, to=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json, application/json, */*"})
    with urllib.request.urlopen(req, timeout=to) as resp:
        return resp.read()


def latest_tag(repo, to=60):
    """Version of the latest release without the API (which rate-limits anonymous callers): follow the /releases/latest redirect."""
    req = urllib.request.Request("https://github.com/%s/releases/latest" % repo, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=to) as resp:
        m = re.search(r"/releases/tag/([^/?#]+)", resp.geturl())
        return m.group(1) if m else None


def latest_release_asset(repo, candidates):
    """candidates: asset-name templates with {tag} and {ver}; the first that downloads wins."""
    tag = latest_tag(repo)
    if not tag:
        return None, None, ""
    ver = tag.lstrip("v")
    for tpl in candidates:
        name = tpl.format(tag=tag, ver=ver)
        url = "https://github.com/%s/releases/download/%s/%s" % (repo, tag, name)
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60):
                return url, name, tag
        except urllib.error.HTTPError:
            continue
    return None, None, tag


def extract_into(archive, name, members):
    """Pull the named executables out of a .zip or .tar.gz into BIN_DIR."""
    import tarfile
    import zipfile
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    got = []
    if name.endswith(".zip"):
        with zipfile.ZipFile(str(archive)) as z:
            for n in z.namelist():
                base = n.rsplit("/", 1)[-1]
                if base in members:
                    with z.open(n) as src, open(BIN_DIR / base, "wb") as out:
                        shutil.copyfileobj(src, out)
                    got.append(base)
    else:
        with tarfile.open(str(archive), "r:*") as t:
            for m in t.getmembers():
                base = m.name.rsplit("/", 1)[-1]
                if base in members and m.isfile():
                    with t.extractfile(m) as src, open(BIN_DIR / base, "wb") as out:
                        shutil.copyfileobj(src, out)
                    got.append(base)
    for g in got:
        try:
            os.chmod(BIN_DIR / g, 0o755)
        except OSError:
            pass
    return got


def ensure_cli(name):
    """Download a CLI into BIN_DIR if it is not on PATH. Returns (path, note)."""
    if tool(name):
        return tool(name), "present"
    win = os.name == "nt"
    try:
        if name == "supabase":
            url, asset, tag = latest_release_asset("supabase/cli", ["supabase_windows_amd64.tar.gz", "supabase_{ver}_windows_amd64.tar.gz"] if win
                                                   else ["supabase_linux_amd64.tar.gz", "supabase_{ver}_linux_amd64.tar.gz"])
            members = {"supabase.exe"} if win else {"supabase"}
        elif name == "gh":
            url, asset, tag = latest_release_asset("cli/cli", ["gh_{ver}_windows_amd64.zip"] if win else ["gh_{ver}_linux_amd64.tar.gz"])
            members = {"gh.exe"} if win else {"gh"}
        elif name == "vercel":
            npm = shutil.which("npm")
            if not npm:
                return None, "needs Node.js (npm) - install Node, then re-run"
            out = subprocess.run([npm, "install", "-g", "vercel"], capture_output=True, text=True, timeout=600, **NOWIN)
            return tool("vercel"), ("installed with npm" if tool("vercel") else "npm install -g vercel failed: " + (out.stderr or out.stdout)[-200:])
        else:
            return None, "unknown tool"
        if not url:
            return None, "no release asset found for this platform (%s)" % tag
        tmp = Path(tempfile.mkdtemp()) / asset
        tmp.write_bytes(http_get(url, to=300))
        got = extract_into(tmp, asset, members)
        return (tool(name), "downloaded %s" % tag) if got else (None, "archive had no %s" % "/".join(members))
    except Exception as e:
        return None, "download failed: %s" % e


def add_bin_to_user_path():
    if os.name != "nt":
        return
    try:
        cur = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetEnvironmentVariable('Path','User')"],
                             capture_output=True, text=True, timeout=30, **NOWIN).stdout.strip()
        if str(BIN_DIR).lower() in cur.lower():
            return
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';%s', 'User')" % BIN_DIR],
                       capture_output=True, text=True, timeout=30, **NOWIN)
    except Exception:
        pass


def logins(interactive):
    """Check the three logins; run them when there is a terminal to do it in."""
    lines = []
    gh = tool("gh")
    if gh:
        ok = sh([gh, "auth", "status"]).returncode == 0
        if not ok and interactive:
            subprocess.call([gh, "auth", "login", "--web", "--git-protocol", "https"])
            ok = sh([gh, "auth", "status"]).returncode == 0
        lines.append(("GitHub", ok, "gh auth login --web"))
    else:
        lines.append(("GitHub", False, "gh not installed"))
    vt = vercel_token()
    vercel = tool("vercel")
    if not vt and vercel and interactive:
        subprocess.call([vercel, "login"])
        vt = vercel_token()
    lines.append(("Vercel", bool(vt), "vercel login" if vercel else "vercel CLI not installed (needs Node)"))
    st = supabase_token()
    sb = tool("supabase")
    if not st and sb and interactive:
        subprocess.call([sb, "login"])
        st = supabase_token()
    lines.append(("Supabase", bool(st), "supabase login" if sb else "supabase CLI not installed"))
    return lines


def cmd_update(args):
    """Fetch the latest release from GitHub and re-run install (config, repos and logins untouched)."""
    repo = CONFIG.get("source") or DEFAULTS["source"]
    try:
        tag = latest_tag(repo)
    except Exception as e:
        sys.exit("cannot reach github.com/%s: %s" % (repo, e))
    if not tag:
        sys.exit("no release found at github.com/%s/releases" % repo)
    ver = tag.lstrip("v")
    if ver == VERSION and not args.force:
        say("kit        v%s is the latest release (github.com/%s)" % (VERSION, repo))
        return
    url, asset, _ = latest_release_asset(repo, ["SoneloSolutionDevKit-v{ver}.zip", "sonelo-devkit-v{ver}.zip", "teknobu-kit-v{ver}.zip", "SoneloSolutionDevKit.zip"])
    if not url:
        sys.exit("release %s has no kit zip attached; download it from github.com/%s/releases and run install from the unzipped folder" % (tag, repo))
    import zipfile
    tmp = Path(tempfile.mkdtemp())
    (tmp / asset).write_bytes(http_get(url, to=300))
    with zipfile.ZipFile(str(tmp / asset)) as z:
        z.extractall(str(tmp))
    found = list(tmp.rglob("repo_setup.py"))
    if not found:
        sys.exit("the release zip has no repo_setup.py")
    src = found[0].parent
    say("kit        v%s -> v%s from %s" % (VERSION, ver, url))
    out = subprocess.run([sys.executable, str(src / "repo_setup.py"), "install", "--yes", "--no-login"] + (["--no-cli"] if args.no_cli else []),
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, **NOWIN)
    for line in (out.stdout or out.stderr).strip().splitlines():
        say("  " + line)
    say("Repos pick the new worklog up on open; run `refresh` in a repo to take the new agents, commands and hooks.")


def cmd_doctor(args):
    """Everything the setup needs, as present/absent. Never prints a value."""
    say("kit        v%s at %s%s" % (VERSION, INSTALLED, "" if INSTALLED.exists() else "  (not installed - run install)"))
    say("pipeline   built in (%d files: agents, commands, hooks, gates)%s" % (len(BUILTIN_PIPELINE),
        ("; plus your starter (%d files) which takes precedence" % sum(1 for p in PIPELINE_DIR.rglob("*") if p.is_file())) if pipeline_present() else ""))
    say("worklog    %s" % ("v%s" % ".".join(map(str, version_of(WORKLOG))) if WORKLOG.exists() else "missing"))
    for name in ("git", "node", "npm", "gh", "vercel", "supabase"):
        say("%-10s %s" % (name, tool(name) or "not found"))
    gh = tool("gh")
    say("GitHub     %s" % ("logged in" if gh and sh([gh, "auth", "status"]).returncode == 0 else "not logged in (gh auth login --web)"))
    tok, src = vercel_token(want_source=True)
    if tok:
        try:
            user = vapi(tok, "GET", "/v2/user").get("user", {}).get("username") or "?"
            say("Vercel     token from %s - valid (account %s)" % (src, user))
        except VercelError as e:
            say("Vercel     token from %s - REJECTED (%s)" % (src, e))
    else:
        say("Vercel     no token (vercel login, or VERCEL_TOKEN)")
    tok, src = supabase_token(want_source=True)
    if tok:
        try:
            orgs = sapi(tok, "GET", "/v1/organizations") or []
            say("Supabase   token from %s - valid; organisation%s: %s" % (src, "" if len(orgs) == 1 else "s", ", ".join("%s (%s)" % (o.get("name"), o.get("id")) for o in orgs)))
        except VercelError as e:
            say("Supabase   token from %s - REJECTED (%s)" % (src, e))
            if "env var" in src:
                say("           the env var wins over `supabase login`; remove it (or set a fresh token) and re-run")
    else:
        say("Supabase   no token (supabase login, or SUPABASE_ACCESS_TOKEN)")
    say("UAT Hub    %s; %s %s" % (UAT_HUB_URL, UAT_HUB_KEY_VAR,
        "set" if os.environ.get(UAT_HUB_KEY_VAR) else "not set - export it in your environment"))
    say("           MCP server %s" % (UAT_HUB_SERVER.as_posix() if UAT_HUB_SERVER.exists() else
        "not found at %s (sessions fall back to the HTTP endpoint)" % UAT_HUB_SERVER.as_posix()))
    root = repo_root(args.repo) if hasattr(args, "repo") else repo_root()
    if root:
        items, _ = status(root)
        missing = [n for n, ok in items if not ok]
        say("repo       %s: %s" % (root.name, ("missing " + ", ".join(missing)) if missing else "standards complete"))
        say("           UAT Hub project %s - a slug the hub does not know is refused, so create the "
            "project there first" % uat_slug(root))


def command_text(tpl):
    c = CONFIG
    pattern = c.get("domain_pattern") or "{name}.example.com"
    return fill(tpl, WORK=c["work_branch"], MAIN=c["main_branch"], ENVDOC=c["work_branch"].upper() + ".md",
                STACK=c.get("stack_default") or DEFAULTS["stack_default"], ORG_OR_USER=c.get("github_org") or "your GitHub user",
                REGION=c.get("supabase_region") or DEFAULTS["supabase_region"], DATABASE=c.get("database") or "separate",
                DB_PLAN=("create production and a persistent `%s` database branch" % c["work_branch"]) if c.get("database") == "branching"
                else ("create `<name>-%s` and `<name>` projects" % c["work_branch"]),
                UAT_HUB=UAT_HUB_URL,
                DOMAIN_PATTERN=pattern.replace("{name}", "<name>"), DOMAIN_EXAMPLE=pattern.replace("{name}", "<repo>"))


def frontmatter(path):
    """name/description/model from a Claude Code agent or command file."""
    text = read(path) or ""
    out = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        for line in text[3:end if end > 0 else None].splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                out[k.strip()] = v.strip()
    return out


# ----------------------------------------------------------------------------- worktrees

def wt_dirname(repo_name, branch):
    """Folder name for a worktree: <repo>-wt-<branch>, sanitised (slashes and odd characters become dashes)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.") or "branch"
    return "%s-wt-%s" % (repo_name, safe)


def wt_list(root):
    """Worktrees from `git worktree list --porcelain`: [{path, branch, main}]; git lists the main worktree first."""
    out = sh(["git", "-C", str(root), "worktree", "list", "--porcelain"])
    items, cur = [], {}
    for line in (out.stdout or "").splitlines() + [""]:
        if not line.strip():
            if cur:
                items.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[len("worktree "):]
        elif line.startswith("branch "):
            b = line[len("branch "):]
            cur["branch"] = b[len("refs/heads/"):] if b.startswith("refs/heads/") else b
        elif line == "detached":
            cur["branch"] = None
    for i, it in enumerate(items):
        it["main"] = (i == 0)
    return items


def wt_state(root, wt):
    """(dirty, merged-into-the-work-branch) for one worktree. Squash-merged branches read as not merged.
    Refs are fully qualified so a tag sharing the branch's name cannot shadow it."""
    dirty = bool((sh(["git", "-C", wt["path"], "status", "--porcelain"]).stdout or "").strip())
    merged = bool(wt.get("branch")) and sh(
        ["git", "-C", str(root), "merge-base", "--is-ancestor",
         "refs/heads/%s" % wt["branch"], "refs/heads/%s" % WORK_BRANCH]).returncode == 0
    return dirty, merged


def git_tip(root, ref):
    out = sh(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", ref])
    return (out.stdout or "").strip() if out.returncode == 0 else None


def cmd_worktree(args):
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository")
    use_repo_config(root)
    if args.verb == "new":
        if not args.branch:
            sys.exit("usage: worktree new <branch>")
        wts = wt_list(root)
        if not wts:
            sys.exit("git worktree list failed - git 2.7+ is required")
        main_wt = Path(wts[0]["path"])             # naming and placement follow the main worktree, wherever this runs from
        dest = main_wt.parent / wt_dirname(main_wt.name, args.branch)
        if dest.exists():
            sys.exit("%s already exists - open your session there, or pick another branch name" % dest)
        have_branch = sh(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                          "refs/heads/%s" % args.branch]).returncode == 0
        have_work = sh(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                        "refs/heads/%s" % WORK_BRANCH]).returncode == 0
        cmd = ["git", "-C", str(root), "worktree", "add", str(dest)]
        cmd += [args.branch] if have_branch else (["-b", args.branch] + ([WORK_BRANCH] if have_work else []))
        out = sh(cmd)
        if out.returncode != 0:
            sys.exit((out.stderr or out.stdout or "git worktree add failed").strip())
        project = read_json(main_wt / ".worklog" / "worklog.json", {}).get("project") or main_wt.name
        write(dest / ".worklog" / "worklog.json", json.dumps({"project": project}, indent=2) + "\n")
        ex = sh(["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"])
        if ex.returncode == 0 and ex.stdout.strip():   # shared across worktrees: keep the stamp from reading as dirt in repos without the kit's .gitignore
            p = Path(ex.stdout.strip())
            p = p if p.is_absolute() else root / p
            try:
                cur = p.read_text(encoding="utf-8") if p.exists() else ""
                if ".worklog/" not in cur:
                    write(p, cur.rstrip("\n") + ("\n" if cur else "") + ".worklog/\n")
            except OSError:
                pass
        say("%-10s %s" % ("worktree", dest))
        say("%-10s %s%s" % ("branch", args.branch, "" if have_branch else (" (new, off %s)" % (WORK_BRANCH if have_work else "HEAD"))))
        say('%-10s reports under project "%s" (repo column shows the folder name)' % ("worklog", project))
        say("%-10s open your Claude Code session in %s; the worklog installs itself at session start" % ("next", dest))
        return
    work_tip = git_tip(root, "refs/heads/%s" % WORK_BRANCH)
    if args.verb == "list":
        for wt in wt_list(root):
            if wt["main"]:
                say("%s  %s  (main worktree)" % (wt["path"], wt.get("branch") or "detached"))
                continue
            if not Path(wt["path"]).exists():
                say("%s  %s  · directory gone (run worktree clean)" % (wt["path"], wt.get("branch") or "detached"))
                continue
            dirty, merged = wt_state(root, wt)
            fresh = merged and work_tip and git_tip(root, "refs/heads/%s" % wt["branch"]) == work_tip
            say("%s  %s%s%s" % (wt["path"], wt.get("branch") or "detached",
                                "  · uncommitted changes" if dirty else "",
                                "  · no commits yet" if fresh else (("  · merged into %s" % WORK_BRANCH) if merged
                                                                    else ("  · not merged into %s" % WORK_BRANCH))))
        return
    removed = kept = 0
    for wt in wt_list(root):
        if wt["main"]:
            continue
        if not Path(wt["path"]).exists():
            say("%-10s %s - directory already gone; stale record pruned" % ("removed", wt["path"]))
            removed += 1
            continue
        dirty, merged = wt_state(root, wt)
        if dirty:
            say("%-10s %s - uncommitted changes (commit or stash there, then re-run clean)" % ("kept", wt["path"]))
            kept += 1
            continue
        if not wt.get("branch"):
            say('%-10s %s - detached HEAD; remove by hand: git worktree remove "%s"' % ("kept", wt["path"], wt["path"]))
            kept += 1
            continue
        if not merged:
            if work_tip is None:
                reason = "the work branch %s has no local ref here, so merges cannot be proven" % WORK_BRANCH
            else:
                reason = ('%s is not merged into %s (a squash merge looks unmerged; remove by hand: git worktree remove "%s")'
                          % (wt["branch"], WORK_BRANCH, wt["path"]))
            say("%-10s %s - %s" % ("kept", wt["path"], reason))
            kept += 1
            continue
        fresh = work_tip and git_tip(root, "refs/heads/%s" % wt["branch"]) == work_tip
        out = sh(["git", "-C", str(root), "worktree", "remove", wt["path"]])
        if out.returncode == 0:
            say("%-10s %s - %sbranch %s kept" % ("removed", wt["path"], "no commits yet; " if fresh else "", wt["branch"]))
            removed += 1
        else:
            say("%-10s %s - %s" % ("kept", wt["path"], (out.stderr or "").strip()))
            kept += 1
    sh(["git", "-C", str(root), "worktree", "prune"])
    say("%d removed, %d kept" % (removed, kept))


def cmd_landing(args):
    import html
    import webbrowser
    root = repo_root(args.repo)
    if not root:
        sys.exit("not inside a git repository")
    use_repo_config(root)
    esc = html.escape
    tcfg = read_json(root / ".teknobu.json", {})
    branch = (sh(["git", "branch", "--show-current"], cwd=str(root)).stdout or "").strip() or "?"

    def rows(items):
        return "".join('<div class="row"><span class="k">%s</span><span class="d">%s</span>%s%s</div>' % (
            esc(k), esc(d), ('<span class="m">%s</span>' % esc(m)) if m else "",
            ('<button class="copy" data-copy="%s">copy</button>' % esc(c)) if c else "") for k, d, m, c in items) or '<div class="muted">none</div>'

    cmds = []
    for f in sorted((root / ".claude" / "commands").glob("*.md")):
        cmds.append(("/" + f.stem, frontmatter(f).get("description", ""), "repo", "/" + f.stem))
    for f in sorted(Path("~/.claude/commands").expanduser().glob("*.md")):
        if f.stem in ("repo-setup", "new-repo", "landing"):
            cmds.append(("/" + f.stem, frontmatter(f).get("description", ""), "kit", "/" + f.stem))
    agents = []
    for f in sorted((root / ".claude" / "agents").glob("*.md")):
        fm = frontmatter(f)
        agents.append((fm.get("name") or f.stem, (fm.get("description") or "").split(". Use ")[0].rstrip("."), fm.get("model") or "", ""))
    items, _ = status(root)
    state = "".join('<div><span class="tick%s"></span>%s</div>' % ("" if ok else " no", esc(n)) for n, ok in items)
    envs = []
    if tcfg.get("work_url"):
        envs.append((WORK_BRANCH, tcfg["work_url"], "Vercel", tcfg["work_url"]))
    if tcfg.get("production_url"):
        envs.append((PROTECTED[0], tcfg["production_url"], "Vercel", tcfg["production_url"]))
    for label, envf in ((WORK_BRANCH, ".env.%s" % WORK_BRANCH), ("production", ".env.production"), ("local", ".env")):
        m = re.search(r"^(?:VITE_)?SUPABASE_PROJECT_REF=(\w+)", read(root / envf) or "", re.M)
        if m:
            envs.append(("supabase " + label, "project ref %s (keys in %s, git-ignored)" % (m.group(1), envf), "", "https://supabase.com/dashboard/project/" + m.group(1)))
    remote = (sh(["git", "remote", "get-url", "origin"], cwd=str(root)).stdout or "").strip()
    if remote:
        envs.append(("github", remote.replace(".git", ""), "", remote.replace(".git", "")))
    docs = []
    for rel, d in (("docs/SCOPE.md", "numbered deliverables, out of scope, change log"), ("docs/STATUS.md", "now, done, blocked, next"),
                   ("docs/UAT_PLAN.md", "master list of user-observable behaviours"), ("docs/uat/", "UAT documents per pull request"),
                   ("docs/ARCHITECTURE.md", "services, data, functions, integrations"), ("docs/BRAND.md", "brand guidelines as given"),
                   (".claude/rules/design.md", "design contract the reviewer judges against"), ("CHANGELOG.md", "kept by changelog-scribe"),
                   (env_doc(), "the manual wiring checklist"), ("MIGRATION.md", "Lovable migration checklist"), ("CLAUDE.md", "rules, tiers, standards")):
        if (root / rel).exists():
            docs.append((rel, d, "", ""))
    docs_html = "".join('<div class="row"><span class="k"><a href="%s">%s</a></span><span class="d">%s</span></div>' % (
        esc((root / rel).as_uri()), esc(rel), esc(d)) for rel, d, _, _ in docs) or '<div class="muted">none yet</div>'
    wl = read_json(Path("~/.claude/worklog.json").expanduser(), {}) or {}
    pot = Path(wl.get("pot") or "") if wl.get("pot") else None
    wl_items = []
    if pot and pot.exists():
        for name, d in (("dashboard.html", "time, commits, sessions, tokens, agents per project"), ("morning.html", "today's morning page"),
                        ("latest-week.md", "this week's report"), ("latest.md", "yesterday and today")):
            if (pot / name).exists():
                wl_items.append('<div class="row"><span class="k"><a href="%s">%s</a></span><span class="d">%s</span></div>' % (esc((pot / name).as_uri()), esc(name), esc(d)))
    worklog_html = "".join(wl_items) or '<div class="muted">no worklog pot on this machine</div>'
    ok_n = sum(1 for _, ok in items if ok)
    missing = [n for n, ok in items if not ok]
    page = fill(LANDING_HTML, NAME=esc(root.name), BRANCH=esc(branch), WORK=esc(WORK_BRANCH), MAIN=esc(PROTECTED[0]), VERSION=VERSION,
                OKCOUNT=str(ok_n), TOTAL=str(len(items)),
                STATE_NOTE=('<br><span class="no">missing: %s</span>' % esc(", ".join(missing[:3]) + (" +%d" % (len(missing) - 3) if len(missing) > 3 else ""))) if missing else '<br><span class="ok">ready to work</span>',
                WHEN=datetime.now().strftime("%a %d %b %H:%M"), ACCENT="#00AF9F" if "Teknobu" in json.dumps(CONFIG.get("brand", {})) else "#2f6fed",
                COMMANDS=rows(cmds), AGENTS=rows(agents), STATE=state, ENVS=rows(envs) if envs else '<div class="muted">none recorded yet - supabase --create and vercel --create fill this in</div>',
                DOCS=docs_html, WORKLOG=worklog_html)
    out_dir = HOME_DIR / "landing"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (root.name + ".html")
    write(out, page)
    say("landing    %s" % out)
    if not args.no_open and not os.environ.get("WORKLOG_NO_OPEN"):
        try:
            webbrowser.open(out.as_uri())
        except Exception:
            pass


def _is_ours(entry):
    return any(HOOK_MARK in (h.get("command") or "") for h in entry.get("hooks", []))


def ask(prompt, default):
    try:
        v = input("%s [%s]: " % (prompt, default)).strip()
    except EOFError:
        return default
    return v or default


def configure(args):
    """Build config.json from preset, --set, and (first time, in a terminal) a few questions."""
    global CONFIG, WORK_BRANCH, PROTECTED, DEFAULT_GITHUB_ORG, DEFAULT_SUPABASE_REGION
    cfg = load_config()
    existed = CONFIG_FILE.exists()
    if getattr(args, "preset", None):
        if args.preset not in PRESETS:
            sys.exit("unknown preset %r (have: %s)" % (args.preset, ", ".join(PRESETS)))
        for k, v in PRESETS[args.preset].items():
            cfg[k] = json.loads(json.dumps(v))
    if getattr(args, "mode", None):
        cfg["mode"] = args.mode
    for kv in getattr(args, "set", None) or []:
        k, _, v = kv.partition("=")
        if not _:
            sys.exit("--set expects key=value")
        cfg[k.strip()] = v.strip()
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not getattr(args, "yes", False)
    if interactive and not existed and not getattr(args, "preset", None):
        say("First install: a few questions (Enter keeps the default; edit %s later)." % CONFIG_FILE)
        cfg["mode"] = "worklog" if ask("Full setup (standards, agents, infrastructure) or worklog only? full/worklog", cfg["mode"]).lower().startswith("w") else "full"
        if cfg["mode"] == "full":
            cfg["github_org"] = ask("GitHub organisation or user for new repos", cfg["github_org"] or "")
            cfg["work_branch"] = ask("Name of the branch you work on (gets its own URL and database)", cfg["work_branch"])
            cfg["database"] = "branching" if ask("Database strategy: separate projects, or Supabase branching? separate/branching", cfg["database"]).lower().startswith("b") else "separate"
            cfg["supabase_region"] = ask("Supabase region", cfg["supabase_region"])
            cfg["domain_pattern"] = ask("Production domain pattern for new projects ({name} is the project)", cfg["domain_pattern"])
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    write(CONFIG_FILE, json.dumps(cfg, indent=2) + "\n")
    CONFIG = cfg
    WORK_BRANCH = cfg["work_branch"]
    PROTECTED = [cfg["main_branch"]]
    DEFAULT_GITHUB_ORG = cfg["github_org"]
    DEFAULT_SUPABASE_REGION = cfg["supabase_region"]
    return cfg


def migrate_old_home():
    """v3 lived in ~/.claude/teknobu; carry config, pipeline, CLIs and landing pages across once."""
    if HOME_DIR.exists() or not OLD_HOME_DIR.exists():
        return False
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in ("config.json", "pipeline", "bin", "landing"):
        src, dst = OLD_HOME_DIR / name, HOME_DIR / name
        if src.exists() and not dst.exists():
            if src.is_dir():
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copyfile(str(src), str(dst))
            moved.append(name)
    if moved:
        say("migrated   %s -> %s (%s); the old folder is untouched" % (OLD_HOME_DIR, HOME_DIR, ", ".join(moved)))
    return True


def cmd_install(args):
    migrate_old_home()
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    me = Path(__file__).resolve()
    if me != INSTALLED.resolve():
        shutil.copyfile(str(me), str(INSTALLED))
    bundled = Path(__file__).resolve().parent / "worklog_agent.py"
    if bundled.exists() and bundled.resolve() != WORKLOG.resolve():
        shutil.copyfile(str(bundled), str(WORKLOG))
    elif not bundled.exists():
        # installed straight from a URL: fetch the worklog from the same repo
        raw = os.environ.get("TEKNOBU_RAW", "https://raw.githubusercontent.com")
        src = CONFIG.get("source") or DEFAULTS["source"]
        try:
            text = http_get("%s/%s/main/worklog_agent.py" % (raw, src), to=120).decode("utf-8")
            if "WORKLOG_VERSION" in text or "worklog" in text[:2000]:
                old_v = version_of(WORKLOG) if WORKLOG.exists() else None
                WORKLOG.write_text(text, encoding="utf-8")
                say("worklog    fetched from github.com/%s%s" % (src, "" if not old_v else " (was v%s)" % ".".join(map(str, old_v))))
        except Exception as e:
            say("worklog    not bundled and could not fetch from github.com/%s (%s) - kit works, worklog absent until you run install from a clone" % (src, e))
    cfg = configure(args)
    say("config     %s (mode %s, work branch %s, database %s)" % (CONFIG_FILE, cfg["mode"], cfg["work_branch"], cfg["database"]))
    if cfg["mode"] == "worklog":
        for f in (COMMAND_FILE, NEW_COMMAND_FILE):
            if f.exists():
                f.unlink()
        if WORKLOG.exists():
            out = subprocess.run([sys.executable, str(WORKLOG), "setup"] + (["--no-presence"] if getattr(args, "no_presence", False) else []),
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, **NOWIN)
            say("worklog    agent v%s; machine setup:" % ".".join(map(str, version_of(WORKLOG))))
            for line in (out.stdout or out.stderr).strip().splitlines():
                say("             " + line)
        say("")
        say("Worklog only: every git repo you open in Claude Code gets the agent; the dashboard is in the pot. Re-run install with --mode full for the rest.")
        return
    write(COMMAND_FILE, command_text(COMMAND_MD))
    write(NEW_COMMAND_FILE, command_text(NEW_COMMAND_MD))
    write(COMMAND_FILE.parent / "landing.md", LANDING_COMMAND_MD)
    data = read_json(USER_SETTINGS, None) if USER_SETTINGS.exists() else {}
    if data is None:
        sys.exit("cannot parse %s; fix it first" % USER_SETTINGS)
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault("SessionStart", [])
    entries[:] = [e for e in entries if not _is_ours(e)]
    py = Path(sys.executable).as_posix()
    cmd = '%s "%s" nudge' % (py if " " not in py else '"%s"' % py, INSTALLED.as_posix())
    entries.append({"hooks": [{"type": "command", "command": cmd, "timeout": 15}]})
    write(USER_SETTINGS, json.dumps(data, indent=2) + "\n")
    PIPELINE_DIR.mkdir(exist_ok=True)
    say("kit        %s (v%s)" % (INSTALLED, VERSION))
    if not pipeline_present():
        z = find_pipeline_zip()
        if z:
            say("pipeline   built in; your starter installed from %s (%d files) takes precedence" % (z, install_pipeline_zip(z)))
        else:
            say("pipeline   built in (%d files). Optional: a starter zip next to the kit or in Downloads overrides any of them" % len(BUILTIN_PIPELINE))
    else:
        say("pipeline   built in; plus your starter in %s (%d files)" % (PIPELINE_DIR, sum(1 for p in PIPELINE_DIR.rglob("*") if p.is_file())))
    if not getattr(args, "no_cli", False):
        for name in ("gh", "supabase", "vercel"):
            path, note = ensure_cli(name)
            say("%-10s %s" % (name, (path + "  (" + note + ")") if path else "not available: " + note))
        add_bin_to_user_path()
    if not getattr(args, "no_login", False):
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
        for svc, ok, how in logins(interactive):
            say("%-10s %s" % (svc, "logged in" if ok else "not logged in - run: " + how))
        if not interactive:
            say("           (logins need a terminal: run the commands above in PowerShell, or double-click install.cmd)")
    if WORKLOG.exists():
        out = subprocess.run([sys.executable, str(WORKLOG), "setup"] + (["--no-presence"] if getattr(args, "no_presence", False) else []),
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, **NOWIN)
        say("worklog    agent v%s installed at %s; machine setup:" % (".".join(map(str, version_of(WORKLOG))), WORKLOG))
        for line in (out.stdout or out.stderr).strip().splitlines():
            say("             " + line)
    else:
        say("worklog    not bundled next to repo_setup.py; repos won't get the worklog from apply")
    say("commands   /repo-setup (existing repo, or asks)  ->  %s" % COMMAND_FILE)
    say("           /new-repo (scaffold, standards, GitHub, Supabase, Vercel)  ->  %s" % NEW_COMMAND_FILE)
    say("nudge      session-start hook in %s (says so when a repo lacks the standards; .nokit silences it)" % USER_SETTINGS)
    say("")
    say("In any repo: open Claude Code and run /repo-setup, or: python \"%s\" apply" % INSTALLED.as_posix())


def cmd_uninstall(args):
    data = read_json(USER_SETTINGS, None) if USER_SETTINGS.exists() else None
    if data:
        hooks = data.get("hooks") or {}
        for event in list(hooks):
            hooks[event] = [e for e in hooks[event] if not _is_ours(e)]
            if not hooks[event]:
                del hooks[event]
        if not hooks:
            data.pop("hooks", None)
        write(USER_SETTINGS, json.dumps(data, indent=2) + "\n")
    for f in (COMMAND_FILE, NEW_COMMAND_FILE):
        if f.exists():
            f.unlink()
    say("removed the /repo-setup and /new-repo commands and the session-start nudge; %s and the repos' files are left in place" % HOME_DIR)


# ----------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Teknobu repo standards kit v%s" % VERSION)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("apply", help="lay the standards into the current repo")
    p.add_argument("--repo", help="repo path (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="show what would change")
    p.add_argument("--force", action="store_true", help="replace files that exist without the kit marker")
    p.add_argument("--update-pipeline", action="store_true", help="refresh the built-in pipeline files (agents, commands, hooks, gates) from this kit version; backups kept")
    p.add_argument("--uat-project", metavar="SLUG", help="UAT Hub project slug for this repo (default: the recorded one, else the folder name); the project must already exist in the hub")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("refresh", help="take this kit's agents, commands, hooks and CI gates - and "
                                       "nothing else (not your ci.yml, env files, branches or worklog); "
                                       "backups kept")
    p.add_argument("--repo", help="repo path (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="show what would change")
    p.set_defaults(fn=cmd_refresh)

    p = sub.add_parser("check", help="what's in place in the current repo")
    p.add_argument("--repo")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("protect", help="GitHub branch protection for main (gh CLI)")
    p.add_argument("--repo")
    p.set_defaults(fn=cmd_protect)
    p = sub.add_parser("github", help="create the GitHub repo with gh, push main + the work branch, protect main")
    p.add_argument("--org", default=DEFAULT_GITHUB_ORG or None, help="organisation or user (default: config github_org, else your gh user)")
    p.add_argument("--name", help="repository name (default: the folder name)")
    p.add_argument("--public", action="store_true", help="public repository (default private)")
    p.add_argument("--repo")
    p.set_defaults(fn=cmd_github)
    p = sub.add_parser("supabase", help="create the work (and production) databases on Supabase and wire the secrets")
    p.add_argument("--create", action="store_true", help="create the database(s) for this repo per --database")
    p.add_argument("--only", metavar="WORK", help="only the work database (production already exists), e.g. --only %s" % WORK_BRANCH)
    p.add_argument("--list-orgs", action="store_true", help="list your Supabase organisations")
    p.add_argument("--org", default=CONFIG.get("supabase_org") or None, help="organisation id/slug (needed if you have more than one)")
    p.add_argument("--region", default=DEFAULT_SUPABASE_REGION, help="default %s (config)" % DEFAULT_SUPABASE_REGION)
    p.add_argument("--database", choices=["separate", "branching"], default=CONFIG.get("database", "separate"),
                   help="separate: <name>-<work> and <name> projects | branching: one project + a persistent work branch (default from config)")
    p.add_argument("--name", help="project base name (default: the folder name)")
    p.add_argument("--token", help="Supabase access token (default: SUPABASE_ACCESS_TOKEN or the CLI login)")
    p.add_argument("--poll", type=int, default=10, help=argparse.SUPPRESS)
    p.add_argument("--repo")
    p.add_argument("--api", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_supabase)
    p = sub.add_parser("vercel", help="wire the work branch on Vercel: domain, DNS check, branch-scoped env vars")
    p.add_argument("--create", action="store_true", help="create the Vercel project from the GitHub repo if it doesn't exist")
    p.add_argument("--team", default=CONFIG.get("vercel_team") or None, help="Vercel team id to create the project in (when you have several)")
    p.add_argument("--production-domain", help="also attach the production domain (serves main)")
    p.add_argument("--domain", help="domain for the prelive branch, e.g. prelive.knecta.io")
    p.add_argument("--env-file", help="values to push as Preview variables scoped to the work branch (default .env.<work>)")
    p.add_argument("--project", help="Vercel project name if it differs from the repo folder and the repo isn't linked yet")
    p.add_argument("--token", help="Vercel token (default: VERCEL_TOKEN or the Vercel CLI login)")
    p.add_argument("--repo")
    p.add_argument("--api", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_vercel)
    sub.add_parser("nudge", help="session-start hook entry point").set_defaults(fn=cmd_nudge)
    p = sub.add_parser("install", help="install the kit, the worklog, the pipeline, the CLIs and the Claude Code commands")
    p.add_argument("--no-presence", action="store_true", help="skip the worklog's lock/unlock Task Scheduler tasks")
    p.add_argument("--no-cli", action="store_true", help="don't download gh / supabase / vercel")
    p.add_argument("--no-login", action="store_true", help="don't run or check logins")
    p.add_argument("--mode", choices=["full", "worklog"], help="full (standards, agents, infrastructure) or worklog only")
    p.add_argument("--preset", help="a known configuration, e.g. --preset teknobu")
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="set a config value, e.g. --set work_branch=staging")
    p.add_argument("--yes", action="store_true", help="no questions; defaults/preset/--set only")
    p.set_defaults(fn=cmd_install)
    p = sub.add_parser("landing", help="build and open this repo's landing page: commands, agents, state, environments, docs, worklog")
    p.add_argument("--repo")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=cmd_landing)
    p = sub.add_parser("worktree", help="git worktrees for parallel sessions: new <branch> | list | clean (removes merged, keeps dirty)")
    p.add_argument("verb", choices=["new", "list", "clean"])
    p.add_argument("branch", nargs="?", help="branch for 'new'; created off the work branch if it doesn't exist")
    p.add_argument("--repo")
    p.set_defaults(fn=cmd_worktree)
    p = sub.add_parser("update", help="fetch the latest kit release from GitHub and install it (config kept)")
    p.add_argument("--force", action="store_true", help="reinstall even if already on the latest version")
    p.add_argument("--no-cli", action="store_true")
    p.set_defaults(fn=cmd_update)
    p = sub.add_parser("doctor", help="what the setup needs, as present/absent: pipeline, CLIs, logins (never prints values)")
    p.add_argument("--repo")
    p.set_defaults(fn=cmd_doctor)
    sub.add_parser("uninstall", help="remove the command and the nudge").set_defaults(fn=cmd_uninstall)
    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    args.fn(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
