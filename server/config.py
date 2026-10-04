"""Configuration loading for The Assistant backend.

Config resolution order, later overriding earlier:
1. Built-in defaults below.
2. `config.json` at the repository root.
3. `ASSISTANT_*` environment variables.

Keeping the engine name here is what makes the coding-agent layer
interchangeable: nothing in the HUD or the server hardcodes an agent.
"""

import json
import os
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    "engine": {
        "name": "OpenCode",
        "runtime": "Ollama",
        "adapters": [],
        "execution": {"enabled": False, "adapter": "none", "timeout_seconds": 120},
    },
    "server": {
        "host": "127.0.0.1",
        "port": 7777,
        "serve_hud": True,
        "allow_origins": [],
    },
    "voice": {
        "stt": {"enabled": False, "adapter": "none", "timeout_seconds": 120},
        "tts": {"enabled": False, "adapter": "none", "timeout_seconds": 60},
    },
    "paths": {"vault": "vault", "skills": "skills", "hud": "hud"},
    "vault": {"refresh_seconds": 10},
    "schedule": [],
}


def _merge(base, override):
    """Recursively merge `override` into a copy of `base`."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _flag(raw):
    """Read an environment flag, tolerant of the usual spellings."""
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _override_block(block, prefix, text_keys=(), flag_keys=()):
    """Apply `<PREFIX>_*` overrides to one adapter settings block."""
    out = dict(block or {})
    enabled = os.environ.get(prefix)
    if enabled is not None and enabled != "":
        out["enabled"] = _flag(enabled)
    for key in ("adapter",) + tuple(text_keys):
        raw = os.environ.get(f"{prefix}_{key.upper()}")
        if raw:
            out[key] = raw
    for key in flag_keys:
        raw = os.environ.get(f"{prefix}_{key.upper()}")
        if raw is not None and raw != "":
            out[key] = _flag(raw)
    command = os.environ.get(f"{prefix}_COMMAND")
    if command:
        out["command"] = shlex.split(command)
    timeout = os.environ.get(f"{prefix}_TIMEOUT")
    if timeout and timeout.isdigit():
        out["timeout_seconds"] = int(timeout)
    return out


def _from_env(cfg):
    """Apply ASSISTANT_* environment overrides."""
    env_map = {
        "ASSISTANT_ENGINE": ("engine", "name"),
        "ASSISTANT_RUNTIME": ("engine", "runtime"),
        "ASSISTANT_HOST": ("server", "host"),
        "ASSISTANT_PORT": ("server", "port"),
        "ASSISTANT_VAULT": ("paths", "vault"),
        "ASSISTANT_SKILLS": ("paths", "skills"),
    }
    for env_name, (section, key) in env_map.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        cfg[section][key] = int(raw) if key == "port" else raw

    # Execution and voice overrides, so a tool can be tried for a single
    # run without committing it to config.json.
    cfg["engine"]["execution"] = _override_block(
        cfg["engine"].get("execution"), "ASSISTANT_EXEC", ("model", "base_url")
    )
    voice = dict(cfg.get("voice") or {})
    voice["stt"] = _override_block(
        voice.get("stt"), "ASSISTANT_STT", flag_keys=("strip_timestamps",)
    )
    voice["tts"] = _override_block(
        voice.get("tts"), "ASSISTANT_TTS", flag_keys=("speak_replies",)
    )
    cfg["voice"] = voice
    return cfg


def load():
    """Return the effective config, with `paths` resolved to absolute Paths."""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg = _merge(cfg, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            # A broken config must not take the server down; fall back to
            # defaults and say so rather than silently pretending it loaded.
            print(f"[config] ignoring {CONFIG_PATH.name}: {exc}")
    cfg = _from_env(cfg)
    # Expand `~` before joining: a bare `ROOT / "~/vault"` would resolve to a
    # literal "~" directory inside the repo rather than the user's home.
    # Absolute paths replace ROOT, relative ones stay repo-relative.
    cfg["paths"] = {
        k: (ROOT / Path(v).expanduser()).resolve() for k, v in cfg["paths"].items()
    }
    return cfg
