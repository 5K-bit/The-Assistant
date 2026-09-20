"""Test suite for The Assistant backend. Stdlib only."""

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from server import app, config, metrics, skills, vault, vault_cache, vitals  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2, buffer=False)
