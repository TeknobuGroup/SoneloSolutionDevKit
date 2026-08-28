# UAT — prelive -> main — 2026-08-28 — Kit v4.7 fast lane

**Branch:** prelive (from `spike/fast-lane`)  **Environment:** Windows machine with PowerShell, Git Bash, Python 3.8+, git  **Prepared by:** Claude Code  **Status:** awaiting sign-off after a 24-hour soak

## What changed

The risk tiering relieved the cheap parts of a change — plan mode, the impact report — and left the expensive ones in place, so a stylesheet paid almost what a migration paid. Three changes:

1. **`.githooks/checks` lines may name the paths they care about.** `[src/* *.css] npm run test:ui` runs only when the push touches one of them; a line with no prefix always runs. **`ci.yml` now generates its steps from that same file**, prefix stripped, so every line still runs somewhere — that is what makes scoping safe rather than a hole, and it was claimed but untrue when the feature was first written.
2. **`spike/`, `draft/` and `proto/` branches** report outstanding review work instead of blocking the session.
3. **`uat-writer` pushes to UAT Hub** and leaves a record for the PR, resolving a contradiction shipped in v4.5: `CLAUDE.md` said "do NOT write them to a Markdown file", the agent said "you write `docs/uat/…`", and `ci-gates.yml` failed the PR without that file.

**One feature was dropped before release.** Design-only diffs were briefly going to skip `code-reviewer`. Measured against the shipped hook, `useAuth.tsx`, `AuthProvider.tsx`, `supabaseAdmin.tsx` and a `tailwind.config.js` running `child_process.execSync` all classified as design-only. The justification was circular — the reviewer is what catches the design-lane rule being broken. Reverted; `.tsx` is application code.

295 tests green.

## Preconditions

- Windows machine with **both** PowerShell and Git Bash; Python 3.8+, git, `sh`.
- **Run every case against a throwaway directory, never a client repo.**
- Point `HOME`/`USERPROFILE` at a temp directory so `apply` cannot upgrade the machine's installed kit mid-test.

## Test data

```sh
export SCRATCH=/tmp/kit47 HOME=/tmp/kit47home USERPROFILE=/tmp/kit47home
rm -rf "$SCRATCH" "$HOME"; mkdir -p "$SCRATCH" "$HOME"
git init -q -b prelive "$SCRATCH"
git -C "$SCRATCH" config user.email t@example.com
git -C "$SCRATCH" config user.name Tester
KIT=<this checkout>/repo_setup.py
```

For the scoped-check cases, put this in `$SCRATCH/.githooks/checks`:

```
echo ALWAYS
[tests/*] echo SUITE
[src/* *.css] echo UI
```

