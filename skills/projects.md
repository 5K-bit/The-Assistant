---
name: projects
version: 0.1
description: Maintain canonical project state across OBEOS, The Assistant, creative productions, and experiments.
commands: [project, projects, projectstatus, resumeproject]
reads: ["/wiki/projects", "/output", "/raw"]
writes: ["/wiki/projects", "/output"]
---

# Projects

## Role
Keep each real project understandable across sessions.

## Canonical Project Note
Each project should have one canonical note under:

`/wiki/projects/<project-name>.md`

Recommended fields:
- Purpose
- Current state
- Architecture
- Active branch or repo
- Devices/services involved
- Working features
- Broken features
- Decisions
- Dependencies
- Next executable actions
- Recent outputs
- Last updated

## Procedure
1. Identify the project.
2. Read its canonical note first.
3. Pull only recent related outputs/raw notes needed to recover state.
4. Update state when work changes the project.
5. Preserve old decisions in a Decisions section or linked decision note.
6. Never overwrite uncertainty with an assumption.

## Special Context
The user's ecosystem can include OBEOS, DAISE, The Assistant, Blackcomputer, Legion, Sentinel, AWS/cloud nodes, Pi devices, media servers, AIFL, The Syndicate, and new experiments. Treat these as separate systems unless the vault explicitly links them.

## Output
Project status reports go to:
`/output/projects/YYYY-MM-DD-<project>-status.md`
