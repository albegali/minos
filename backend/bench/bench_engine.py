"""Engine benchmark — gate G0 of the roadmap.

Builds a synthetic rule graph of 100 nodes (conditions, groups, set nodes with
aggregates over arrays, a switch) and an input of about 10 KB, then measures engine-only
latency. Exits with status 1 if p99 exceeds ``MINOS_BENCH_P99_MS`` (default 2.0 ms).

    uv run python bench/bench_engine.py [--iterations 20000] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from minos.engine import ExecuteOptions, compile_ruleset

ROOT = Path(__file__).resolve().parents[2]


def synthetic_input(n_courses: int = 70) -> dict[str, Any]:
    areas = ["FIN", "STR", "MKT", "OPS", "ORG", "ACC", "DIG"]
    return {
        "studentId": "S2027-99999",
        "submittedAt": "2027-09-20T10:15:00Z",
        "program": {"code": "EMBA", "edition": "2027", "track": "FINANCE"},
        "student": {"birthDate": "1990-04-12", "country": "IT", "scholarship": {"percent": 10}},
        "courses": [
            {
                "code": f"C{i:03d}",
                "title": f"Course number {i} with a reasonably long descriptive title",
                "area": areas[i % len(areas)],
                "cfu": 4 + i % 5,
                "type": "CORE" if i % 3 else "ELECTIVE",
                "term": 1 + i % 4,
            }
            for i in range(n_courses)
        ],
        "payment": {"plan": "INSTALLMENTS", "installments": 3},
    }


def synthetic_graph(n_nodes: int = 100) -> dict[str, Any]:
    """A chain of ``n_nodes`` nodes (start and end included) mixing every node type."""
    nodes: list[dict[str, Any]] = [{"id": "start", "type": "start"}]
    edges: list[dict[str, Any]] = []
    prev, port = "start", "next"
    areas = ["FIN", "STR", "MKT", "OPS", "ORG", "ACC", "DIG"]
    body = n_nodes - 2
    for i in range(body):
        nid = f"n{i}"
        kind = i % 4
        area = areas[i % len(areas)]
        if kind == 0:
            node: dict[str, Any] = {
                "id": nid,
                "type": "set",
                "assign": {
                    f"cfu_{i}": {
                        "fn": "sum",
                        "args": [{"ref": "$.input.courses"}],
                        "where": {"op": "==", "left": {"ref": "$.item.area"}, "right": area},
                        "select": {"ref": "$.item.cfu"},
                    }
                },
            }
            out = "next"
        elif kind == 1:
            node = {
                "id": nid,
                "type": "condition",
                "condition": {
                    "op": "date_between",
                    "left": {"ref": "$.input.submittedAt"},
                    "right": ["2027-09-01", "2027-10-15"],
                },
                "onFail": "continue",
                "feedback": {
                    "fail": {"code": f"R{i}", "message": "Fuori finestra: {{input.submittedAt}}"}
                },
            }
            out = "pass"
        elif kind == 2:
            node = {
                "id": nid,
                "type": "group",
                "operator": "and",
                "evaluate": "all",
                "children": [
                    {"op": ">=", "left": {"ref": f"$.vars.cfu_{i - 2}"}, "right": 0},
                    {
                        "op": "or",
                        "args": [
                            {
                                "op": "==",
                                "left": {"ref": "$.input.program.track"},
                                "right": "FINANCE",
                            },
                            {
                                "op": "in",
                                "left": {"ref": "$.input.program.code"},
                                "right": ["EMBA", "MBA"],
                            },
                        ],
                    },
                    {
                        "op": "regex",
                        "left": {"ref": "$.input.studentId"},
                        "right": "^S\\d{4}-\\d{5}$",
                    },
                ],
                "onFail": "continue",
            }
            out = "pass"
        else:
            node = {
                "id": nid,
                "type": "switch",
                "cases": [
                    {
                        "name": "fin",
                        "when": {
                            "op": "==",
                            "left": {"ref": "$.input.program.track"},
                            "right": "FINANCE",
                        },
                    }
                ],
            }
            out = "SWITCH"
        nodes.append(node)
        edges.append({"from": prev, "to": nid, "on": port})
        if out == "SWITCH":
            # both branches of the switch converge on the next node
            prev, port = nid, "fin"
            nodes[-1]["_pending_default"] = True
        else:
            prev, port = nid, out
    nodes.append(
        {
            "id": "end",
            "type": "end",
            "outcome": "valid",
            "output": {"total": {"fn": "sum", "args": [{"ref": "$.input.courses[*].cfu"}]}},
        }
    )
    edges.append({"from": prev, "to": "end", "on": port})

    # wire switch defaults to the same successor as their "fin" port
    succ = {(e["from"], e["on"]): e["to"] for e in edges}
    for n in nodes:
        if n.pop("_pending_default", False):
            edges.append({"from": n["id"], "to": succ[(n["id"], "fin")], "on": "default"})

    return {
        "rgdVersion": "1.0",
        "ruleset": "bench.synthetic",
        "version": "0.0.0",
        "settings": {"mode": "collect_all", "maxSteps": 1000},
        "nodes": nodes,
        "edges": edges,
    }


def measure(fn: Any, iterations: int) -> list[float]:
    for _ in range(min(1000, iterations)):  # warm-up
        fn()
    samples = []
    clock = time.perf_counter_ns
    for _ in range(iterations):
        t = clock()
        fn()
        samples.append((clock() - t) / 1e6)
    return samples


def summarise(name: str, samples: list[float]) -> dict[str, Any]:
    q = statistics.quantiles(samples, n=1000)
    return {
        "case": name,
        "iterations": len(samples),
        "p50_ms": round(statistics.median(samples), 4),
        "p95_ms": round(q[949], 4),
        "p99_ms": round(q[989], 4),
        "max_ms": round(max(samples), 4),
        "throughput_per_s": round(1000 / statistics.fmean(samples)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20_000)
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()
    threshold = float(os.environ.get("MINOS_BENCH_P99_MS", "2.0"))

    data = synthetic_input()
    graph = synthetic_graph()
    compiled = compile_ruleset(graph)
    opts = ExecuteOptions(reference_date="2027-09-20", request_id="bench")
    assert len(graph["nodes"]) == 100
    result = compiled.execute(data, opts)
    assert result["outcome"] == "valid", result

    aurora = compile_ruleset(
        json.loads((ROOT / "examples/rulesets/aurora.studyplan.emba.json").read_text())
    )
    aurora_input = json.loads((ROOT / "examples/inputs/studyplan-emba-invalid.json").read_text())

    results = [
        summarise(
            "synthetic-100-nodes", measure(lambda: compiled.execute(data, opts), args.iterations)
        ),
        summarise(
            "aurora-emba-invalid",
            measure(lambda: aurora.execute(aurora_input, opts), args.iterations),
        ),
    ]
    meta = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "input_bytes": len(json.dumps(data)),
        "graph_nodes": len(graph["nodes"]),
        "p99_threshold_ms": threshold,
    }

    if args.json:
        print(json.dumps({"meta": meta, "results": results}, indent=2))
    else:
        print(f"Python {meta['python']} on {meta['machine']} · input {meta['input_bytes']} B")
        print(f"{'case':<22}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}{'req/s':>9}")
        for r in results:
            print(
                f"{r['case']:<22}{r['p50_ms']:>9}{r['p95_ms']:>9}{r['p99_ms']:>9}"
                f"{r['max_ms']:>9}{r['throughput_per_s']:>9}"
            )

    p99 = results[0]["p99_ms"]
    if p99 > threshold:
        print(f"GATE G0 FAILED: p99 {p99} ms > {threshold} ms", file=sys.stderr)
        return 1
    print(f"GATE G0 OK: p99 {p99} ms <= {threshold} ms", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
