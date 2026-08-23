#!/bin/sh
# sonelo-devkit pipeline: Stop hook. Blocks the session from stopping while "done" is not true.
# Checks: (1) code changed -> CHANGELOG.md changed; (2) migrations changed -> generated types changed;
# (3) the pipeline verdict for this branch is not "blocked". Exit 2 with the reason keeps Claude working.
{ [ -n "$SONELO_SKIP_HOOKS" ] || [ -n "$TEKNOBU_SKIP_HOOKS" ]; } && exit 0
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
branch=$(git branch --show-current 2>/dev/null)
main=$(python -c "import json; print((json.load(open('.teknobu.json')).get('protected') or ['main'])[0])" 2>/dev/null || echo main)
types=$(python -c "import json; print(json.load(open('.teknobu.json')).get('generated_types') or 'src/types/database.ts')" 2>/dev/null || echo src/types/database.ts)
# The working tree is this session's work; the branch-level check (code vs changelog vs UAT across the whole PR) is CI's job.
changed=$( { git diff --name-only 2>/dev/null; git diff --name-only --cached 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | sort -u)
[ -z "$changed" ] && exit 0
code=$(printf '%s\n' "$changed" | grep -Ev '^(docs/|CHANGELOG\.md|README|\.claude/|\.github/|PRELIVE\.md|STAGING\.md|[A-Z]+\.md|.*\.md$)' | grep -Ev '^\.(env|teknobu)' | head -1)
reasons=""
if [ -n "$code" ] && ! printf '%s\n' "$changed" | grep -q '^CHANGELOG\.md$'; then
  reasons="$reasons
- Code changed but CHANGELOG.md has no entry for it. Run changelog-scribe (or /post-change)."
fi
if printf '%s\n' "$changed" | grep -q '^supabase/migrations/' && ! printf '%s\n' "$changed" | grep -q "^$types\$"; then
  reasons="$reasons
- A migration changed but $types was not regenerated. Run the types generation command from .claude/rules/supabase.md and commit it."
fi
verdict=".claude/state/$branch/review.json"
if [ -f "$verdict" ]; then
  v=$(python -c "import json; print(json.load(open('$verdict')).get('verdict',''))" 2>/dev/null)
  if [ "$v" = "blocked" ]; then
    reasons="$reasons
- The pipeline verdict for $branch is blocked (see $verdict). Fix the blocking findings and re-run /post-change."
  fi
fi
if [ -n "$reasons" ]; then
  printf '%s\n' "Not done yet:$reasons" >&2
  exit 2
fi
exit 0
