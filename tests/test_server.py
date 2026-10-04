"""Test suite for The Assistant backend. Stdlib only."""

import io
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from server import app, config, engine, executor, metrics, skills, vault, vault_cache, vitals, voice  # noqa: E402


# ---------- helpers ----------

class Server:
    """Run the real handler on an ephemeral port with a given config."""

    def __init__(self, cfg):
        self.cls = type("TestHandler", (app.Handler,), {"cfg": cfg, "log_message": lambda *a: None})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.cls)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path, headers=None, method="GET"):
        req = urllib.request.Request(self.url(path), headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.read(), dict(res.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def post(self, path, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.url(path), data=data, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def post_raw(self, path, data, content_type="application/octet-stream"):
        """POST bytes and return the bytes back, for audio either way."""
        req = urllib.request.Request(
            self.url(path), data=data, headers={"Content-Type": content_type}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, res.read(), res.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type")


def base_cfg(**over):
    cfg = config.load()
    cfg.update(over)
    return cfg


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------- skills ----------

class TestSkills(unittest.TestCase):
    def test_real_skills_all_parse(self):
        found = skills.load(REPO / "skills")
        self.assertEqual(len(found), 25)
        self.assertTrue(all(s["loaded"] for s in found))
        self.assertTrue(all(s["name"] for s in found))
        self.assertTrue(all(s["commands"] for s in found), "every skill should declare commands")

    def test_real_commands_have_no_collisions(self):
        index, collisions = skills.command_index(skills.load(REPO / "skills"))
        self.assertEqual(collisions, {})
        self.assertEqual(len(index), 78)

    def test_collision_is_recorded(self):
        a = {"file": "a.md", "commands": ["dup", "x"]}
        b = {"file": "b.md", "commands": ["dup"]}
        index, collisions = skills.command_index([a, b])
        self.assertIn("dup", collisions)
        self.assertEqual(collisions["dup"], ["a.md", "b.md"])
        self.assertEqual(index["x"], "a.md")

    def test_no_frontmatter(self):
        self.assertEqual(skills.parse_frontmatter("# Just a heading\n"), {})

    def test_empty_list_value(self):
        meta = skills.parse_frontmatter("---\nname: x\nreads: []\n---\n")
        self.assertEqual(meta["reads"], [])

    def test_quoted_and_unquoted_lists(self):
        meta = skills.parse_frontmatter('---\na: [one, two]\nb: ["x", "y"]\n---\n')
        self.assertEqual(meta["a"], ["one", "two"])
        self.assertEqual(meta["b"], ["x", "y"])

    def test_colon_inside_value_is_kept(self):
        meta = skills.parse_frontmatter("---\ndescription: Do X: then Y\n---\n")
        self.assertEqual(meta["description"], "Do X: then Y")

    def test_crlf_frontmatter(self):
        meta = skills.parse_frontmatter("---\r\nname: crlf\r\ncommands: [a, b]\r\n---\r\n")
        self.assertEqual(meta["name"], "crlf")
        self.assertEqual(meta["commands"], ["a", "b"])

    def test_unterminated_frontmatter_does_not_hang(self):
        meta = skills.parse_frontmatter("---\nname: x\ncommands: [a]\n")
        self.assertEqual(meta["name"], "x")

    def test_missing_directory(self):
        self.assertEqual(skills.load(Path("/nonexistent/skills")), [])

    def test_defaults_filled_for_list_keys(self):
        meta = skills.parse_frontmatter("---\nname: bare\n---\n")
        for key in ("commands", "reads", "writes"):
            self.assertEqual(meta[key], [])


# ---------- vault ----------

class TestVault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = Path(self.tmp.name)
        for f in ("raw", "wiki", "output"):
            (self.v / f).mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_vault_reports_zeros(self):
        self.assertEqual(
            vault.stats(self.v),
            {"notes": 0, "links": 0, "bytes": 0, "raw": 0, "wiki": 0, "output": 0},
        )
        self.assertEqual(vault.activity(self.v), [])
        self.assertEqual(vault.graph(self.v), {"nodes": [], "edges": []})

    def test_counts_per_folder(self):
        write(self.v / "raw" / "a.md", "raw note")
        write(self.v / "wiki" / "b.md", "wiki note")
        write(self.v / "wiki" / "c.md", "another")
        write(self.v / "output" / "d.md", "out")
        s = vault.stats(self.v)
        self.assertEqual((s["notes"], s["raw"], s["wiki"], s["output"]), (4, 1, 2, 1))
        self.assertGreater(s["bytes"], 0)

    def test_non_markdown_ignored(self):
        write(self.v / "wiki" / "a.md", "note")
        write(self.v / "wiki" / "b.txt", "not a note")
        (self.v / "wiki" / "image.png").write_bytes(b"\x89PNG\r\n")
        self.assertEqual(vault.stats(self.v)["notes"], 1)

    def test_nested_subdirectories_counted(self):
        write(self.v / "wiki" / "projects" / "deep" / "x.md", "deep note")
        self.assertEqual(vault.stats(self.v)["wiki"], 1)
        rows = vault.activity(self.v)
        self.assertEqual(rows[0]["path"], "/wiki/projects/deep/x.md")

    def test_wikilink_variants(self):
        write(self.v / "wiki" / "src.md", "[[plain]] [[target|alias]] [[page#head]] [[p2#h|a]]")
        self.assertEqual(vault.stats(self.v)["links"], 4)
        g = vault.graph(self.v)
        ids = {n["id"] for n in g["nodes"]}
        self.assertTrue({"plain", "target", "page", "p2"} <= ids)

    def test_empty_wikilink_not_counted(self):
        write(self.v / "wiki" / "src.md", "[[]] and [[ok]]")
        self.assertEqual(vault.stats(self.v)["links"], 1)

    def test_self_link_excluded_from_graph(self):
        write(self.v / "wiki" / "me.md", "[[me]] [[other]]")
        g = vault.graph(self.v)
        self.assertNotIn(("me", "me"), {(e["source"], e["target"]) for e in g["edges"]})

    def test_unicode_filename(self):
        write(self.v / "wiki" / "café-note.md", "[[other]]")
        self.assertEqual(vault.stats(self.v)["notes"], 1)
        self.assertIn("café", vault.activity(self.v)[0]["path"])

    def test_activity_is_newest_first_and_limited(self):
        for i in range(12):
            p = self.v / "raw" / f"n{i:02d}.md"
            write(p, "x")
            import os
            os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        rows = vault.activity(self.v, limit=5)
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["path"] for r in rows][0], "/raw/n11.md")
        self.assertTrue(all(rows[i]["mtime"] >= rows[i + 1]["mtime"] for i in range(len(rows) - 1)))

    def test_activity_type_is_folder(self):
        write(self.v / "output" / "o.md", "x")
        self.assertEqual(vault.activity(self.v)[0]["type"], "OUTPUT")

    def test_graph_centres_most_connected(self):
        write(self.v / "wiki" / "hub.md", "[[a]] [[b]] [[c]]")
        write(self.v / "wiki" / "a.md", "[[hub]]")
        write(self.v / "wiki" / "b.md", "[[hub]]")
        write(self.v / "wiki" / "c.md", "[[hub]]")
        g = vault.graph(self.v)
        self.assertEqual(g["nodes"][0]["id"], "hub")

    def test_graph_with_notes_but_no_links(self):
        write(self.v / "wiki" / "lonely.md", "no links here")
        self.assertEqual(vault.graph(self.v), {"nodes": [], "edges": []})

    def test_graph_respects_limit(self):
        write(self.v / "wiki" / "hub.md", " ".join(f"[[n{i}]]" for i in range(20)))
        g = vault.graph(self.v, limit=5)
        self.assertLessEqual(len(g["nodes"]), 5)

    def test_missing_vault_directory(self):
        missing = Path("/nonexistent/vault")
        self.assertEqual(vault.stats(missing)["notes"], 0)
        self.assertEqual(vault.activity(missing), [])


# ---------- vitals ----------

class TestVitals(unittest.TestCase):
    def test_shape(self):
        v = vitals.read()
        for key in ("cpu", "ram", "disk", "uptime", "uptime_seconds", "load", "cores", "source"):
            self.assertIn(key, v)
        self.assertIn(v["source"], ("psutil", "procfs", "sysctl", "unavailable"))

    def test_percentages_in_range_or_none(self):
        v = vitals.read()
        for key in ("cpu", "ram", "disk"):
            if v[key] is not None:
                self.assertGreaterEqual(v[key], 0, key)
                self.assertLessEqual(v[key], 100, key)

    def test_rapid_polling_does_not_report_noise(self):
        # Regression: back-to-back reads once returned a spurious 100%.
        readings = [vitals.read()["cpu"] for _ in range(6)]
        for r in readings:
            if r is not None:
                self.assertLessEqual(r, 100)
        idle = [r for r in readings if r is not None]
        self.assertTrue(all(r < 95 for r in idle), f"suspicious idle CPU readings: {idle}")

    def test_uptime_format(self):
        v = vitals.read()
        if v["uptime"] is not None:
            self.assertRegex(v["uptime"], r"^\d{2,}:\d{2}$")


# ---------- config ----------

class TestConfig(unittest.TestCase):
    def test_paths_absolute(self):
        cfg = config.load()
        for key, p in cfg["paths"].items():
            self.assertTrue(Path(p).is_absolute(), key)

    def test_env_override(self, ):
        import os
        old = os.environ.get("ASSISTANT_ENGINE")
        os.environ["ASSISTANT_ENGINE"] = "TestEngine"
        os.environ["ASSISTANT_PORT"] = "9999"
        try:
            cfg = config.load()
            self.assertEqual(cfg["engine"]["name"], "TestEngine")
            self.assertEqual(cfg["server"]["port"], 9999)
            self.assertIsInstance(cfg["server"]["port"], int)
        finally:
            os.environ.pop("ASSISTANT_PORT", None)
            if old is None:
                os.environ.pop("ASSISTANT_ENGINE", None)
            else:
                os.environ["ASSISTANT_ENGINE"] = old

    def test_broken_config_falls_back_to_defaults(self):
        original = config.CONFIG_PATH
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "config.json"
            bad.write_text("{ not json", encoding="utf-8")
            config.CONFIG_PATH = bad
            try:
                cfg = config.load()
                self.assertEqual(cfg["engine"]["name"], config.DEFAULTS["engine"]["name"])
            finally:
                config.CONFIG_PATH = original

    def test_tilde_in_path_expands_to_home(self):
        import os
        old = os.environ.get("ASSISTANT_VAULT")
        os.environ["ASSISTANT_VAULT"] = "~/SomeVault"
        try:
            resolved = str(config.load()["paths"]["vault"])
            self.assertNotIn("~", resolved)
            self.assertTrue(resolved.startswith(str(Path.home())), resolved)
        finally:
            if old is None:
                os.environ.pop("ASSISTANT_VAULT", None)
            else:
                os.environ["ASSISTANT_VAULT"] = old

    def test_absolute_path_replaces_repo_root(self):
        import os
        old = os.environ.get("ASSISTANT_VAULT")
        os.environ["ASSISTANT_VAULT"] = "/tmp/elsewhere/vault"
        try:
            self.assertEqual(str(config.load()["paths"]["vault"]), "/tmp/elsewhere/vault")
        finally:
            if old is None:
                os.environ.pop("ASSISTANT_VAULT", None)
            else:
                os.environ["ASSISTANT_VAULT"] = old

    def test_relative_path_stays_repo_relative(self):
        self.assertEqual(config.load()["paths"]["vault"], (REPO / "vault").resolve())

    def test_merge_is_deep(self):
        merged = config._merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 9}})
        self.assertEqual(merged["a"], {"x": 1, "y": 9})