| ID | Area | Steps | Expected | Result | Tester | Date |
|----|------|-------|----------|--------|--------|------|
| UAT-4.7-1 | Scoping — the point of it | 1. Commit a change to `src/app.css` only. 2. `git push`. | `ALWAYS` and `UI` run; the `SUITE` line is skipped and the skip is **printed**, naming the globs. A silent skip is indistinguishable from a pass, so the notice is the feature. | | | |
| UAT-4.7-2 | **A deep path still matches** | 1. Commit a change to `src/pages/admin/app.css`. 2. Push. | `UI` runs. An interim version matched only what existed one level down, so anything deeper was silently skipped — the deeper the path, the more certain the wrong skip. | | | |
| UAT-4.7-3 | **A deletion still matches** | 1. `git rm src/gone.css`, commit, push. | `UI` runs, even though the path is no longer on disk. | | | |
| UAT-4.7-4 | **An unknown changed set runs everything** | 1. Create a branch the remote has never seen. 2. Push it. | Every line runs, scoped or not. Scoping may only skip work it is *certain* is irrelevant. | | | |
| UAT-4.7-5 | **An existing conditional check is not eaten** | 1. Put `[ -f package.json ] && npm test` in `checks` (a very common line). 2. Push. | It **runs as a command**. It is not parsed as a path filter and skipped — which is what an interim version did, silently, while reporting success. `[[ … ]]` likewise. | | | |
| UAT-4.7-6 | Accented paths | 1. Commit a change to `src/café.css`. 2. Push. | `UI` runs. git quotes non-ASCII paths unless told not to, which previously made them match nothing. | | | |
| UAT-4.7-7 | **CI runs what pre-push runs** | 1. Run `apply`. 2. Open `.github/workflows/ci.yml`. 3. *Then* add `[src/*] npm run test:ui` to `.githooks/checks` and commit — **without** re-running `apply`. | The workflow does not list the individual commands; it has a step that reads `.githooks/checks` and runs each line with the prefix stripped. So the line added in step 3 runs in CI immediately. Baking the list at apply time meant a line added later ran nowhere — skipped locally, absent from CI — until someone re-ran `apply`. | | | |
| UAT-4.7-8 | Spike branch states the debt, once | 1. On `spike/ui`, change a code file, do not run `/post-change`. 2. End the session. 3. End it again. | The **first** stop is blocked and the message reaches the session: it says the work is UNREVIEWED, that nothing downstream recomputes it once committed, and to run `/post-change` on the branch you merge into. The **second** stop is allowed. Simply exiting 0 with the message on stdout did not work — a Stop hook's stdout is transcript-only and its stderr is fed back only on an exit 2, so the disclosure was never actually made. | | | |
| UAT-4.7-9 | A real branch still blocks | 1. Repeat on `prelive` and on `feature/x`. 2. End the session. | Blocked both times. Also check `spikes-not-a-spike` blocks — the match is on the `spike/` prefix, not the word. | | | |
| UAT-4.7-10 | Nothing irreversible is relaxed | 1. On `spike/x`: stage a file containing `sk-ant-` plus 25 characters and commit. 2. `git push origin HEAD:main`. 3. Edit an existing file under `supabase/migrations/`. | All three refused: secret scan, protected-branch push, migrations guard. The spike lane relaxes only the review gate. | | | |
| UAT-4.7-11 | Design work still gets reviewed | 1. `sh .claude/hooks/pipeline-state.sh due` with only `src/a.css` staged. | `code design`. A brief version returned `design` alone; `.tsx` is application code and the reviewer is what catches a design-lane change that is not one. | | | |
| UAT-4.7-12 | Auth naming wakes security | 1. Repeat with `src/hooks/useAuth.tsx`, then `src/components/AuthProvider.tsx`, then `src/author.ts`. | The first two include `security`; `author.ts` does **not** — the trigger must catch React auth naming without matching every word containing "auth". | | | |
| UAT-4.7-13 | UAT reaches the hub | 1. In a repo wired to a hub project, finish a change and run `/pr`. | `uat-writer` pushes the cases to UAT Hub and writes `docs/uat/<branch>-<date>.md` containing a `source_ref` table rather than a second copy of the cases. The CI gate passes. | | | |
| UAT-4.7-14 | …and still works without a hub | 1. Repeat in a repo with no hub project or no `UAT_HUB_KEY`. | It says plainly that the push did not happen and why, and writes the cases into the document in full so the branch still has usable UAT. It does not invent a slug. | | | |
| UAT-4.7-15 | **A multi-ref push does not scope against half a picture** | 1. On a fresh clone, create `spike/x` off `prelive` with a change under `src/`. 2. `git push -u origin prelive spike/x` where the remote has never seen `prelive`, and `prelive` carries a change under `supabase/`. | **Every** line runs, scoped or not. One range that cannot be resolved disables scoping for the whole push. Previously the unresolvable range contributed nothing, the set still looked non-empty, and the migrations suite was skipped with the hook exiting 0. | | | |
| UAT-4.7-16 | **A rename out of a scoped tree still counts** | 1. `git mv src/a.tsx a.tsx` and `git mv supabase/migrations/900.sql archive.sql`. 2. Commit and push. | Both scoped checks run. `git diff --name-only` reports only a rename's destination, so both trees previously looked untouched — reorganising directories is the commonest way those suites actually break. | | | |
| UAT-4.7-17 | **`refresh` carries the release** | 1. On a repo at kit 4.6, run `refresh`. 2. Open `.githooks/pre-push`, `.github/workflows/ci.yml` and `.githooks/checks`. 3. Run `check`. | `pre-push` and `ci.yml` are at 4.7; `.githooks/checks` is **byte-identical** to what you had (it is yours to edit). Previously `refresh` wrote `"kit": "4.7"` into `.teknobu.json` while leaving both files at 4.6 — marked current, running none of the release. See `docs/decisions/0007`. | | | |
| UAT-4.7-18 | …without taking a file you own | 1. Delete the `# sonelo-devkit` header line from `ci.yml`. 2. `refresh`. | The file is untouched and the output says `skipped (exists without kit marker; use --force to replace)`. Per-file ownership by marker, not by scoping, is what protects your work. | | | |

## The 24-hour soak

The defects this release fixed were all **silent skips** — a control that stopped working while the transcript still said success. Review found them; tests did not, because the tests were shallower than the failure. Use is the third check, so before merging:

- [ ] Install from this branch on one machine (`python repo_setup.py install` from the checkout) and work normally for a day.
- [ ] Watch for a `pre-push` that skips something you expected to run — the skip is always printed, so grep your terminal for `skipped, nothing matching`.
- [ ] Confirm a real push you expected to be slow got faster, and that a push touching backend code still ran the suite.
- [ ] Note that installing from a branch puts 4.7 on that machine ahead of release; `repo_setup.py update` will put it back to the released version.

## Sign-off

| Role | Name | Date | Outcome |
|---|---|---|---|
| Tester | | | |
| Accepted by | | | |

## Known at time of writing

- Both reviewers' passes are complete and every finding was acted on. `code-reviewer` returned **two blocking defects** — the partial changed set on a multi-ref push, and renames — each reproduced with a real push, and each invisible to the 23 tests that existed at the time. It pinned its findings to a blob hash because the worktree was being edited while it read; that is the third review this session degraded that way, and the reason async review in a snapshot worktree is STATUS Next-0a.
- **Committing silences the Stop gate**, on any branch, because `pipeline-state.sh` sees only uncommitted work. Pre-existing, not fixed here, and it is why the spike lane's debt evaporates on commit. Recorded as STATUS Next-0b.
- Async review in a snapshot worktree is specified but not built (STATUS Next-0a). It is the reason three reviews were degraded today and one reviewer overwrote this repo's own `.githooks/checks`.
