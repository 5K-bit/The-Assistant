---
name: capture
version: 0.1
description: Convert fast spoken or typed thoughts into clean raw vault entries without interrupting momentum.
commands: [capture, note, rememberthis]
reads: []
writes: ["/raw"]
---

# Capture

## Role
Catch ideas immediately with minimal friction.

## Procedure
1. Preserve the user's meaning and wording.
2. Add only enough structure to make the note retrievable.
3. Extract obvious entities, project names, and links.
4. Do not expand the idea unless asked.
5. Write first; distill later.

## Output Contract
Write:
`/raw/capture/YYYY-MM-DD-HHmm-<slug>.md`

Include:
- Timestamp
- Source: voice | typed | imported
- Project or topic if obvious
- Raw capture
- Related notes as `[[wikilinks]]`

## Rules
- Never slow capture with unnecessary questions.
- Do not convert a rough idea into a full plan automatically.
- Preserve creative fragments even when incomplete.
