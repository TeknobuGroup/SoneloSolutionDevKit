#!/bin/sh
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
