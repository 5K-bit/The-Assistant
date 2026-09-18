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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, skills, vault, vitals

API_VERSION = "0.1.0"
MAX_BODY_BYTES = 64 * 1024

STARTED_AT = datetime.now(timezone.utc)


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
        }
        if path in routes:
            return routes[path]()
        if path.startswith("/api/"):
            return self._json({"error": "not found", "path": path}, 404)
        if self.cfg["server"].get("serve_hud", True):
            return self.serve_static(path)
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path != "/api/command":
            return self._json({"error": "not found", "path": path}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"error": "bad content-length"}, 400)
        if length > MAX_BODY_BYTES:
            return self._json({"error": "body too large"}, 413)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json({"error": "invalid json"}, 400)
        return self.api_command(payload)

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
        return self._json(
            {
                "status": "ok" if all(checks.values()) else "degraded",
                "version": API_VERSION,
                "engine": self.cfg["engine"]["name"],
                "runtime": self.cfg["engine"]["runtime"],
                "started_at": STARTED_AT.isoformat(),
                "checks": checks,
            },
            200 if all(checks.values()) else 503,
        )

    def api_config(self):
        # Only the view-facing subset: filesystem paths stay server-side.
        return self._json(
            {
                "engine": self.cfg["engine"],
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

    def api_vault_stats(self):
        return self._json(vault.stats(self.cfg["paths"]["vault"]))

    def api_vault_activity(self):
        return self._json({"rows": vault.activity(self.cfg["paths"]["vault"])})

    def api_vault_graph(self):
        return self._json(vault.graph(self.cfg["paths"]["vault"]))

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

        # Routing is real; execution is not wired yet. Say exactly that
        # rather than implying the skill ran.
        return self._json(
            {
                "reply": f"routed to {index[verb]} — {engine} execution not wired yet.",
                "command": raw,
                "skill": index[verb],
                "routed": True,
                "executed": False,
            }
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
