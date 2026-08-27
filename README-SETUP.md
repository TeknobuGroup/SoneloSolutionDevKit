# Claude Code change-pipeline starter — setup

Gated pipeline for Claude Code: impact review before edits, then review → changelog →
tests → UAT plan → docs after, enforced by a Stop-hook gate locally and mirrored in CI.

## v1.1 changes (speed, same guarantees)

- **Risk tiers**: docs/copy/styling-only changes take a fast lane (no plan mode or
  impact report; gate + CI still apply). Full pipeline stays mandatory for data,
  auth, contracts, and shared code. See CLAUDE.md.
- **Model routing**: every agent declares the model it runs on, so none of them silently
  inherits the session's Opus. The four scribes (changelog-scribe, docs-maintainer,
  uat-writer, uat-plan-maintainer) run on `model: haiku` — formatting work. design-reviewer,
  test-writer, test-runner and qa-runner run on `model: sonnet` — judgement against a written
  contract. code-reviewer, security-reviewer and impact-analyst declare nothing and inherit the
  session model: they decide whether a change ships and how it is built, so they are the ones
  worth paying for.
- **Parallel tail**: /post-change runs UAT plan + docs updates concurrently after
  tests pass.
- **Batching guidance**: run /post-change once per work block, not per micro-edit.

## Install (15 minutes)

1. Copy everything in this bundle into your repo root (merge with existing files;
   keep your existing CHANGELOG if you have one).
2. Search the repo for `TODO:` and fill in: project name, build/test commands, the
   generated Supabase types path (in `.claude/hooks/stop-gate.sh`, `.github/workflows/
   ci-gates.yml`, `.claude/rules/supabase.md`, `CLAUDE.md`), and source globs in the
   gate script if your layout isn't `src/` + `supabase/`.
3. `chmod +x .claude/hooks/stop-gate.sh` (if the executable bit didn't survive).
4. Update Claude Code (`claude update`) — you want v2.1.203+ for `--effort ultracode`
   and v2.1.219+ for `workflowSizeGuideline` in settings; workflows themselves need
   v2.1.154+.
5. Open the repo in VS Code, start Claude Code, and ask it to read CLAUDE.md and
   confirm the pipeline. Run `/hooks` to verify the Stop gate is registered.
6. Commit. The pipeline now travels with the repo for anyone using Claude Code on it.

## Seed the docs (first session)

Ask Claude: "Read the codebase and draft docs/ARCHITECTURE.md and an initial
docs/STATUS.md; list what you couldn't determine." Review and correct — these files
are the ground truth every future session starts from.

## First pilot change (prove the loop)

1. Pick a small, real change. Create a branch.
2. Enter plan mode. Ask for an impact-analyst report first; save it to
   docs/changes/<branch>/impact-report.md. Approve the plan.
3. Let Claude make the change. Try to finish without a changelog entry — watch the
   Stop gate block it. That's the system working.
4. Run /post-change. Fix anything RED, re-run until green.
5. Push and watch CI run the same gates.

## Same day — afternoon (after the pilot change proves the loop)

1. **Test target first** (the one real dependency): if Docker is installed, run
   `supabase start` and point the test command at the local instance; otherwise use a
   staging Supabase project. Until one exists, temporarily limit test-runner to
   typecheck + build only. NEVER point tests at production.
2. **Coverage audit, small slice first** to gauge cost:
   `ultracode: audit test coverage in <one module>; map critical paths with zero
   tests; propose a prioritised backfill list.` Then widen to the full repo if the
   cost profile looks fine (watch it in /workflows).
3. **Backfill the top 2–3 regression tests** the audit flags — enough that tomorrow's
   gate means something.
4. **Save the pipeline as a workflow**: "use a workflow to run the /post-change
   stages", then press `s` in /workflows to save it as a command.
5. **Push** and confirm CI runs the same gates green.

End-of-day done = gate blocked you once, /post-change ran green, CI green, STATUS.md
reflects reality. Repo-specific agents and docs/modules/ files come later, as
patterns emerge.

## Design notes

- The Stop gate is deliberately CHEAP (changelog + type-drift only) because it fires
  every turn. Full tests run in /post-change and CI, not the gate.
- Hooks fire only on Claude's tool calls. Manual edits in VS Code and other pushes are
  caught by CI — that's why both layers exist.
- Reviewer/analyst agents are read-only on purpose: workflow-spawned subagents
  auto-approve file edits, so tool restriction is the real safety boundary.
- `.env` reads are denied via permissions in .claude/settings.json.
- If a gate misfires on a genuinely trivial change (docs-only etc.), widen the globs
  in stop-gate.sh rather than deleting the gate.
