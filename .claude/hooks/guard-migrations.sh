#!/bin/sh
# sonelo-devkit pipeline: PreToolUse hook on Edit/Write/MultiEdit. Migrations are append-only.
{ [ -n "$SONELO_SKIP_HOOKS" ] || [ -n "$TEKNOBU_SKIP_HOOKS" ]; } && exit 0
input=$(cat)
file=$(printf '%s' "$input" | python -c "import json,sys; d=json.load(sys.stdin); print((d.get('tool_input') or {}).get('file_path') or '')" 2>/dev/null)
case "$file" in
  *supabase/migrations/*|*supabase\\migrations\\*) ;;
  *) exit 0 ;;
esac
if [ -f "$file" ]; then
  echo "Blocked: $file is an existing migration. Migrations are append-only - create a new file under supabase/migrations/ instead. (SONELO_SKIP_HOOKS=1 overrides, say why in the commit.)" >&2
  exit 2
fi
exit 0
