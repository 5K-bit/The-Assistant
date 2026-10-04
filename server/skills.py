"""Skill index: parse the Markdown skill modules into a routable command map.

The frontmatter dialect used by `skills/*.md` is a small, fixed subset of
YAML (scalars plus single-line bracketed lists), so it is parsed here
directly rather than taking on a YAML dependency.
"""

from pathlib import Path

LIST_KEYS = ("commands", "reads", "writes")


def _split_list(raw):
    """Parse `[a, b]` or `["a", "b"]` into a list of strings."""
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]


def parse_frontmatter(text):
    """Return the frontmatter of a skill file as a dict, or {} if absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = _split_list(value)
        else:
            meta[key] = value.strip('"').strip("'")
    for key in LIST_KEYS:
        meta.setdefault(key, [])
    return meta


def load(skills_dir):
    """Read every `*.md` in `skills_dir` into a sorted list of skill records."""
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []
    found = []
    for path in sorted(skills_dir.glob("*.md")):
        try:
            meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        found.append(
            {
                "file": path.name,
                "name": meta.get("name") or path.stem,
                "version": meta.get("version", ""),
                "description": meta.get("description", ""),
                "commands": meta.get("commands", []),
                "reads": meta.get("reads", []),
                "writes": meta.get("writes", []),
                "loaded": bool(meta),
            }
        )
    return found


def command_index(skill_list):
    """Map every declared command to the skill that owns it.

    A command declared by two skills is ambiguous routing, so the
    collision is recorded rather than silently resolved to the last writer.
    """
    index, collisions = {}, {}
    for skill in skill_list:
        for command in skill["commands"]:
            if command in index:
                collisions.setdefault(command, [index[command]]).append(skill["file"])
            else:
                index[command] = skill["file"]
    return index, collisions
