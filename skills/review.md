---
name: review
version: 0.1
description: Perform day and week reviews from vault evidence rather than memory alone.
commands: [dayreview, wkreview]
reads: ["/output", "/wiki", "/raw"]
writes: ["/output/reviews"]
---

# Review

## Role
Summarize what actually happened and convert it into useful continuity.

## Day Review
Cover:
- Completed
- Changed
- Broken / blocked
- Decisions made
- New ideas captured
- What carries forward
- Files/notes created

Write:
`/output/reviews/YYYY-MM-DD-day-review.md`

## Week Review
Cover:
- Major wins
- Systems advanced
- Projects stalled
- Recurring blockers
- Decisions
- New capabilities
- Important vault growth
- Next week's likely priorities

Write:
`/output/reviews/YYYY-Www-week-review.md`

## Rules
- Use the vault as evidence.
- Do not grade the user.
- Do not add motivational commentary.
- Preserve unfinished creative threads so they can be resumed.
