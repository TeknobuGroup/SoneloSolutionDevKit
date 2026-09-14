# ADR-0014 — a desk figure nothing could measure is not printed as one

- Date: 2026-09-14
- Status: Accepted

## Context

Phill reported "the at desk time is not correct" against the W37 dashboard, which showed
13h 02m / 1h 03m / 32m / 1h 53m / 12m / – / 9m at the desk for Monday 7 to Sunday 13
September — a week he had worked through. He then said he "did remote in a lot as well as
cloud", which is the cause.

**ActivityWatch cannot measure a remote session.** All three of its inputs fail, and each
fails silently:

- `aw-watcher-afk` counts **local** input. Over Chrome Remote Desktop there is none, so it
  reports `afk` for the whole day.
- The window watcher polls the foreground window of a **disconnected console session** and
  freezes on whatever was there. 13 September logged 8 window events, one of them claiming
  13.5 hours of `Code.exe`; 12 September logged a single event claiming 24 hours.
- The Win32 lock/unlock scheduled tasks stop firing entirely. The last presence event is
  `2026-09-09T06:17:37 logon`, and nothing through Sunday — while `LockApp.exe` was the
  foreground window for ten hours in that period.

`remoting_desktop.exe` appears in the window bucket on 6, 7, 9, 10, 11 and 13 September.

Not one of the three watchers reports being blind. Each reports a small number, confidently.
**A confident wrong small number is worse than no number**, because a blank cell already
means zero and a reader cannot tell the two apart. It is also structural: it will recur on
every remote day, and last week's figures are not recoverable — the raw data is wrong at
source, not mis-rendered.

There is an independent witness on the same machine. Claude Code writes its own session
bursts locally, by the session process, **however the user is connected** — remote desktop,
cloud or at the keyboard. Measured across the 28-day window in this machine's pot:

| day | desk shown | Claude active | ratio |
|---|---:|---:|---:|
| Mon 7 Sept | 13h 02m | 11h 23m | 1.15 |
| Tue 8 Sept | 1h 03m | 15h 08m | **0.07** |
| Wed 9 Sept | 32m | 16h 17m | **0.03** |
| Thu 10 Sept | 1h 53m | 12h 25m | **0.15** |
| Fri 11 Sept | 12m | 8h 32m | **0.02** |
| Sat 12 Sept | – | 4h 33m | **0.00** |
| Sun 13 Sept | 9m | 5h 48m | **0.02** |

## Decision

**A day's desk and editor figures read "not measurable" when Claude Code was active on this
machine for at least two hours that day and the desk figure is under a quarter of that.**

The rule is applied at `load_slices()` — the one choke point every consumer of the pot comes
through — for the reason ADR-0013 settled for commit dedupe: the report, the weekly CSVs, the
dashboard payload, the morning page and the diary otherwise need five copies of it, one of
them written in JavaScript.

Eight decisions inside that one:

**Calibrated, not guessed.** Over the whole 28-day window: 9 days flagged (ratios 0.00–0.15),
18 kept (0.34–1.15). The gap between the highest flagged day and the lowest kept day carrying
real evidence is wide, and 0.25 sits almost exactly in its middle — √(0.15 × 0.41) = 0.248.
The two-hour floor keeps quiet days out: 21 August sits at 0.20 on only 1h 41m of Claude
time, far too little to call anything a contradiction.

**"Claude active" is the union of session bursts**, concurrent sessions counted once — not
`active_min`, which `session_day_minutes()` documents as adding one idle cap per gap and
which therefore runs materially above a union and would fire the two-hour gate at the wrong
time. That union already existed twice: as a closure inside `build_report` and again in the
dashboard's JavaScript. It is now `day_active_union()`, and `build_report`'s closure is a
one-line wrapper over it.

