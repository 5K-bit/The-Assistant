---
name: experiment
version: 0.1
description: Turn a creative technical idea into a bounded experiment without prematurely changing core architecture.
commands: [experiment, prototype, trythis]
reads: ["/wiki/projects", "/wiki/infra", "/output/research"]
writes: ["/raw/experiments", "/output/experiments"]
---

# Experiment

## Role
Protect creative momentum while keeping experiments contained.

## Procedure
1. State the idea in one sentence.
2. Define the smallest test that can prove or disprove it.
3. Reuse existing hardware/software where practical.
4. Keep the experiment isolated from production systems.
5. Define success and failure before building.
6. Capture observations.
7. End with one of:
   - promote
   - iterate
   - archive

## Output
Raw lab note:
`/raw/experiments/YYYY-MM-DD-<experiment>.md`

Result:
`/output/experiments/YYYY-MM-DD-<experiment>-result.md`

## Rules
- Do not turn every experiment into a permanent subsystem.
- Do not kill an idea because it is unconventional; test it.
- Do not merge experimental code into core systems without an explicit promotion decision.
