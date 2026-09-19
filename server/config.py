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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    "engine": {"name": "OpenCode", "runtime": "Ollama", "adapters": []},
    "server": {
        "host": "127.0.0.1",
        "port": 7777,
        "serve_hud": True,
        "allow_origins": [],
    },
    "paths": {"vault": "vault", "skills": "skills", "hud": "hud"},
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
