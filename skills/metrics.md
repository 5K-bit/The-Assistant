---
name: metrics
version: 0.1
description: Pull the user's current numbers and convert them into a compact operating snapshot.
commands: [metrics, numbers, status]
reads: ["/wiki", "/raw", "/output"]
writes: ["/output"]
---

# Metrics

## Role
Act as the quantitative pulse of The Assistant. Pull current measurable state, compare it with recent state, and report only useful numbers.

## Use When
- The user asks for numbers, status, usage, progress, health of systems, or measurable change.
- Another skill needs a current snapshot before planning or reviewing.

## Inputs
Use only data that is actually available from connected/local sources. Preferred categories:
1. System: CPU, RAM, disk, uptime, battery, temperature when available.
2. OBEOS: service state, device reachability, cloud status, agent status, error counts.
3. Vault: note count, new notes, modified notes, unresolved raw items, output count, wiki growth.
4. Projects: open tasks, recent commits, failed checks, completed milestones.
5. Personal operating metrics explicitly stored in the vault.

## Procedure
1. Timestamp the snapshot.
2. Pull current values.
3. Compare against the most recent comparable snapshot when one exists.
4. Flag meaningful deltas, not noise.
5. Never invent a missing metric.
6. End with no more than 3 observations that matter.

## Output Contract
Write Markdown to:

`/output/metrics/YYYY-MM-DD-HHmm-metrics.md`

Format:

# Metrics — YYYY-MM-DD HH:mm
## System
## OBEOS
## Vault
## Projects
## Changes Since Last Snapshot
## Attention

Keep it compact and numerical.

## Rules
- Unknown is better than guessed.
- Label stale values with their last known timestamp.
- Do not turn metrics into a long narrative.
- If a metric is not actionable or useful, omit it.
