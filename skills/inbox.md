---
name: inbox
version: 0.1
description: Build the morning brief from new information that requires awareness or action.
commands: [inbox, morningbrief, brief]
reads: ["/raw", "/wiki", "/output"]
writes: ["/output"]
---

# Inbox

## Role
Create the morning operating brief. Reduce incoming information into what changed, what matters, and what requires action.

## Sources
Use available sources such as:
- Vault notes changed since the last brief.
- Email or messages when connected.
- Calendar/schedule when connected.
- OBEOS alerts or service events.
- Project activity and failed builds.
- Items written into `/raw/inbox`.
- Relevant outputs from `trends`, `metrics`, or `research`.

## Procedure
1. Identify new items since the previous brief.
2. Deduplicate repeated information.
3. Separate information from action.
4. Identify deadlines, blockers, commitments, and waiting items.
5. Surface no more than 7 priority items unless the user explicitly asks for everything.
6. Link every claim back to a vault note or source reference when possible.

## Output Contract
Write:

`/output/briefs/YYYY-MM-DD-morning-brief.md`

Format:

# Morning Brief — YYYY-MM-DD
## Immediate
## Today
## Waiting On
## Project Changes
## Schedule
## Worth Knowing
## Suggested Commands

Suggested commands may include `plantoday`, `metrics`, `whatsnew`, or a project-specific command.

## Rules
- Do not manufacture urgency.
- Do not bury deadlines.
- If no action is needed, say so.
- Prefer one-line bullets over paragraphs.
