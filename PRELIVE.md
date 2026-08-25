<!-- sonelo-devkit v4.2 -->
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
- [ ] `python ~/.claude/sonelo/repo_setup.py vercel --domain prelive.<your-domain>` - links the project, assigns the domain to the `prelive` branch, checks DNS, pushes `.env.prelive` as Preview variables scoped to `prelive`. Uses your Vercel CLI login or a `VERCEL_TOKEN` (vercel.com/account/tokens).
- [ ] If it reports DNS as misconfigured: add the CNAME it prints at your DNS provider (GoDaddy), then re-run.
- [ ] By hand instead: Settings -> Domains (add domain, Git branch `prelive`); Settings -> Environment Variables (Preview, scoped to `prelive`); production branch stays `main`.

### GitHub
- [ ] `python ~/.claude/sonelo/repo_setup.py protect` (needs the `gh` CLI logged in) - or Settings -> Branches -> add rule for `main`: require a pull request, require the `checks` status, block force pushes and deletions.
- [ ] Actions -> Secrets: see the list at the top of `.github/workflows/deploy-supabase.yml` (Supabase repos only).

### Escape hatches
- `SONELO_SKIP=1 git commit ...` / `SONELO_SKIP=1 git push ...` disables the hooks for one command.
- `SONELO_ALLOW_MAIN=1 git push origin main` allows one direct push (hotfix, first push).
