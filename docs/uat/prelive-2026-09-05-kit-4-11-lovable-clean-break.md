# UAT — kit 4.11 — a Lovable migration is a clean break — 2026-09-05

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were NOT pushed to UAT Hub

`repo_setup.py doctor` reports `UAT_HUB_KEY not set` on this machine, and the `uat-hub` MCP
server failed to connect this session (CONNECTION_CLOSED). The cases below are written out in
full here instead and **must be pushed to UAT Hub before a tester picks them up** — nothing is
lost, but nothing is queued for a tester either. This is the third release in a row in that
position: the 28 cases in `prelive-2026-09-03-kit-4-9-worklog-1-19.md` and the 14 in
`prelive-2026-09-03-kit-4-10-post-edit-hook.md` have not reached the hub either.

---

## What changed

The kit's provisioning code was already right — `github`, `supabase --create` and `vercel
--create` all create new instances. The guidance beside it was not.

`/repo-setup` question 3 read "Supabase: already has a production project [yes for an existing
app] — then create only the {WORK} database". A Lovable app **is** an existing app with a
production project, so the honest answer was yes, and the result was `--only prelive`: a new
prelive database, and production left on Lovable Cloud permanently.

That outcome has no symptom. Lovable's generated `src/integrations/supabase/client.ts`
**hardcodes** the project URL and publishable key, so env files do not decide which database the
app reads. A repo can be moved to a new GitHub org, given new Supabase projects and deployed on
Vercel, and still read Lovable Cloud on every request — with nothing failing. It surfaces when
the Lovable project lapses, which is when nobody remembers what it was still doing.

Two further gaps came from assuming only the database matters: nobody had written down what a
Lovable app is *connected* to (AI gateway, webhooks, payments, analytics), so "is this still
needed?" was asked of nothing; and Lovable's title, description, Open Graph image, favicons and
`package.json` name survive a migration untouched, which no test, type check or build can see.

Kit 4.11:

- **New `repo_setup.py lovable [--strict]`** — sweeps the tree and reports what still ties it to
  Lovable, every external host the code talks to, and the SEO/branding artefacts to rewrite.
  `--strict` exits 1 while anything is left, so a cutover is gated rather than declared.
- **`MIGRATION.md` rewritten** around three sweeps (instances → connections → branding), opening
  with the rule it exists to enforce, filled with that repo's own findings.
- **Question 3 corrected** — the production project must be **yours**, and a Lovable migration
  always creates both.

Security constraint held throughout: the sweep reads `.env` files for key **names** only. The
one value it ever reports is the Supabase project ref, which is public and appears in the
dashboard URL.

Decision recorded in `docs/decisions/0010-a-lovable-migration-is-a-clean-break.md`.

## Preconditions

- Windows, Python 3, this branch checked out. No npm, no network, no Supabase or Vercel account
  needed — every case below is local and read-only against the filesystem.
- Cases 02 onwards need a **fake Lovable repo** built in case 01. Do not point any of these at a
  real client repo: case 12 requires you to leave a stale hardcoded key in place.
- `python repo_setup.py lovable` is run from a repo root, or with `--repo <path>` from anywhere.
  Read the exit code with `echo $?` after each run — `0` and `1` are both correct answers
  depending on the case, and the exit code is half of what is being tested.

---

## 01. Build the fake Lovable repo the later cases use

**Steps.** In an empty folder run `git init`, then create these files:

- `package.json` containing `{"name":"vite_react_shadcn_ts","devDependencies":{"lovable-tagger":"^1.1.0"}}`
- `index.html` with `<title>Lovable Generated Project</title>`, a
  `<meta property="og:image" content="https://lovable.dev/opengraph-image-p98pqg.png" />`, a
  `<meta name="twitter:site" content="@lovable_dev" />` and a
  `<script src="https://cdn.gpteng.co/gptengineer.js"></script>`
- `src/integrations/supabase/client.ts` that calls `createClient` with the literal string
  `"https://pxqckcvyymppsrulnebb.supabase.co"` and a literal key
- `src/lib/pay.ts` containing the string `https://api.stripe.com/v1/charges`
- `src/lib/hook.ts` containing the string `https://hooks.zapier.com/hooks/catch/1/abc`
- `src/lib/odd.ts` containing the string `https://telemetry.some-vendor-nobody-knows.io/v1`
- `.env` containing `VITE_SUPABASE_PUBLISHABLE_KEY=...` and
  `VITE_SUPABASE_URL=https://pxqckcvyymppsrulnebb.supabase.co`
- `public/placeholder.svg` (any content)

