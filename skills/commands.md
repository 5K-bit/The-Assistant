---
name: commands
version: 0.1
description: Enumerate available skills and command aliases from the skills folder.
commands: [listcommands, help]
reads: ["/skills"]
writes: ["/output"]
---

# Commands

## Role
Generate the command index dynamically from installed skill Markdown files.

## Procedure
1. Scan `/skills/*.md`.
2. Read YAML frontmatter.
3. Extract `name`, `description`, and `commands`.
4. Group commands by function.
5. Detect duplicate aliases.
6. Never advertise a command whose skill file is missing.

## Output
On request, display a compact command list.

Optional persistent index:
`/output/system/command-index.md`

## Rules
- The filesystem is authoritative.
- No hard-coded command registry if the same information already exists in skill frontmatter.
