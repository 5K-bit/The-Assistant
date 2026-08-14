# The Assistant

Local-first personal assistant project designed to integrate into the OBEOS ecosystem.

## Architecture

- **Engine:** Claude Code
- **Memory:** Obsidian Markdown vault
- **Brain:** interchangeable Markdown skills
- **Voice:** local push-to-talk STT/TTS
- **Face:** single-screen terminal HUD
- **Source of truth:** the vault

Operating loop:

**Speak → Route → Remember → Repeat**

## Repository

```text
The-Assistant/
├── hud/
│   └── index.html
├── skills/
│   ├── assistant_core.md
│   ├── metrics.md
│   ├── inbox.md
│   ├── trends.md
│   ├── plan.md
│   ├── vault.md
│   └── ...
└── vault/
    ├── raw/
    ├── wiki/
    └── output/
```

## Memory Contract

- `vault/raw/` — capture, transcripts, imports, observations, source material
- `vault/wiki/` — distilled durable knowledge and canonical project state
- `vault/output/` — everything The Assistant produces

**If it is not in the vault, it did not happen.**

## Skills

Each file in `skills/` is one concentrated behavior module. The router should load only the skill or small combination of skills needed for the current turn.

The original five core skills are:

1. `metrics.md`
2. `inbox.md`
3. `trends.md`
4. `plan.md`
5. `vault.md`

## HUD

`hud/index.html` is the current v0.1 single-screen terminal HUD. It includes system vitals, command deck, schedule, local audio I/O, terminal interaction, and live-vault visualization.

## Status

Early architecture / v0.1.
