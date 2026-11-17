# 0001 · Rule storage: PostgreSQL + in-memory cache

- Status: Accepted
- Date: 2026-11-16

## Context

The execution APIs must respond in real time (server-side p99 under 10 ms, engine under 2 ms) and
be cheap to run. Rules change rarely compared with how often they are executed.

## Decision

- **PostgreSQL** is the source of truth for schemas, graphs, immutable versions, aliases, tests and
  audit (JSONB for documents, relational tables for identity and permissions).
- Every Execution API worker keeps the compiled versions of the active aliases **in RAM**
  (`RulesetRegistry`), swapping the dictionary atomically.
- Invalidation through PostgreSQL **`LISTEN/NOTIFY`** on publication or alias change, plus a
  safety poll of the hashes every 30 s.
- No database on the hot path of a call.

## Rejected alternatives

- Redis as the primary store: adds 0.2–1 ms per call and one more service to run.
- MongoDB/Cosmos DB read on every request: higher latency and cost, and a cache is needed anyway.
- Object storage: great for distributing multi-region bundles (phase F5), not for editing.

## Consequences

- Implemented in F1 (`minos.api.registry.DbSync`): initial load, `LISTEN` on the `minos_changes`
  channel, reload of only the alias that changed, polling that compares hashes. In development the
  registry can still load files (`local` workspace).
- The Execution API keeps serving even when the database is unreachable.
- Drift between workers must be measured (version hash in the `X-Ruleset-Version` header).
