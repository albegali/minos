"""API load test — gate G1 of the roadmap.

1. recreates a database, applies migrations and creates an admin key;
2. starts the combined app with uvicorn, **one worker process** (one core);
3. seeds the Aurora examples through the management API (schema inferred from the example
   inputs, rule sets with their test suites, publish to ``prod`` — the tests gate it);
4. sends an open-loop load (fixed arrival rate, independent of response times) to
   ``POST /v1/exec/aurora/aurora.studyplan.emba`` with schema validation on;
5. reports client-side latency (includes HTTP parsing, auth, schema validation, engine,
   serialisation and loopback) and fails if p99 exceeds ``MINOS_BENCH_API_P99_MS``
   (default 10 ms) or if any request fails.

    MINOS_BENCH_DATABASE_URL=postgresql+asyncpg://... uv run python bench/bench_api.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from minos.cli import create_admin_key, migrate

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
DEFAULT_DB = "postgresql+asyncpg://minos:minos@localhost:5432/minos_bench"


async def recreate(url: str) -> None:
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    base, _, name = dsn.rpartition("/")
    conn = await asyncpg.connect(f"{base}/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def load(rel: str) -> Any:
    return json.loads((EXAMPLES / rel).read_text())


def example_rulesets() -> list[dict[str, Any]]:
    """Every example graph, dependencies (pinned sub-rulesets) before their users."""
    graphs = {
        g["ruleset"]: g
        for g in (
            load(f"rulesets/{p.name}") for p in sorted((EXAMPLES / "rulesets").glob("*.json"))
        )
    }
    ordered: list[dict[str, Any]] = []

    def visit(key: str) -> None:
        graph = graphs[key]
        if graph in ordered:
            return
        for node in graph["nodes"]:
            if node["type"] == "subruleset":
                visit(node["ruleset"])
        ordered.append(graph)

    for key in graphs:
        visit(key)
    return ordered


async def seed(base: str, admin_key: str) -> str:
    """Publish every example to workspace ``aurora`` (entity schemas inferred from the
    example inputs), each version gated by its test suite; return an exec key."""
    admin = {"Authorization": f"Bearer {admin_key}"}
    async with httpx.AsyncClient(base_url=base, headers=admin, timeout=30) as c:

        async def post(path: str, body: Any) -> dict[str, Any]:
            r = await c.post(path, json=body)
            if r.status_code >= 300:
                raise RuntimeError(f"{path}: {r.status_code} {r.text}")
            out: dict[str, Any] = r.json()
            return out

        ws = "/v1/workspaces/aurora"
        await post("/v1/workspaces", {"slug": "aurora", "name": "Aurora Business School"})
        graphs = example_rulesets()
        for entity in sorted({g["schemaRef"]["entity"] for g in graphs}):
            files = sorted((EXAMPLES / "inputs").glob(f"{entity.lower()}-*.json"))
            await post(f"{ws}/entities", {"key": entity, "name": entity})
            await post(
                f"{ws}/entities/{entity}/schemas",
                {"samples": [json.loads(p.read_text()) for p in files]},
            )
        for graph in graphs:
            ruleset = graph["ruleset"]
            await post(
                f"{ws}/rulesets",
                {
                    "key": ruleset,
                    "name": ruleset,
                    "entity": graph["schemaRef"]["entity"],
                    "graph": graph,
                },
            )
            for case in load(f"tests/{ruleset}.tests.json"):
                await post(f"{ws}/rulesets/{ruleset}/tests", case)
            published = await post(
                f"{ws}/rulesets/{ruleset}/publish", {"bump": "minor", "promoteTo": "prod"}
            )
            print(
                f"published {ruleset} {published['version']} "
                f"({len(published['tests'])} tests passed)"
            )
        key = await post(f"{ws}/api-keys", {"name": "bench", "scopes": ["exec"]})
        return str(key["key"])


async def wait_ready(base: str, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(base_url=base) as c:
        while True:
            try:
                if (await c.get("/v1/ready")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("server did not become ready")
            await asyncio.sleep(0.2)


async def wait_deployed(base: str, path: str, key: str, body: bytes) -> None:
    async with httpx.AsyncClient(base_url=base, headers={"X-Api-Key": key}) as c:
        for _ in range(100):
            r = await c.post(path, content=body, headers={"content-type": "application/json"})
            if r.status_code == 200:
                return
            await asyncio.sleep(0.05)
    raise RuntimeError("deployment did not appear")


async def load_test(
    base: str, path: str, key: str, body: bytes, rate: float, seconds: float
) -> tuple[list[float], list[float], int]:
    latencies: list[float] = []
    engine: list[float] = []
    errors = 0
    limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
    headers = {"X-Api-Key": key, "content-type": "application/json"}
    async with httpx.AsyncClient(base_url=base, limits=limits, headers=headers) as c:

        async def one() -> None:
            nonlocal errors
            t = time.perf_counter()
            try:
                r = await c.post(path, content=body)
            except httpx.TransportError:
                errors += 1
                return
            latencies.append((time.perf_counter() - t) * 1000)
            if r.status_code != 200:
                errors += 1
                return
            timing = r.headers.get("server-timing", "")
            if "dur=" in timing:
                engine.append(float(timing.split("dur=")[1]))

        tasks = []
        total = int(rate * seconds)
        start = time.perf_counter()
        for i in range(total):
            delay = start + i / rate - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(one()))
        await asyncio.gather(*tasks)
    return latencies, engine, errors


def pct(values: list[float], q: float) -> float:
    return statistics.quantiles(values, n=1000)[int(q * 1000) - 1]


async def run(args: argparse.Namespace) -> int:
    url = os.environ.get("MINOS_BENCH_DATABASE_URL", DEFAULT_DB)
    threshold = float(os.environ.get("MINOS_BENCH_API_P99_MS", "10"))
    await recreate(url)
    await asyncio.to_thread(migrate, url)
    admin_key = await create_admin_key(url, "bench-admin")

    base = f"http://127.0.0.1:{args.port}"
    env = {**os.environ, "MINOS_DATABASE_URL": url, "MINOS_REQUIRE_AUTH": "true"}
    env.pop("MINOS_RULESETS_DIR", None)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "minos.api.app:app",
            "--port",
            str(args.port),
            "--workers",
            "1",
            "--no-access-log",
            "--log-level",
            "warning",
        ],
        env=env,
    )
    try:
        await wait_ready(base)
        exec_key = await seed(base, admin_key)
        path = "/v1/exec/aurora/aurora.studyplan.emba"
        body = json.dumps(
            {
                "input": load("inputs/studyplan-emba-invalid.json"),
                "options": {"referenceDate": "2027-09-20"},
            }
        ).encode()
        await wait_deployed(base, path, exec_key, body)
        await load_test(base, path, exec_key, body, args.rate, 2)  # warm-up
        latencies, engine, errors = await load_test(
            base, path, exec_key, body, args.rate, args.seconds
        )
    finally:
        server.terminate()
        server.wait(timeout=10)

    result = {
        "python": platform.python_version(),
        "rate_per_s": args.rate,
        "seconds": args.seconds,
        "requests": len(latencies),
        "errors": errors,
        "client_p50_ms": round(statistics.median(latencies), 3),
        "client_p95_ms": round(pct(latencies, 0.95), 3),
        "client_p99_ms": round(pct(latencies, 0.99), 3),
        "client_max_ms": round(max(latencies), 3),
        "engine_p50_ms": round(statistics.median(engine), 3),
        "engine_p99_ms": round(pct(engine, 0.99), 3),
        "p99_threshold_ms": threshold,
    }
    print(json.dumps(result, indent=2))
    if errors or result["client_p99_ms"] > threshold:
        print(f"GATE G1 FAILED: p99 {result['client_p99_ms']} ms, errors {errors}", file=sys.stderr)
        return 1
    print(
        f"GATE G1 OK: p99 {result['client_p99_ms']} ms <= {threshold} ms at "
        f"{args.rate:.0f} req/s on one worker",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=200)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--port", type=int, default=8765)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
