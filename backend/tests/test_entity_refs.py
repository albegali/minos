"""Entities referencing other entities: pinning, resolution, and rule sets over the result."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from minos.schema import InputValidator, SchemaError, find_refs, pin_refs, resolve_path
from minos.schema.refs import parse_ref, resolve_refs

from .test_platform import admin, client, eventually  # noqa: F401  (fixtures)

# --------------------------------------------------------------------------- pure functions

COURSE = {
    "type": "object",
    "properties": {"code": {"type": "string"}, "cfu": {"type": "integer"}},
    "required": ["code", "cfu"],
}


def test_parse_ref() -> None:
    assert parse_ref("entity:Course") == ("Course", None)
    assert parse_ref("entity:Course@2") == ("Course", 2)
    assert parse_ref("#/$defs/x") is None
    assert parse_ref(3) is None
    for bad in ("entity:", "entity:Course@0", "entity:Course@x", "entity:a b"):
        with pytest.raises(SchemaError, match="invalid entity reference"):
            parse_ref(bad)


def test_find_and_pin_refs() -> None:
    doc = {
        "type": "object",
        "properties": {
            "main": {"$ref": "entity:Course", "description": "the main course"},
            "others": {"type": "array", "items": {"$ref": "entity:Course"}},
            "student": {"$ref": "entity:Student@3"},
            "note": {"const": {"$ref": "entity:NotAReference"}},  # data, not a schema
        },
    }
    assert find_refs(doc) == [("Course", None), ("Student", 3)]
    pinned = pin_refs(doc, {"Course": 2})
    assert pinned["properties"]["main"]["$ref"] == "entity:Course@2"
    assert pinned["properties"]["others"]["items"]["$ref"] == "entity:Course@2"
    assert pinned["properties"]["student"]["$ref"] == "entity:Student@3"
    assert doc["properties"]["main"]["$ref"] == "entity:Course"  # input untouched


def test_constraints_next_to_a_reference_are_rejected() -> None:
    with pytest.raises(SchemaError, match="only carry annotations"):
        find_refs({"$ref": "entity:Course", "required": ["code"]})
    assert find_refs({"$ref": "entity:Course", "title": "T", "x-ui": 1}) == [("Course", None)]


def test_resolve_refs_bundles_and_hoists() -> None:
    # Program@1 already embeds Course@1 and has a local definition of its own.
    program = resolve_refs(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "code": {"$ref": "#/$defs/code"},
                "courses": {"type": "array", "items": {"$ref": "entity:Course@1"}},
            },
            "$defs": {"code": {"type": "string", "pattern": "^[A-Z]+$"}},
        },
        {("Course", 1): COURSE},
    )
    assert program["properties"]["courses"]["items"] == {"$ref": "#/$defs/entity:Course@1"}
    assert program["$defs"]["entity:Course@1"] == COURSE

    enrollment = resolve_refs(
        {
            "type": "object",
            "properties": {
                "program": {"$ref": "entity:Program@1"},
                "extra": {"$ref": "entity:Course@1"},
            },
        },
        {("Program", 1): program, ("Course", 1): COURSE},
    )
    defs = enrollment["$defs"]
    assert set(defs) == {"entity:Program@1", "entity:Course@1"}  # Course hoisted, once
    moved = defs["entity:Program@1"]
    assert "$schema" not in moved
    assert moved["properties"]["code"] == {"$ref": "#/$defs/entity:Program@1/$defs/code"}
    assert moved["properties"]["courses"]["items"] == {"$ref": "#/$defs/entity:Course@1"}

    # the result is a valid standalone schema, and paths resolve through the references
    v = InputValidator(enrollment)
    good = {"program": {"code": "MBA", "courses": [{"code": "A", "cfu": 6}]}}
    assert v.is_valid(good)
    bad = {"program": {"code": "mba", "courses": [{"code": "A", "cfu": "6"}]}}
    assert {e["path"] for e in v.errors(bad)} == {"/program/code", "/program/courses/0/cfu"}
    node = resolve_path(enrollment, ("program", "courses", object(), "cfu"))
    assert node is not None and node.types == {"integer", "number"}
    assert resolve_path(enrollment, ("program", "nope")) is None


def test_resolve_without_refs_and_conflicts() -> None:
    plain = {"type": "object"}
    assert resolve_refs(plain, {}) is plain
    with pytest.raises(SchemaError, match="two different definitions"):
        resolve_refs(
            {"properties": {"c": {"$ref": "entity:Course@1"}}, "$defs": {"entity:Course@1": {}}},
            {("Course", 1): COURSE},
        )
    with pytest.raises(SchemaError, match=r"\$defs must be an object"):
        resolve_refs(
            {"properties": {"c": {"$ref": "entity:Course@1"}}, "$defs": []}, {("Course", 1): COURSE}
        )


# --------------------------------------------------------------------------- end to end

WS = "/v1/workspaces/uni"
RS = f"{WS}/rulesets/enrollment"
EXEC = "/v1/exec/uni/enrollment"

STUDENT = {"id": "S1", "name": "Ada", "age": 30}
COURSES = [{"code": "FIN", "cfu": 30}, {"code": "MKT", "cfu": 30}]
PROGRAM = {"code": "EMBA", "minCfu": 60, "courses": COURSES}
ENROLLMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "student": {"$ref": "entity:Student", "description": "Who enrolls"},
        "program": {"$ref": "entity:Program"},
        "plan": {
            "type": "object",
            "properties": {"courses": {"type": "array", "items": {"type": "string"}}},
            "required": ["courses"],
        },
    },
    "required": ["student", "program", "plan"],
}
GRAPH = {
    "rgdVersion": "1.0",
    "ruleset": "enrollment",
    "settings": {"mode": "collect_all"},
    "nodes": [
        {"id": "start", "type": "start"},
        {
            "id": "adult",
            "type": "condition",
            "condition": {"op": ">=", "left": {"ref": "$.input.student.age"}, "right": 18},
            "feedback": {"fail": {"code": "MINOR", "message": "{{input.student.name}} is a minor"}},
        },
        {
            "id": "offered",
            "type": "condition",
            "condition": {
                "fn": "all",
                "args": [{"ref": "$.input.plan.courses"}],
                "select": {
                    "op": "in",
                    "left": {"ref": "$.item"},
                    "right": {"ref": "$.input.program.courses[*].code"},
                },
            },
            "feedback": {"fail": {"code": "NOT_OFFERED", "message": "course not offered"}},
        },
        {
            "id": "cfu",
            "type": "condition",
            "condition": {
                "op": ">=",
                "left": {"fn": "sum", "args": [{"ref": "$.input.program.courses[*].cfu"}]},
                "right": {"ref": "$.input.program.minCfu"},
            },
        },
        {"id": "end", "type": "end", "outcome": "valid"},
    ],
    "edges": [
        {"from": "start", "to": "adult"},
        {"from": "adult", "to": "offered", "on": "pass"},
        {"from": "offered", "to": "cfu", "on": "pass"},
        {"from": "cfu", "to": "end", "on": "pass"},
    ],
}


async def _entity(c: httpx.AsyncClient, h: dict[str, str], key: str, body: Any) -> dict[str, Any]:
    r = await c.post(f"{WS}/entities", json={"key": key, "name": key}, headers=h)
    assert r.status_code == 201, r.text
    r = await c.post(f"{WS}/entities/{key}/schemas", json=body, headers=h)
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


async def test_rule_set_over_several_entities(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
) -> None:
    c, h = client, admin
    assert (await c.post("/v1/workspaces", json={"slug": "uni", "name": "U"}, headers=h)).is_success
    await _entity(c, h, "Student", {"samples": [STUDENT]})
    await _entity(c, h, "Course", {"samples": COURSES})
    program = await _entity(
        c,
        h,
        "Program",
        {
            "schema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "minCfu": {"type": "integer"},
                    "courses": {"type": "array", "items": {"$ref": "entity:Course"}},
                },
                "required": ["code", "courses"],
            }
        },
    )
    assert program["references"] == [{"entity": "Course", "version": 1, "latest": 1}]
    assert program["schema"]["properties"]["courses"]["items"] == {"$ref": "entity:Course@1"}

    enrollment = await _entity(c, h, "Enrollment", {"schema": ENROLLMENT_SCHEMA})
    assert [r["entity"] for r in enrollment["references"]] == ["Student", "Program"]
    assert set(enrollment["resolved"]["$defs"]) == {
        "entity:Student@1",
        "entity:Program@1",
        "entity:Course@1",
    }
    info = (await c.get(f"{WS}/entities/Course", headers=h)).json()
    assert info["usedBy"] == ["Program"]

    # the rule set reads every entity through $.input: typos are caught at validation
    body = {"key": "enrollment", "name": "Enrollment", "entity": "Enrollment", "graph": GRAPH}
    assert (await c.post(f"{WS}/rulesets", json=body, headers=h)).status_code == 201
    assert (await c.post(f"{RS}/validate", headers=h)).json()["valid"] is True
    broken = dict(GRAPH, constants={})
    broken["nodes"] = [
        *GRAPH["nodes"][:-1],
        {
            "id": "end",
            "type": "end",
            "outcome": "valid",
            "output": {"x": {"ref": "$.input.student.nope"}},
        },
    ]
    r = await c.put(f"{RS}/draft", json={"graph": broken}, headers=h)
    assert r.status_code == 200, r.text
    issues = (await c.post(f"{RS}/validate", headers=h)).json()["issues"]
    assert any("student.nope" in i["message"] for i in issues)
    await c.put(f"{RS}/draft", json={"graph": GRAPH}, headers=h)

    payload = {"student": STUDENT, "program": PROGRAM, "plan": {"courses": ["FIN", "LAW"]}}
    sim = (await c.post(f"{RS}/simulate", json={"input": payload}, headers=h)).json()
    assert [f["code"] for f in sim["feedback"]] == ["NOT_OFFERED"]

    # published and executed: the input is validated against every embedded entity
    r = await c.post(f"{RS}/publish", json={"promoteTo": "prod"}, headers=h)
    assert r.status_code == 201, r.text
    key = await c.post(f"{WS}/api-keys", json={"name": "k", "scopes": ["exec"]}, headers=h)
    exec_h = {"X-Api-Key": key.json()["key"]}

    async def deployed() -> bool:
        return (await c.post(EXEC, json={"input": payload}, headers=exec_h)).status_code == 200

    await eventually(deployed)
    ok = {**payload, "plan": {"courses": ["FIN"]}}
    assert (await c.post(EXEC, json={"input": ok}, headers=exec_h)).json()["outcome"] == "valid"
    wrong = {**ok, "program": {**PROGRAM, "courses": [{"code": "FIN", "cfu": "30"}]}}
    r = await c.post(EXEC, json={"input": wrong}, headers=exec_h)
    assert r.status_code == 400
    assert [e["path"] for e in r.json()["errors"]] == ["/program/courses/0/cfu"]

    # the Swagger embeds the whole composite schema
    doc = (await c.get("/v1/exec/openapi.json", headers=exec_h)).json()
    (component,) = [v for k, v in doc["components"]["schemas"].items() if "$defs" in v]
    assert "entity:Course@1" in component["$defs"]

    # the bundle is standalone: it imports where the referenced entities do not exist
    bundle = (await c.get(f"{RS}/export", headers=h)).json()
    assert "entity:Program@1" in bundle["schema"]["$defs"]
    assert (await c.post("/v1/workspaces", json={"slug": "u2", "name": "U2"}, headers=h)).is_success
    r = await c.post("/v1/workspaces/u2/import", json=bundle, headers=h)
    assert r.status_code == 201, r.text
    r = await c.post("/v1/workspaces/u2/rulesets/enrollment/validate", headers=h)
    assert r.json()["valid"] is True


async def test_reference_versions(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
) -> None:
    c, h = client, admin
    assert (await c.post("/v1/workspaces", json={"slug": "uni", "name": "U"}, headers=h)).is_success
    await _entity(c, h, "Course", {"samples": COURSES})
    wrapper = {"type": "object", "properties": {"c": {"$ref": "entity:Course"}}}
    first = await _entity(c, h, "Wrapper", {"schema": wrapper})
    assert first["version"] == 1

    # a new Course version does not move existing references...
    await c.post(f"{WS}/entities/Course/schemas", json={"samples": [{"code": "X"}]}, headers=h)
    r = await c.get(f"{WS}/entities/Wrapper/schemas/1", headers=h)
    assert r.json()["references"] == [{"entity": "Course", "version": 1, "latest": 2}]
    # ...saving the unpinned schema again does, as a new version
    r = await c.post(f"{WS}/entities/Wrapper/schemas", json={"schema": wrapper}, headers=h)
    assert (r.json()["version"], r.json()["references"][0]["version"]) == (2, 2)
    # an explicit version stays as written
    pinned = {"type": "object", "properties": {"c": {"$ref": "entity:Course@1"}}}
    r = await c.post(f"{WS}/entities/Wrapper/schemas", json={"schema": pinned}, headers=h)
    assert r.json()["references"] == [{"entity": "Course", "version": 1, "latest": 2}]

    async def rejected(doc: dict[str, Any], match: str) -> None:
        r = await c.post(f"{WS}/entities/Wrapper/schemas", json={"schema": doc}, headers=h)
        assert r.status_code == 422 and match in r.json()["detail"], r.text

    await rejected({"$ref": "entity:Nope"}, "'Nope' referenced by the schema does not exist")
    await rejected({"$ref": "entity:Course@9"}, "schema version 9 of 'Course' not found")
    await rejected({"$ref": "entity:Wrapper"}, "cannot reference its own latest version")
    await rejected({"$ref": "entity:Course", "minProperties": 1}, "only carry annotations")
    r = await c.post(f"{WS}/entities", json={"key": "Empty", "name": "E"}, headers=h)
    await rejected({"$ref": "entity:Empty"}, "'Empty' has no schema yet")
