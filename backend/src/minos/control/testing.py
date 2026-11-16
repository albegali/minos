"""Comparison of an execution result with a test case's expectations.

``expected`` may contain any of:

* ``outcome``: exact match;
* ``exitNodeId``: exact match;
* ``feedbackCodes``: the emitted codes, order-insensitive, duplicates counted;
* ``result``: a subset of the result document (nested objects compared recursively).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

EXPECTATION_KEYS = frozenset({"outcome", "exitNodeId", "feedbackCodes", "result"})


def _subset(expected: Any, actual: Any, path: str, out: list[str]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for k, v in expected.items():
            if k not in actual:
                out.append(f"{path}.{k}: missing")
            else:
                _subset(v, actual[k], f"{path}.{k}", out)
    elif expected != actual:
        out.append(f"{path}: expected {expected!r}, got {actual!r}")


def compare(expected: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Return human-readable differences; an empty list means the test passed."""
    diffs: list[str] = []
    if "outcome" in expected and expected["outcome"] != result["outcome"]:
        diffs.append(f"outcome: expected {expected['outcome']!r}, got {result['outcome']!r}")
    if "exitNodeId" in expected and expected["exitNodeId"] != result["exit"]["nodeId"]:
        diffs.append(
            f"exitNodeId: expected {expected['exitNodeId']!r}, got {result['exit']['nodeId']!r}"
        )
    if "feedbackCodes" in expected:
        want = Counter(expected["feedbackCodes"])
        got = Counter(f["code"] for f in result["feedback"])
        if want != got:
            missing = sorted((want - got).elements())
            extra = sorted((got - want).elements())
            diffs.append(f"feedbackCodes: missing {missing}, unexpected {extra}")
    if "result" in expected:
        _subset(expected["result"], result["result"], "result", diffs)
    return diffs
