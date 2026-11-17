# 0002 · Engine compiled to closures in pure Python

- Status: Accepted
- Date: 2026-11-16

## Context

The backend is written in Python. An interpreter that walks the AST on every call risks missing
gate G0 (p99 under 2 ms on a 100-node graph with a 10 KB input). Native engines with Python
bindings exist (e.g. GoRules' `zen-engine`, with a Rust core).

## Decision

- On publication the **compiler** validates the graph (ports, DAG, reachability) and turns every
  node and expression into prebuilt **Python closures**: paths become accessors, operators become
  specialised functions (e.g. comparison with a literal without normalisation), regexes are
  precompiled, message templates are split into parts.
- The **runtime** walks the graph following one port per node, with no parsing and no Pydantic
  validation.
- Aggregations with `where`/`select` bind `$.item` in place instead of copying the scope.

## Spike results (gate G0)

`backend/bench/bench_engine.py`, Python 3.14.6, x86_64, shared container:

| Case | p50 | p99 |
| --- | --- | --- |
| Synthetic graph, 100 nodes, 10 KB input, 25 aggregations over 70 items | ~0.55 ms | ~1.1–1.3 ms |
| Aurora EMBA rule set (10 nodes), invalid plan | ~0.03 ms | ~0.08–0.14 ms |

Gate G0 is passed. The first profile showed time dominated by the `==` comparison inside `where`
clauses; specialising on literals cut p99 by about 30%.

## Alternatives and plan B

- The head-to-head comparison with `zen-engine` planned for F0 **was not run**: it is postponed
  until decision tables are needed (F3), where the advantage of a native core is more likely.
- If real rule sets exceed the targets: rewrite the runtime in Rust with PyO3 keeping the RGD
  format, or delegate individual nodes (decision tables) to a native engine.

## Consequences

- The benchmark runs in CI as a regression test with threshold `MINOS_BENCH_P99_MS=3.0`: shared
  runners are noisier than the reference hardware the gate (2 ms) is measured on.
- New functions and operators must be added to the compiler, not interpreted at runtime.
