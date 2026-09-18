"""Vault reader: counts, recent activity, and the wikilink graph.

Everything here is measured from the Markdown on disk. An empty vault
reports zeros; it never reports an estimate.
"""

import re
from datetime import datetime
from pathlib import Path

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
FOLDERS = ("raw", "wiki", "output")


def _notes(vault_dir):
    """Yield (folder, path) for every Markdown note in the vault."""
    for folder in FOLDERS:
        base = Path(vault_dir) / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if path.is_file():
                yield folder, path


def stats(vault_dir):
    """Count notes per folder, total wikilinks, and bytes on disk."""
    per_folder = {folder: 0 for folder in FOLDERS}
    links = 0
    size = 0
    for folder, path in _notes(vault_dir):
        per_folder[folder] += 1
        try:
            size += path.stat().st_size
            links += len(WIKILINK.findall(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return {
        "notes": sum(per_folder.values()),
        "links": links,
        "bytes": size,
        **per_folder,
    }


def activity(vault_dir, limit=8):
    """Return the most recently modified notes, newest first.

    The reported type is the vault folder the note lives in — an observed
    fact — rather than an inferred action such as DISTILL or LINK.
    """
    rows = []
    for folder, path in _notes(vault_dir):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        rows.append(
            {
                "time": datetime.fromtimestamp(mtime).strftime("%H:%M:%S"),
                "type": folder.upper(),
                "path": "/" + str(path.relative_to(vault_dir)).replace("\\", "/"),
                "mtime": mtime,
            }
        )
    rows.sort(key=lambda row: row["mtime"], reverse=True)
    return rows[:limit]


def graph(vault_dir, limit=7):
    """Return the most-connected note and its immediate neighbourhood."""
    folder_of, edges, degree = {}, set(), {}
    for folder, path in _notes(vault_dir):
        stem = path.stem
        folder_of[stem] = folder
        degree.setdefault(stem, 0)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for target in WIKILINK.findall(text):
            target = target.strip()
            if not target or target == stem:
                continue
            edges.add(tuple(sorted((stem, target))))
            degree[stem] = degree.get(stem, 0) + 1
            degree[target] = degree.get(target, 0) + 1

    if not degree:
        return {"nodes": [], "edges": []}

    center = max(degree, key=lambda node: (degree[node], node))
    neighbours = [b if a == center else a for a, b in edges if center in (a, b)]
    keep = [center] + sorted(set(neighbours), key=lambda n: -degree.get(n, 0))[: limit - 1]
    keep_set = set(keep)

    return {
        "nodes": [
            {"id": node, "folder": folder_of.get(node, "wiki"), "degree": degree.get(node, 0)}
            for node in keep
        ],
        "edges": [
            {"source": a, "target": b} for a, b in sorted(edges) if a in keep_set and b in keep_set
        ],
    }
