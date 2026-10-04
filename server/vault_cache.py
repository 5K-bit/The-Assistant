"""Prepared vault state.

AO-2 of the operations patch. Serving `stats`, `activity` and `graph`
straight from disk meant three independent traversals per HUD refresh,
and the cost grew with the vault. This keeps one snapshot warm in the
background so a request reads prepared state instead of waiting on a
filesystem walk.

Every snapshot carries when it was built, and the API passes that age
through: prepared state without an age is a number you cannot trust.
"""

import threading
import time
from datetime import datetime, timezone

from . import vault


class VaultCache:
    """A background-refreshed snapshot of the vault."""

    def __init__(self, vault_dir, interval=10.0):
        self.vault_dir = vault_dir
        self.interval = max(1.0, float(interval))
        self._lock = threading.Lock()
        self._snapshot = None
        self._built_at = None  # monotonic
        self._stop = threading.Event()
        self._thread = None

    # --- building -----------------------------------------------------

    def _build(self):
        start = time.perf_counter()
        data = vault.scan(self.vault_dir)
        build_ms = (time.perf_counter() - start) * 1000
        return {
            **data,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "build_ms": round(build_ms, 3),
        }

    def refresh(self):
        """Rebuild the snapshot now. Keeps the previous one on failure."""
        try:
            snapshot = self._build()
        except OSError:
            # A vault that has gone away should not take the server with
            # it; the existing snapshot keeps serving and ages visibly.
            return self._snapshot
        with self._lock:
            self._snapshot = snapshot
            self._built_at = time.monotonic()
        return snapshot

    def snapshot(self):
        """Return the current snapshot, building one if none exists yet."""
        with self._lock:
            current, built_at = self._snapshot, self._built_at
        if current is None:
            self.refresh()
            with self._lock:
                current, built_at = self._snapshot, self._built_at
        if current is None:
            return None
        age_ms = round((time.monotonic() - built_at) * 1000, 1) if built_at else None
        return {**current, "age_ms": age_ms}

    # --- lifecycle ----------------------------------------------------

    def _loop(self):
        while not self._stop.wait(self.interval):
            self.refresh()

    def start(self):
        if self._thread is not None:
            return self
        self.refresh()
        self._thread = threading.Thread(target=self._loop, name="vault-cache", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)
