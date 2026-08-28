# UAT — prelive -> main — 2026-08-28 — Kit v4.5 UAT Hub wiring (+ worklog v1.17)

**Branch:** prelive  **Environment:** local machine with Python 3.8+, git and the kit checkout  **Prepared by:** Claude Code  **Status:** awaiting sign-off

## What changed

Kit v4.5 wires every repo the kit touches to UAT Hub, so a Claude Code session can push UAT test cases to https://testing.teknobugroup.com instead of writing a Markdown file nobody opens. `apply` and `refresh` now write `.mcp.json` registering the `uat-hub` MCP server, merging into any `.mcp.json` the repo already has rather than replacing it. `CLAUDE.md` gains a managed "Writing UAT" block, copied verbatim from the hub's `docs/AGENT_PROMPT.md` because it states a field contract the endpoint enforces. `UAT_HUB_KEY` is documented in `.env.example` with an empty value, and `doctor` reports whether that variable is set — presence only, never the value. The project slug is asked for once (`apply --uat-project <slug>`, question 5 of `/repo-setup`) and remembered in `.teknobu.json`; the hub URL and the path to the uat-hub checkout are constants in the kit. VERSION goes 4.3 -> 4.5 (4.4 is taken by the parked `kit-4.4` branch). Decision recorded in `docs/decisions/0006`.

This PR also carries **worklog v1.17** from a parallel session: agent-hours shown beside elapsed with both named, and a fix so an idle session no longer counts its whole span as activity. Its scenarios are UAT-1.17-1 to UAT-1.17-8 in `docs/UAT_PLAN.md` and are **not** re-listed here.

## Preconditions

- Python 3.8+, git and `sh` on PATH. The kit checkout on `prelive`.
- **Run every case against a throwaway directory, never a client repo.** `apply` writes committed files and creates a branch.
- `apply` installs the kit to `~/.claude/sonelo` if the checkout is newer than the installed copy. To avoid upgrading the machine mid-test, run with `HOME` and `USERPROFILE` pointed at a temp directory (see Test data).
- A UAT Hub project is **not** required. The wiring is inert without one; that is UAT-4.5-12.

## Test data

```sh
# throwaway repo + isolated HOME so the machine's installed kit is not upgraded
export SCRATCH=/tmp/kit-uat-scratch
export HOME=/tmp/kit-uat-home
export USERPROFILE=$HOME
rm -rf "$SCRATCH" "$HOME"; mkdir -p "$SCRATCH" "$HOME"
git init -q "$SCRATCH"
git -C "$SCRATCH" config user.email t@example.com
git -C "$SCRATCH" config user.name Tester
git -C "$SCRATCH" commit -q --allow-empty -m "chore: seed"

# a real-looking key, to prove it is never written to a file
export UAT_HUB_KEY="uath_live_DO_NOT_WRITE_ME_0123456789"

KIT=<path to this checkout>/repo_setup.py
```

