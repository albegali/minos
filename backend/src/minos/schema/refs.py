"""References between entities: a schema may use another entity as the type of a field.

Authored form, inside any sub-schema::

    {"$ref": "entity:Course"}        # pinned to Course's latest version when saved
    {"$ref": "entity:Course@2"}      # pinned explicitly

A schema version is stored twice: as written, with every reference pinned (what the user edits
and what the hash covers), and *resolved*: a standalone JSON Schema where each referenced
version sits under ``$defs["entity:<key>@<version>"]`` and references are local
(``#/$defs/entity:Course@2``). Rules, input validation and the Swagger use the resolved form.

Referenced versions are immutable and can only point at versions that existed before them, so
resolution is one level deep (the referenced resolved schemas are already complete) and there
are no cycles.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Mapping
from typing import Any, Final

from .validate import SchemaError

PREFIX: Final = "entity:"
DEFS_REF: Final = "#/$defs/" + PREFIX
_REF = re.compile(r"^entity:([A-Za-z0-9][A-Za-z0-9_.\-]{0,99})(?:@([1-9][0-9]*))?$")
# Keywords whose values are data, not sub-schemas.
_DATA_KEYS: Final = frozenset({"enum", "const", "default", "examples"})
# What may sit next to an entity reference: annotations only. Constraints would silently
# change the referenced entity, so they belong in the entity itself.
_ANNOTATIONS: Final = frozenset(
    {"$ref", "title", "description", "$comment", "deprecated", "readOnly", "writeOnly"} | _DATA_KEYS
)

type EntityRef = tuple[str, int | None]


def def_key(entity: str, version: int) -> str:
    """Key of a referenced version under ``$defs`` (and in local references)."""
    return f"{PREFIX}{entity}@{version}"


def parse_ref(value: Any) -> EntityRef | None:
    """``"entity:Course@2"`` -> ``("Course", 2)``; ``None`` if not an entity reference."""
    if not isinstance(value, str):
        return None
    m = _REF.match(value)
    if m is None:
        if value.startswith(PREFIX):
            raise SchemaError(
                f"invalid entity reference {value!r} (use 'entity:<key>' or 'entity:<key>@<n>')"
            )
        return None
    return m.group(1), int(m.group(2)) if m.group(2) else None


# Keywords whose value maps names to sub-schemas: the names are the user's (a property may well
# be called "default" or "enum"), so they are never mistaken for keywords.
_SCHEMA_MAPS: Final = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
)


def _subschemas(node: Any) -> Iterator[dict[str, Any]]:
    """Every dict reachable from ``node`` through schema positions (data keywords skipped)."""
    if isinstance(node, dict):
        yield node
        for k, v in node.items():
            if k in _SCHEMA_MAPS and isinstance(v, dict):
                for sub in v.values():
                    yield from _subschemas(sub)
            elif k not in _DATA_KEYS:
                yield from _subschemas(v)
    elif isinstance(node, list):
        for v in node:
            yield from _subschemas(v)


def find_refs(schema: dict[str, Any]) -> list[EntityRef]:
    """Entity references of an authored schema, in document order, without duplicates.

    Raises :class:`SchemaError` for malformed references or constraints next to them.
    """
    out: list[EntityRef] = []
    for node in _subschemas(schema):
        ref = parse_ref(node.get("$ref"))
        if ref is None:
            continue
        extra = sorted(k for k in node if k not in _ANNOTATIONS and not k.startswith("x-"))
        if extra:
            raise SchemaError(
                f"the reference to {node['$ref']!r} can only carry annotations (title, "
                f"description), not {', '.join(extra)}: put constraints in the entity itself"
            )
        if ref not in out:
            out.append(ref)
    return out


def pin_refs(schema: dict[str, Any], latest: Mapping[str, int]) -> dict[str, Any]:
    """Copy of ``schema`` with every unversioned reference pinned to ``latest[entity]``."""
    out = copy.deepcopy(schema)
    for node in _subschemas(out):
        ref = parse_ref(node.get("$ref"))
        if ref is not None and ref[1] is None:
            if ref[0] not in latest:
                raise SchemaError(f"no version of entity {ref[0]!r} to pin the reference to")
            node["$ref"] = def_key(ref[0], latest[ref[0]])
    return out


def repin_refs(schema: dict[str, Any], versions: Mapping[tuple[str, int], int]) -> dict[str, Any]:
    """Copy of a pinned ``schema`` with ``entity:K@v`` moved to ``entity:K@versions[(K, v)]``
    (used when a schema moves to a workspace where the same entities have other numbers)."""
    out = copy.deepcopy(schema)
    for node in _subschemas(out):
        ref = parse_ref(node.get("$ref"))
        if ref is not None and ref[1] is not None and ref in versions:
            node["$ref"] = def_key(ref[0], versions[(ref[0], ref[1])])
    return out


def _relocate(node: Any, base: str) -> None:
    """Rewrite the local references of a schema moved under ``base`` (a JSON pointer), except
    those to hoisted entity definitions, which stay at the root."""
    for sub in _subschemas(node):
        ref = sub.get("$ref")
        if isinstance(ref, str) and ref.startswith("#") and not ref.startswith(DEFS_REF):
            sub["$ref"] = "#" + base + ref[1:]


def _put(defs: dict[str, Any], key: str, schema: Any) -> None:
    if key in defs and defs[key] != schema:
        raise SchemaError(f"two different definitions of {key!r}")
    defs[key] = schema


def resolve_refs(
    schema: dict[str, Any], targets: Mapping[tuple[str, int], dict[str, Any]]
) -> dict[str, Any]:
    """Resolved form of a *pinned* schema: ``targets`` maps every referenced ``(entity,
    version)`` to that version's resolved schema. Without references, returns ``schema``."""
    refs = find_refs(schema)
    if not refs:
        return schema
    out = copy.deepcopy(schema)
    hoisted: dict[str, Any] = {}
    for entity, version in refs:
        assert version is not None, "pin the references first"
        target = copy.deepcopy(targets[(entity, version)])
        for k in ("$schema", "$id"):
            target.pop(k, None)
        # Entities the referenced version itself refers to are already resolved under its
        # $defs: lift them to the root so that every entity is defined once.
        own_defs = target.get("$defs")
        if isinstance(own_defs, dict):
            for k in [k for k in own_defs if k.startswith(PREFIX)]:
                _put(hoisted, k, own_defs.pop(k))
            if not own_defs:
                del target["$defs"]
        key = def_key(entity, version)
        _relocate(target, f"/$defs/{key}")
        _put(hoisted, key, target)
    for node in _subschemas(out):
        ref = parse_ref(node.get("$ref"))
        if ref is not None:
            node["$ref"] = "#/$defs/" + def_key(ref[0], ref[1] or 0)
    defs = out.setdefault("$defs", {})
    if not isinstance(defs, dict):
        raise SchemaError("$defs must be an object")
    for k, v in hoisted.items():
        _put(defs, k, v)
    return out
