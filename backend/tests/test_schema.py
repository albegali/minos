from __future__ import annotations

from typing import Any

import pytest

from minos.engine.refs import parse_path
from minos.schema import InputValidator, SchemaError, check_schema, infer_schema, resolve_path


def test_infer_single_sample(valid_plan: dict[str, Any]) -> None:
    schema = infer_schema([valid_plan], title="StudyPlan")
    check_schema(schema)
    assert schema["title"] == "StudyPlan"
    assert schema["type"] == "object"
    props = schema["properties"]
    assert props["submittedAt"]["format"] == "date-time"
    assert props["student"]["properties"]["birthDate"]["format"] == "date"
    course = props["courses"]["items"]
    assert course["properties"]["cfu"]["type"] == "integer"
    assert course["required"] == ["area", "cfu", "code", "term", "type"]
    assert InputValidator(schema).is_valid(valid_plan)


def test_infer_merges_samples(valid_plan: dict[str, Any], invalid_plan: dict[str, Any]) -> None:
    schema = infer_schema([valid_plan, invalid_plan])
    student = schema["properties"]["student"]
    assert "scholarship" in student["properties"]
    assert "scholarship" not in student["required"]  # missing in the second sample
    assert InputValidator(schema).is_valid(invalid_plan)


@pytest.mark.parametrize(
    ("samples", "expected"),
    [
        ([1, 2.5], {"type": "number", "examples": [1]}),
        (["a", None], {"type": ["string", "null"], "examples": ["a"]}),
        ([True], {"type": "boolean"}),
        ([[]], {"type": "array", "items": {}}),
        ([None], {"type": "null"}),
        (["x@y.it"], {"type": "string", "format": "email", "examples": ["x@y.it"]}),
        (
            ["123e4567-e89b-12d3-a456-426614174000"],
            {
                "type": "string",
                "format": "uuid",
                "examples": ["123e4567-e89b-12d3-a456-426614174000"],
            },
        ),
        (["2027-02-30"], {"type": "string", "examples": ["2027-02-30"]}),
        (["2027-13-01T10:00:00"], {"type": "string", "examples": ["2027-13-01T10:00:00"]}),
        (["2027-01-01", "x"], {"type": "string", "examples": ["2027-01-01"]}),
        (
            [{"a": 1}, {"b": 2}],
            {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "examples": [1]},
                    "b": {"type": "integer", "examples": [2]},
                },
            },
        ),
    ],
)
def test_infer_types(samples: list[Any], expected: dict[str, Any]) -> None:
    schema = infer_schema(samples)
    schema.pop("$schema")
    assert schema == expected


def test_infer_errors() -> None:
    with pytest.raises(ValueError):
        infer_schema([])
    with pytest.raises(TypeError):
        infer_schema([object()])


def test_validator_errors() -> None:
    schema = infer_schema([{"n": 1, "d": "2027-01-01", "items": [{"x": "a"}]}])
    v = InputValidator(schema)
    errors = v.errors({"n": "one", "d": "2027-02-30", "items": [{"x": 3}]})
    paths = sorted(e["path"] for e in errors)
    assert paths == ["/d", "/items/0/x", "/n"]
    assert len(v.errors({"n": "a", "d": 1, "items": 2}, limit=1)) == 1


@pytest.mark.parametrize(
    "schema",
    [[], {"type": "bogus"}, {"$schema": "http://json-schema.org/draft-07/schema#"}],
)
def test_check_schema_rejects(schema: Any) -> None:
    with pytest.raises(SchemaError):
        check_schema(schema)


SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "$defs": {"course": {"type": "object", "properties": {"cfu": {"type": "integer"}}}},
    "properties": {
        "courses": {"type": "array", "items": {"$ref": "#/$defs/course"}},
        "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "free": {"type": "object"},
        "closed": {"type": "object", "properties": {"a": {}}, "additionalProperties": False},
        "pattern": {"type": "object", "patternProperties": {"^x_": {"type": "number"}}},
        "typed_extra": {"type": "object", "additionalProperties": {"type": "boolean"}},
        "tuple": {"type": "array", "prefixItems": [{"type": "string"}], "items": False},
        "ext": {"$ref": "https://example.com/s.json"},
        "broken": {"$ref": "#/$defs/nope"},
        "mixed": {
            "type": "object",
            "properties": {"k": {"type": "integer"}},
            "allOf": [{"required": ["k"]}],
        },
        "date": {"type": "string", "format": "date"},
        "untyped": {"properties": {"p": {"type": "string"}}},
        "untyped_array": {"items": {"type": "string"}},
    },
}


def resolve(path: str) -> Any:
    return resolve_path(SCHEMA, parse_path(path)[1])


@pytest.mark.parametrize(
    ("path", "types", "many"),
    [
        ("$.input.courses", {"array"}, False),
        ("$.input.courses[*].cfu", {"integer", "number"}, True),
        ("$.input.courses[0].cfu", {"integer", "number"}, False),
        ("$.input.maybe", {"string", "null"}, False),
        ("$.input.free.anything", None, False),
        ("$.input.closed.a", None, False),
        ("$.input.pattern.x_1", {"number"}, False),
        ("$.input.typed_extra.z", {"boolean"}, False),
        ("$.input.tuple[0]", {"string"}, False),
        ("$.input.ext.whatever", None, False),
        ("$.input.mixed.k", {"integer", "number"}, False),
        ("$.input.untyped.p", {"string"}, False),
        ("$.input.untyped_array[*]", {"string"}, True),
    ],
)
def test_resolve_path(path: str, types: set[str] | None, many: bool) -> None:
    node = resolve(path)
    assert node is not None
    assert node.types == (frozenset(types) if types is not None else None)
    assert node.many is many


@pytest.mark.parametrize(
    "path",
    [
        "$.input.nope",
        "$.input.closed.b",
        "$.input.courses.cfu",
        "$.input.courses[*].cfu.x",
        "$.input.broken.x",
        "$.input.date[0]",
        "$.input.pattern.y",
    ],
)
def test_resolve_impossible(path: str) -> None:
    assert resolve(path) is None


def test_formats() -> None:
    node = resolve("$.input.date")
    assert node is not None and node.formats == {"date"}
