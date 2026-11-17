# Benchmarks and phase gates

Measured on a shared Linux x86_64 container, Python 3.14.6, PostgreSQL 16. They are indicative:
repeat them on production hardware.

## G0 · engine (F0)

`backend/bench/bench_engine.py`: latency of the engine alone.

| Case | p50 | p99 | p99 threshold |
| --- | --- | --- | --- |
| Synthetic graph, 100 nodes, 10 KB input | ~0.55 ms | ~1.1–1.3 ms | 2 ms |
| Aurora EMBA rule set | ~0.03 ms | ~0.1 ms | — |

## G1 · API (F1)

`backend/bench/bench_api.py`: fresh database, migrations, publication of the examples through the
Management API (with the tests as the gate), then constant-rate load (open loop) on
`POST /v1/exec/aurora/aurora.studyplan.emba` with authentication and schema validation enabled.
Server: uvicorn with **a single worker** (one core). Latency measured by the client (HTTP, auth,
schema validation, engine, serialisation, loopback).

| Rate | Duration | Requests | Errors | p50 | p95 | p99 | Engine p99 | p99 threshold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 200 req/s | 20 s | 4,000 | 0 | 2.1 ms | 2.9 ms | 6.5 ms | 0.26 ms | 10 ms |

The engine accounts for about 5% of the latency: the rest is the Python HTTP stack and the load
client on the same machine. The Aurora common rules (7 cases) and the EMBA rules (3 cases) pass
their tests at publication time.

In CI the thresholds are looser (G0 3 ms, G1 20 ms) because shared runners are noisy: they are
there to catch regressions, not to certify the gates.

## G2 · editor (F2)

`frontend/e2e/g2.spec.ts` (Playwright, runs in CI with PostgreSQL). A user with a `manage` key,
without admin privileges, using only the interface:

1. creates the entity and infers its schema from two samples;
2. creates the rule set, drags a condition onto the canvas and configures it as "sum of the
   courses' credits ≥ 60" with an error message, without writing JSON;
3. connects the nodes, picks the "collect all errors" mode, saves and validates;
4. simulates a 40-credit plan, saves the simulation as a test and runs the tests;
5. publishes version 0.1.0, promoting it to `test`.

The test then checks, with an `exec` key, that the Execution API answers `valid` for the 60-credit
plan and `invalid` with `SP_CFU_MIN` for the 40-credit one. It takes about 7 seconds.

The roadmap's G2 gate calls for a usability session with a real person from the academic office:
this test automates the path, but does not replace it.
