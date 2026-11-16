"""Validation of JSON Schemas and of input objects against them (jsonschema-rs, Rust core)."""

from __future__ import annotations

from typing import Any

import jsonschema_rs

from .infer import SCHEMA_DIALECT


class SchemaError(ValueError):
    """The document is not a valid JSON Schema."""


def check_schema(schema: Any) -> None:
    """Raise :class:`SchemaError` unless ``schema`` is a valid draft 2020-12 schema object."""
    if not isinstance(schema, dict):
        raise SchemaError("a schema must be a JSON object")
    dialect = schema.get("$schema", SCHEMA_DIALECT)
    if dialect != SCHEMA_DIALECT:
        raise SchemaError(f"only JSON Schema draft 2020-12 is supported, got {dialect!r}")
    try:
        jsonschema_rs.meta.validate(schema)
    except jsonschema_rs.ValidationError as exc:
        raise SchemaError(exc.message) from exc


def _pointer(path: Any) -> str:
    return "".join(f"/{str(p).replace('~', '~0').replace('/', '~1')}" for p in path)


class InputValidator:
    """Compiled validator for one schema version; safe to share between requests."""

    def __init__(self, schema: dict[str, Any]) -> None:
        check_schema(schema)
        self._validator = jsonschema_rs.validator_for(schema, validate_formats=True)

    def is_valid(self, instance: Any) -> bool:
        return bool(self._validator.is_valid(instance))

    def errors(self, instance: Any, limit: int = 50) -> list[dict[str, str]]:
        """Return up to ``limit`` errors as ``{"path": JSON pointer, "message": ...}``."""
        out: list[dict[str, str]] = []
        for err in self._validator.iter_errors(instance):
            out.append({"path": _pointer(err.instance_path), "message": err.message})
            if len(out) >= limit:
                break
        return out
