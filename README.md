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
│   ├── engine.py        # interchangeable engine adapters
│   ├── executor.py      # prompt assembly, job runner, vault writes
│   ├── voice.py         # speech-to-text and text-to-speech adapters
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
| `GET /api/voice` | whether speech in and out are on, and by which adapter |
| `POST /api/command` | routes a command to the skill that declares it, and runs it when execution is on |
| `POST /api/voice/stt` | a WAV recording in, the transcript out |
| `POST /api/voice/speak` | text in, spoken audio out |

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

## Voice

**Off by default**, like execution. With voice off the HUD says so: the
audio panel reads `NOT WIRED`, holding SPACE captures nothing and admits
it, and the privacy rows show `—` rather than claiming an on-device route
that nothing is using.

Turn it on and the loop closes: hold SPACE, speak, and the transcript is
routed like any typed command. Replies are spoken back.

```sh
ASSISTANT_STT=true ASSISTANT_STT_ADAPTER=command \
ASSISTANT_STT_COMMAND="whisper-cli -m models/ggml-base.en.bin -f {audio} -nt" \
ASSISTANT_TTS=true ASSISTANT_TTS_ADAPTER=command \
ASSISTANT_TTS_COMMAND="piper -m voices/en_US-amy.onnx -f {output}" \
  python3 -m server
```

Or set `voice.stt` and `voice.tts` in `config.json` to make it the default.

| Adapter | Speech in | Speech out |
| --- | --- | --- |
| `none` | nothing (the default) | nothing (the default) |
| `command` | any transcriber, from an argv template you supply | any synthesiser, same |
| `browser` | — | the browser's own on-device voices |

As with the engine, nothing here names a particular program. whisper.cpp,
openai-whisper, piper, `say` and espeak-ng all take different flags, and a
wrong guess fails at the worst possible moment — so you give the command
once and the adapter runs exactly that, never through a shell.

**Argv tokens.** `{audio}` is replaced with the path of the recorded WAV,
`{text}` with the line to speak, and `{output}` with a path the tool may
write its result to. Leave `{audio}` or `{text}` out and the input goes to
the process on stdin instead; leave `{output}` out and the result is read
from stdout.

Starting points for the common tools. Flags differ between builds, so
check your own tool's `--help` — the adapter runs exactly the argv you
give it and nothing more:

```sh
# whisper.cpp — reads the clip, prints the words
ASSISTANT_STT_COMMAND="whisper-cli -m models/ggml-base.en.bin -f {audio} -nt"

# openai-whisper — timestamps are stripped for you
ASSISTANT_STT_COMMAND="whisper {audio} --model base.en --output_format txt --fp16 False"

# piper — text on stdin, WAV to the output path
ASSISTANT_TTS_COMMAND="piper -m voices/en_US-amy.onnx -f {output}"

# macOS built-in voice
ASSISTANT_TTS_COMMAND="say -o {output} --data-format=LEI16@16000 {text}"

# espeak-ng
ASSISTANT_TTS_COMMAND="espeak-ng -w {output} {text}"
```

Set `ASSISTANT_TTS_ADAPTER=browser` to skip a synthesiser entirely and use
the browser's voices. The HUD then uses only voices the browser reports as
on-device — a remote voice would ship your replies off the machine, which
is the opposite of the point — and the server synthesises nothing and says
so.

### What the audio path does

- **The browser does the encoding.** The recording is decoded, resampled
  and re-encoded as 16 kHz mono WAV in the HUD before upload, so the
  server needs no audio tooling and your transcriber gets the format it
  expects.
- **Audio goes to this server and nowhere else.** The HUD posts to its own
  origin. The privacy rows report what that actually is: `LOOPBACK ONLY`
  when the server is on localhost, and the host name when it is not.
- **The microphone is released after every utterance**, so the operating
  system's recording indicator goes out when nothing is being said.
- **The level meters show measured amplitude.** Input is the live RMS of
  the signal; output is the real envelope of the audio being played. They
  sit flat when nothing is flowing. (Browser synthesis exposes no signal,
  so in that mode the output meter stays at rest and the badge alone
  reports `SPEAKING`.)
- **A failure is reported as a failure.** A missing model, a non-zero
  exit, a timeout or an empty transcript all surface as an error in the
  terminal — never as silence presented as "you said nothing".
- Recordings are capped at two minutes, and uploads at 8 MB.

Capture needs a secure context, which over plain HTTP means `localhost`.
Reaching the HUD over a LAN address will get you a refusal from the
browser, reported in the terminal rather than swallowed.

`ASSISTANT_STT`, `ASSISTANT_STT_ADAPTER`, `ASSISTANT_STT_COMMAND`,
`ASSISTANT_STT_TIMEOUT`, `ASSISTANT_STT_STRIP_TIMESTAMPS` and the matching
`ASSISTANT_TTS_*` set override the config block per run.
`ASSISTANT_TTS_SPEAK_REPLIES=0` keeps speech out available but silent by
default; the HUD's **Spoken replies** toggle does the same per browser.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

171 tests over the skill parser, vault reader, vitals probes, config
resolution, request instrumentation, the prepared-state cache, the engine
adapters, the executor, the voice adapters and the HTTP surface —
including path-traversal attempts, the CORS policy, oversized and
malformed request bodies, degraded health, and that neither a prompt nor a
spoken reply is ever shell-interpreted. Standard library only, like the
server itself.

`tests/ui/` holds 79 browser assertions covering the rendered HUD, the
controls, markup escaping, the offline/reconnect cycle, and the voice path
— the HUD's own WAV encoder, the upload, transcription and playback. It
needs Node and Chromium, so it is kept separate and optional — see
`tests/ui/README.md`.

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
— speech is transcribed locally, routed to a skill, run by the engine, and
the result lands in the vault and is spoken back.

Execution and voice both ship **off**, so a fresh clone changes nothing
until you point them at an engine and a pair of speech tools. With them
off the HUD says exactly that rather than showing itself armed.
