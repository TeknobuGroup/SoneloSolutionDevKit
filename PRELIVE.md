<!-- sonelo-devkit v4.6 -->
# Prelive setup for teknobu-kit

Branch model: work on **prelive**, which deploys to its own URL and database. **main** is production and only moves by pull request.

```
git checkout prelive                  # day to day
git push -u origin prelive            # first time; CI runs, prelive deploys
gh pr create --base main --head prelive --fill   # when it's ready for production; merge on GitHub
```

What the kit wired automatically: git hooks (commit format, secrets, protected branches, pre-push checks), CI on every push and PR,
a CLAUDE.md section so Claude Code follows the same rules.

## Left to do by hand (once per repo)

### Hosting (Vercel)
- [ ] Fill `.env.prelive` (created next to `.env.example`, git-ignored) with the prelive values: Supabase URL and anon key of the prelive database, API URLs, anything that differs from production.
- [ ] `python "$HOME/.claude/sonelo/repo_setup.py" vercel --domain prelive.<your-domain>` - links the project, assigns the domain to the `prelive` branch, checks DNS, pushes `.env.prelive` as Preview variables scoped to `prelive`. Uses your Vercel CLI login or a `VERCEL_TOKEN` (vercel.com/account/tokens).
- [ ] If it reports DNS as misconfigured: add the CNAME it prints at your DNS provider (GoDaddy), then re-run.
- [ ] By hand instead: Settings -> Domains (add domain, Git branch `prelive`); Settings -> Environment Variables (Preview, scoped to `prelive`); production branch stays `main`.

### UAT Hub
- [ ] The project must exist at https://testing.teknobugroup.com before anything can be pushed: a push never creates one, so an unknown slug is refused (which is what stops a typo inventing a phantom client). Until then the wiring is inert, not broken.
- [ ] Set `UAT_HUB_KEY` in your environment - not in `.env`, not in `.mcp.json`, which is committed. `repo_setup.py doctor` reports whether it is set, never its value.
- [ ] `.mcp.json` records the slug and the server as `${HOME:-${USERPROFILE}}/uat-hub/mcp/server.mjs` - unresolved, so the committed file names no machine and no username. Do **not** hand-edit that path: `check` and `doctor` report an edited one as missing its wiring, and the next `refresh` rewrites it (that entry names the process Claude Code launches with your `UAT_HUB_KEY` in scope, so it self-heals on purpose). If your checkout lives elsewhere, move it or symlink it; a session with no working server falls back to the HTTP endpoint.

### GitHub
- [ ] `python "$HOME/.claude/sonelo/repo_setup.py" protect` (needs the `gh` CLI logged in) - or Settings -> Branches -> add rule for `main`: require a pull request, require the `checks` status, block force pushes and deletions.
- [ ] Actions -> Secrets: see the list at the top of `.github/workflows/deploy-supabase.yml` (Supabase repos only).

### Escape hatches
- `SONELO_SKIP=1 git commit ...` / `SONELO_SKIP=1 git push ...` disables the hooks for one command.
- `SONELO_ALLOW_MAIN=1 git push origin main` allows one direct push (hotfix, first push).
