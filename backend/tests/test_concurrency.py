"""Concurrent writers of the same rows: no lost update, no HTTP 500 (CTL-01, CTL-02)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .test_platform import RS, WS, admin, client, setup_aurora  # noqa: F401  (fixtures)


async def test_concurrent_schema_versions(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    await setup_aurora(client, admin, aurora_graph, [valid_plan])
    url = f"{WS}/entities/StudyPlan/schemas"
    bodies = [
        {"schema": {"type": "object", "properties": {f"f{i}": {"type": "string"}}}}
        for i in range(5)
    ]
    results = await asyncio.gather(*(client.post(url, json=b, headers=admin) for b in bodies))
    assert [r.status_code for r in results] == [201] * 5, [r.text for r in results]
    assert sorted(r.json()["version"] for r in results) == [2, 3, 4, 5, 6]


async def test_concurrent_first_alias(
    client: httpx.AsyncClient,  # noqa: F811
    admin: dict[str, str],  # noqa: F811
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    await setup_aurora(client, admin, aurora_graph, [valid_plan])
    r = await client.post(f"{RS}/publish", json={}, headers=admin)
    assert r.status_code == 201, r.text
    version = r.json()["version"]
    puts = [
        client.put(f"{RS}/aliases/staging", json={"version": version}, headers=admin)
        for _ in range(5)
    ]
    results = await asyncio.gather(*puts)
    assert {r.status_code for r in results} == {200}, [r.text for r in results]
    schedule = (await client.get(f"{RS}/aliases", headers=admin)).json()["staging"]
    assert schedule == [{"version": version, "effectiveFrom": None}]
