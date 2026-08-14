---
name: plan
version: 0.1
description: Produce the user's top seven executable priorities for today or tomorrow.
commands: [plantoday, plantmrw]
reads: ["/wiki", "/raw", "/output"]
writes: ["/output"]
---

# Plan

## Role
Turn the user's real project state, commitments, blockers, and momentum into an executable Top 7.

## Procedure
1. Read the latest morning brief, project states, recent outputs, schedule, and unfinished work.
2. Preserve current creative momentum. Do not redirect the user into self-improvement advice.
3. Rank work using:
   - deadline
   - dependency
   - blocker removal
   - current momentum
   - value to active systems
4. Prefer finishing or unlocking real work over creating speculative work.
5. Break large items into a next executable action.
6. Cap the list at 7.

## Output Contract
For today:
`/output/plans/YYYY-MM-DD-plan-today.md`

For tomorrow:
`/output/plans/YYYY-MM-DD-plan-tomorrow.md`

Format:
# Plan — YYYY-MM-DD
1. **Task**
   - Why now:
   - Definition of done:
   - First action:

## If Time Remains
- Optional items only.

## Rules
- Do not put vague goals in the Top 7.
- Do not add tasks the user did not imply or authorize.
- Do not turn creative momentum into productivity coaching.
- If an item depends on missing information, name the dependency instead of pretending it is actionable.
