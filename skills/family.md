---
name: family
version: 0.1
description: Help reason about family logistics, parenting-time plans, travel, and schedule constraints from explicit vault facts.
commands: [family, brooklynplan, parentingtime]
reads: ["/wiki/family", "/output/schedule"]
writes: ["/output/family"]
---

# Family

## Role
Support logistics involving the user's daughter and family schedule without making assumptions.

## Procedure
1. Read the current canonical schedule/order notes stored in `/wiki/family`.
2. Verify the relevant date range.
3. Distinguish confirmed parenting time from assumptions or proposals.
4. Combine with work/calendar constraints when available.
5. For travel, identify departure/return windows and conflicts.
6. If a legal interpretation is required, separate logistical reasoning from legal advice.

## Rules
- Never assume who is traveling unless stated.
- Never infer custody rights from an old schedule note when a newer source exists.
- Use exact dates for date-sensitive plans.
- Avoid storing unnecessary sensitive detail.

## Output
`/output/family/YYYY-MM-DD-<topic>.md`
