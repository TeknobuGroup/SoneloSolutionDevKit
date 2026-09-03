#!/bin/sh
# sonelo-devkit pipeline: PostToolUse hook on Edit/Write/MultiEdit.
# Lints the edited file and reports only what this change ADDED on top of what the repo already
# accepts, then nudges once per branch when a full-pipeline path is edited with no impact report
# on record. Exit 2 feeds the output back to Claude.
#
# Two things are deliberately NOT here, both measured rather than guessed (ADR-0009):
#   * A whole-project type check. It ran on every single edit, and against a solution-style
#     tsconfig ("files": [], "references": [...]) it compiles the empty file list - seconds per
#     edit for no signal whatever. Types are checked by .githooks/checks on pre-push and by CI,
#     which is where a whole-project check belongs.
#   * Reporting lint errors the session did not cause. A repo with an eslint ratchet carries
#     hundreds of accepted errors; shouting about them after every edit made the hook exit 2 on
#     more than half of all edits and sent the session off fixing debt it had not introduced.
#     Only a rise above the accepted level is reported.
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
    if [ -f eslint.config.js ] || [ -f eslint.config.mjs ] || [ -f eslint.config.ts ] || [ -f .eslintrc.json ] || [ -f .eslintrc.cjs ] || [ -f .eslintrc.js ]; then
      # Call the installed binary directly. `npx` re-resolves the package on every invocation,
      # which measured at roughly twice the wall clock for the identical result. The report goes
      # to a file rather than a pipe because the reader below takes its program on stdin.
      mkdir -p .claude/state/lint 2>/dev/null
      # Per-process: concurrent sessions in one repo must not read each other's report.
      es_file=.claude/state/lint/.report-$$.json
      rm -f "$es_file" 2>/dev/null
      if [ -f node_modules/eslint/bin/eslint.js ]; then
        timeout 60 node node_modules/eslint/bin/eslint.js -f json -- "$file" > "$es_file" 2>/dev/null
      else
        timeout 60 npx --no-install eslint -f json -- "$file" > "$es_file" 2>/dev/null
      fi
      if [ -s "$es_file" ]; then
        tracked=0
        git ls-files --error-unmatch -- "$p" >/dev/null 2>&1 && tracked=1
        es_out=$($py - "$p" "$tracked" "$es_file" <<'PYEOF' 2>/dev/null
import hashlib, json, os, sys

path, tracked = sys.argv[1], sys.argv[2] == "1"
try:
    with open(sys.argv[3], encoding="utf-8") as fh:
        report = json.load(fh)
except Exception:
    raise SystemExit
errors = [m for r in (report or []) for m in (r.get("messages") or []) if m.get("severity") == 2]
current = len(errors)

rel = path
cwd = os.getcwd().replace("\\", "/")
# Case-insensitive: Windows gives back "C:/..." for a cwd Python reports as "c:/...", and a
# missed strip leaves rel absolute, matching no baseline entry and reporting old errors as new.
if rel.lower().startswith(cwd.lower() + "/"):
    rel = rel[len(cwd) + 1:]


def accepted_from_baseline():
    """A ratchet baseline is authoritative: a file it does not list accepts zero."""
    for name in ("scripts/eslint-baseline.json", ".eslint-baseline.json", "scripts/lint-baseline.json"):
        try:
            with open(name, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        counts = doc.get("counts")
        if not isinstance(counts, dict):
            counts = {k: v for k, v in doc.items() if isinstance(v, int)}
        if not counts:
            continue
        value = counts.get(rel)
        return value if isinstance(value, int) else 0
    return None


cache = os.path.join(".claude", "state", "lint", hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16])
try:
    with open(cache, encoding="utf-8") as fh:
        seen = int(fh.read().strip())
except Exception:
    seen = None

accepted = accepted_from_baseline()
# A baseline is a ceiling that only ever falls, so it can sit above what the file really has.
# The lower of the two is the honest bar: never nag about debt, but catch every error added.
if accepted is None:
    # No baseline. A file already in git arrived with whatever it has, so record that and stay
    # quiet; a file this session created owns every error in it.
    accepted = seen if seen is not None else (current if tracked else 0)
elif seen is not None:
    accepted = min(accepted, seen)

try:
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        fh.write(str(current))
except Exception:
    pass

if current <= accepted:
    raise SystemExit

lines = [
    "%s: lint errors went from %d to %d, so this change added %d."
    % (rel, accepted, current, current - accepted),
    "Every error in the file is listed; the ones on lines you just wrote are yours. The other"
    " %d were already accepted here - leave them alone." % accepted,
]
for m in errors[:12]:
    lines.append("  %s:%s  %s  %s" % (m.get("line"), m.get("column"), m.get("message"), m.get("ruleId") or ""))
if len(errors) > 12:
    lines.append("  ... %d more" % (len(errors) - 12))
print("\n".join(lines))
PYEOF
)
        [ -n "$es_out" ] && out="$out
[lint]
$es_out"
      fi
      rm -f "$es_file" 2>/dev/null
    fi
    ;;
esac
if [ -n "$out" ]; then
  printf '%s\n' "Fix or act on these before continuing (from the post-edit hook on $file):$out" >&2
  exit 2
fi
exit 0
