---
name: context
version: 0.1
description: Recover just enough prior context to continue a project or conversation accurately.
commands: [context, catchmeup, resume]
reads: ["/wiki", "/output", "/raw"]
writes: ["/output/context"]
---

# Context

## Role
Reconstruct state without flooding the prompt.

## Procedure
1. Identify the active subject.
2. Read the canonical `/wiki` note.
3. Read the newest relevant outputs.
4. Follow only links needed to resolve current references.
5. Produce a compressed working context.
6. Explicitly mark unknown or stale state.

## Output
`/output/context/YYYY-MM-DD-HHmm-<topic>.md`

Format:
# Context — <topic>
## Current State
## Last Confirmed
## Active Constraints
## Recent Decisions
## Open Threads
## Next Likely Action

## Rules
- Smallest sufficient context wins.
- Do not pull the entire vault into the prompt.
- Prefer recent canonical state over scattered old notes.
