"""Structured differences between two rule graph documents (versions or a draft).

Editor-only data (``ui``) and the ``version`` stamp are ignored, so moving nodes on the
canvas or publishing does not show up as a change.
"""

from __future__ import annotations

from typing import Any

IGNORED = frozenset({"ui", "version"})

type Change = dict[str, Any]


def _changes(old: Any, new: Any, path: str, out: list[Change]) -> None:
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys(), key=str):
            sub = f"{path}.{key}" if path else str(key)
            if key not in old:
                out.append({"path": sub, "kind": "added", "to": new[key]})
            elif key not in new:
                out.append({"path": sub, "kind": "removed", "from": old[key]})
            else:
                _changes(old[key], new[key], sub, out)
        return
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for i, (a, b) in enumerate(zip(old, new, strict=True)):
            _changes(a, b, f"{path}[{i}]", out)
        return
    out.append({"path": path, "kind": "changed", "from": old, "to": new})


def _edge_key(e: dict[str, Any]) -> str:
    return f"{e.get('from')}:{e.get('on', 'next')}->{e.get('to')}"


def diff_graphs(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Return added/removed/changed nodes, added/removed edges and other top-level changes."""
    old_nodes = {n["id"]: n for n in old.get("nodes", []) if isinstance(n, dict) and "id" in n}
    new_nodes = {n["id"]: n for n in new.get("nodes", []) if isinstance(n, dict) and "id" in n}
    changed = []
    for nid in sorted(old_nodes.keys() & new_nodes.keys()):
        found: list[Change] = []
        _changes(old_nodes[nid], new_nodes[nid], "", found)
        if found:
            changed.append({"id": nid, "type": new_nodes[nid].get("type"), "changes": found})

    old_edges = {_edge_key(e) for e in old.get("edges", []) if isinstance(e, dict)}
    new_edges = {_edge_key(e) for e in new.get("edges", []) if isinstance(e, dict)}

    other: list[Change] = []
    skip = IGNORED | {"nodes", "edges"}
    _changes(
        {k: v for k, v in old.items() if k not in skip},
        {k: v for k, v in new.items() if k not in skip},
        "",
        other,
    )

    nodes = {
        "added": [new_nodes[i] for i in sorted(new_nodes.keys() - old_nodes.keys())],
        "removed": [old_nodes[i] for i in sorted(old_nodes.keys() - new_nodes.keys())],
        "changed": changed,
    }
    edges = {
        "added": sorted(new_edges - old_edges),
        "removed": sorted(old_edges - new_edges),
    }
    total = (
        len(nodes["added"])
        + len(nodes["removed"])
        + len(changed)
        + len(edges["added"])
        + len(edges["removed"])
        + len(other)
    )
    return {"identical": total == 0, "nodes": nodes, "edges": edges, "other": other}
