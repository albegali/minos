"""Exceptions raised by the Minos engine."""

from __future__ import annotations


class MinosError(Exception):
    """Base class for every Minos engine error."""


class CompileError(MinosError):
    """A rule graph or an expression cannot be compiled.

    ``where`` points at the offending element (e.g. ``nodes.chkWindow.condition``).
    """

    def __init__(self, message: str, where: str | None = None) -> None:
        self.message = message
        self.where = where
        super().__init__(f"{where}: {message}" if where else message)


class EvaluationError(MinosError):
    """An expression failed while being evaluated (type mismatch, division by zero...)."""


class ExecutionLimitError(MinosError):
    """An execution exceeded the configured step limit."""
