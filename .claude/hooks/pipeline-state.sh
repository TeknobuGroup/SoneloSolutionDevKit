#!/bin/sh
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
    printf '%s\n' "$files" | grep -Eq '^supabase/|(^|/)functions/|(^|/)auth(/|\.)|^\.github/workflows/|(^|/)\.mcp\.json$' && out="$out security"
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
