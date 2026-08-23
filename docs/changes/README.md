Each branch gets a folder: docs/changes/<branch>/
Contents: impact-report.md (from impact-analyst, saved BEFORE editing) and, optionally,
the approved plan. This is the pipeline's state-on-disk: any fresh session can resume
a change mid-flight by reading this folder plus STATUS.md.
