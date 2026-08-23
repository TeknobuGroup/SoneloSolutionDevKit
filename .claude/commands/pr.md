---
description: Create the pull request for this branch into production - pipeline verdict must be clear, UAT document required, PR body is the UAT document.
---
1. Confirm `.claude/state/<branch>/review.json` exists with `"verdict": "clear"` and `"tests": "green"` from this branch's latest work. If not, run `/post-change` first.
2. Run `uat-writer` if `docs/uat/` has no document for this branch dated today. Commit it: `docs: UAT for <branch>`.
3. Push the branch. Create the PR with `gh pr create --base <production branch> --head <branch> --title "<conventional summary>" --body-file docs/uat/<the document>`. Add the changelog lines under a "## Changes" heading in the body if the PR template asks for them.
4. Report the PR URL, the gates that must pass, and the UAT document path. Never print secrets.
