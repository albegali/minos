"""Message templates: ``"Servono almeno {{vars.minCfu}} CFU"``.

Placeholders are references without the ``$.`` prefix and are compiled ahead of time.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .errors import CompileError
from .refs import MISSING, Scope, compile_ref

_PLACEHOLDER = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

type Renderer = Callable[[Scope], str]


def _fmt(v: Any) -> str:
    if v is MISSING or v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def compile_template(text: str, where: str = "message") -> Renderer:
    """Compile ``text`` into a renderer ``scope -> str``."""
    parts: list[str | Callable[[Scope], Any]] = []
    pos = 0
    for m in _PLACEHOLDER.finditer(text):
        if m.start() > pos:
            parts.append(text[pos : m.start()])
        try:
            parts.append(compile_ref("$." + m.group(1)))
        except CompileError as exc:
            raise CompileError(f"bad placeholder {m.group(0)!r}: {exc.message}", where) from exc
        pos = m.end()
    if pos < len(text):
        parts.append(text[pos:])

    if all(isinstance(p, str) for p in parts):
        static = "".join(p for p in parts if isinstance(p, str))
        return lambda scope: static

    frozen = tuple(parts)

    def render(scope: Scope) -> str:
        return "".join(p if isinstance(p, str) else _fmt(p(scope)) for p in frozen)

    return render
