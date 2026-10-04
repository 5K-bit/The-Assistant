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
| `GET /api/metrics` | per-route latency and vault-cache freshness |
| `GET /api/jobs` | recent skill runs |
| `GET /api/jobs/<id>` | one run: status, reply, where it was written |
| `POST /api/command` | routes a command to the skill that declares it, and runs it when execution is on |

## Execution

**Off by default.** With execution disabled, a command routes to the right
skill and the reply says exactly that — nothing runs.

Turn it on and a command becomes a real run: the shared contract in
`assistant_core.md` plus the routed skill plus current vault state go to
the engine, and the reply is written into the vault.

```sh
ASSISTANT_EXEC=true ASSISTANT_EXEC_ADAPTER=ollama \
ASSISTANT_EXEC_MODEL=llama3 python3 -m server
```

Or set `engine.execution` in `config.json` to make it the default.

| Adapter | Drives |
| --- | --- |
| `none` | nothing — routing only (the default) |
| `ollama` | a local Ollama over its HTTP chat API |
| `command` | **any** agent CLI, from an argv template you supply |

The `command` adapter is how OpenCode, Claude Code or anything else gets
driven — you give the exact command, so no adapter has to guess at a CLI's
flags:

```sh
ASSISTANT_EXEC=true ASSISTANT_EXEC_ADAPTER=command \
ASSISTANT_EXEC_COMMAND="opencode run --quiet" python3 -m server
```

The prompt arrives on the process's stdin, or replaces the literal token
`{prompt}` in the argv if you put one there. The command is never run
through a shell, so nothing in a prompt can be read as shell syntax.

Runs happen on a background thread — a local model can take a minute, and
the HUD must not block. `POST /api/command` returns `202` with a `job_id`;
the HUD polls `/api/jobs/<id>` and prints the reply when it lands.

### What a run may do

- It writes **only** inside the paths its skill's `writes:` frontmatter
  declares. A skill declaring none writes nothing, and a declared path
  that escapes the vault is refused.
- It **never overwrites and never deletes.** Each run creates a new
  timestamped note carrying the skill, command, engine and time it came
  from.
- A failure is reported as a failure. An unreachable engine, a non-zero
  exit or an empty reply all surface as a failed job — never as a blank
  answer presented as a result.

### Prepared state

The vault endpoints read from a snapshot rebuilt in the background rather
than walking the vault per request, so a request never waits on the
filesystem. Each response carries `built_at` and `age_ms`, and the HUD
shows the snapshot age — a prepared value with no age is a number you
cannot trust.

Measured on a generated 842-note vault, one HUD vault refresh went from
188.0 ms to 2.1 ms. Re-measure rather than trusting that number:

```sh
python3 tools/bench.py --save baseline.json   # capture
python3 tools/bench.py --compare baseline.json  # after a change
```

`vault.refresh_seconds` in `config.json` sets the rebuild interval
(default 10, floor 1).

### Configuration

`config.json` holds the engine name, server binding, paths and schedule.
Any of it can be overridden per-run:

```sh
ASSISTANT_ENGINE="Claude Code" ASSISTANT_PORT=7788 python3 -m server
```

`ASSISTANT_ENGINE`, `ASSISTANT_RUNTIME`, `ASSISTANT_HOST`, `ASSISTANT_PORT`,
`ASSISTANT_VAULT` and `ASSISTANT_SKILLS` are recognised, as are
`ASSISTANT_EXEC`, `ASSISTANT_EXEC_ADAPTER`, `ASSISTANT_EXEC_MODEL`,
`ASSISTANT_EXEC_BASE_URL`, `ASSISTANT_EXEC_COMMAND` and
`ASSISTANT_EXEC_TIMEOUT` for execution.

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

116 tests over the skill parser, vault reader, vitals probes, config
resolution, request instrumentation, the prepared-state cache, the engine
adapters, the executor and the HTTP surface — including path-traversal attempts, the CORS policy, oversized
and malformed request bodies, and degraded health. Standard library only,
like the server itself.

`tests/ui/` holds a browser suite covering the rendered HUD, the controls,
markup escaping and the offline/reconnect cycle. It needs Node and
Chromium, so it is kept separate and optional — see `tests/ui/README.md`.

## HUD

`hud/index.html` is the v0.1 single-screen terminal HUD: system vitals,
command deck, schedule, local audio I/O, terminal interaction, and
live-vault visualization. Served at `http://127.0.0.1:7777/`.

Every panel renders from the API. When the backend is not running the HUD
stays up and shows unknown values as `—` — it never falls back to
placeholder numbers.

## Plans

`docs/ao-plan.md` is the working phase plan for the distributed operations
patch: what shipped, the resequencing and why, and the open decisions
(state ownership, ordering, authentication, and which model the cloud
instance runs).

## Status

Early architecture / v0.1. The HUD and its API are live against the real
vault and skill set, and the full loop runs: **Speak → Route → Remember**
— a command routes to a skill, the engine runs it, and the result lands in
the vault.

Voice (local STT/TTS) is still not built, and the HUD labels it
`NOT WIRED` rather than showing it armed.
