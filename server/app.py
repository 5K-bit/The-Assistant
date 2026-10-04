"""HTTP server for The Assistant HUD.

Serves the HUD and the read-only API it renders from. Stdlib only, so it
runs anywhere Python 3 does with no install step.

Security posture: binds to 127.0.0.1 by default and sends no CORS headers
unless an origin is explicitly listed in `config.json`. Opening the HUD
from the server URL keeps it same-origin, so no cross-origin grant is
needed for normal use.
"""

import json
import mimetypes
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, engine, executor, metrics, skills, vault_cache, vitals, voice

API_VERSION = "0.1.0"
MAX_BODY_BYTES = 64 * 1024
# A recording is orders of magnitude larger than a command: 16 kHz mono
# 16-bit PCM is 32 KB a second, so this allows roughly four minutes.
MAX_AUDIO_BYTES = 8 * 1024 * 1024

STARTED_AT = datetime.now(timezone.utc)

# One prepared-state cache per vault path, shared by every request.
_caches = {}
_caches_lock = threading.Lock()


def get_cache(cfg):
    key = str(cfg["paths"]["vault"])
    with _caches_lock:
        cache = _caches.get(key)
        if cache is None:
            interval = cfg.get("vault", {}).get("refresh_seconds", 10)
            cache = vault_cache.VaultCache(cfg["paths"]["vault"], interval).start()
            _caches[key] = cache
        return cache


# One skill runner per vault, holding the engine adapter and job history.
_runners = {}
_runners_lock = threading.Lock()


def get_runner(cfg):
    # Keyed by vault *and* execution settings: two configs pointing at the
    # same vault with different engines must not share one adapter.
    execution = (cfg["engine"].get("execution") or {})
    key = (str(cfg["paths"]["vault"]), repr(sorted(execution.items(), key=str)))
    with _runners_lock:
        runner = _runners.get(key)
        if runner is None:
            runner = executor.Runner(
                cfg["paths"]["vault"], cfg["paths"]["skills"], engine.build(cfg["engine"])
            )
            _runners[key] = runner
        return runner


# One pair of voice adapters per voice configuration.
_voices = {}
_voices_lock = threading.Lock()


def get_voice(cfg):
    """Return (stt, tts, error) for this config.

    A bad adapter name in config must not take the HUD down with it, so
    this falls back to silence and hands back the reason to report.
    """
    settings = cfg.get("voice") or {}
    key = repr([(k, sorted((settings.get(k) or {}).items(), key=str)) for k in ("stt", "tts")])
    with _voices_lock:
        trio = _voices.get(key)
        if trio is None:
            try:
                trio = (voice.build_stt(settings), voice.build_tts(settings), None)
            except voice.VoiceError as exc:
                trio = (voice.SttNone(), voice.TtsNone(), str(exc))
            _voices[key] = trio
        return trio


def stop_caches():
    with _caches_lock:
        for cache in _caches.values():
            cache.stop()
        _caches.clear()
    with _runners_lock:
        _runners.clear()
    with _voices_lock:
        _voices.clear()