**Marked, never nulled and never deleted.** The record gains `"unmeasured": true` and keeps
its numbers. `rec["desk_s"]` is *indexed* rather than fetched in two readers, `fmt_dur(None)`
raises, `null / 60` is `0` in JavaScript — which would reprint the exact confident-wrong-
small-number bug on the other side — and deleting the day would turn `have_aw` off and take
the columns away from the measurable days as well.

**A day with no record at all is created and marked**, with no invented numbers, on a machine
that does record desk time. 17, 18 and 19 August carry 6–13 hours of Claude Code each from
before ActivityWatch was installed, and Saturday 12 September has no record either: all four
render an empty cell today, and an empty cell says the machine measured no desk time. It
measured nothing. A machine that has never run ActivityWatch is a different statement — it
has no `aw` days, `have_aw` stays false, and the report already says "ActivityWatch: no data"
— so it gains nothing here.

**The witness is the machine being judged, not the pot.** The kit's own guidance is to import
another machine's repo slices and never its machine slice, so a pot routinely holds sessions
that ran elsewhere — this one holds 20 slices from `DESKTOP-R3M7664` and one from
`PhillLappie2`. Judging this machine's desk record against a union that includes the laptop's
bursts would suppress real measured data on the strength of a file this machine did not
write: the same fault as the bug, pointed the other way. `day_active_union()` is therefore
computed per machine name, cached, over the slices that name that machine — plus those that
name none, because the name was not always recorded and an unnamed slice is evidence about
whichever machine is being judged rather than about none.

**The creation half is bounded to a year.** It is sized by timestamps read out of a slice
file, and `clean_session()` does not range-check a burst: one pair spanning 2020–2035 would
fabricate 5,480 day records, every one of which reaches `dashboard.html` as a single string
built in memory by an unattended hook. A year is past any window the report is ever asked
for, and future-dated days are never created at all.

**The printed reason names every cause that fits, and no more.** Three do: the day was worked
remotely, ActivityWatch was not running, or the session ran unattended with nobody at the
machine. In the third the watchers were not blind — they measured an empty chair — so a
sentence naming only the first two would state a cause with more confidence than the rule has.
The sentence is one Python constant, substituted into the dashboard's JavaScript at import; it
had already been written by hand four times and the fourth copy had drifted.

**Read time, not collect time.** `collect_machine()` sets `refresh_from` to yesterday and
`docs/UAT_PLAN.md` records that nothing rebuilds a machine slice's history, so a rule applied
where the days are written would never restate the week that prompted it. Applied on read,
the nine days correct themselves on the next render with no recollection.

## Consequences

- Nine of the last 28 days on this machine restate as "not measurable" — 17, 18, 19 August
  and 8, 9, 10, 11, 12, 13 September. Eighteen are untouched. Monday 7 September still reads
  13h 02m, which is the check that the rule is not simply suppressing the remote week.
- The rule catches two different causes with one test — a remote session, and the watchers
  not being installed yet — which is evidence it is not overfitted to the case that prompted
  it.
- **KPI totals exclude marked days and say how many.** A week with six of seven days marked
  must not present one day's desk time as the week's total.
- The per-title `editor` map is suppressed with `editor_s`. Three of the five editor readers
  go through the map rather than the scalar, so suppressing only the scalar would leave the
  Editor table, the CSV column, the dashboard grid and the Weeks chart still printing it.
- **Where the words do not fit, the mark is `n/m` and a legend says what it means** — the
  Editor table's narrow per-project columns and the dashboard's day-row figures. A blank in
  those cells already means *under a minute for this project*, so a blind day cannot borrow
  it without telling the same lie in a different sentence.
- A day record filed under a non-canonical key — `2026-9-8` rather than `2026-09-08` — is
  re-filed where every reader looks it up, never over a canonical record that already stands.
  Before this it was invisible to all five readers *and* counted as a record that already
  existed, which silently cancelled the marking for that day.
- Slices written by kit copies on other machines carry no flag, so every read of it is a
  `.get()`.
