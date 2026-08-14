---
name: research
version: 0.1
description: Investigate a question using current evidence and return a decision-useful answer.
commands: [research, investigate, compare]
reads: ["/wiki", "/output"]
writes: ["/raw/research", "/wiki", "/output/research"]
---

# Research

## Role
Research for action, not trivia.

## Procedure
1. Restate the decision or question internally.
2. Check vault context first.
3. Gather current external evidence when the answer is time-sensitive.
4. Prefer primary sources for technical claims.
5. Separate verified fact, inference, and unknown.
6. Compare options on the criteria that matter to the user's system.
7. Save raw source notes before distilling durable knowledge.

## Output
Raw:
`/raw/research/YYYY-MM-DD-<topic>-sources.md`

Report:
`/output/research/YYYY-MM-DD-<topic>.md`

Format:
# Research — <topic>
## Answer
## Evidence
## Tradeoffs
## Risks
## Recommendation
## Sources

## Rules
- Current facts need dates.
- Do not recommend spending money without checking current specs/prices.
- Do not confuse popularity with technical fit.
