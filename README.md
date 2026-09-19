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

The engine is named in `config.json`, not hardcoded anywhere. Point it at a different agent and the HUD, the API and the command router all follow.

Operating loop:

**Speak → Route → Remember → Repeat**

## Repository

```text
The-Assistant/
├── config.json          # engine, server, paths, schedule
├── server/              # local API + static HUD host
│   ├── __main__.py      # python3 -m server
│   ├── app.py           # routing, static serving, CORS policy
│   ├── config.py        # config.json + ASSISTANT_* env overrides
│   ├── skills.py        # frontmatter parsing, command index
│   ├── vault.py         # counts, activity, wikilink graph
│   └── vitals.py        # CPU / memory / disk / uptime
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

## Backend

```sh
python3 -m server          # http://127.0.0.1:7777
```

Python 3.9+, standard library only — no install step. `psutil` is used for
system vitals if it happens to be installed; without it the server falls
back to `/proc` on Linux and `sysctl`/`vm_stat` on macOS.

| Endpoint | Returns |
| --- | --- |
| `GET /api/health` | status, engine, and per-subsystem checks |
| `GET /api/config` | engine name, runtime, schedule |
| `GET /api/vitals` | CPU, memory, disk, uptime, load |
| `GET /api/skills` | every parsed skill, plus the command index |
| `GET /api/vault/stats` | note, link and byte counts per folder |
| `GET /api/vault/activity` | most recently modified notes |
| `GET /api/vault/graph` | most-linked note and its neighbourhood |
| `POST /api/command` | routes a command to the skill that declares it |

Command routing is real; skill *execution* is not wired to an engine yet,
and the API says so in its reply rather than implying the skill ran.

### Configuration

`config.json` holds the engine name, server binding, paths and schedule.
Any of it can be overridden per-run:

```sh
ASSISTANT_ENGINE="Claude Code" ASSISTANT_PORT=7788 python3 -m server
```

`ASSISTANT_ENGINE`, `ASSISTANT_RUNTIME`, `ASSISTANT_HOST`, `ASSISTANT_PORT`,
`ASSISTANT_VAULT` and `ASSISTANT_SKILLS` are recognised.

To run against a real Obsidian vault instead of the one in this repo,
point `paths.vault` in `config.json` at it, or pass it per-run:

```sh
ASSISTANT_VAULT=~/Obsidian/MyVault python3 -m server
```

Vault and skills paths may be absolute or `~`-relative; a bare relative
path is resolved against the repository root. The vault is expected to
contain `raw/`, `wiki/` and `output/`; `/api/health` reports `degraded`
with HTTP 503 if the directory is missing.

The server binds to `127.0.0.1` and sends **no** CORS headers unless an
origin is listed in `config.json`. Opening the HUD from the server URL
keeps it same-origin, so nothing needs to be granted for normal use.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

61 tests over the skill parser, vault reader, vitals probes, config
resolution and the HTTP surface — including path-traversal attempts, the
CORS policy, oversized and malformed request bodies, and degraded health.
Standard library only, like the server itself.

## HUD

`hud/index.html` is the v0.1 single-screen terminal HUD: system vitals,
command deck, schedule, local audio I/O, terminal interaction, and
live-vault visualization. Served at `http://127.0.0.1:7777/`.

Every panel renders from the API. When the backend is not running the HUD
stays up and shows unknown values as `—` — it never falls back to
placeholder numbers.

## Status

Early architecture / v0.1. The HUD and its API are live against the real
vault and skill set. Voice (local STT/TTS) and engine execution are not
wired yet, and the HUD labels them `NOT WIRED` rather than showing them
armed.