# ---------- HTTP ----------

class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = base_cfg()
        cls.srv = Server(cls.cfg).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.srv.__exit__()

    def test_all_get_endpoints_ok(self):
        for ep in ("/api/health", "/api/config", "/api/vitals", "/api/skills",
                   "/api/vault/stats", "/api/vault/activity", "/api/vault/graph"):
            status, body, headers = self.srv.get(ep)
            self.assertEqual(status, 200, ep)
            self.assertIn("application/json", headers["Content-Type"], ep)
            json.loads(body)

    def test_trailing_slash_tolerated(self):
        self.assertEqual(self.srv.get("/api/health/")[0], 200)

    def test_query_string_ignored(self):
        self.assertEqual(self.srv.get("/api/health?x=1")[0], 200)

    def test_unknown_api_path_404_json(self):
        status, body, headers = self.srv.get("/api/nope")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertIn("error", json.loads(body))

    def test_static_hud_served(self):
        for path, ctype in (("/", "text/html"), ("/style.css", "text/css"), ("/app.js", "javascript")):
            status, body, headers = self.srv.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn(ctype, headers["Content-Type"], path)
            self.assertGreater(len(body), 100, path)

    def test_unknown_static_404(self):
        self.assertEqual(self.srv.get("/nope.html")[0], 404)

    def test_path_traversal_blocked(self):
        for evil in ("/../config.json", "/../server/app.py", "/../../etc/passwd",
                     "/..%2fconfig.json", "/%2e%2e/config.json"):
            status, body, _ = self.srv.get(evil)
            self.assertEqual(status, 404, evil)
            self.assertNotIn(b"engine", body.lower(), evil)

    def test_sibling_directory_not_served(self):
        # A string-prefix check would wrongly allow "hud-x"; ensure it does not.
        self.assertEqual(self.srv.get("/../hud-backup/secret.txt")[0], 404)

    def test_head_returns_no_body(self):
        status, body, headers = self.srv.get("/api/health", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertIn("Content-Length", headers)

    def test_no_cors_headers_by_default(self):
        _, _, headers = self.srv.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_cache_control_no_store(self):
        _, _, headers = self.srv.get("/api/vitals")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_health_shape(self):
        _, body, _ = self.srv.get("/api/health")
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(set(data["checks"]), {"skills", "vault", "hud"})
        self.assertTrue(all(data["checks"].values()))

    def test_config_does_not_leak_filesystem_paths(self):
        _, body, _ = self.srv.get("/api/config")
        self.assertNotIn(b"/home/", body)
        self.assertNotIn(b"paths", body)

    def test_skills_endpoint_matches_disk(self):
        _, body, _ = self.srv.get("/api/skills")
        data = json.loads(body)
        self.assertEqual(data["count"], 25)
        self.assertEqual(data["command_count"], 78)
        self.assertEqual(data["collisions"], {})

    def test_command_routes_known(self):
        status, data = self.srv.post("/api/command", {"command": "metrics"})
        self.assertEqual(status, 200)
        self.assertTrue(data["routed"])
        self.assertFalse(data["executed"])
        self.assertEqual(data["skill"], "metrics.md")

    def test_command_case_slash_and_args(self):
        _, data = self.srv.post("/api/command", {"command": "/PlanToday next week"})
        self.assertTrue(data["routed"])
        self.assertEqual(data["skill"], "plan.md")

    def test_command_unknown(self):
        status, data = self.srv.post("/api/command", {"command": "summon dragons"})
        self.assertEqual(status, 200)
        self.assertFalse(data["routed"])
        self.assertIn("summon", data["reply"])

    def test_command_never_claims_execution(self):
        _, data = self.srv.post("/api/command", {"command": "vaultclean"})
        self.assertIn("not wired", data["reply"])
        self.assertIs(data["executed"], False)

    def test_command_empty_and_whitespace(self):
        for bad in ("", "   "):
            status, data = self.srv.post("/api/command", {"command": bad})
            self.assertEqual(status, 400, repr(bad))

    def test_command_invalid_json(self):
        status, _ = self.srv.post("/api/command", b"not json at all")
        self.assertEqual(status, 400)

    def test_command_oversized_body_rejected(self):
        big = json.dumps({"command": "x" * (app.MAX_BODY_BYTES + 100)}).encode()
        status, _ = self.srv.post("/api/command", big)
        self.assertEqual(status, 413)

    def test_command_non_string_value(self):
        status, data = self.srv.post("/api/command", {"command": 12345})
        self.assertEqual(status, 200)
        self.assertFalse(data["routed"])

    def test_post_to_wrong_path_404(self):
        status, _ = self.srv.post("/api/vitals", {"x": 1})
        self.assertEqual(status, 404)


class TestHTTPVariants(unittest.TestCase):
    def test_cors_emitted_only_for_allowed_origin(self):
        cfg = base_cfg()
        cfg["server"] = {**cfg["server"], "allow_origins": ["https://ok.example"]}
        with Server(cfg) as srv:
            _, _, h = srv.get("/api/health", headers={"Origin": "https://ok.example"})
            self.assertEqual(h.get("Access-Control-Allow-Origin"), "https://ok.example")
            self.assertEqual(h.get("Vary"), "Origin")
            _, _, h2 = srv.get("/api/health", headers={"Origin": "https://evil.example"})
            self.assertNotIn("Access-Control-Allow-Origin", h2)

    def test_health_degraded_returns_503(self):
        cfg = base_cfg()
        cfg["paths"] = {**cfg["paths"], "vault": Path("/nonexistent/vault")}
        with Server(cfg) as srv:
            status, body, _ = srv.get("/api/health")
            self.assertEqual(status, 503)
            data = json.loads(body)
            self.assertEqual(data["status"], "degraded")
            self.assertFalse(data["checks"]["vault"])

    def test_serve_hud_disabled(self):
        cfg = base_cfg()
        cfg["server"] = {**cfg["server"], "serve_hud": False}
        with Server(cfg) as srv:
            self.assertEqual(srv.get("/")[0], 404)
            self.assertEqual(srv.get("/api/health")[0], 200)

    def test_engine_name_flows_from_config_to_api(self):
        cfg = base_cfg()
        cfg["engine"] = {"name": "SomeOtherAgent", "runtime": "SomeRuntime", "adapters": []}
        with Server(cfg) as srv:
            _, body, _ = srv.get("/api/config")
            self.assertEqual(json.loads(body)["engine"]["name"], "SomeOtherAgent")
            _, data = srv.post("/api/command", {"command": "metrics"})
            self.assertIn("SomeOtherAgent", data["reply"])
            _, hbody, _ = srv.get("/api/health")
            self.assertEqual(json.loads(hbody)["engine"], "SomeOtherAgent")

    def test_concurrent_requests(self):
        cfg = base_cfg()
        with Server(cfg) as srv:
            results = []
            def hit():
                results.append(srv.get("/api/vault/stats")[0])
            threads = [threading.Thread(target=hit) for _ in range(20)]
            for t in threads: t.start()
            for t in threads: t.join(timeout=20)
            self.assertEqual(len(results), 20)
            self.assertTrue(all(r == 200 for r in results))


# ---------- metrics (AO-0) ----------

class TestMetrics(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def tearDown(self):
        metrics.reset()

    def test_records_count_and_percentiles(self):
        for value in range(1, 101):
            metrics.record("/x", float(value))
        route = metrics.snapshot()["routes"]["/x"]
        self.assertEqual(route["count"], 100)
        self.assertEqual(route["min_ms"], 1.0)
        self.assertEqual(route["max_ms"], 100.0)
        self.assertLessEqual(route["p50_ms"], route["p95_ms"])
        self.assertLessEqual(route["p95_ms"], route["max_ms"])

    def test_counts_errors_separately(self):
        metrics.record("/y", 1.0, 200)
        metrics.record("/y", 1.0, 404)
        metrics.record("/y", 1.0, None)
        route = metrics.snapshot()["routes"]["/y"]
        self.assertEqual(route["count"], 3)
        self.assertEqual(route["errors"], 2)

    def test_samples_are_bounded(self):
        for value in range(metrics.MAX_SAMPLES * 2):
            metrics.record("/z", float(value))
        self.assertEqual(metrics.snapshot()["routes"]["/z"]["count"], metrics.MAX_SAMPLES * 2)

    def test_empty_snapshot(self):
        self.assertEqual(metrics.snapshot()["routes"], {})


# ---------- vault cache (AO-2) ----------

class TestVaultCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = Path(self.tmp.name)
        for f in ("raw", "wiki", "output"):
            (self.v / f).mkdir()
        write(self.v / "wiki" / "a.md", "[[b]]")
        write(self.v / "wiki" / "b.md", "[[a]]")

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_matches_direct_scan(self):
        cache = vault_cache.VaultCache(self.v, interval=60)
        try:
            snapshot = cache.snapshot()
            self.assertEqual(snapshot["stats"], vault.stats(self.v))
            self.assertEqual(snapshot["graph"], vault.graph(self.v))
            self.assertEqual(
                [r["path"] for r in snapshot["activity"]],
                [r["path"] for r in vault.activity(self.v)],
            )
        finally:
            cache.stop()

    def test_snapshot_carries_age(self):
        cache = vault_cache.VaultCache(self.v, interval=60)
        try:
            snapshot = cache.snapshot()
            self.assertIsNotNone(snapshot["built_at"])
            self.assertIsNotNone(snapshot["build_ms"])
            self.assertGreaterEqual(snapshot["age_ms"], 0)
        finally:
            cache.stop()

    def test_builds_on_demand_without_start(self):
        cache = vault_cache.VaultCache(self.v, interval=60)
        try:
            self.assertEqual(cache.snapshot()["stats"]["notes"], 2)
        finally:
            cache.stop()

    def test_refresh_picks_up_new_notes(self):
        cache = vault_cache.VaultCache(self.v, interval=60)
        try:
            self.assertEqual(cache.snapshot()["stats"]["notes"], 2)
            write(self.v / "raw" / "c.md", "new note")
            cache.refresh()
            self.assertEqual(cache.snapshot()["stats"]["notes"], 3)
        finally:
            cache.stop()

    def test_background_thread_refreshes_and_stops(self):
        cache = vault_cache.VaultCache(self.v, interval=1).start()
        try:
            write(self.v / "raw" / "later.md", "added after start")
            deadline = time.time() + 10
            while time.time() < deadline:
                if cache.snapshot()["stats"]["notes"] == 3:
                    break
                time.sleep(0.2)
            self.assertEqual(cache.snapshot()["stats"]["notes"], 3)
        finally:
            cache.stop()
        self.assertIsNone(cache._thread)

    def test_interval_has_a_floor(self):
        self.assertGreaterEqual(vault_cache.VaultCache(self.v, interval=0).interval, 1.0)

    def test_missing_vault_yields_zeros(self):
        cache = vault_cache.VaultCache(Path("/nonexistent/vault"), interval=60)
        try:
            self.assertEqual(cache.snapshot()["stats"]["notes"], 0)
        finally:
            cache.stop()


class TestCachedEndpoints(unittest.TestCase):
    def test_vault_endpoints_expose_freshness(self):
        with Server(base_cfg()) as srv:
            for ep in ("/api/vault/stats", "/api/vault/activity", "/api/vault/graph"):
                _, body, _ = srv.get(ep)
                data = json.loads(body)
                self.assertIn("built_at", data, ep)
                self.assertIn("age_ms", data, ep)
                self.assertGreaterEqual(data["age_ms"], 0, ep)

    def test_metrics_endpoint_reports_routes_and_cache(self):
        with Server(base_cfg()) as srv:
            srv.get("/api/health")
            srv.get("/api/vitals")
            _, body, _ = srv.get("/api/metrics")
            data = json.loads(body)
            self.assertIn("/api/health", data["routes"])
            self.assertGreaterEqual(data["routes"]["/api/health"]["count"], 1)
            self.assertIn("vault_cache", data)
            self.assertIsNotNone(data["vault_cache"]["build_ms"])

    def test_repeated_vault_reads_are_served_from_one_scan(self):
        with Server(base_cfg()) as srv:
            first = json.loads(srv.get("/api/vault/stats")[1])["built_at"]
            second = json.loads(srv.get("/api/vault/graph")[1])["built_at"]
            self.assertEqual(first, second, "both views should come from the same snapshot")


# ---------- engine adapters ----------

ECHO_SCRIPT = "import sys; sys.stdout.write('echo:' + sys.stdin.read()[:40])"


class FakeOllama(threading.Thread):
    """A stand-in Ollama, so the real HTTP client path is exercised."""

    def __init__(self, mode="ok"):
        super().__init__(daemon=True)
        self.mode = mode
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                if outer.mode == "http_error":
                    body = b'{"error":"model not found"}'
                    self.send_response(500)
                elif outer.mode == "not_json":
                    body = b"this is not json"
                    self.send_response(200)
                elif outer.mode == "no_content":
                    body = b'{"message":{}}'
                    self.send_response(200)
                else:
                    body = b'{"message":{"role":"assistant","content":"a reply"}}'
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"


class TestEngineBuild(unittest.TestCase):
    def test_disabled_by_default(self):
        adapter = engine.build({})
        self.assertFalse(adapter.available)
        self.assertEqual(adapter.name, "none")

    def test_disabled_adapter_refuses_to_run(self):
        with self.assertRaises(engine.EngineError):
            engine.build({}).run("anything")

    def test_unknown_adapter_is_rejected(self):
        with self.assertRaises(engine.EngineError):
            engine.build({"execution": {"enabled": True, "adapter": "telepathy"}})

    def test_enabled_selects_named_adapter(self):
        adapter = engine.build({"execution": {"enabled": True, "adapter": "ollama"}})
        self.assertEqual(adapter.name, "ollama")
        self.assertTrue(adapter.available)


class TestCommandAdapter(unittest.TestCase):
    def build(self, **over):
        cfg = {"enabled": True, "adapter": "command", "timeout_seconds": 30}
        cfg.update(over)
        return engine.build({"execution": cfg})

    def test_no_command_configured(self):
        with self.assertRaises(engine.EngineError) as ctx:
            self.build(command=[]).run("hello")
        self.assertIn("no command configured", str(ctx.exception))

    def test_prompt_on_stdin(self):
        adapter = self.build(command=[sys.executable, "-c", ECHO_SCRIPT])
        self.assertTrue(adapter.run("ping").startswith("echo:ping"))

    def test_prompt_substituted_as_single_argument(self):
        adapter = self.build(
            command=[sys.executable, "-c", "import sys; print(sys.argv[1][::-1])", "{prompt}"]
        )
        self.assertEqual(adapter.run("abc"), "cba")

    def test_prompt_is_never_shell_interpreted(self):
        adapter = self.build(
            command=[sys.executable, "-c", "import sys; print(len(sys.argv[1]))", "{prompt}"]
        )
        hostile = "; rm -rf /; $(whoami) `id`"
        self.assertEqual(adapter.run(hostile), str(len(hostile)))

    def test_missing_binary(self):
        with self.assertRaises(engine.EngineError) as ctx:
            self.build(command=["definitely-not-a-real-binary-xyz"]).run("x")
        self.assertIn("not found", str(ctx.exception))

    def test_non_zero_exit_reports_stderr(self):
        adapter = self.build(
            command=[sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]
        )
        with self.assertRaises(engine.EngineError) as ctx:
            adapter.run("x")
        self.assertIn("exited 3", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_empty_output_is_a_failure_not_a_blank_answer(self):
        with self.assertRaises(engine.EngineError):
            self.build(command=[sys.executable, "-c", "pass"]).run("x")

    def test_timeout(self):
        adapter = self.build(
            command=[sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=1
        )
        with self.assertRaises(engine.EngineError) as ctx:
            adapter.run("x")
        self.assertIn("timed out", str(ctx.exception))


class TestOllamaAdapter(unittest.TestCase):
    def adapter(self, base, **over):
        cfg = {"enabled": True, "adapter": "ollama", "base_url": base, "timeout_seconds": 10}
        cfg.update(over)
        return engine.build({"execution": cfg})

    def test_success(self):
        server = FakeOllama("ok")
        server.start()
        try:
            self.assertEqual(self.adapter(server.base).run("hi"), "a reply")
        finally:
            server.stop()

    def test_http_error_is_surfaced(self):
        server = FakeOllama("http_error")
        server.start()
        try:
            with self.assertRaises(engine.EngineError) as ctx:
                self.adapter(server.base).run("hi")
            self.assertIn("500", str(ctx.exception))
        finally:
            server.stop()

    def test_non_json_response(self):
        server = FakeOllama("not_json")
        server.start()
        try:
            with self.assertRaises(engine.EngineError):
                self.adapter(server.base).run("hi")
        finally:
            server.stop()

    def test_missing_content_is_not_treated_as_an_answer(self):
        server = FakeOllama("no_content")
        server.start()
        try:
            with self.assertRaises(engine.EngineError) as ctx:
                self.adapter(server.base).run("hi")
            self.assertIn("no content", str(ctx.exception))
        finally:
            server.stop()

    def test_unreachable(self):
        with self.assertRaises(engine.EngineError) as ctx:
            self.adapter("http://127.0.0.1:1").run("hi")
        self.assertIn("unreachable", str(ctx.exception))


# ---------- executor ----------

class StubAdapter:
    name = "stub"
    available = True

    def __init__(self, reply="a result", fail=None):
        self.reply, self.fail, self.prompts = reply, fail, []

    def describe(self):
        return "stub"

    def run(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise engine.EngineError(self.fail)
        return self.reply


class TestExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = Path(self.tmp.name)
        for f in ("raw", "wiki", "output"):
            (self.v / f).mkdir()
        self.skills = {s["file"]: s for s in skills.load(REPO / "skills")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_strip_frontmatter(self):
        self.assertEqual(executor.strip_frontmatter("---\na: b\n---\n\nBody"), "Body")
        self.assertEqual(executor.strip_frontmatter("No frontmatter"), "No frontmatter")
        self.assertEqual(executor.strip_frontmatter("---\nunterminated\n"), "---\nunterminated")

    def test_prompt_carries_contract_skill_state_and_request(self):
        prompt = executor.build_prompt("CORE", "SKILL", "metrics", {"notes": 3})
        for probe in ("Operating contract", "CORE", "Active skill", "SKILL",
                      "notes: 3", "The operator ran: metrics"):
            self.assertIn(probe, prompt)

    def test_output_path_uses_declared_write_root(self):
        path = executor.output_path(self.skills["metrics.md"], self.v)
        self.assertTrue(path.is_relative_to(self.v / "output"))
        self.assertTrue(path.name.endswith("-metrics.md"))

    def test_skill_declaring_no_writes_writes_nothing(self):
        self.assertIsNone(executor.output_path({"name": "x", "writes": []}, self.v))

    def test_write_root_cannot_escape_the_vault(self):
        for hostile in ("/../../etc", "/../outside", "/.."):
            self.assertIsNone(
                executor.output_path({"name": "x", "writes": [hostile]}, self.v), hostile
            )

    def test_existing_note_is_never_overwritten(self):
        skill = self.skills["metrics.md"]
        now = datetime(2026, 1, 1, 12, 0, 0)
        first = executor.output_path(skill, self.v, now)
        executor.write_output(first, skill, "metrics", "stub", "one")
        second = executor.output_path(skill, self.v, now)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_text(encoding="utf-8").strip().split("\n")[-1], "one")

    def test_written_note_records_provenance(self):
        skill = self.skills["metrics.md"]
        path = executor.write_output(
            executor.output_path(skill, self.v), skill, "metrics", "stub engine", "BODY"
        )
        text = path.read_text(encoding="utf-8")
        for probe in ("skill: metrics", "command: metrics", "engine: stub engine", "BODY"):
            self.assertIn(probe, text)

    def test_successful_run_writes_and_reports(self):
        stub = StubAdapter("## Result\nall good")
        runner = executor.Runner(self.v, REPO / "skills", stub)
        job = runner.run_sync(self.skills["metrics.md"], "metrics", {"notes": 0})
        self.assertEqual(job.status, "done")
        self.assertIsNone(job.error)
        self.assertIn("all good", job.reply)
        self.assertTrue((self.v / job.output.lstrip("/")).is_file())
        self.assertIn("quantitative pulse", stub.prompts[0])

    def test_failed_run_reports_and_writes_nothing(self):
        runner = executor.Runner(self.v, REPO / "skills", StubAdapter(fail="engine offline"))
        job = runner.run_sync(self.skills["metrics.md"], "metrics")
        self.assertEqual(job.status, "failed")
        self.assertIn("engine offline", job.error)
        self.assertIsNone(job.output)
        self.assertEqual(list((self.v / "output").rglob("*.md")), [])

    def test_unexpected_adapter_error_does_not_escape(self):
        class Exploding(StubAdapter):
            def run(self, prompt):
                raise ValueError("kaboom")

        runner = executor.Runner(self.v, REPO / "skills", Exploding())
        job = runner.run_sync(self.skills["metrics.md"], "metrics")
        self.assertEqual(job.status, "failed")
        self.assertIn("kaboom", job.error)

    def test_background_start_completes(self):
        runner = executor.Runner(self.v, REPO / "skills", StubAdapter())
        job = runner.start(self.skills["metrics.md"], "metrics")
        deadline = time.time() + 10
        while time.time() < deadline and runner.get(job.id)["status"] == "running":
            time.sleep(0.05)
        self.assertEqual(runner.get(job.id)["status"], "done")

    def test_job_history_is_newest_first_and_bounded(self):
        runner = executor.Runner(self.v, REPO / "skills", StubAdapter())
        for _ in range(executor.MAX_JOBS + 5):
            runner.run_sync(self.skills["metrics.md"], "metrics")
        self.assertLessEqual(len(runner._order), executor.MAX_JOBS)
        recent = runner.recent(3)
        self.assertEqual(len(recent), 3)

    def test_unknown_job_id(self):
        runner = executor.Runner(self.v, REPO / "skills", StubAdapter())
        self.assertIsNone(runner.get("nope"))


# ---------- execution over HTTP ----------

def exec_cfg(vault, command):
    cfg = base_cfg()
    cfg["paths"] = {**cfg["paths"], "vault": vault}
    cfg["engine"] = {
        **cfg["engine"],
        "execution": {
            "enabled": True,
            "adapter": "command",
            "command": command,
            "timeout_seconds": 30,
        },
    }
    return cfg


class TestExecutionHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = Path(self.tmp.name)
        for f in ("raw", "wiki", "output"):
            (self.v / f).mkdir()
        self.cfg = exec_cfg(self.v, [sys.executable, "-c", ECHO_SCRIPT])

    def tearDown(self):
        app.stop_caches()
        self.tmp.cleanup()

    def test_command_starts_a_job_that_completes(self):
        with Server(self.cfg) as srv:
            status, data = srv.post("/api/command", {"command": "metrics"})
            self.assertEqual(status, 202)
            self.assertTrue(data["routed"])
            self.assertEqual(data["status"], "running")
            job_id = data["job_id"]

            deadline = time.time() + 15
            job = None
            while time.time() < deadline:
                _, body, _ = srv.get(f"/api/jobs/{job_id}")
                job = json.loads(body)
                if job["status"] != "running":
                    break
                time.sleep(0.1)

            self.assertEqual(job["status"], "done", job)
            self.assertIn("echo:", job["reply"])
            self.assertTrue(job["output"].startswith("/output/metrics/"))
            self.assertTrue((self.v / job["output"].lstrip("/")).is_file())

    def test_unknown_job_is_404(self):
        with Server(self.cfg) as srv:
            status, body, _ = srv.get("/api/jobs/doesnotexist")
            self.assertEqual(status, 404)
            self.assertIn("error", json.loads(body))

    def test_jobs_list(self):
        with Server(self.cfg) as srv:
            srv.post("/api/command", {"command": "metrics"})
            _, body, _ = srv.get("/api/jobs")
            self.assertGreaterEqual(len(json.loads(body)["jobs"]), 1)

    def test_health_reports_execution_state(self):
        with Server(self.cfg) as srv:
            _, body, _ = srv.get("/api/health")
            self.assertEqual(
                json.loads(body)["execution"], {"enabled": True, "adapter": "command"}
            )

    def test_config_exposes_state_without_the_command_line(self):
        with Server(self.cfg) as srv:
            _, body, _ = srv.get("/api/config")
            self.assertEqual(
                json.loads(body)["engine"]["execution"],
                {"enabled": True, "adapter": "command"},
            )
            self.assertNotIn(b"-c", body)

    def test_unknown_command_still_does_not_execute(self):
        with Server(self.cfg) as srv:
            status, data = srv.post("/api/command", {"command": "summon dragons"})
            self.assertEqual(status, 200)
            self.assertFalse(data["routed"])
            self.assertNotIn("job_id", data)


class TestExecutionDisabledByDefault(unittest.TestCase):
    def test_repo_config_does_not_execute(self):
        self.assertFalse(config.load()["engine"]["execution"]["enabled"])

    def test_disabled_response_is_unchanged(self):
        with Server(base_cfg()) as srv:
            status, data = srv.post("/api/command", {"command": "metrics"})
            self.assertEqual(status, 200)
            self.assertTrue(data["routed"])
            self.assertIs(data["executed"], False)
            self.assertNotIn("job_id", data)


if __name__ == "__main__":
    unittest.main(verbosity=2, buffer=False)


# ---------- voice ----------

# Fake tools, so the voice path is testable without a model on disk.
# Answers with whisper-style timestamped segments on stdout.
STT_STDOUT = (
    "print('[00:00:00.000 --> 00:00:02.400]   capture milk'); "
    "print('[00:00:02.400 --> 00:00:03.100]   and call mum')"
)
# Writes its transcript to the path it is given, instead of stdout.
STT_TO_FILE = "import sys; open(sys.argv[1], 'w').write('from the output file')"
# Reads the clip from stdin, proving stdin delivery.
STT_FROM_STDIN = "import sys; print('stdin bytes', len(sys.stdin.buffer.read()))"
STT_SILENT = "pass"
STT_ANGRY = "import sys; sys.stderr.write('model file missing'); sys.exit(3)"

# A 44-byte WAV with no frames: enough to prove audio came back.
_WAV = (
    r"b'RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    r"\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'"
)
# Writes a WAV to the path after -o, else to stdout.
TTS_WAV = (
    f"import sys; data = {_WAV}; "
    "out = [a for a in sys.argv if a.endswith('.wav')]; "
    "open(out[0], 'wb').write(data) if out else sys.stdout.buffer.write(data)"
)
# Records the text it was handed, so a test can prove it arrived verbatim.
TTS_CAPTURE = (
    f"import sys; data = {_WAV}; "
    "open(sys.argv[1], 'w').write(sys.argv[2]); "
    "open(sys.argv[3], 'wb').write(data)"
)
TTS_FROM_STDIN = (
    f"import sys; data = {_WAV}; "
    "open(sys.argv[1], 'w').write(sys.stdin.read()); "
    "sys.stdout.buffer.write(data)"
)


def wav_bytes(seconds=0.5, rate=16000):
    """A real 16 kHz mono WAV, the shape the HUD uploads."""
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(i * 0.05)))
        for i in range(int(rate * seconds))
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return buf.getvalue()


def stt_cfg(*args, **extra):
    return {"stt": {"enabled": True, "adapter": "command",
                    "command": [sys.executable, "-c", *args], **extra}}


def tts_cfg(*args, **extra):
    return {"tts": {"enabled": True, "adapter": "command",
                    "command": [sys.executable, "-c", *args], **extra}}


class TestVoiceHelpers(unittest.TestCase):
    def test_is_wav_accepts_a_real_recording(self):
        self.assertTrue(voice.is_wav(wav_bytes(0.1)))

    def test_is_wav_rejects_other_bytes(self):
        for junk in (b"", b"RIFF", b"not audio at all", b"\x00" * 64, b"RIFFxxxxNOPE"):
            self.assertFalse(voice.is_wav(junk), repr(junk[:12]))

    def test_whisper_cpp_timestamps_are_stripped(self):
        text = voice.clean_transcript(
            "[00:00:00.000 --> 00:00:02.400]   capture milk\n"
            "[00:00:02.400 --> 00:00:03.100]   and call mum\n"
        )
        self.assertEqual(text, "capture milk and call mum")

    def test_short_form_timestamps_are_stripped(self):
        self.assertEqual(
            voice.clean_transcript("[00:00.000 --> 00:03.000] plan tomorrow"),
            "plan tomorrow",
        )

    def test_timestamps_are_kept_when_asked(self):
        raw = "[00:00.000 --> 00:03.000] plan tomorrow"
        self.assertEqual(voice.clean_transcript(raw, strip_timestamps=False), raw)

    def test_bracketed_progress_lines_carry_no_speech(self):
        text = voice.clean_transcript("[loading model]\n[BLANK_AUDIO]\nreal words\n")
        self.assertEqual(text, "real words")

    def test_empty_input_is_empty_output(self):
        self.assertEqual(voice.clean_transcript(""), "")
        self.assertEqual(voice.clean_transcript(None), "")


class TestVoiceBuild(unittest.TestCase):
    def test_disabled_by_default(self):
        stt = voice.build_stt({})
        tts = voice.build_tts({})
        self.assertEqual((stt.name, stt.available), ("none", False))
        self.assertEqual((tts.name, tts.available), ("none", False))

    def test_enabled_flag_is_what_decides(self):
        cfg = {"stt": {"enabled": False, "adapter": "command", "command": ["x"]}}
        self.assertEqual(voice.build_stt(cfg).name, "none")

    def test_command_adapters(self):
        self.assertIsInstance(voice.build_stt(stt_cfg("pass")), voice.SttCommand)
        self.assertIsInstance(voice.build_tts(tts_cfg("pass")), voice.TtsCommand)

    def test_browser_tts_is_not_server_side(self):
        tts = voice.build_tts({"tts": {"enabled": True, "adapter": "browser"}})
        self.assertTrue(tts.available)
        self.assertFalse(tts.server_side)
        with self.assertRaises(voice.VoiceError):
            tts.speak("hello")

    def test_unknown_adapter_names_are_refused(self):
        with self.assertRaises(voice.VoiceError):
            voice.build_stt({"stt": {"enabled": True, "adapter": "wishful"}})
        with self.assertRaises(voice.VoiceError):
            voice.build_tts({"tts": {"enabled": True, "adapter": "wishful"}})

    def test_browser_is_not_an_stt_adapter(self):
        # Browser speech recognition ships audio to a vendor; it is not an
        # on-device option, so it is not offered as one.
        with self.assertRaises(voice.VoiceError):
            voice.build_stt({"stt": {"enabled": True, "adapter": "browser"}})

    def test_state_reports_mode(self):
        off = voice.state(voice.SttNone(), voice.TtsNone(), {})
        self.assertEqual(off["tts"]["mode"], "off")
        self.assertFalse(off["tts"]["speak_replies"])
        browser = voice.state(voice.SttNone(), voice.TtsBrowser(), {})
        self.assertEqual(browser["tts"]["mode"], "browser")
        server = voice.state(
            voice.build_stt(stt_cfg("pass")), voice.build_tts(tts_cfg("pass")), {}
        )
        self.assertEqual(server["tts"]["mode"], "server")
        self.assertTrue(server["stt"]["enabled"])

    def test_state_carries_no_command_line(self):
        # The HUD is told the adapter name, never the local command.
        payload = json.dumps(
            voice.state(voice.build_stt(stt_cfg("pass")), voice.build_tts(tts_cfg("pass")), {})
        )
        self.assertNotIn(sys.executable, payload)


class TestSttCommand(unittest.TestCase):
    def setUp(self):
        self.clip = wav_bytes(0.2)

    def test_transcribes_from_a_file_path(self):
        stt = voice.build_stt(stt_cfg(STT_STDOUT, "{audio}"))
        self.assertEqual(stt.transcribe(self.clip), "capture milk and call mum")

    def test_transcribes_from_stdin_when_no_audio_token(self):
        stt = voice.build_stt(stt_cfg(STT_FROM_STDIN))
        self.assertEqual(stt.transcribe(self.clip), f"stdin bytes {len(self.clip)}")

    def test_output_file_wins_over_stdout(self):
        stt = voice.build_stt(stt_cfg(STT_TO_FILE, "{output}", "{audio}"))
        self.assertEqual(stt.transcribe(self.clip), "from the output file")

    def test_non_wav_never_reaches_the_tool(self):
        stt = voice.build_stt(stt_cfg(STT_STDOUT, "{audio}"))
        with self.assertRaises(voice.VoiceError) as caught:
            stt.transcribe(b"this is not audio")
        self.assertIn("WAV", str(caught.exception))

    def test_unset_command_says_so(self):
        stt = voice.build_stt({"stt": {"enabled": True, "adapter": "command", "command": []}})
        with self.assertRaises(voice.VoiceError) as caught:
            stt.transcribe(self.clip)
        self.assertIn("voice.stt.command", str(caught.exception))

    def test_missing_binary_is_reported(self):
        stt = voice.build_stt({"stt": {"enabled": True, "adapter": "command",
                                       "command": ["./no-such-transcriber"]}})
        with self.assertRaises(voice.VoiceError) as caught:
            stt.transcribe(self.clip)
        self.assertIn("not found", str(caught.exception))

    def test_failure_carries_the_tools_own_words(self):
        stt = voice.build_stt(stt_cfg(STT_ANGRY, "{audio}"))
        with self.assertRaises(voice.VoiceError) as caught:
            stt.transcribe(self.clip)
        self.assertIn("model file missing", str(caught.exception))
        self.assertIn("exited 3", str(caught.exception))

    def test_silence_is_not_passed_off_as_speech(self):
        stt = voice.build_stt(stt_cfg(STT_SILENT, "{audio}"))
        with self.assertRaises(voice.VoiceError) as caught:
            stt.transcribe(self.clip)
        self.assertIn("no speech", str(caught.exception))

    def test_a_slow_tool_times_out(self):
        stt = voice.build_stt(
            stt_cfg("import time; time.sleep(5)", "{audio}", timeout_seconds=1)
        )
        with self.assertRaises(voice.VoiceError) as caught:
            stt.transcribe(self.clip)
        self.assertIn("timed out", str(caught.exception))

    def test_the_clip_is_gone_once_the_run_ends(self):
        # The recording is a temporary file and must not outlive the call.
        leaked = []
        stt = voice.build_stt(stt_cfg("import sys; print(sys.argv[1])", "{audio}"))
        leaked.append(stt.transcribe(self.clip))
        self.assertFalse(Path(leaked[0]).exists(), leaked[0])


class TestTtsCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.capture = Path(self.tmp.name) / "said.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_speaks_to_an_output_file(self):
        tts = voice.build_tts(tts_cfg(TTS_WAV, "-o", "{output}", "{text}"))
        audio, content_type = tts.speak("routed to metrics")
        self.assertTrue(voice.is_wav(audio))
        self.assertEqual(content_type, "audio/wav")

    def test_speaks_to_stdout(self):
        tts = voice.build_tts(tts_cfg(TTS_WAV, "{text}"))
        audio, _ = tts.speak("routed to metrics")
        self.assertTrue(voice.is_wav(audio))

    def test_text_goes_on_stdin_when_no_text_token(self):
        tts = voice.build_tts(tts_cfg(TTS_FROM_STDIN, str(self.capture)))
        audio, _ = tts.speak("spoken over stdin")
        self.assertTrue(voice.is_wav(audio))
        self.assertEqual(self.capture.read_text(), "spoken over stdin")

    def test_text_is_never_shell_interpreted(self):
        # The reply is attacker-adjacent: it can carry whatever a note or a
        # model produced. It must arrive as one argument, never as syntax.
        hostile = 'hi"; rm -rf / #$(whoami)`id`'
        tts = voice.build_tts(tts_cfg(TTS_CAPTURE, str(self.capture), "{text}", "{output}"))
        audio, _ = tts.speak(hostile)
        self.assertTrue(voice.is_wav(audio))
        self.assertEqual(self.capture.read_text(), hostile)

    def test_blank_text_is_refused(self):
        tts = voice.build_tts(tts_cfg(TTS_WAV, "{text}"))
        for blank in ("", "   ", None):
            with self.assertRaises(voice.VoiceError):
                tts.speak(blank)

    def test_unset_command_says_so(self):
        tts = voice.build_tts({"tts": {"enabled": True, "adapter": "command", "command": []}})
        with self.assertRaises(voice.VoiceError) as caught:
            tts.speak("hello")
        self.assertIn("voice.tts.command", str(caught.exception))

    def test_silence_is_not_passed_off_as_speech(self):
        tts = voice.build_tts(tts_cfg("pass", "{text}"))
        with self.assertRaises(voice.VoiceError) as caught:
            tts.speak("hello")
        self.assertIn("no audio", str(caught.exception))

    def test_failure_carries_the_tools_own_words(self):
        tts = voice.build_tts(
            tts_cfg("import sys; sys.stderr.write('no voice model'); sys.exit(2)", "{text}")
        )
        with self.assertRaises(voice.VoiceError) as caught:
            tts.speak("hello")
        self.assertIn("no voice model", str(caught.exception))


# ---------- voice over HTTP ----------

def voice_cfg(**voice_block):
    cfg = base_cfg()
    cfg["voice"] = {"stt": {"enabled": False, "adapter": "none"},
                    "tts": {"enabled": False, "adapter": "none"},
                    **voice_block}
    return cfg


class TestVoiceHTTP(unittest.TestCase):
    def setUp(self):
        self.cfg = voice_cfg(
            **stt_cfg(STT_STDOUT, "{audio}"),
            **tts_cfg(TTS_WAV, "-o", "{output}", "{text}"),
        )
        self.clip = wav_bytes(0.2)

    def tearDown(self):
        app.stop_caches()

    def test_state_endpoint_reports_both_directions(self):
        with Server(self.cfg) as srv:
            status, body, _ = srv.get("/api/voice")
            data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data["stt"]["enabled"])
        self.assertEqual(data["tts"]["mode"], "server")

    def test_state_endpoint_leaks_no_paths(self):
        with Server(self.cfg) as srv:
            _, body, _ = srv.get("/api/voice")
        self.assertNotIn(sys.executable.encode(), body)

    def test_a_recording_comes_back_as_text(self):
        with Server(self.cfg) as srv:
            status, body, _ = srv.post_raw("/api/voice/stt", self.clip, "audio/wav")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["text"], "capture milk and call mum")
        self.assertEqual(data["bytes"], len(self.clip))
        self.assertIn("ms", data)

    def test_non_wav_upload_is_refused(self):
        with Server(self.cfg) as srv:
            status, body, _ = srv.post_raw("/api/voice/stt", b"<html>nope</html>", "audio/wav")
        self.assertEqual(status, 415)
        self.assertIn("WAV", json.loads(body)["error"])

    def test_empty_upload_is_refused(self):
        with Server(self.cfg) as srv:
            status, data = srv.post("/api/voice/stt", b"")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "no audio received")

    def test_oversized_upload_gets_its_answer_not_a_broken_pipe(self):
        # The server must read off what the client is still sending before
        # refusing, or the HUD sees a transport error instead of the 413.
        too_much = b"RIFF" + b"\x00" * app.MAX_AUDIO_BYTES
        with Server(self.cfg) as srv:
            status, body, _ = srv.post_raw("/api/voice/stt", too_much, "audio/wav")
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["limit"], app.MAX_AUDIO_BYTES)

    def test_a_failing_transcriber_is_reported_as_a_failure(self):
        cfg = voice_cfg(**stt_cfg(STT_ANGRY, "{audio}"))
        with Server(cfg) as srv:
            status, body, _ = srv.post_raw("/api/voice/stt", self.clip, "audio/wav")
        self.assertEqual(status, 502)
        self.assertIn("model file missing", json.loads(body)["error"])

    def test_speak_returns_audio(self):
        with Server(self.cfg) as srv:
            status, body, content_type = srv.post_raw(
                "/api/voice/speak", json.dumps({"text": "routed to metrics"}).encode(),
                "application/json",
            )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "audio/wav")
        self.assertTrue(voice.is_wav(body))

    def test_speak_needs_something_to_say(self):
        with Server(self.cfg) as srv:
            status, data = srv.post("/api/voice/speak", {"text": "   "})
        self.assertEqual(status, 400)

    def test_health_carries_voice_state(self):
        with Server(self.cfg) as srv:
            _, body, _ = srv.get("/api/health")
        state = json.loads(body)["voice"]
        self.assertTrue(state["stt"]["enabled"])
        self.assertEqual(state["tts"]["mode"], "server")

    def test_voice_routes_are_instrumented(self):
        metrics.reset()
        with Server(self.cfg) as srv:
            srv.post_raw("/api/voice/stt", self.clip, "audio/wav")
            srv.get("/api/voice")
        routes = metrics.snapshot()["routes"]
        self.assertIn("/api/voice/stt", routes)
        self.assertIn("/api/voice", routes)


