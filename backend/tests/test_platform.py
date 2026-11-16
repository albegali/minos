"""End-to-end tests of management + execution APIs against a real PostgreSQL."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest

from minos.api.app import create_app
from minos.api.execution import create_execution_app
from minos.api.management import create_management_app
from minos.cli import create_admin_key, main
from minos.settings import Settings

WS = "/v1/workspaces/aurora"
RS = f"{WS}/rulesets/studyplan-emba"
EXEC = "/v1/exec/aurora/studyplan-emba"


def settings(url: str, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": url,
        "rulesets_dir": None,
        "require_auth": True,
        "poll_interval_s": 0.2,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
async def client(clean_db: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings(clean_db))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://minos") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
async def admin(clean_db: str) -> dict[str, str]:
    key = await create_admin_key(clean_db, "test-admin")
    return {"Authorization": f"Bearer {key}"}


async def eventually(check: Callable[[], Awaitable[bool]], timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


async def setup_aurora(
    c: httpx.AsyncClient,
    admin: dict[str, str],
    graph: dict[str, Any],
    samples: list[Any],
) -> dict[str, str]:
    """Workspace, entity, schema from samples, rule set; returns an exec key header."""
    assert (
        await c.post("/v1/workspaces", json={"slug": "aurora", "name": "Aurora"}, headers=admin)
    ).status_code == 201
    r = await c.post(
        f"{WS}/entities", json={"key": "StudyPlan", "name": "Piano di studi"}, headers=admin
    )
    assert r.status_code == 201, r.text
    r = await c.post(f"{WS}/entities/StudyPlan/schemas", json={"samples": samples}, headers=admin)
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1
    body = {"key": "studyplan-emba", "name": "EMBA", "entity": "StudyPlan", "graph": graph}
    r = await c.post(f"{WS}/rulesets", json=body, headers=admin)
    assert r.status_code == 201, r.text
    r = await c.post(f"{WS}/api-keys", json={"name": "dynamics", "scopes": ["exec"]}, headers=admin)
    assert r.status_code == 201, r.text
    return {"X-Api-Key": r.json()["key"]}


async def test_full_lifecycle(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
    invalid_plan: dict[str, Any],
) -> None:
    c = client
    exec_key = await setup_aurora(c, admin, aurora_graph, [valid_plan, invalid_plan])

    # draft: optimistic locking
    r = await c.get(f"{RS}/draft", headers=admin)
    assert r.status_code == 200
    assert r.headers["etag"] == '"1"'
    assert r.json()["schemaVersion"] == 1
    graph = r.json()["graph"]
    assert graph["ruleset"] == "studyplan-emba"
    r = await c.put(f"{RS}/draft", json={"graph": graph}, headers={**admin, "If-Match": '"1"'})
    assert r.status_code == 200 and r.json()["lockVersion"] == 2
    r = await c.put(f"{RS}/draft", json={"graph": graph}, headers={**admin, "If-Match": '"1"'})
    assert r.status_code == 412
    assert r.json()["lockVersion"] == 2

    # validation reports type-check issues, then a clean draft
    broken = copy.deepcopy(graph)
    broken["nodes"][2]["condition"]["left"]["ref"] = "$.input.submitedAt"
    await c.put(f"{RS}/draft", json={"graph": broken}, headers=admin)
    r = await c.post(f"{RS}/validate", headers=admin)
    assert r.json()["valid"] is False
    assert "submitedAt" in r.json()["issues"][0]["message"]
    r = await c.post(f"{RS}/publish", json={}, headers=admin)
    assert r.status_code == 422 and r.json()["issues"]
    await c.put(f"{RS}/draft", json={"graph": graph}, headers=admin)
    assert (await c.post(f"{RS}/validate", headers=admin)).json() == {
        "valid": True,
        "issues": [],
        "warnings": [],
    }

    # simulate the draft
    r = await c.post(f"{RS}/simulate", json={"input": invalid_plan}, headers=admin)
    assert r.status_code == 200
    assert r.json()["outcome"] == "invalid"
    assert r.json()["trace"][0]["nodeId"] == "start"

    # tests gate the publication
    ok = {
        "name": "valid plan",
        "input": valid_plan,
        "expected": {"outcome": "valid", "result": {"tuitionFee": 30800}},
    }
    ko = {
        "name": "invalid plan",
        "input": invalid_plan,
        "referenceDate": "2027-09-20",
        "expected": {
            "outcome": "invalid",
            "feedbackCodes": [
                "SP_WINDOW_OK",
                "SP_CFU_MIN",
                "SP_ELECTIVE_MAX",
                "SP_FIN_LIMIT",
                "SP_INSTALLMENTS",
            ],
        },
    }
    for t in (ok, ko):
        assert (await c.post(f"{RS}/tests", json=t, headers=admin)).status_code == 201
    r = await c.post(f"{RS}/tests/run", headers=admin)
    assert r.json()["passed"] is True
    assert len((await c.get(f"{RS}/tests", headers=admin)).json()) == 2

    # publish 0.1.0 straight to prod
    r = await c.post(f"{RS}/publish", json={"bump": "minor", "promoteTo": "prod"}, headers=admin)
    assert r.status_code == 201, r.text
    assert r.json()["version"] == "0.1.0"
    assert all(t["passed"] for t in r.json()["tests"])

    # execution picks it up (NOTIFY) and enforces the schema
    async def deployed(version: str) -> bool:
        res = await c.post(EXEC, json={"input": valid_plan}, headers=exec_key)
        return res.status_code == 200 and res.headers["x-ruleset-version"] == version

    await eventually(lambda: deployed("0.1.0"))
    r = await c.post(
        EXEC, json={"input": invalid_plan, "options": {"trace": "summary"}}, headers=exec_key
    )
    assert r.json()["outcome"] == "invalid"
    r = await c.post(EXEC, json={"input": {**valid_plan, "courses": "nope"}}, headers=exec_key)
    assert r.status_code == 400 and r.json()["errors"][0]["path"] == "/courses"
    r = await c.post(
        EXEC,
        json={"input": {**valid_plan, "courses": "nope"}, "options": {"validateSchema": False}},
        headers=exec_key,
    )
    # without the schema gate the engine itself reports the type error
    assert r.status_code == 422 and r.json()["outcome"] == "error"

    # 0.2.0 raises the minimum CFU; prod stays on 0.1.0 until the alias moves
    stricter = copy.deepcopy(graph)
    stricter["constants"]["minCfu"] = 70
    await c.put(f"{RS}/draft", json={"graph": stricter}, headers=admin)
    await c.delete(f"{RS}/tests/valid plan", headers=admin)
    r = await c.post(f"{RS}/publish", json={"bump": "minor", "promoteTo": "test"}, headers=admin)
    assert r.json()["version"] == "0.2.0"
    await eventually(lambda: deployed("0.1.0"))

    async def on_test() -> bool:
        res = await c.post(f"{EXEC}@test", json={"input": valid_plan}, headers=exec_key)
        return res.status_code == 200 and res.headers["x-ruleset-version"] == "0.2.0"

    await eventually(on_test)
    r = await c.post(f"{EXEC}@test", json={"input": valid_plan}, headers=exec_key)
    assert r.json()["outcome"] == "invalid"  # 60 CFU no longer enough

    r = await c.put(f"{RS}/aliases/prod", json={"version": "0.2.0"}, headers=admin)
    assert r.status_code == 200
    await eventually(lambda: deployed("0.2.0"))
    assert (await c.get(f"{RS}/aliases", headers=admin)).json() == {
        "prod": [{"version": "0.2.0", "effectiveFrom": None}],
        "test": [{"version": "0.2.0", "effectiveFrom": None}],
    }

    # fixed versions stay reachable
    r = await c.post(f"{EXEC}/versions/0.1.0", json={"input": valid_plan}, headers=exec_key)
    assert r.json()["outcome"] == "valid" and r.json()["version"] == "0.1.0"
    r = await c.post(f"{EXEC}/versions/9.9.9", json={"input": valid_plan}, headers=exec_key)
    assert r.status_code == 404

    # metadata
    info = (await c.get(RS, headers=admin)).json()
    assert info["latestVersion"] == "0.2.0"
    assert info["entity"] == "StudyPlan"
    versions = (await c.get(f"{RS}/versions", headers=admin)).json()
    assert [v["version"] for v in versions] == ["0.2.0", "0.1.0"]
    full = (await c.get(f"{RS}/versions/0.1.0", headers=admin)).json()
    assert full["graph"]["version"] == "0.1.0"
    schemas = (await c.get(f"{WS}/entities/StudyPlan/schemas", headers=admin)).json()
    assert schemas[0]["version"] == 1 and "schema" not in schemas[0]
    schema = (await c.get(f"{WS}/entities/StudyPlan/schemas/1", headers=admin)).json()
    assert schema["schema"]["type"] == "object"
    assert [e["key"] for e in (await c.get(f"{WS}/entities", headers=admin)).json()] == [
        "StudyPlan"
    ]
    assert [r["key"] for r in (await c.get(f"{WS}/rulesets", headers=admin)).json()] == [
        "studyplan-emba"
    ]
    actions = [e["action"] for e in (await c.get(f"{WS}/audit", headers=admin)).json()]
    assert {"ruleset.publish", "alias.set", "draft.save", "test.create"} <= set(actions)

    # alias removal undeploys
    assert (await c.delete(f"{RS}/aliases/test", headers=admin)).status_code == 204

    async def undeployed() -> bool:
        res = await c.post(f"{EXEC}@test", json={"input": valid_plan}, headers=exec_key)
        return res.status_code == 404

    await eventually(undeployed)
    deps = (await c.get("/v1/deployments", headers=admin)).json()
    assert [(d["env"], d["version"]) for d in deps] == [("prod", "0.2.0")]


async def test_failing_tests_block_publication(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    c = client
    await setup_aurora(c, admin, aurora_graph, [valid_plan])
    wrong = {
        "name": "wrong",
        "input": valid_plan,
        "expected": {"outcome": "invalid", "exitNodeId": "x", "result": {"nope": 1, "totalCfu": 1}},
    }
    assert (await c.post(f"{RS}/tests", json=wrong, headers=admin)).status_code == 201
    r = await c.post(f"{RS}/publish", json={}, headers=admin)
    assert r.status_code == 422
    diffs = r.json()["tests"][0]["differences"]
    assert len(diffs) == 4
    assert (await c.get(f"{RS}/versions", headers=admin)).json() == []


async def test_authorisation(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    c = client
    exec_key = await setup_aurora(c, admin, aurora_graph, [valid_plan])
    await c.post(f"{RS}/publish", json={"promoteTo": "prod"}, headers=admin)

    # no key / bad key
    assert (await c.get(f"{WS}/rulesets")).status_code == 401
    assert (await c.get(f"{WS}/rulesets", headers={"X-Api-Key": "mns_nope"})).status_code == 401
    assert (await c.post(EXEC, json={"input": valid_plan})).status_code == 401
    assert (
        await c.post(EXEC, json={"input": valid_plan}, headers={"X-Api-Key": "x"})
    ).status_code == 401

    # exec keys cannot manage, nor list deployments
    assert (await c.get(f"{WS}/rulesets", headers=exec_key)).status_code == 403
    assert (await c.get("/v1/deployments", headers=exec_key)).status_code == 403
    assert (
        await c.post("/v1/workspaces", json={"slug": "x", "name": "x"}, headers=exec_key)
    ).status_code == 403

    # a manage key of another workspace sees nothing here
    await c.post("/v1/workspaces", json={"slug": "other", "name": "Other"}, headers=admin)
    r = await c.post(
        "/v1/workspaces/other/api-keys",
        json={"name": "m", "scopes": ["manage", "exec"]},
        headers=admin,
    )
    other = {"Authorization": f"Bearer {r.json()['key']}"}
    assert (await c.get(f"{WS}/rulesets", headers=other)).status_code == 403
    assert (await c.post(EXEC, json={"input": valid_plan}, headers=other)).status_code == 403
    assert [w["slug"] for w in (await c.get("/v1/workspaces", headers=other)).json()] == ["other"]
    assert len((await c.get("/v1/workspaces", headers=admin)).json()) == 2

    # key management and revocation (propagated to the execution cache by NOTIFY)
    assert (await c.post(EXEC, json={"input": valid_plan}, headers=exec_key)).status_code == 200
    keys = (await c.get(f"{WS}/api-keys", headers=admin)).json()
    assert keys[0]["prefix"].startswith("mns_") and "key" not in keys[0]
    assert (await c.delete(f"{WS}/api-keys/{keys[0]['id']}", headers=admin)).status_code == 204

    async def revoked() -> bool:
        res = await c.post(EXEC, json={"input": valid_plan}, headers=exec_key)
        return res.status_code == 401

    await eventually(revoked)
    assert (await c.get(f"{WS}/api-keys", headers=admin)).json()[0]["revoked"] is True

    # admin keys
    r = await c.post("/v1/admin/api-keys", json={"name": "ops", "scopes": ["admin"]}, headers=admin)
    assert r.status_code == 201
    bad = await c.post(f"{WS}/api-keys", json={"name": "x", "scopes": ["admin"]}, headers=admin)
    assert bad.status_code == 422
    bad = await c.post(f"{WS}/api-keys", json={"name": "x", "scopes": ["root"]}, headers=admin)
    assert bad.status_code == 422
    bad = await c.post("/v1/admin/api-keys", json={"name": "x", "scopes": ["exec"]}, headers=admin)
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("post", "/v1/workspaces", {"slug": "Bad Slug", "name": "x"}, 422),
        ("post", "/v1/workspaces", {"slug": "aurora", "name": "dup"}, 409),
        ("get", "/v1/workspaces/nope/rulesets", None, 404),
        ("post", f"{WS}/entities", {"key": "StudyPlan", "name": "dup"}, 409),
        ("post", f"{WS}/entities/Nope/schemas", {"samples": [{}]}, 404),
        ("post", f"{WS}/entities/StudyPlan/schemas", {"schema": {"type": "bogus"}}, 422),
        ("post", f"{WS}/entities/StudyPlan/schemas", {}, 422),
        (
            "post",
            f"{WS}/entities/StudyPlan/schemas",
            {"samples": [object.__name__, 1, [], {}]},
            201,
        ),
        ("get", f"{WS}/entities/StudyPlan/schemas/9", None, 404),
        (
            "post",
            f"{WS}/rulesets",
            {"key": "studyplan-emba", "name": "dup", "entity": "StudyPlan"},
            409,
        ),
        ("post", f"{WS}/rulesets", {"key": "x", "name": "x", "entity": "Nope"}, 404),
        ("get", f"{WS}/rulesets/nope", None, 404),
        ("put", f"{RS}/draft", {"graph": {}}, 200),
        ("put", f"{RS}/draft", {"graph": {}, "schemaVersion": 7}, 404),
        ("post", f"{RS}/simulate", {"input": {}}, 200),
        ("post", f"{RS}/tests", {"name": "t", "input": {}, "expected": {"bogus": 1}}, 422),
        ("delete", f"{RS}/tests/nope", None, 404),
        ("post", f"{RS}/tests/run", None, 200),
        ("put", f"{RS}/aliases/prod", {"version": "1.0.0"}, 404),
        ("put", f"{RS}/aliases/Bad_Env", {"version": "1.0.0"}, 422),
        ("delete", f"{RS}/aliases/prod", None, 404),
        ("get", f"{RS}/versions/1.0.0", None, 404),
        ("post", "/v1/schemas/infer", {"samples": [{"a": 1}], "title": "T"}, 200),
        ("delete", f"{WS}/api-keys/00000000-0000-0000-0000-000000000000", None, 404),
    ],
)
async def test_error_mapping(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
    method: str,
    path: str,
    body: Any,
    status: int,
) -> None:
    await setup_aurora(client, admin, aurora_graph, [valid_plan])
    kwargs: dict[str, Any] = {"headers": admin}
    if body is not None:
        kwargs["json"] = body
    r = await client.request(method.upper(), path, **kwargs)
    assert r.status_code == status, r.text
    if status >= 400:
        assert r.headers["content-type"] == "application/problem+json"


async def test_if_match_must_be_numeric(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    await setup_aurora(client, admin, aurora_graph, [valid_plan])
    r = await client.put(f"{RS}/draft", json={"graph": {}}, headers={**admin, "If-Match": "W/x"})
    assert r.status_code == 422


async def test_unchanged_schema_is_not_a_new_version(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    await setup_aurora(client, admin, aurora_graph, [valid_plan])
    path = f"{WS}/entities/StudyPlan/schemas"
    again = await client.post(path, json={"samples": [valid_plan]}, headers=admin)
    assert again.json()["version"] == 1
    other = await client.post(path, json={"samples": [{"x": 1}]}, headers=admin)
    assert other.json()["version"] == 2


async def test_polling_repairs_missed_notifications(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
    clean_db: str,
) -> None:
    c = client
    exec_key = await setup_aurora(c, admin, aurora_graph, [valid_plan])
    await c.post(f"{RS}/publish", json={"promoteTo": "prod"}, headers=admin)
    await c.post(f"{RS}/publish", json={"bump": "patch"}, headers=admin)
    rt = c.app.state.runtime  # type: ignore[attr-defined]

    async def version() -> str:
        r = await c.post(EXEC, json={"input": valid_plan}, headers=exec_key)
        return r.headers.get("x-ruleset-version", "")

    async def is_v1() -> bool:
        return await version() == "0.1.0"

    await eventually(is_v1)
    # Move the alias behind the platform's back: no NOTIFY is sent.
    conn = await asyncpg.connect(clean_db.replace("+asyncpg", ""))
    try:
        await conn.execute(
            "UPDATE ruleset_alias SET version_id = (SELECT id FROM ruleset_version "
            "WHERE semver = '0.1.1')"
        )
    finally:
        await conn.close()

    async def is_v11() -> bool:
        return await version() == "0.1.1"

    before = rt.sync.reloads
    await eventually(is_v11)
    assert rt.sync.reloads > before


def test_cli(
    clean_db: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MINOS_DATABASE_URL", clean_db)
    assert main(["migrate"]) == 0
    assert main(["create-admin-key", "--name", "cli"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("mns_")
    monkeypatch.delenv("MINOS_DATABASE_URL")
    assert main(["migrate"]) == 2


async def test_split_apps(clean_db: str) -> None:
    key = await create_admin_key(clean_db, "split")
    headers = {"Authorization": f"Bearer {key}"}
    mgmt = create_management_app(settings(clean_db))
    exe = create_execution_app(settings(clean_db))
    async with (
        mgmt.router.lifespan_context(mgmt),
        exe.router.lifespan_context(exe),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=mgmt), base_url="http://m") as m,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=exe), base_url="http://e") as e,
    ):
        r = await m.post("/v1/workspaces", json={"slug": "a", "name": "A"}, headers=headers)
        assert r.status_code == 201
        assert (await e.get("/v1/ready")).json() == {"status": "ready"}
        assert (await e.get("/v1/health")).json()["deployments"] == 0
        r = await e.post("/v1/exec/a/x", json={"input": {}}, headers=headers)
        assert r.status_code == 404
    with pytest.raises(RuntimeError):
        create_management_app(settings(None))  # type: ignore[arg-type]


async def test_node_types_and_cors(clean_db: str, admin: dict[str, str]) -> None:
    app = create_app(settings(clean_db, cors_origins=("http://studio.example",)))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://m") as c,
    ):
        info = (await c.get("/v1/info")).json()
        assert info["management"] is True and info["authRequired"] is True
        r = await c.get("/v1/node-types", headers=admin)
        assert r.status_code == 200
        assert {n["type"] for n in r.json()["nodeTypes"]} >= {"condition", "group", "end"}
        assert (await c.get("/v1/node-types")).status_code == 401
        pre = await c.options(
            "/v1/exec/x/y",
            headers={"Origin": "http://studio.example", "Access-Control-Request-Method": "POST"},
        )
        assert pre.headers["access-control-allow-origin"] == "http://studio.example"
    exe = create_execution_app(
        settings(
            None, rulesets_dir=None, require_auth=False, cors_origins=("http://studio.example",)
        )
    )
    async with (
        exe.router.lifespan_context(exe),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=exe), base_url="http://e") as e,
    ):
        r = await e.get("/v1/health", headers={"Origin": "http://studio.example"})
        assert r.headers["access-control-allow-origin"] == "http://studio.example"


async def test_sub_rulesets_and_decision_tables_end_to_end(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    valid_plan: dict[str, Any],
    invalid_plan: dict[str, Any],
) -> None:
    c = client
    examples = Path(__file__).resolve().parents[2] / "examples"
    common = json.loads((examples / "rulesets/aurora.studyplan.common.json").read_text())
    full = json.loads((examples / "rulesets/aurora.studyplan.full.json").read_text())
    await c.post("/v1/workspaces", json={"slug": "aurora", "name": "Aurora"}, headers=admin)
    await c.post(f"{WS}/entities", json={"key": "StudyPlan", "name": "Piano"}, headers=admin)
    await c.post(
        f"{WS}/entities/StudyPlan/schemas",
        json={"samples": [valid_plan, invalid_plan]},
        headers=admin,
    )

    # the parent cannot be validated before the version it pins is published
    body = {"key": "aurora.studyplan.full", "name": "Full", "entity": "StudyPlan", "graph": full}
    assert (await c.post(f"{WS}/rulesets", json=body, headers=admin)).status_code == 201
    full_rs = f"{WS}/rulesets/aurora.studyplan.full"
    v = (await c.post(f"{full_rs}/validate", headers=admin)).json()
    assert v["valid"] is False
    assert "not published" in v["issues"][0]["message"]

    body = {
        "key": "aurora.studyplan.common",
        "name": "Common",
        "entity": "StudyPlan",
        "graph": common,
    }
    await c.post(f"{WS}/rulesets", json=body, headers=admin)
    r = await c.post(f"{WS}/rulesets/aurora.studyplan.common/publish", json={}, headers=admin)
    assert r.json()["version"] == "0.1.0"
    assert (await c.post(f"{full_rs}/validate", headers=admin)).json()["valid"] is True

    sim = await c.post(f"{full_rs}/simulate", json={"input": valid_plan}, headers=admin)
    assert sim.json()["result"]["fees"] == {"baseFee": 38500, "discount": 20}
    r = await c.post(f"{full_rs}/publish", json={"promoteTo": "prod"}, headers=admin)
    assert r.status_code == 201, r.text

    async def deployed() -> bool:
        res = await c.post(
            "/v1/exec/aurora/aurora.studyplan.full", json={"input": valid_plan}, headers=admin
        )
        return res.status_code == 200

    await eventually(deployed)
    res = await c.post(
        "/v1/exec/aurora/aurora.studyplan.full", json={"input": invalid_plan}, headers=admin
    )
    assert res.json()["result"]["tuitionFee"] == 38500
    fixed = await c.post(
        "/v1/exec/aurora/aurora.studyplan.full/versions/0.1.0",
        json={"input": valid_plan},
        headers=admin,
    )
    assert fixed.json()["result"]["tuitionFee"] == 30800
    # a restarted worker loads the parent with its pinned dependency
    rt = c.app.state.runtime  # type: ignore[attr-defined]
    await rt.sync.load_all()
    assert rt.registry.get("aurora", "aurora.studyplan.full") is not None