class Handler(BaseHTTPRequestHandler):
    server_version = "TheAssistant/" + API_VERSION
    cfg = config.load()

    # --- plumbing -----------------------------------------------------

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def _cors(self):
        origin = self.headers.get("Origin")
        allowed = self.cfg["server"].get("allow_origins") or []
        if origin and (origin in allowed or "*" in allowed):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, status, body, content_type):
        self._status = status
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status=200):
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _timed(self, route, handler):
        """Run a route handler, recording how long it took."""
        self._status = None
        start = time.perf_counter()
        try:
            return handler()
        finally:
            metrics.record(route, (time.perf_counter() - start) * 1000, self._status)

    # --- routing ------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        routes = {
            "/api/health": self.api_health,
            "/api/config": self.api_config,
            "/api/vitals": self.api_vitals,
            "/api/skills": self.api_skills,
            "/api/vault/stats": self.api_vault_stats,
            "/api/vault/activity": self.api_vault_activity,
            "/api/vault/graph": self.api_vault_graph,
            "/api/metrics": self.api_metrics,
            "/api/jobs": self.api_jobs,
            "/api/voice": self.api_voice,
        }
        if path in routes:
            return self._timed(path, routes[path])
        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            return self._timed("/api/jobs/:id", lambda: self.api_job(job_id))
        if path.startswith("/api/"):
            return self._timed("api:unknown", lambda: self._json({"error": "not found", "path": path}, 404))
        if self.cfg["server"].get("serve_hud", True):
            return self._timed("static", lambda: self.serve_static(path))
        return self._timed("unknown", lambda: self._json({"error": "not found"}, 404))

    def _drain(self, total):
        """Discard up to `total` bytes of a body we are refusing."""
        remaining = total
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def _read_body(self, limit):
        """Read the request body, or send the error and return None."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json({"error": "bad content-length"}, 400)
            return None
        if length > limit:
            # Read off what the client is already sending before answering,
            # or it sees a broken pipe instead of the 413. Bounded, so an
            # absurd Content-Length cannot hold the thread open forever.
            self._drain(min(length, limit * 2))
            self.close_connection = True
            self._json({"error": "body too large", "limit": limit}, 413)
            return None
        return self.rfile.read(length)

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/voice/stt":
            # A recording gets its own, much larger limit and never goes
            # near the JSON parser.
            audio = self._read_body(MAX_AUDIO_BYTES)
            if audio is None:
                return None
            return self._timed(path, lambda: self.api_voice_stt(audio))

        routes = {
            "/api/command": self.api_command,
            "/api/voice/speak": self.api_voice_speak,
        }
        if path not in routes:
            return self._json({"error": "not found", "path": path}, 404)
        body = self._read_body(MAX_BODY_BYTES)
        if body is None:
            return None
        try:
            payload = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json({"error": "invalid json"}, 400)
        return self._timed(path, lambda: routes[path](payload))

    # --- static HUD ---------------------------------------------------

    def serve_static(self, path):
        hud_dir = self.cfg["paths"]["hud"]
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (hud_dir / relative).resolve()
        # Refuse anything that escapes the HUD directory. A string prefix
        # test would also accept a sibling like `hud-backup/`, so compare
        # as paths.
        if not target.is_relative_to(hud_dir) or not target.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        return self._send(200, target.read_bytes(), content_type)

    # --- API ----------------------------------------------------------

    def api_health(self):
        skill_list = skills.load(self.cfg["paths"]["skills"])
        vault_dir = self.cfg["paths"]["vault"]
        checks = {
            "skills": bool(skill_list),
            "vault": vault_dir.is_dir(),
            "hud": (self.cfg["paths"]["hud"] / "index.html").is_file(),
        }
        adapter = get_runner(self.cfg).adapter
        stt, tts, _ = get_voice(self.cfg)
        return self._json(
            {
                "status": "ok" if all(checks.values()) else "degraded",
                "version": API_VERSION,
                "engine": self.cfg["engine"]["name"],
                "runtime": self.cfg["engine"]["runtime"],
                "started_at": STARTED_AT.isoformat(),
                "execution": {"enabled": adapter.available, "adapter": adapter.name},
                "voice": voice.state(stt, tts, self.cfg.get("voice")),
                "checks": checks,
            },
            200 if all(checks.values()) else 503,
        )

    def api_config(self):
        # Only the view-facing subset: filesystem paths stay server-side,
        # and the execution block may hold a local command line.
        adapter = get_runner(self.cfg).adapter
        engine_cfg = {
            key: value for key, value in self.cfg["engine"].items() if key != "execution"
        }
        # The adapter's description can contain a local command line, so
        # only its name and state cross the API boundary.
        engine_cfg["execution"] = {"enabled": adapter.available, "adapter": adapter.name}
        return self._json(
            {
                "engine": engine_cfg,
                "schedule": self.cfg["schedule"],
                "version": API_VERSION,
            }
        )

    def api_vitals(self):
        return self._json(vitals.read(str(config.ROOT)))

    def api_skills(self):
        skill_list = skills.load(self.cfg["paths"]["skills"])
        index, collisions = skills.command_index(skill_list)
        return self._json(
            {
                "count": len(skill_list),
                "command_count": len(index),
                "skills": skill_list,
                "collisions": collisions,
            }
        )

    def _vault_snapshot(self):
        return get_cache(self.cfg).snapshot() or {}

    def _freshness(self, snapshot):
        """Age metadata travels with the data, so a stale number is visible."""
        return {"built_at": snapshot.get("built_at"), "age_ms": snapshot.get("age_ms")}

    def api_vault_stats(self):
        snapshot = self._vault_snapshot()
        return self._json({**snapshot.get("stats", {}), **self._freshness(snapshot)})

    def api_vault_activity(self):
        snapshot = self._vault_snapshot()
        return self._json({"rows": snapshot.get("activity", []), **self._freshness(snapshot)})

    def api_vault_graph(self):
        snapshot = self._vault_snapshot()
        graph = snapshot.get("graph") or {"nodes": [], "edges": []}
        return self._json({**graph, **self._freshness(snapshot)})

    def api_jobs(self):
        return self._json({"jobs": get_runner(self.cfg).recent()})

    def api_job(self, job_id):
        job = get_runner(self.cfg).get(job_id)
        if job is None:
            return self._json({"error": "no such job", "job_id": job_id}, 404)
        return self._json(job)

    def api_voice(self):
        stt, tts, error = get_voice(self.cfg)
        payload = voice.state(stt, tts, self.cfg.get("voice"))
        if error:
            payload["error"] = error
        return self._json(payload)

    def api_voice_stt(self, audio):
        stt, _, _ = get_voice(self.cfg)
        if not stt.available:
            return self._json({"error": "transcription is not enabled", "adapter": stt.name}, 409)
        if not audio:
            return self._json({"error": "no audio received"}, 400)
        if not voice.is_wav(audio):
            return self._json({"error": "expected a WAV recording"}, 415)
        start = time.perf_counter()
        try:
            text = stt.transcribe(audio)
        except voice.VoiceError as exc:
            # A transcription that failed is reported as failed. Returning
            # an empty string would read as "you said nothing".
            return self._json({"error": str(exc), "adapter": stt.name}, 502)
        return self._json(
            {
                "text": text,
                "adapter": stt.name,
                "bytes": len(audio),
                "ms": round((time.perf_counter() - start) * 1000, 1),
            }
        )

    def api_voice_speak(self, payload):
        _, tts, _ = get_voice(self.cfg)
        if not tts.available:
            return self._json({"error": "speech is not enabled", "adapter": tts.name}, 409)
        if not tts.server_side:
            # The HUD synthesises in this mode; saying so beats returning
            # silence that would look like success.
            return self._json({"error": tts.describe(), "mode": "browser"}, 409)
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return self._json({"error": "no text to speak"}, 400)
        try:
            audio, content_type = tts.speak(text)
        except voice.VoiceError as exc:
            return self._json({"error": str(exc), "adapter": tts.name}, 502)
        return self._send(200, audio, content_type)

    def api_metrics(self):
        snapshot = self._vault_snapshot()
        payload = metrics.snapshot()
        payload["vault_cache"] = {
            "refresh_seconds": self.cfg.get("vault", {}).get("refresh_seconds", 10),
            "build_ms": snapshot.get("build_ms"),
            "age_ms": snapshot.get("age_ms"),
            "built_at": snapshot.get("built_at"),
        }
        return self._json(payload)

    def api_command(self, payload):
        raw = str(payload.get("command", "")).strip()
        if not raw:
            return self._json({"error": "empty command"}, 400)

        verb = raw.split()[0].lstrip("/").lower()
        skill_list = skills.load(self.cfg["paths"]["skills"])
        index, _ = skills.command_index(skill_list)
        engine = self.cfg["engine"]["name"]

        if verb not in index:
            return self._json(
                {
                    "reply": f"no skill declares '{verb}'. Try listcommands.",
                    "command": raw,
                    "routed": False,
                }
            )

        skill = next(s for s in skill_list if s["file"] == index[verb])
        runner = get_runner(self.cfg)

        if not runner.adapter.available:
            # Execution is off. Say exactly that rather than implying a run.
            return self._json(
                {
                    "reply": f"routed to {index[verb]} — {engine} execution not wired yet.",
                    "command": raw,
                    "skill": index[verb],
                    "routed": True,
                    "executed": False,
                }
            )

        snapshot = self._vault_snapshot()
        stats = snapshot.get("stats", {})
        context = {
            "now": datetime.now(timezone.utc).isoformat(),
            "vault notes": stats.get("notes"),
            "vault links": stats.get("links"),
            "snapshot age (ms)": snapshot.get("age_ms"),
        }
        job = runner.start(skill, raw, context)
        return self._json(
            {
                "reply": f"routed to {index[verb]} — running on {runner.adapter.describe()}.",
                "command": raw,
                "skill": index[verb],
                "routed": True,
                "job_id": job.id,
                "status": job.status,
            },
            202,
        )


def serve():
    cfg = Handler.cfg
    host, port = cfg["server"]["host"], cfg["server"]["port"]
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"The Assistant // API + HUD on http://{host}:{port}")
    print(f"  engine: {cfg['engine']['name']} · runtime: {cfg['engine']['runtime']}")
    print(f"  vault:  {cfg['paths']['vault']}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
    finally:
        httpd.server_close()
        stop_caches()