class TestVoiceOffByDefault(unittest.TestCase):
    def tearDown(self):
        app.stop_caches()

    def test_shipped_config_keeps_voice_off(self):
        cfg = config.load()
        self.assertFalse(cfg["voice"]["stt"]["enabled"])
        self.assertFalse(cfg["voice"]["tts"]["enabled"])

    def test_state_says_off_rather_than_pretending(self):
        with Server(voice_cfg()) as srv:
            _, body, _ = srv.get("/api/voice")
        data = json.loads(body)
        self.assertFalse(data["stt"]["enabled"])
        self.assertEqual(data["tts"]["mode"], "off")
        self.assertFalse(data["tts"]["speak_replies"])

    def test_transcription_while_off_is_a_clear_refusal(self):
        with Server(voice_cfg()) as srv:
            status, body, _ = srv.post_raw("/api/voice/stt", wav_bytes(0.1), "audio/wav")
        self.assertEqual(status, 409)
        self.assertIn("not enabled", json.loads(body)["error"])

    def test_speech_while_off_is_a_clear_refusal(self):
        with Server(voice_cfg()) as srv:
            status, data = srv.post("/api/voice/speak", {"text": "hello"})
        self.assertEqual(status, 409)
        self.assertIn("not enabled", data["error"])

    def test_browser_mode_sends_the_hud_away_empty_handed(self):
        cfg = voice_cfg(tts={"enabled": True, "adapter": "browser"})
        with Server(cfg) as srv:
            status, data = srv.post("/api/voice/speak", {"text": "hello"})
        self.assertEqual(status, 409)
        self.assertEqual(data["mode"], "browser")

    def test_a_bad_adapter_name_degrades_instead_of_falling_over(self):
        # A typo in config must not take the HUD down with it.
        cfg = voice_cfg(stt={"enabled": True, "adapter": "wishful"})
        with Server(cfg) as srv:
            status, body, _ = srv.get("/api/voice")
            health, health_body, _ = srv.get("/api/health")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(health, 200)
        self.assertFalse(data["stt"]["enabled"])
        self.assertIn("wishful", data["error"])


