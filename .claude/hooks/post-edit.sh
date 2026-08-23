#!/bin/sh
# sonelo-devkit pipeline: PostToolUse hook on Edit/Write/MultiEdit.
# Type-checks and lints the edited file's project so errors surface immediately. Exit 2 feeds the output back to Claude.
{ [ -n "$SONELO_SKIP_HOOKS" ] || [ -n "$TEKNOBU_SKIP_HOOKS" ]; } && exit 0
input=$(cat)
file=$(printf '%s' "$input" | python -c "import json,sys; d=json.load(sys.stdin); print((d.get('tool_input') or {}).get('file_path') or '')" 2>/dev/null)
[ -z "$file" ] && exit 0
case "$file" in
  *.ts|*.tsx|*.js|*.jsx|*.mts|*.cts) ;;
  *) exit 0 ;;
esac
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
out=""
if [ -f tsconfig.json ]; then
  tsc_out=$(timeout 90 npx --no-install tsc --noEmit -p tsconfig.json 2>&1 | grep -v '^$' | head -40)
  [ -n "$tsc_out" ] && out="$out
[typecheck]
$tsc_out"
fi
if [ -f eslint.config.js ] || [ -f eslint.config.mjs ] || [ -f eslint.config.ts ] || [ -f .eslintrc.json ] || [ -f .eslintrc.cjs ] || [ -f .eslintrc.js ]; then
  es_out=$(timeout 60 npx --no-install eslint "$file" 2>&1 | grep -v '^$' | head -40)
  [ -n "$es_out" ] && out="$out
[lint]
$es_out"
fi
if [ -n "$out" ]; then
  printf '%s\n' "Fix these before continuing (from the post-edit hook on $file):$out" >&2
  exit 2
fi
exit 0