| ID | Area | Steps | Expected | Result | Tester | Date |
|----|------|-------|----------|--------|--------|------|
| UAT-4.5-1 | Dry run writes nothing | 1. Run `python "$KIT" apply --repo "$SCRATCH" --dry-run --uat-project fortex-hub`. 2. Run `ls "$SCRATCH/.mcp.json"`. | The command lists `.mcp.json` as `created (uat-hub -> project fortex-hub)` among its planned changes. `ls` reports **No such file or directory** — nothing was written. | | | |
| UAT-4.5-2 | .mcp.json is written with the placeholder | 1. Run `python "$KIT" apply --repo "$SCRATCH" --uat-project fortex-hub`. 2. Open `$SCRATCH/.mcp.json`. | The file contains an `mcpServers` object with a `uat-hub` entry whose `command` is `node`, whose `env.UAT_HUB_URL` is `https://testing.teknobugroup.com`, whose `env.UAT_HUB_PROJECT` is `fortex-hub`, and whose `env.UAT_HUB_KEY` is the six-character-plus placeholder `${UAT_HUB_KEY}` — **not** the value exported above. | | | |
| UAT-4.5-3 | The key is nowhere in the repo | 1. With `UAT_HUB_KEY` still exported, run `grep -rI "uath_" "$SCRATCH"`. 2. Run `grep -rI "DO_NOT_WRITE_ME" "$SCRATCH"`. | Both greps print nothing and exit non-zero. No file the kit created contains the key or any fragment of it. | | | |
| UAT-4.5-4 | CLAUDE.md carries the UAT section | 1. Open `$SCRATCH/CLAUDE.md`. | There is one block bounded by `<!-- sonelo-devkit:uat:start` and `<!-- sonelo-devkit:uat:end -->`. It begins with the heading `## Writing UAT`, names the tool `push_uat_test_cases`, and lists the five case fields `title`, `steps`, `expected_result`, `test_url`, `source_ref`. The project line reads `project:    fortex-hub`. | | | |
| UAT-4.5-5 | The section is a copy, not a paraphrase | 1. Compare the text between `## Writing UAT` and `### How this repo is wired` in `$SCRATCH/CLAUDE.md` against the fenced ```markdown block in `uat-hub/docs/AGENT_PROMPT.md`. | The two are identical line for line, with the single exception that `<project-slug>` has been replaced by `fortex-hub`. | | | |
| UAT-4.5-6 | .env.example documents the key, empty | 1. Open `$SCRATCH/.env.example`. | It contains the line `UAT_HUB_KEY=` with nothing after the equals sign, above it a comment naming UAT Hub and saying the key is not a deploy variable. | | | |
| UAT-4.5-7 | The key is not pushed to hosting | 1. Create `$SCRATCH/.env` containing `VITE_API_URL=x`. 2. Re-run `apply`. 3. Open `$SCRATCH/.env.prelive` (or `.env.staging`, per your configured work branch). | The file lists `VITE_API_URL=` but **does not** contain `UAT_HUB_KEY`. That file is pushed to Vercel as Preview variables; the hub key has no use there. | | | |
| UAT-4.5-8 | A second apply merges, does not duplicate | 1. Note the contents of `$SCRATCH/.mcp.json`. 2. Run `python "$KIT" apply --repo "$SCRATCH"` again, with no `--uat-project` flag. 3. Compare. | The file is byte-identical. It still holds exactly one `uat-hub` entry, still with `fortex-hub` — the slug recorded on the first run is reused, not replaced by the folder name. `CLAUDE.md` still has exactly one `## Writing UAT` heading. | | | |
| UAT-4.5-9 | Another MCP server survives | 1. Replace `$SCRATCH/.mcp.json` with `{ "mcpServers": { "theirs": { "command": "node", "args": ["./tools/theirs.mjs"] } }, "someOtherKey": 1 }`. 2. Run `apply`. 3. Open the file. | `theirs` is present and unchanged, `someOtherKey` is still `1`, and `uat-hub` has been added alongside. The original file is copied into `.claude/.backup/<timestamp>/.mcp.json`. | | | |
| UAT-4.5-10 | An unreadable .mcp.json is not destroyed | 1. Write the text `not json at all {{{` into `$SCRATCH/.mcp.json`. 2. Run `apply`. 3. Open the file. | The command reports `skipped (not a JSON object; add the uat-hub server by hand)` for `.mcp.json`, and the file still contains exactly `not json at all {{{`. Nothing was overwritten. | | | |
| UAT-4.5-11 | doctor reports presence, never the value | 1. Run `python "$KIT" doctor --repo "$SCRATCH"`. 2. Read every line of the output. | One line reads `UAT Hub   https://testing.teknobugroup.com; UAT_HUB_KEY set`. The string `uath_` appears nowhere in the output. A further line names the repo's hub project and says an unknown slug is refused. | | | |
| UAT-4.5-12 | Unset key, and a repo with no hub project | 1. Run `unset UAT_HUB_KEY`. 2. Run `python "$KIT" doctor --repo "$SCRATCH"`. 3. Run `apply` in a fresh throwaway repo with no `--uat-project`. | doctor says `UAT_HUB_KEY not set - export it in your environment` and does not fail. The fresh repo still gets `.mcp.json` and the CLAUDE.md section, with the slug defaulted to the folder name. No command errors. The wiring is inert, not broken. | | | |
| UAT-4.5-13 | refresh delivers the wiring too | 1. In `$SCRATCH`, delete `.mcp.json`. 2. Run `python "$KIT" refresh --repo "$SCRATCH"`. 3. Check the output and the files. | `.mcp.json` is recreated with the `uat-hub` entry and `CLAUDE.md` still carries the UAT section. The closing summary names `.mcp.json` in its "Refreshed" line. | | | |
| UAT-4.5-14 | refresh is still narrow | 1. Before running `refresh`, write recognisable content into `$SCRATCH/.githooks/checks`, `$SCRATCH/.github/workflows/ci.yml`, `$SCRATCH/.env.example` and `$SCRATCH/.claude/rules/design.md`. 2. Run `refresh`. 3. Re-read those four files. | All four are byte-identical to what you wrote. `refresh` adding `.mcp.json` must not have widened what else it touches. | | | |
| UAT-4.5-15 | The slug can be corrected | 1. Run `python "$KIT" apply --repo "$SCRATCH" --uat-project a-different-slug`. 2. Open `.mcp.json`, `CLAUDE.md` and `.teknobu.json`. | All three now say `a-different-slug`. `CLAUDE.md` has exactly one UAT block — the old slug appears nowhere in it. `.teknobu.json` records `"uat_project": "a-different-slug"`. | | | |
| UAT-4.5-16 | check reports the wiring | 1. Run `python "$KIT" check --repo "$SCRATCH"`. 2. Delete `.mcp.json` and run it again. | The first run lists `.mcp.json (uat-hub server)` as `ok`. After deletion it is listed as `missing` and the command exits non-zero. | | | |
| UAT-4.5-17 | Version and docs agree | 1. Run `python "$KIT" doctor` and read the first line. 2. Open `README.md`. | doctor reports `kit v4.5`. The README's first paragraph reads `Kit v4.5 · worklog v1.17`. There is no v4.4 anywhere in the released kit. | | | |

## Sign-off

| Role | Name | Date | Outcome |
|---|---|---|---|
| Tester | | | |
| Accepted by | | | |

## Known gaps at time of writing

- **`code-reviewer` and `security-reviewer` did not run on the kit v4.5 diff.** The session that wrote it was instructed not to launch agents. This is kit code that writes a credential reference into files committed to client repos, so a reviewer pass before merge is the outstanding item, not a formality.
- `.mcp.json` records the uat-hub checkout path as it resolved on the machine that ran the kit (`~/uat-hub/mcp/server.mjs`). On a machine that keeps the checkout elsewhere, that absolute path is wrong and sessions fall back to the HTTP endpoint. The per-repo environment doc says so; UAT does not cover a second machine.
- One `UAT_HUB_KEY` covers every project. See `docs/decisions/0006` — worth deciding before many repos are wired to it.