- **A record with nothing in it is a measured zero, not a mark.** `clean_machine()` guarantees
  a dict and nothing about the keys in it; `{}` is falsy in Python and truthy in JavaScript, and
  a `bool(rec)` test split the two halves of the rule apart on exactly that — the report named
  such a day in the Editor table's footnote while no cell anywhere, and no figure on the
  dashboard, carried the mark the footnote was explaining.
- `diary_agent.VERSION` goes to 1.1 **and `is_stale()` now compares the stamp**, which is what
  makes an already-written day-file rebuild under the new rule instead of being served as it
  stands. The stamp was already written into every day-file and nothing read it back; the other
  staleness tests are mtimes against the notes and the slices, so on a pot nobody has written to
  since, a 1.0 day-file would have kept its `desk_hours` for good.
- **A record that exists and is empty now prints a measured zero rather than a blank**, on the
  Days table's At desk and Editor columns and on the dashboard's day rows. That distinction is
  the point of the release, and the Editor column had been left one hunk behind the At desk
  column beside it: an editor genuinely shut all day rendered the same blank as a day the
  watchers never ran. A missing record is still blank, and on the dashboard still a dash.

## What this does not fix

- **The rule cannot say which of the three causes applied**, and the sentence it prints does not
  pretend to. The obvious second witness is presence, and it is not usable as one: the
  lock/unlock events stop firing on a remote day, and `presence_days()` caps an unclosed span at
  16 hours out of an invented end time — 8 September renders `00:00–09:34 (9h 35m)` and
  9 September `06:17–22:17 (16h)`. Reading a long unlocked span as "the user was here" would
  un-mark two of the very days that prompted the change. It becomes a usable witness only after
  the Unlocked column below is fixed.

- **The Unlocked column has the same disease and is deliberately left alone** — Phill's
  decision, so that this change stays one thing. W37 prints `06:17–22:17 (16h)` for Wednesday
  9 and `17:34–00:00` / `00:00–09:34` for Monday 7 into Tuesday 8: the 16-hour presence cap
  firing three times with invented end times. That is the next change, alongside the already
  queued per-machine `presence_days()` bug.
- **The dashboard's Projects card and At-a-glance grid drop a marked day's editor minutes with
  no note.** The suppression itself is right - `editorFor()` returns 0 for a marked record - but
  the per-project editor column and the grid cells then read low with nothing saying why, where
  the KPI card totalling the same minutes carries "N days excluded, not measurable" and the
  report's per-project Editor cells print `n/m`. A per-project cell has no room for the words
  and `n/m` in a coloured grid cell would read as data; it wants the card-level note the KPIs
  got, which is a change to that card rather than to this rule.
- **The per-row explanation on the dashboard is a `title` tooltip**, so it is mouse-only. The
  same sentence is always visible as static text once per range, in the Days note and the KPI
  subtitles, so nothing is unreachable - but the row itself is not the thing carrying it.
- **`morning.html` has no design-token layer at all** - raw hex, a system font stack, 10-12px
  radii - where `dashboard.html` has a `:root` custom-property layer. It predates this change
  and is untouched by it.
- **`read_weekly_csvs()`** does `int(float(r.get(col) or 0))`, so the new blank
  `editor_minutes` cell reads back as `0` and the dashboard's Weeks chart plots a suppressed
  week as a *measured* zero. Wrong in the same direction the chart is wrong today, and not
  made worse by this change.
- **Archived weekly CSVs for weeks outside the 28-day window keep their old numbers.**
  Nothing rewrites them, as 1.20 disclosed for commit counts.
- **`render()` wraps `write_dashboard` and `build_morning` in a bare `except Exception` that
  only logs**, so a break on either path leaves `cmd_render` printing "rendered …" with the
  suite green. This is the single biggest way a regression here would go unnoticed, and it is
  a CLAUDE.md violation in its own right ("a silent catch is a bug"). It is answered here
  only by the tests asserting on both functions **directly** rather than through `render()`;
  fixing the catch is a separate change.
