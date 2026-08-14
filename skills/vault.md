---
name: vault
version: 0.1
description: Read, write, link, distill, and maintain the Obsidian vault as the source of truth.
commands: [vault, vaultclean, remember, recall]
reads: ["/raw", "/wiki", "/output"]
writes: ["/raw", "/wiki", "/output"]
---

# Vault

## Role
The vault is the memory system for The Assistant.

**If it is not in the vault, it did not happen.**

No database is the source of truth. Notes and links form the memory graph.

## Folder Contract
- `/raw` — unprocessed capture, transcripts, imports, observations, temporary research.
- `/wiki` — distilled durable knowledge, project state, people, systems, decisions, canonical facts.
- `/output` — everything The Assistant produces: plans, briefs, reports, reviews, research, summaries.

## Read Strategy
1. Start with the smallest relevant set of notes.
2. Follow explicit links and backlinks.
3. Prefer `/wiki` for canonical state.
4. Use `/raw` only when detail or provenance is needed.
5. Use `/output` for recent operating context.

## Write Strategy
1. Raw facts first when provenance matters.
2. Distill stable facts into `/wiki`.
3. Link related notes using `[[wikilinks]]`.
4. Update an existing canonical note instead of creating duplicates.
5. Add timestamps to changing state.
6. Preserve source references.

## Vault Clean
When `vaultclean` is called:
1. Find stale or unprocessed `/raw` notes.
2. Extract durable knowledge.
3. Merge into the correct `/wiki` note.
4. Add or repair links.
5. Mark the raw note as distilled rather than silently deleting it.
6. Produce a cleanup report in `/output`.

## Rules
- Never erase history just to make the graph neat.
- Never merge two entities unless identity is certain.
- Never treat an Assistant inference as a user fact.
- Record uncertainty explicitly.
- Do not write sensitive personal details unless the user intentionally provides or stores them.
