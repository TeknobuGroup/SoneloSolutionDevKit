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
- One key across every repo is **settled**, not an open trade-off: the hub's
  [ADR-0004](../../../uat-hub/docs/decisions/0004-shared-push-key.md) put the question again at ten
  projects - precisely because this kit was about to make the choice permanent by repetition - and
  confirmed it. So the kit wires every repo to the same `UAT_HUB_KEY` without asking. That ADR also
  lists what keeps the blast radius bounded (create-only endpoint, unknown slugs refused, key stored
  only as a sha256, and the `${UAT_HUB_KEY}` placeholder in every file the kit writes). Those are
  load-bearing: the kit must not weaken any of them without reopening that decision.
- `.env.example` is now created in every repo, even one with no `.env` to derive keys from - it is
  where the kit documents configuration, and `UAT_HUB_KEY` has to appear there.
- `UAT_HUB_KEY` is deliberately excluded from `.env.<work>`, which is pushed to the hosting provider.
  It is a session variable with no use in a deployed environment; spreading it buys nothing.
- `.mcp.json` names the server as `${HOME:-${USERPROFILE}}/uat-hub/mcp/server.mjs`, so the committed
  file names no developer's home directory. **`HOME` alone is wrong**: it is not a Windows
  environment variable - absent from both User and Machine scope, set only per process by Git Bash -
  so a `${HOME}`-only form fails on the kit's stated first-class platform, and a `claude mcp list`
  check run from a Git-Bash-derived shell cannot detect that. `USERPROFILE` is always set by Windows;
  `HOME` is always set on mac and Linux. What is verified: `claude mcp list` reports an unset bare
  `${VAR}` and accepts the `:-` default form, nested included. What is **not** verified: that the
  path resolves. If it does not, the server does not start and the session uses the HTTP endpoint,
  which is the same outcome as any wrong path.
