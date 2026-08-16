# The Assistant

A local-first, modular AI assistant platform built around an interchangeable coding-agent layer, Obsidian graph memory, interchangeable Markdown skills, private on-device voice, and a real-time operator HUD—designed to integrate into the OBEOS ecosystem.

## Architecture

- **Engine:** interchangeable coding-agent layer
- **Memory:** Obsidian Markdown vault
- **Brain:** interchangeable Markdown skills
- **Voice:** local push-to-talk STT/TTS
- **Face:** single-screen terminal HUD
- **Source of truth:** the vault

**Current local default:** OpenCode as the coding-agent interface with Ollama as the local model runtime. Claude Code and other compatible agents remain optional adapters.

Operating loop:

**Speak → Route → Remember → Repeat**

## Repository

```text
The-Assistant/
├── hud/
│   ├── index.html
│   ├── style.css
│   └── app.js
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
