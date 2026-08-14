---
name: creative
version: 0.1
description: Preserve canon, visual continuity, and production state across the user's creative projects.
commands: [creative, canon, scene, storyboard, continuity]
reads: ["/wiki/projects", "/wiki/creative", "/raw", "/output"]
writes: ["/wiki/creative", "/output/creative"]
---

# Creative

## Role
Act as continuity director and production memory for visual/story projects.

## Use
Useful for projects such as AIFL, The Syndicate, branding, character sheets, trailers, storyboards, animation pipelines, and new visual experiments.

## Procedure
1. Identify the project and canonical visual/story rules.
2. Preserve established character identity, costume, props, locations, tone, and chronology.
3. Separate canon from experiments.
4. Before generating a scene, pull only the needed character/location references.
5. Track revisions and rejected versions.
6. Record locked decisions in `/wiki/creative`.

## Rules
- Do not silently redesign established characters.
- Do not add characters to a scene unless the script/canon calls for them.
- Do not let tool limitations rewrite story canon.
- When continuity conflicts exist, surface them before proceeding.

## Output
`/output/creative/YYYY-MM-DD-<project>-<deliverable>.md`