**Expected result.** The folder exists with all nine files. Call it **Lovable Repo** — every
case from 02 to 15 uses it. Nothing is run yet.

## 02. The sweep names what still ties the repo to Lovable

**Steps.** From the kit repo run
`python repo_setup.py lovable --repo <path to Lovable Repo>` and read the output.

**Expected result.** The output has a section listing Lovable traces, and it names at least the
`cdn.gpteng.co` script in `index.html`, `lovable-tagger` in `package.json`, the package name
`vite_react_shadcn_ts`, and `VITE_SUPABASE_PUBLISHABLE_KEY` in `.env`. Each one is shown with
the file it was found in.

## 03. Every external connection is listed, not just Lovable's

**Steps.** In the same output, find the connections section.

**Expected result.** All four external hosts appear: `api.stripe.com`, `hooks.zapier.com`,
`telemetry.some-vendor-nobody-knows.io` and the Supabase host. Stripe and Zapier are named as
the services they are. Nothing is omitted for being unfamiliar. Above the list is one line saying
that an unannotated row means "confirm whose account this is" — that is the default answer, said
once rather than repeated under every row where it stops being read.

## 04. A host the kit does not recognise says so, rather than being dropped

**Steps.** In the connections list from case 03, read the line for
`telemetry.some-vendor-nobody-knows.io`.

**Expected result.** It is marked **unrecognised** and asks for it to be identified. It is not
absent, and it is not labelled safe, kept, or third-party-analytics by guess.

## 05. The Supabase project is reported as Lovable's, not as yours

**Steps.** In the connections list, read the line for the `*.supabase.co` host — noting that its
project ref is also sitting in the repo's own `.env`.

