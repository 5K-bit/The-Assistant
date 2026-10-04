"""Engine adapters.

The coding-agent layer is interchangeable by design, so execution goes
through a small adapter interface rather than naming an agent in code.

Three adapters ship:

- ``none``    — routing only. The default, so nothing executes until the
                operator turns it on.
- ``ollama``  — talks to a local Ollama over its HTTP chat API.
- ``command`` — runs any agent CLI from a configured argv template, with
                the prompt on stdin. This is how OpenCode, Claude Code or
                anything else gets driven: the operator supplies the exact
                command, so no adapter has to guess at a CLI's flags.

An adapter either returns text or raises EngineError. It never invents a
result, and a failure is reported as a failure.
"""

import json
import subprocess
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 120


class EngineError(RuntimeError):
    """The engine could not be reached, refused the work, or failed."""


class NoneAdapter:
    """Routes but does not execute."""

    name = "none"
    available = False

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def describe(self):
        return "execution disabled"

    def run(self, prompt):
        raise EngineError("execution is disabled; set engine.execution.enabled to true")


class OllamaAdapter:
    """A local Ollama runtime, over its HTTP chat API."""

    name = "ollama"
    available = True

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.base = str(self.cfg.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        self.model = self.cfg.get("model", "llama3")
        self.timeout = int(self.cfg.get("timeout_seconds", DEFAULT_TIMEOUT))

    def describe(self):
        return f"ollama {self.model} at {self.base}"

    def run(self, prompt):
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise EngineError(f"ollama returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise EngineError(f"ollama unreachable at {self.base}: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise EngineError(f"ollama call failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise EngineError("ollama returned a response that was not JSON") from exc

        text = (payload.get("message") or {}).get("content")
        if not text:
            raise EngineError(f"ollama returned no content: {str(payload)[:200]}")
        return text


class CommandAdapter:
    """Any agent CLI, driven by a configured argv template.

    The prompt goes to the process on stdin. If the configured argv
    contains the token ``{prompt}`` it is substituted instead, as a single
    argument — the command is never run through a shell, so nothing in the
    prompt can be interpreted as shell syntax.
    """

    name = "command"
    available = True

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.argv = list(self.cfg.get("command") or [])
        self.timeout = int(self.cfg.get("timeout_seconds", DEFAULT_TIMEOUT))
        self.cwd = self.cfg.get("cwd") or None

    def describe(self):
        return f"command {' '.join(self.argv) if self.argv else '(unset)'}"

    def run(self, prompt):
        if not self.argv:
            raise EngineError(
                "no command configured; set engine.execution.command to the "
                "argv of your agent CLI"
            )
        argv = [prompt if part == "{prompt}" else part for part in self.argv]
        stdin = None if "{prompt}" in self.argv else prompt
        try:
            result = subprocess.run(
                argv,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.cwd,
                check=False,
            )
        except FileNotFoundError as exc:
            raise EngineError(f"command not found: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise EngineError(f"command timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise EngineError(f"command failed to start: {exc}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:400]
            raise EngineError(f"command exited {result.returncode}: {detail}")
        text = (result.stdout or "").strip()
        if not text:
            raise EngineError("command produced no output on stdout")
        return text


ADAPTERS = {"none": NoneAdapter, "ollama": OllamaAdapter, "command": CommandAdapter}


def build(engine_cfg):
    """Return the adapter named by config, or NoneAdapter when disabled."""
    execution = (engine_cfg or {}).get("execution") or {}
    if not execution.get("enabled"):
        return NoneAdapter(execution)
    adapter_name = str(execution.get("adapter", "none")).lower()
    adapter = ADAPTERS.get(adapter_name)
    if adapter is None:
        raise EngineError(
            f"unknown engine adapter '{adapter_name}'; known: {', '.join(sorted(ADAPTERS))}"
        )
    return adapter(execution)
