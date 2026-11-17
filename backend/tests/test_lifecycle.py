"""Version lifecycle: scheduled aliases, diffs, bundles (export / import)."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import asyncpg
import httpx
import pytest
from alembic import command

from minos.cli import alembic_config, migrate
from minos.control.diff import diff_graphs

from .test_platform import EXEC, RS, WS, admin, client, eventually, setup_aurora  # noqa: F401

pytestmark = pytest.mark.usefixtures("clean_db")


# --------------------------------------------------------------------------- diff (unit)


def test_diff_graphs() -> None:
    old = {
        "rgdVersion": "1.0",
        "ruleset": "x",
        "version": "1.0.0",
        "constants": {"min": 60, "gone": 1},
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "c", "type": "condition", "condition": {"op": ">", "left": 1, "right": 2}},
            {"id": "old", "type": "end", "outcome": "invalid"},
            {"id": "end", "type": "end", "outcome": "valid"},
        ],
        "edges": [{"from": "start", "to": "c"}, {"from": "c", "to": "end", "on": "pass"}],
        "ui": {"positions": {"c": [0, 0]}},
    }
    new = copy.deepcopy(old)
    new["version"] = "1.1.0"
    new["ui"] = {"positions": {"c": [99, 99]}}
    assert diff_graphs(old, new)["identical"] is True

    new["constants"] = {"min": 70, "added": True}
    new["nodes"][1]["condition"]["right"] = 3
    new["nodes"][1]["label"] = "Soglia"
    new["nodes"] = [n for n in new["nodes"] if n["id"] != "old"]
    new["nodes"].append({"id": "extra", "type": "feedback"})
    new["edges"].append({"from": "c", "to": "extra", "on": "fail"})
    new["edges"] = [e for e in new["edges"] if e["to"] != "end"]
    d = diff_graphs(old, new)
    assert d["identical"] is False
    assert [n["id"] for n in d["nodes"]["added"]] == ["extra"]
    assert [n["id"] for n in d["nodes"]["removed"]] == ["old"]
    changed = d["nodes"]["changed"][0]
    assert changed["id"] == "c"
    assert changed["changes"] == [
        {"path": "condition.right", "kind": "changed", "from": 2, "to": 3},
        {"path": "label", "kind": "added", "to": "Soglia"},
    ]
    assert d["edges"] == {"added": ["c:fail->extra"], "removed": ["c:pass->end"]}
    assert {c["path"] for c in d["other"]} == {
        "constants.added",
        "constants.gone",
        "constants.min",
    }
    lists = diff_graphs({"constants": {"a": [1, 2]}}, {"constants": {"a": [1, 2, 3]}})
    assert lists["other"] == [
        {"path": "constants.a", "kind": "changed", "from": [1, 2], "to": [1, 2, 3]}
    ]


# --------------------------------------------------------------------------- platform


async def publish(
    c: httpx.AsyncClient, headers: dict[str, str], graph: dict[str, Any], **body: Any
) -> str:
    await c.put(f"{RS}/draft", json={"graph": graph}, headers=headers)
    r = await c.post(f"{RS}/publish", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return str(r.json()["version"])


async def test_scheduled_aliases(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    c = client
    key = await setup_aurora(c, admin, aurora_graph, [valid_plan])
    v1 = await publish(c, admin, aurora_graph, promoteTo="prod")
    stricter = copy.deepcopy(aurora_graph)
    stricter["constants"]["minCfu"] = 70
    v2 = await publish(c, admin, stricter)
    # from 2027-08-01 prod runs the stricter rules
    r = await c.put(
        f"{RS}/aliases/prod", json={"version": v2, "effectiveFrom": "2027-08-01"}, headers=admin
    )
    assert r.json() == {"env": "prod", "version": v2, "effectiveFrom": "2027-08-01"}

    async def version_on(day: str) -> str:
        res = await c.post(
            EXEC, json={"input": valid_plan, "options": {"referenceDate": day}}, headers=key
        )
        return res.headers.get("x-ruleset-version", str(res.status_code))

    async def scheduled() -> bool:
        return await version_on("2027-09-20") == v2

    await eventually(scheduled)
    assert await version_on("2027-07-31") == v1
    assert await version_on("2027-08-01") == v2

    schedule = (await c.get(f"{RS}/aliases", headers=admin)).json()["prod"]
    assert schedule == [
        {"version": v1, "effectiveFrom": None},
        {"version": v2, "effectiveFrom": "2027-08-01"},
    ]
    info = (await c.get(RS, headers=admin)).json()
    assert info["schedule"]["prod"] == schedule
    assert info["aliases"]["prod"] in (v1, v2)  # depends on today's date
    deps = (await c.get("/v1/deployments", headers=admin)).json()
    assert [(d["version"], d["effectiveFrom"]) for d in deps] == [(v1, None), (v2, "2027-08-01")]

    bad = await c.post(
        EXEC, json={"input": valid_plan, "options": {"referenceDate": "soon"}}, headers=key
    )
    assert bad.status_code == 400

    # only a future entry: earlier dates have no deployment
    assert (await c.delete(f"{RS}/aliases/prod?effectiveFrom=x", headers=admin)).status_code == 422
    r = await c.delete(f"{RS}/aliases/prod?effectiveFrom=always", headers=admin)
    assert r.status_code == 204

    async def only_future() -> bool:
        return await version_on("2027-01-01") == "404"

    await eventually(only_future)
    assert await version_on("2028-01-01") == v2
    # a restarted worker rebuilds the same schedule
    rt = c.app.state.runtime  # type: ignore[attr-defined]
    await rt.sync.load_all()
    assert await rt.sync.check_drift() == 0

    r = await c.delete(f"{RS}/aliases/prod?effectiveFrom=2027-08-01", headers=admin)
    assert r.status_code == 204
    r = await c.delete(f"{RS}/aliases/prod", headers=admin)
    assert r.status_code == 404


async def test_diff_endpoint(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    c = client
    await setup_aurora(c, admin, aurora_graph, [valid_plan])
    v1 = await publish(c, admin, aurora_graph)
    changed = copy.deepcopy(aurora_graph)
    changed["constants"]["minCfu"] = 70
    await c.put(f"{RS}/draft", json={"graph": changed}, headers=admin)
    d = (await c.get(f"{RS}/diff?from={v1}", headers=admin)).json()
    assert d["from"] == v1 and d["to"] == "draft"
    assert d["other"] == [{"path": "constants.minCfu", "kind": "changed", "from": 60, "to": 70}]
    v2 = await publish(c, admin, changed)
    same = (await c.get(f"{RS}/diff?from={v2}&to=draft", headers=admin)).json()
    assert same["identical"] is True
    assert (await c.get(f"{RS}/diff", headers=admin)).status_code == 422
    assert (await c.get(f"{RS}/diff?from=9.9.9", headers=admin)).status_code == 404


async def test_export_import_round_trip(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
    invalid_plan: dict[str, Any],
) -> None:
    c = client
    await setup_aurora(c, admin, aurora_graph, [valid_plan, invalid_plan])
    test = {"name": "valido", "input": valid_plan, "expected": {"outcome": "valid"}}
    await c.post(f"{RS}/tests", json=test, headers=admin)
    v1 = await publish(c, admin, aurora_graph)

    r = await c.get(f"{RS}/export?version={v1}", headers=admin)
    assert (
        r.headers["content-disposition"] == 'attachment; filename="studyplan-emba-0.1.0.minos.json"'
    )
    bundle = r.json()
    assert bundle["format"] == "minos-bundle/1"
    assert bundle["source"]["version"] == v1
    assert bundle["entity"]["key"] == "StudyPlan"
    assert bundle["schema"]["type"] == "object"
    assert [t["name"] for t in bundle["tests"]] == ["valido"]
    assert bundle["dependencies"] == []
    draft = (await c.get(f"{RS}/export", headers=admin)).json()
    assert draft["source"]["version"] == "draft"

    # into another workspace: everything is created, then it publishes as is
    await c.post("/v1/workspaces", json={"slug": "copy", "name": "Copy"}, headers=admin)
    r = await c.post(
        "/v1/workspaces/copy/import",
        content=r.content,
        headers={**admin, "Content-Type": "application/json"},
    )
    assert r.status_code == 201, r.text
    assert r.json() == {
        "ruleset": "studyplan-emba",
        "created": True,
        "entity": "StudyPlan",
        "entityCreated": True,
        "schemaVersion": 1,
        "tests": 1,
        "dependencies": [],
    }
    copied = "/v1/workspaces/copy/rulesets/studyplan-emba"
    r = await c.post(f"{copied}/publish", json={}, headers=admin)
    assert r.status_code == 201 and r.json()["tests"][0]["passed"] is True

    # importing again updates the draft and replaces tests with the same name
    bundle["graph"]["constants"]["minCfu"] = 61
    bundle["tests"][0]["expected"] = {"outcome": "valid", "result": {"totalCfu": 60}}
    r = await c.post("/v1/workspaces/copy/import", json=bundle, headers=admin)
    assert r.status_code == 200
    assert r.json()["created"] is False and r.json()["entityCreated"] is False
    assert r.json()["schemaVersion"] == 1  # same schema: no new version
    d = (await c.get(f"{copied}/diff?from=0.1.0", headers=admin)).json()
    assert d["other"][0]["path"] == "constants.minCfu"
    tests = (await c.get(f"{copied}/tests", headers=admin)).json()
    assert tests[0]["expected"]["result"] == {"totalCfu": 60}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"{not json", "invalid JSON"),
        (b'{"format": "other"}', "not a Minos bundle"),
        (b'{"format": "minos-bundle/1"}', "'ruleset'"),
        (b'{"format": "minos-bundle/1", "ruleset": {}, "entity": {}, "graph": {}}', "required"),
        (
            b'{"format": "minos-bundle/1", "ruleset": {"key": "a"}, "entity": {"key": "E"},'
            b' "graph": {}, "tests": 3}',
            "'tests' must be a list",
        ),
        (
            b'{"format": "minos-bundle/1", "ruleset": {"key": "a"}, "entity": {"key": "E"},'
            b' "graph": {}, "tests": [{}]}',
            "needs a name",
        ),
    ],
)
async def test_import_errors(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
    payload: bytes,
    message: str,
) -> None:
    await client.post("/v1/workspaces", json={"slug": "aurora", "name": "A"}, headers=admin)
    r = await client.post(
        f"{WS}/import", content=payload, headers={**admin, "Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert message in r.json()["detail"]


async def test_import_refuses_a_ruleset_of_another_entity(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    c = client
    await setup_aurora(c, admin, aurora_graph, [valid_plan])
    bundle = (await c.get(f"{RS}/export", headers=admin)).json()
    bundle["entity"] = {"key": "Other", "name": "Other"}
    r = await c.post(f"{WS}/import", json=bundle, headers=admin)
    assert r.status_code == 422 and "another entity" in r.json()["detail"]


def test_alias_migration_round_trip(clean_db: str) -> None:
    async def seed() -> None:
        conn = await asyncpg.connect(clean_db.replace("+asyncpg", ""))
        try:
            await conn.execute(
                "INSERT INTO workspace (id, slug, name) VALUES (gen_random_uuid(), 'w', 'W')"
            )
        finally:
            await conn.close()

    cfg = alembic_config(clean_db)
    command.downgrade(cfg, "0001")
    asyncio.run(seed())
    migrate(clean_db)
    command.downgrade(cfg, "0001")
    migrate(clean_db)
