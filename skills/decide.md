---
name: decide
version: 0.1
description: Compare real options, expose tradeoffs, and record a durable decision.
commands: [decide, choose, compareoptions]
reads: ["/wiki", "/output/research"]
writes: ["/wiki/decisions", "/output"]
---

# Decide

## Role
Make architecture and product decisions explicit.

## Procedure
1. Define the decision.
2. Identify hard constraints.
3. Compare viable options.
4. Reject options that violate constraints.
5. Evaluate:
   - reliability
   - complexity
   - interoperability
   - cost
   - security
   - maintenance
   - reversibility
6. Recommend one path when evidence supports it.
7. Record what would cause the decision to be revisited.

## Output
Canonical:
`/wiki/decisions/YYYY-MM-DD-<decision>.md`

Format:
# Decision
## Context
## Constraints
## Options
## Decision
## Why
## Rejected
## Risks
## Revisit When
