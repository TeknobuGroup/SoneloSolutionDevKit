# ADR-0010 — A Lovable migration is a clean break, and the kit proves it

- Date: 2026-09-05
- Status: Accepted

## Context

The kit has detected Lovable projects since v3 and written a `MIGRATION.md` for them. That checklist
started at "create the Supabase databases" and assumed everything before and after it was obvious. Two
things in the surrounding kit then pointed the other way:

- `/repo-setup` question 3 reads "Supabase: already has a production project [yes for an existing app] -
  then create only the {WORK} database; or create both." A Lovable app **is** an existing app with a
  production project, so the default answer is yes, and the honest-looking consequence is `--only prelive`:
  a new prelive database, and production left on Lovable Cloud permanently.
- Lovable's generated `src/integrations/supabase/client.ts` **hardcodes** the project URL and publishable
  key. Env files do not control it. A repo can be moved to a new GitHub org, given new Supabase projects,
  deployed on Vercel, and still read Lovable Cloud on every request — and nothing fails, so nobody looks.

That is the failure this ADR exists for: not a migration that breaks, a migration that appears to have
happened. It surfaces when the Lovable project lapses or is deleted, which is exactly when nobody
remembers what it was still doing.

Two further gaps came from the same assumption that only the database matters. A Lovable app arrives wired
to whatever the builder connected — an AI gateway, webhooks, a payment provider, analytics — and nobody had
written down the list, so "is this still needed?" was never asked of anything. And Lovable's `index.html`,
favicon set, Open Graph image and `package.json` name survive a migration untouched; they are the most
visible thing left behind, they follow the app into search results and every shared link, and no test,
type check or build can see them.

## Decision

A Lovable migration means: **a new GitHub repo, a new Supabase project, a new Vercel project, and nothing
of Lovable's kept.** Lovable Cloud's database is a thing to copy from once, never the database to run on.

The kit enforces it three ways:

1. `MIGRATION.md` is rewritten around the three sweeps — new instances, connections, branding/SEO — and
   states the rule before the steps, including the by-hand dashboard route (region, generated password to a
   password manager, and only the **project ref** coming back into a session — never the database password
   or the service_role key).
2. `repo_setup.py lovable` sweeps the tree and reports what still ties it to Lovable, every external host
   the code talks to (named where we can, marked **unrecognised** where we cannot — never dropped), and the
   SEO and branding artefacts to rewrite. `--strict` exits non-zero while anything is left, so a cutover can
   be gated rather than declared.
3. `/repo-setup` question 3 now says the production project must be **yours**, and that a Lovable migration
   always creates both.

## Alternatives considered

- **Leave it as prose in `MIGRATION.md` and trust the reader.** Rejected: the checklist was already prose
  and the contradicting default was two files away, in the prompt an agent actually follows.
- **Make `supabase --create` refuse `--only` on a Lovable repo.** Rejected: the detection is a grep over
  package.json and env files, and a command that refuses a legitimate flag on a false positive gets worked
  around with `--force` habits. Guidance where the decision is made, plus a gate that reports, is the
  reversible version.
- **Only check for Lovable's own hosts.** Rejected: it answers "have we left Lovable?" and not "what is
  this app connected to?", which is the question that decides what a migration costs. An unrecognised host
  is now reported as unrecognised; "not in our list" and "safe to keep" are different statements, and only
  a person may make the second.
- **Block on anything the sweep cannot judge (a favicon, an og:image on an unfamiliar domain).** Rejected:
  a gate nobody can pass gets switched off. Findings carry their own severity, and only what is provably
  Lovable's blocks.

## Consequences

- The generated `MIGRATION.md` is longer and is regenerated with live findings each time `apply` runs on a
  Lovable repo — a repo that has taken it over (marker removed) keeps its own, as before.
- `apply` now walks the tree on Lovable repos. `os.walk` with pruned directories and a 512 KB per-file cap
  keeps it bounded; `node_modules` and build output are never descended into (pinned by test).
- The sweep reads `.env` files, so it carries a standing constraint: **key names only, never values.** The
  single exception is a Supabase project ref, which is public and appears in the dashboard URL. Two tests
  assert no env value reaches the command output or the generated document.
- `--strict` fails closed on a file it cannot read (UTF-16 is routine on Windows), because a gate that
  silently skips what it cannot parse reports "clean" for a repo it never swept.
- The command and the generated checklist share one `connection_origin()`. They were written apart
  and disagreed - the checklist said "Lovable Cloud - the database to copy FROM" for a project the
  command listed as plain "Supabase" - and the command is the thing a person runs. Anything either of
  them says about whose account a host belongs to now has one implementation.
- We commit to keeping the service table current. It only *names* hosts, so a stale table degrades to
  "unrecognised — identify it" rather than to silence.
