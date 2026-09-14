# UAT — worklog 1.21 — desktop time marked "not measurable" when ActivityWatch is blind — 2026-09-14

**Branch:** prelive   **Prepared by:** Claude Code   **Status:** awaiting sign-off

## Cases were pushed to UAT Hub

**Project:** teknobu-kit  
**Module:** 08. Worklog — desktop time 'not measurable'  
**Test cases sent:** 12 (10 new + 2 re-test), into round 1  
**Hub read back:** 12 cases in this module, and **135 across 8 modules**, up from 123 before the
push — so all 12 landed and none duplicated.  

Run them top to bottom. Cases 01, 09 and 10 are the ones that prove the rule is not simply
suppressing a week: a measurable day, a quiet day below the two-hour floor, and a slice imported
from another machine must all be left alone.

## What changed

When ActivityWatch could not measure the machine — because it was accessed remotely, ran unattended, or was not running — a day's desk and editor time now reads "not measurable" instead of a small confident number or a blank. The rule applies at read time, so existing days restate themselves on the next render with no re-collection.

A day is marked when Claude Code was active 2+ hours on this machine AND the desktop time is less than 25% of that — a clear contradiction that signals measurement failure. Days below the 2-hour floor are left alone (quiet days stay quiet). A day with a record but no data prints a measured zero and is not marked.

The marking appears across the report, the dashboard (day rows and KPI cards), the morning page, the weekly CSV, and the diary. Where space is tight — the per-project Editor table columns and dashboard day-row figures — it shows as `n/m` with a legend.

## Cases pushed

| source_ref | Title | Area |
|---|---|---|
| worklog-121-measurable-day | A measurable day shows desk and editor time without marking | New behaviour |
| worklog-121-unmeasured-day | A low-desktop day shows 'not measurable' in the weekly report | New behaviour |
| worklog-121-missing-aw-record | A day missing ActivityWatch data shows 'not measurable' | New behaviour |
| worklog-121-editor-table-nm | Editor table in multi-day reports shows 'n/m' for marked days | New behaviour |
| worklog-121-dashboard-nm | Dashboard shows 'n/m' in day rows for marked days | New behaviour |
| worklog-121-morning-nm | Morning page shows 'not measurable' for marked days | New behaviour |
| worklog-121-csv-blank | Weekly CSV shows blank 'editor_minutes' for marked days | New behaviour |
| worklog-121-diary-unmeasured | Diary marks immeasurable days with 'desk_hours_unmeasured' | New behaviour |
| worklog-121-quiet-day | Quiet days below 2-hour threshold remain unmarked | Boundary condition |
| worklog-121-imported-slice | Imported slices don't suppress the local machine's desktop data | Machine scoping |
| worklog-118-split-with-unmeasured | 11. Re-test: a session split across midnight still splits correctly beside a marked day | Existing feature |
| worklog-120-corrupted-aw-field | 12. Re-test: a corrupted machine slice still renders, and marked days still say 'not measurable' | Robustness |

## Not covered here

- The Unlocked column (same disease, deliberately left for a separate change)
- The Projects card and At-a-glance grid per-project editor columns (suppression exists, per-project note does not; addressed in a following change to those cards)
- The dashboard Weeks chart reading blank `editor_minutes` cells as zero (a separate existing bug)
- Weekly CSVs archived outside the 28-day window (nothing re-renders them; numbers there are stale by design)
- The `morning.html` design token layer (untouched in this release)

## Sign-off

Results are recorded in UAT Hub against this round, not in this file.
