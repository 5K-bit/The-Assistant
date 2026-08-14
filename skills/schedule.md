---
name: schedule
version: 0.1
description: Convert calendar commitments and project timing into an accurate daily timeline.
commands: [schedule, today, tomorrow, availability]
reads: ["/wiki", "/output"]
writes: ["/output/schedule"]
---

# Schedule

## Role
Provide time-aware operating context.

## Procedure
1. Use the current local date and time.
2. Pull calendar data when connected.
3. Merge only vault commitments that have explicit dates/times.
4. Identify conflicts and real free windows.
5. Preserve timezone.
6. Never invent event times.

## Output
`/output/schedule/YYYY-MM-DD.md`

Format:
# Schedule — YYYY-MM-DD
## Fixed
## Flexible
## Deadlines
## Open Windows
## Conflicts

## Rules
- Distinguish fixed appointments from intended work.
- Do not silently move commitments.
