"""In-memory registry of compiled rule sets.

F0 loads Rule Graph Documents from a directory at startup. From F1 the registry is
filled from PostgreSQL and refreshed on ``LISTEN/NOTIFY``; the lookup API stays the same:
an atomic dict swap, so in-flight requests finish on the version they started with.
"""

from __future__ import annotations

import logging
from pathlib import Path

import orjson

from minos.engine import CompiledRuleset, compile_ruleset

log = logging.getLogger(__name__)


class RulesetRegistry:
    def __init__(self) -> None:
        self._rulesets: dict[str, CompiledRuleset] = {}

    def get(self, name: str) -> CompiledRuleset | None:
        return self._rulesets.get(name)

    def all(self) -> list[CompiledRuleset]:
        return sorted(self._rulesets.values(), key=lambda r: r.ruleset)

    def publish(self, compiled: CompiledRuleset) -> None:
        updated = dict(self._rulesets)
        updated[compiled.ruleset] = compiled
        self._rulesets = updated  # atomic swap

    def load_directory(self, directory: Path) -> int:
        count = 0
        for file in sorted(directory.glob("*.json")):
            compiled = compile_ruleset(orjson.loads(file.read_bytes()))
            for warning in compiled.warnings:
                log.warning("%s: %s", file.name, warning)
            self.publish(compiled)
            count += 1
        return count
