#!/bin/sh
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
