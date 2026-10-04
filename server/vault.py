"""Vault reader: counts, recent activity, and the wikilink graph.

Everything here is measured from the Markdown on disk. An empty vault
reports zeros; it never reports an estimate.

`scan()` traverses the vault once and derives all three views from that
single pass. The individual `stats`/`activity`/`graph` helpers remain for
direct use, but the server reads through `vault_cache`, which keeps a
prepared snapshot warm so a request never waits on a traversal.
"""

import re
from datetime import datetime
from pathlib import Path

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
FOLDERS = ("raw", "wiki", "output")


def _collect(vault_dir):
    """Walk the vault once, returning one record per Markdown note."""
    vault_dir = Path(vault_dir)
    records = []
    for folder in FOLDERS:
        base = vault_dir / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = None

            stem = path.stem
            raw_links = WIKILINK.findall(text) if text is not None else []
            targets = []
            for target in raw_links:
                target = target.strip()
                if target and target != stem:
                    targets.append(target)

            records.append(
                {
                    "folder": folder,
                    "stem": stem,
                    "rel": str(path.relative_to(vault_dir)).replace("\\", "/"),
                    "mtime": stat.st_mtime,
                    "size": stat.st_size if text is not None else 0,
                    "link_count": len(raw_links),
                    "targets": targets,
                    "readable": text is not None,
                }
            )
    return records


def _stats_from(records):
    per_folder = {folder: 0 for folder in FOLDERS}
    links = 0
    size = 0
    for record in records:
        per_folder[record["folder"]] += 1
        if record["readable"]:
            size += record["size"]
            links += record["link_count"]
    return {"notes": len(records), "links": links, "bytes": size, **per_folder}


def _activity_from(records, limit):
    """Most recently modified notes, newest first.

    The reported type is the vault folder the note lives in — an observed
    fact — rather than an inferred action such as DISTILL or LINK.
    """
    rows = [
        {
            "time": datetime.fromtimestamp(record["mtime"]).strftime("%H:%M:%S"),
            "type": record["folder"].upper(),
            "path": "/" + record["rel"],
            "mtime": record["mtime"],
        }
        for record in records
    ]
    rows.sort(key=lambda row: row["mtime"], reverse=True)
    return rows[:limit]


def _graph_from(records, limit):
    """The most-connected note and its immediate neighbourhood."""
    folder_of, edges, degree = {}, set(), {}
    for record in records:
        stem = record["stem"]
        folder_of[stem] = record["folder"]
        degree.setdefault(stem, 0)
        for target in record["targets"]:
            edges.add(tuple(sorted((stem, target))))
            degree[stem] = degree.get(stem, 0) + 1
            degree[target] = degree.get(target, 0) + 1

    # No links at all means there is no neighbourhood to draw. Guarding on
    # `degree` alone would pass here, since every note gets a zero entry.
    if not edges:
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


def scan(vault_dir, activity_limit=8, graph_limit=7):
    """Traverse the vault once and derive every view the API serves."""
    records = _collect(vault_dir)
    return {
        "stats": _stats_from(records),
        "activity": _activity_from(records, activity_limit),
        "graph": _graph_from(records, graph_limit),
    }


def stats(vault_dir):
    """Count notes per folder, total wikilinks, and bytes on disk."""
    return _stats_from(_collect(vault_dir))


def activity(vault_dir, limit=8):
    """Return the most recently modified notes, newest first."""
    return _activity_from(_collect(vault_dir), limit)


def graph(vault_dir, limit=7):
    """Return the most-connected note and its immediate neighbourhood."""
    return _graph_from(_collect(vault_dir), limit)
