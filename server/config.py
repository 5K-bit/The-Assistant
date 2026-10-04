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

    # Execution overrides, so an engine can be tried for one run without
    # committing it to config.json.
    execution = dict(cfg["engine"].get("execution") or {})
    enabled = os.environ.get("ASSISTANT_EXEC")
    if enabled is not None and enabled != "":
        execution["enabled"] = enabled.strip().lower() in ("1", "true", "yes", "on")
    for env_name, key in (
        ("ASSISTANT_EXEC_ADAPTER", "adapter"),
        ("ASSISTANT_EXEC_MODEL", "model"),
        ("ASSISTANT_EXEC_BASE_URL", "base_url"),
    ):
        raw = os.environ.get(env_name)
        if raw:
            execution[key] = raw
    command = os.environ.get("ASSISTANT_EXEC_COMMAND")
    if command:
        execution["command"] = shlex.split(command)
    timeout = os.environ.get("ASSISTANT_EXEC_TIMEOUT")
    if timeout and timeout.isdigit():
        execution["timeout_seconds"] = int(timeout)
    cfg["engine"]["execution"] = execution
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