class TestVoiceConfig(unittest.TestCase):
    def setUp(self):
        self.saved = {k: v for k, v in os.environ.items() if k.startswith("ASSISTANT_")}

    def tearDown(self):
        for key in [k for k in os.environ if k.startswith("ASSISTANT_")]:
            del os.environ[key]
        os.environ.update(self.saved)

    def test_env_turns_transcription_on(self):
        os.environ["ASSISTANT_STT"] = "1"
        os.environ["ASSISTANT_STT_ADAPTER"] = "command"
        os.environ["ASSISTANT_STT_COMMAND"] = "whisper-cli -m model.bin -f {audio} -nt"
        stt = config.load()["voice"]["stt"]
        self.assertTrue(stt["enabled"])
        self.assertEqual(
            stt["command"], ["whisper-cli", "-m", "model.bin", "-f", "{audio}", "-nt"]
        )

    def test_quoted_paths_survive_the_split(self):
        os.environ["ASSISTANT_TTS_COMMAND"] = "piper -m '/models/en US/voice.onnx' -f {output}"
        self.assertEqual(
            config.load()["voice"]["tts"]["command"],
            ["piper", "-m", "/models/en US/voice.onnx", "-f", "{output}"],
        )

    def test_flags_read_the_usual_spellings(self):
        for raw, expected in (("1", True), ("true", True), ("ON", True),
                              ("0", False), ("no", False), ("off", False)):
            os.environ["ASSISTANT_TTS"] = raw
            self.assertIs(config.load()["voice"]["tts"]["enabled"], expected, raw)

    def test_replies_can_be_muted_from_the_environment(self):
        os.environ["ASSISTANT_TTS"] = "1"
        os.environ["ASSISTANT_TTS_ADAPTER"] = "browser"
        os.environ["ASSISTANT_TTS_SPEAK_REPLIES"] = "0"
        self.assertFalse(config.load()["voice"]["tts"]["speak_replies"])

    def test_timeouts_take_only_numbers(self):
        os.environ["ASSISTANT_STT_TIMEOUT"] = "45"
        self.assertEqual(config.load()["voice"]["stt"]["timeout_seconds"], 45)
        os.environ["ASSISTANT_STT_TIMEOUT"] = "soon"
        self.assertEqual(config.load()["voice"]["stt"]["timeout_seconds"], 120)
