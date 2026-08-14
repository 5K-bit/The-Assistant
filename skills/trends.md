---
name: trends
version: 0.1
description: Scan for current developments relevant to the user's active projects and interests.
commands: [whatsnew, trends]
reads: ["/wiki", "/output"]
writes: ["/raw", "/output"]
---

# Trends

## Role
Scan current information for developments that can materially affect what the user is building, buying, learning, watching, or planning.

## Priority Domains
Prioritize only domains connected to active vault context, especially:
- AI models, agents, local AI, MCP, RAG, memory systems.
- Python, Claude Code, developer tooling, open-source projects.
- OBEOS infrastructure, AWS, Tailscale, Raspberry Pi, edge devices.
- Cybersecurity and homelab tooling.
- Meshtastic and offline/mesh communications.
- Creative AI video, image, animation, story production.
- Self-hosted media and personal cloud tooling.
- Flight training when active in the vault.

## Procedure
1. Read current active-project context from `/wiki`.
2. Search only for changes that could affect those projects.
3. Separate:
   - New release
   - New capability
   - Breaking change
   - Opportunity
   - Risk
4. Record source, date, and why it matters.
5. Ignore hype with no practical consequence.

## Output Contract
Raw findings:
`/raw/trends/YYYY-MM-DD-trends-raw.md`

Distilled report:
`/output/trends/YYYY-MM-DD-whats-new.md`

Format:
# What's New — YYYY-MM-DD
## High Impact
## Worth Watching
## Ignore For Now
## Possible Project Impact

## Rules
- Current claims require a current source.
- Never call something "new" without a date.
- Do not recommend changing architecture only because something is trending.
- Explain why a development matters before proposing action.
