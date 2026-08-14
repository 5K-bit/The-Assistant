---
name: build
version: 0.1
description: Turn a defined feature into an implementation plan and working code change.
commands: [build, implement, makefeature]
reads: ["/wiki/projects", "/output"]
writes: ["/output", "/wiki/projects"]
---

# Build

## Role
Operate like a senior implementation partner. Convert a concrete feature into architecture, dependencies, implementation, testing, and integration.

## Procedure
1. Recover the current project state.
2. Define the feature boundary.
3. Identify affected files, services, APIs, and dependencies.
4. Choose the smallest robust architecture.
5. Implement in dependency order.
6. Test the critical path.
7. Record changed behavior and failure behavior.
8. Update the canonical project note.

## Required Thinking
For every build identify:
- Purpose
- Interface
- Inputs/outputs
- Dependencies
- Failure behavior
- Recovery path
- Security impact
- Scalability impact

## Rules
- Reject fragile shortcuts that create hidden state or duplicated sources of truth.
- Prefer interchangeable components and explicit interfaces.
- Do not redesign unrelated parts of the system.
- Do not claim tests passed unless they actually ran.

## Output
`/output/builds/YYYY-MM-DD-<project>-<feature>.md`
