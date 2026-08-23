---
description: Design-led polish of a screen within the design contract - applies the design-reviewer's polish and consistency findings in the fast lane; leaves anything that blocks or hurts the task for a human.
argument-hint: <screen or component path>
---
Run `design-reviewer` on $ARGUMENTS (or on the screens touched since the last commit if no argument).

Then, in the fast lane and without asking:
- Apply every finding marked **polish** or **inconsistency**: spacing, hierarchy by size/weight/space, empty/loading/error states, reuse of the existing component for the same job, tokens instead of literals, accessible names, focus rings.
- Do not touch data flow, contracts, handlers, or logic. If a finding needs any of those, leave it and list it.
- Do not apply findings marked **blocks the task** or **hurts the task**; list them for the user with the reviewer's wording.

Re-run `design-reviewer` once on the result. Report: what was applied (file:line), what was left and why, and the screens a human should open to see the result. Commit message if asked: `style: design pass on <screen>`.
