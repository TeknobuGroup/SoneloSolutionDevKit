#!/bin/sh
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
