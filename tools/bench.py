#!/usr/bin/env python3
"""Latency benchmark for The Assistant's API.

AO-0: capture a baseline before a change, compare after it. Targets come
from the operations patch; this reports measured numbers against them
rather than assuming an improvement.

    python3 tools/bench.py --save baseline.json
    python3 tools/bench.py --compare baseline.json
"""

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

ENDPOINTS = [
    "/api/health",
    "/api/config",
    "/api/vitals",
    "/api/skills",
    "/api/vault/stats",
    "/api/vault/activity",
    "/api/vault/graph",
]

# The HUD refreshes the vault panel by firing these three together, so the
# wall-clock time of the group is what an operator actually waits for.
HUD_VAULT_REFRESH = ["/api/vault/stats", "/api/vault/activity", "/api/vault/graph"]

TARGET_MS = {"hud_vault_refresh": 250.0, "cached_service_query": 100.0}


def fetch(url, timeout=30):
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            res.read()
            ok = True
    except (urllib.error.URLError, OSError):
        ok = False
    return (time.perf_counter() - start) * 1000, ok


def summarise(samples):
    ordered = sorted(samples)
    return {
        "runs": len(ordered),
        "min_ms": round(ordered[0], 2),
        "mean_ms": round(statistics.fmean(ordered), 2),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))], 2),
        "max_ms": round(ordered[-1], 2),
    }


def bench_endpoint(base, path, runs):
    samples, failures = [], 0
    for _ in range(runs):
        elapsed, ok = fetch(base + path)
        samples.append(elapsed)
        failures += 0 if ok else 1
    result = summarise(samples)
    result["failures"] = failures
    return result


def bench_hud_vault_refresh(base, runs):
    """Time the three vault calls fired concurrently, as the HUD does."""
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        threads = [threading.Thread(target=fetch, args=(base + p,)) for p in HUD_VAULT_REFRESH]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        samples.append((time.perf_counter() - start) * 1000)
    return summarise(samples)


def run(base, runs, warmup):
    for path in ENDPOINTS:
        for _ in range(warmup):
            fetch(base + path)

    results = {path: bench_endpoint(base, path, runs) for path in ENDPOINTS}
    results["hud_vault_refresh"] = bench_hud_vault_refresh(base, runs)
    return {"base": base, "runs": runs, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results}


def print_table(report, baseline=None):
    print(f"\n{'endpoint':<26} {'mean':>9} {'p95':>9} {'max':>9}  vs baseline")
    print("-" * 74)
    for name, stats in report["results"].items():
        line = f"{name:<26} {stats['mean_ms']:>8.1f}ms {stats['p95_ms']:>8.1f}ms {stats['max_ms']:>8.1f}ms"
        if baseline and name in baseline["results"]:
            before = baseline["results"][name]["mean_ms"]
            after = stats["mean_ms"]
            if before > 0:
                change = (after - before) / before * 100
                arrow = "faster" if change < 0 else "slower"
                line += f"  {before:.1f}ms -> {after:.1f}ms ({abs(change):.0f}% {arrow})"
        print(line)

    print()
    for name, target in TARGET_MS.items():
        if name in report["results"]:
            mean = report["results"][name]["mean_ms"]
            verdict = "PASS" if mean <= target else "OVER"
            print(f"target {name} <= {target:.0f}ms : {mean:.1f}ms  [{verdict}]")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7777")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--save", metavar="FILE", help="write this run as a baseline")
    parser.add_argument("--compare", metavar="FILE", help="compare this run against a saved baseline")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    _, ok = fetch(base + "/api/health", timeout=5)
    if not ok:
        print(f"no server answering at {base} — start it with: python3 -m server", file=sys.stderr)
        return 2

    report = run(base, args.runs, args.warmup)

    baseline = None
    if args.compare:
        try:
            with open(args.compare, encoding="utf-8") as handle:
                baseline = json.load(handle)
        except OSError as exc:
            print(f"could not read baseline: {exc}", file=sys.stderr)
            return 2

    print_table(report, baseline)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(f"\nbaseline written to {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
