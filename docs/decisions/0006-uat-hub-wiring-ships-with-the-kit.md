# ADR-0006 — UAT Hub wiring ships with the kit, on one shared key

- Date: 2026-08-28
- Status: Accepted

## Context

UAT Hub (https://testing.teknobugroup.com) tracks UAT across every client project and accepts test
cases pushed from a Claude Code session, through an MCP server or a plain HTTP endpoint. Until now
every repo had to be wired to it by hand: `grep -c mcp repo_setup.py` returned 0, so a session in a
client repo either wrote UAT to a Markdown file nobody picks up, or someone hand-built `.mcp.json`.

Four things have to be true for a push to work, and only one of them varies per repo:

| | Varies? |
|---|---|
| the hub URL | no - one internal deployment |
| the path to the uat-hub checkout | no - `~/uat-hub/mcp/server.mjs` on every Teknobu machine |
| `UAT_HUB_KEY` | no - one key covers every project |
| the project slug | **yes** - fixed by the hub when the project is created, and unchangeable |

## Decision

`apply` and `refresh` wire the repo up: `.mcp.json` registering the `uat-hub` MCP server, a managed
"Writing UAT" block in `CLAUDE.md` copied verbatim from the hub's `docs/AGENT_PROMPT.md`,
`UAT_HUB_KEY` in `.env.example`, and a `doctor` line reporting whether that variable is set.

The hub URL and the server path are constants in the kit, not configuration. Only the slug is asked
for - once, during `/repo-setup` - and it is remembered in `.teknobu.json` as `uat_project`.

The key is written as the literal string `${UAT_HUB_KEY}` and never resolved.

## Alternatives considered

**Configuration for the hub URL and the checkout path.** Rejected: there is one internal hub and no
second deployment to configure for. A knob nobody turns is one more thing to fall out of step, and
the kit already carries several settings that only ever hold their default.

**Deriving the slug from the folder or the GitHub repo name.** Rejected: the hub fixes a slug when
the project is created and it cannot change afterwards, because client repos address projects by it.
A guess would be wrong often enough to be worse than asking. The folder name is still the *default* -
safe, because a push to a slug the hub does not know is refused rather than creating a project, so an
unwired repo is inert rather than broken.

**Writing the key into `.mcp.json` because the kit is internal.** Rejected outright. `.mcp.json` is
committed into client repos, which may be handed over or shared, and one key covers every project -
so a literal in one repo's history would expose push access for the whole estate. This is the one
rule in the feature with an estate-wide blast radius, and `NoLiteralKeyEverWritten` in
`tests/test_repo_setup_uat.py` puts a real key in the environment and greps everything the kit writes.

**Leaving `.mcp.json` to `apply` alone.** Rejected. `refresh` is the recommended verb for taking a
release into an existing repo, and it refreshes the managed `CLAUDE.md` sections - so a refresh-only
repo would be told to use an MCP tool that had never been installed. `refresh` therefore merges the
`uat-hub` entry too. It stays narrow in the way that matters: the merge never touches another server,
and nothing else in its untouched list moves.

## Consequences

- Every repo the kit touches can push UAT with no further work, once its project exists in the hub.
- One key across every repo is a known trade-off, already recorded in the hub's `docs/SCOPE.md`: a
  leak or a rotation touches every project at once. It was accepted at a handful of projects. **The
  kit is what makes this scale, so it is now the thing to watch:** around ten wired repos it is worth
  revisiting. The hub's schema already supports multiple keys, so per-project keys are a change of
  practice rather than a rebuild.
- `.env.example` is now created in every repo, even one with no `.env` to derive keys from - it is
  where the kit documents configuration, and `UAT_HUB_KEY` has to appear there.
- `UAT_HUB_KEY` is deliberately excluded from `.env.<work>`, which is pushed to the hosting provider.
  It is a session variable with no use in a deployed environment; spreading it buys nothing.
- `.mcp.json` records an absolute path resolved on the machine that ran the kit. On a machine that
  keeps the uat-hub checkout somewhere else that path is wrong, and the session falls back to the
  HTTP endpoint. The per-repo environment doc says so.
