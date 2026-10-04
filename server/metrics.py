"""Request instrumentation.

AO-0 of the operations patch: nothing about this system's latency can be
claimed without measurement, so the server records how long it actually
spends per route and exposes it for comparison against a baseline.

Samples are bounded per route, so memory stays flat on a long-running
process.
"""

import threading
import time
from collections import deque

MAX_SAMPLES = 512

_lock = threading.Lock()
_routes = {}
_started = time.time()


def _blank():
    return {"count": 0, "errors": 0, "samples": deque(maxlen=MAX_SAMPLES), "last_ms": None}


def record(route, duration_ms, status=200):
    """Record one handled request."""
    with _lock:
        entry = _routes.setdefault(route, _blank())
        entry["count"] += 1
        entry["last_ms"] = round(duration_ms, 3)
        entry["samples"].append(duration_ms)
        if status is None or status >= 400:
            entry["errors"] += 1


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return round(sorted_values[index], 3)


def snapshot():
    """Return per-route latency statistics."""
    with _lock:
        items = [(route, dict(entry, samples=sorted(entry["samples"]))) for route, entry in _routes.items()]

    routes = {}
    for route, entry in items:
        values = entry["samples"]
        routes[route] = {
            "count": entry["count"],
            "errors": entry["errors"],
            "last_ms": entry["last_ms"],
            "min_ms": round(values[0], 3) if values else None,
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
            "max_ms": round(values[-1], 3) if values else None,
        }
    return {
        "uptime_seconds": int(time.time() - _started),
        "sampled_per_route": MAX_SAMPLES,
        "routes": routes,
    }


def reset():
    """Clear all recorded samples. Used by tests and between benchmark runs."""
    with _lock:
        _routes.clear()
