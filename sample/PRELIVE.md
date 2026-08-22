<!-- teknobu-kit v1.1 -->
# Prelive setup for app

Branch model: work on **prelive**, which deploys to its own URL and database. **main** is production and only moves by pull request.

```
git checkout prelive                  # day to day
git push -u origin prelive            # first time; CI runs, prelive deploys
gh pr create --base main --head prelive --fill   # when it's ready for production; merge on GitHub
```

What the kit wired automatically: git hooks (commit format, secrets, protected branches, pre-push checks), CI on every push and PR,
Supabase migrations and edge functions deployed per branch, a CLAUDE.md section so Claude Code follows the same rules.

## Left to do by hand (once per repo)

### Database (Supabase)
- [ ] Create a second Supabase project for prelive (same org, name it `<project>-prelive`).
- [ ] Copy the production schema into it once: `supabase db dump --linked -f schema.sql` against production, then apply to prelive. Seed only what you need - no client data.
- [ ] Edge function secrets are per project: set them in the prelive project (Project -> Edge Functions -> Secrets) as well as production.
- [ ] Auth: add the prelive URL to Site URL / Redirect URLs in the prelive project.
- [ ] GitHub secrets: `SUPABASE_ACCESS_TOKEN` (account token), `SUPABASE_PRELIVE_PROJECT_REF`, `SUPABASE_PRELIVE_DB_PASSWORD`, `SUPABASE_PROJECT_REF`, `SUPABASE_DB_PASSWORD`.

### Hosting (Vercel)
- [ ] Fill `.env.prelive` (created next to `.env.example`, git-ignored) with the prelive values: Supabase URL and anon key of the prelive project, API URLs, anything that differs from production.
- [ ] `python ~/.claude/teknobu/repo_setup.py vercel --domain prelive.<your-domain>` - links the project, assigns the domain to the `prelive` branch, checks DNS, pushes `.env.prelive` as Preview variables scoped to `prelive`. Uses your Vercel CLI login or a `VERCEL_TOKEN` (vercel.com/account/tokens).
- [ ] If it reports DNS as misconfigured: add the CNAME it prints at your DNS provider (GoDaddy), then re-run.
- [ ] By hand instead: Settings -> Domains (add domain, Git branch `prelive`); Settings -> Environment Variables (Preview, scoped to `prelive`); production branch stays `main`.

### GitHub
- [ ] `python ~/.claude/teknobu/repo_setup.py protect` (needs the `gh` CLI logged in) - or Settings -> Branches -> add rule for `main`: require a pull request, require the `checks` status, block force pushes and deletions.
- [ ] Actions -> Secrets: see the list at the top of `.github/workflows/deploy-supabase.yml` (Supabase repos only).

### Escape hatches
- `TEKNOBU_SKIP=1 git commit ...` / `TEKNOBU_SKIP=1 git push ...` disables the hooks for one command.
- `TEKNOBU_ALLOW_MAIN=1 git push origin main` allows one direct push (hotfix, first push).