**Expected result.** The row beneath it reads `-> Lovable Cloud - the database to copy FROM`. It
must not be described as yours, and the service column reading `Supabase` on its own is a fail —
that is what it said before this release and it is exactly the misreading the release removes.
(The ref being in `.env` proves nothing before cutover: those env files are Lovable's too.) Open
the `MIGRATION.md` from case 10 afterwards and confirm its table says the same words.

## 06. The SEO and branding to rewrite is listed with the files

**Steps.** In the same output, find the branding/SEO section.

**Expected result.** It names at least: the `Lovable Generated Project` title, the **meta
description** left at that same default, the `lovable.dev` Open Graph image, the `@lovable_dev`
twitter:site, the `vite_react_shadcn_ts` package name and `public/placeholder.svg`. Each is shown
with the file it is in, and each is marked as blocking (leading `!`).

## 07. The gate fails while anything is left

**Steps.** Run `python repo_setup.py lovable --repo <Lovable Repo> --strict`, then `echo $?`.

**Expected result.** Exit code `1`. The output states how many things are blocking, and each
blocker is something a person could go and fix. A count of `0` blockers with exit code 1 is a
fail.

## 08. No environment value is printed, ever

**Steps.** Edit Lovable Repo's `.env` and give every variable an obviously recognisable value —
for example `VITE_SUPABASE_PUBLISHABLE_KEY=THIS_IS_THE_SECRET_VALUE`. Run <!-- sonelo:allow -->
`python repo_setup.py lovable --repo <Lovable Repo>` and search the entire output for
`THIS_IS_THE_SECRET_VALUE`.

**Expected result.** It does not appear anywhere in the output. Variable *names* may appear; the
one and only value permitted anywhere in the output is the Supabase project ref
(`pxqckcvyymppsrulnebb`), which is public. Finding any other env value is a **blocker, not a
finding** — stop and report it.

## 09. A password embedded in a URL is dropped before the host is reported

**Steps.** In Lovable Repo, add a file `src/lib/legacy.ts` containing the string
`https://admin:hunter2@legacy.example.com/api`. Run the sweep again and read the connections
list.

**Expected result.** `legacy.example.com` is listed as a connection. The strings `admin` and
`hunter2` appear nowhere in the output.

## 10. `MIGRATION.md` is written with this repo's actual findings

**Steps.** From the kit repo run `python repo_setup.py apply --repo <path to Lovable Repo>`,
answering any prompts with the defaults. Then open the `MIGRATION.md` it wrote in Lovable Repo.

**Expected result.** The document contains all three sweep headings — new instances, the
connections sweep, and SEO/branding — and its connections table lists the same hosts you saw in
cases 03 and 04, including the unrecognised one. There are no leftover placeholder tokens in
curly braces anywhere in the file.

## 11. `MIGRATION.md` states the rule before it states the steps, including what may come back

**Steps.** Read the top of that `MIGRATION.md`, above step 1, and then read step 1 itself.

**Expected result.** The opening states that nothing Lovable created is kept and that Lovable
Cloud's database is copied **from**, once. Step 1 covers all three new instances — GitHub,
Supabase, Vercel — and the by-hand Supabase route names the region, says to save the generated
password in a password manager because it cannot be retrieved later, and says the only value
that comes back into a chat session is the **project ref**, never the database password and
never the service_role or secret key.

## 12. A hardcoded database that no env file mentions is a blocker on its own

**Steps.** In Lovable Repo, delete `.env` entirely, leaving
`src/integrations/supabase/client.ts` with its hardcoded `https://pxqckcvyymppsrulnebb.supabase.co`.
Run `python repo_setup.py lovable --repo <Lovable Repo> --strict` and `echo $?`.

**Expected result.** Exit code `1`, and the blockers name the hardcoded Supabase project in
`client.ts`. This is the case the whole release exists for: a repo can look migrated everywhere
else and still read Lovable on every request.

## 13. A repo that hardcodes its OWN ref is reported but not blocked

**Steps.** Restore `.env`, then change every Lovable string in Lovable Repo so nothing of
Lovable's remains: rename the package, rewrite `index.html`'s title, description, og:image and
twitter tags to your own, delete the `cdn.gpteng.co` script tag, remove `lovable-tagger`, delete
`public/placeholder.svg`, and change both the hardcoded ref in `client.ts` and the ref in `.env`
to the same new value. Run `--strict` and `echo $?`.

**Expected result.** Exit code `0`. The hardcoded ref may still be *mentioned* in the report, but
it does not block, because it matches the env files — the repo is hardcoding its own project,
which is allowed.

## 14. A file the sweep cannot read fails the gate rather than being skipped

**Steps.** Starting from the clean repo in case 13, save one source file as **UTF-16** (in
PowerShell: `Set-Content -Encoding Unicode`). Run `--strict` and `echo $?`.

**Expected result.** Exit code `1`, and the output names the file it could not read. It must not
exit `0` — a gate that silently skips what it cannot parse reports "clean" for a repo it never
swept.

## 15. The sweep does not walk `node_modules`

**Steps.** In Lovable Repo create `node_modules/junk/index.js` containing
`https://cdn.gpteng.co/gptengineer.js`. Run the sweep.

**Expected result.** That file is not reported, and the command still returns in a couple of
seconds. (A real `node_modules` is tens of thousands of files; if this is ever swept the command
becomes unusable and the finding is noise.)

## 16. `/repo-setup` no longer recommends keeping Lovable's database

**Steps.** From the kit repo run `python repo_setup.py install` (this rewrites the machine's
slash commands from this version — it does not touch any repo). Then open
`%USERPROFILE%\.claude\commands
epo-setup.md`, read question 3, and search the file for every
occurrence of `--only`.

**Expected result.** Question 3 says the existing production project must be one **of yours**,
and says that on a Lovable migration the answer is always "create both", because the project it
has now is Lovable's and reusing it means the migration never happened. There are exactly two
occurrences of `--only` and **both carry the prohibition on the same line** — question 3 ends
"Never `--only prelive` there", and the run step reads "(never `--only` on a Lovable migration -
see question 3)". A line offering `--only` with the warning only in the sentence after it is a
fail: that is the shape this release exists to remove.

## 17. The kit's own suite passes

**Steps.** In the kit repo run `python -m unittest discover -s tests` and then `echo $?`.

**Expected result.** `OK`, 448 tests, and exit code `0`. Note the exit code specifically — a
green-looking summary with a non-zero exit code is a fail.

---

## Known limitations to check against, not bugs to raise

- **The service table names hosts, it does not judge them.** A host the kit has never heard of
  comes back as "unrecognised — identify it", which is a question for a person, not a finding.
  As the table ages it will degrade towards more unrecognised lines, never towards silence.
- **A favicon does not block.** Bytes cannot say whose mark they are, so favicons are reported
  as "replace, or confirm it is not Lovable's default" and `--strict` passes with them in place.
  `public/placeholder.svg` does block, because that one is provably Lovable's.
- **The sweep reads; it never calls out.** It does not check whether a host is reachable, whether
  an API key still works, or whether a Lovable project still exists. Every keep/replace/drop
  decision is a person's.
- **`--strict` passing is not proof the migration is complete.** It proves nothing in the tree
  still points at Lovable. Copying the data, rotating every key that ever reached git history and
  turning off Lovable's GitHub sync are steps 3 and 5 of the checklist and no gate can see them.
