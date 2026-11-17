"""Runtime configuration from environment variables (prefix ``MINOS_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class SettingsError(ValueError):
    """An environment variable has a value Minos cannot use."""


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    # An unknown value must not silently turn a security switch off (e.g. "required").
    raise SettingsError(f"{name}={raw!r}: use one of {sorted(_TRUE | _FALSE - {''})}")


def _number(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        raise SettingsError(f"{name}={raw!r} is not a number") from None
    if value < minimum:
        raise SettingsError(f"{name}={raw!r} must be at least {minimum:g}")
    return value


def _database_url(raw: str | None) -> str | None:
    if not raw:
        return None
    if not raw.startswith("postgresql+asyncpg://"):
        raise SettingsError("MINOS_DATABASE_URL must start with postgresql+asyncpg://")
    return raw


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str | None
    """``postgresql+asyncpg://...``; when unset the execution API serves files only."""
    rulesets_dir: Path | None
    """Directory of RGD files served as workspace ``local`` (development, offline use)."""
    require_auth: bool
    """API keys are optional: off by default (open local installation), on with
    MINOS_REQUIRE_AUTH=true."""
    poll_interval_s: float
    """Safety net for missed NOTIFY messages: how often workers re-check alias hashes."""
    cors_origins: tuple[str, ...] = ()
    """Origins allowed to call the APIs from a browser (comma-separated MINOS_CORS_ORIGINS)."""
    studio_url: str = "http://localhost:8080"
    """Where Minos Studio is reachable: the MCP server links drafts there (MINOS_STUDIO_URL)."""
    exec_time_limit_ms: float = 1000
    """Wall-clock budget of one execution, sub-rule sets included (MINOS_EXEC_TIME_LIMIT_MS)."""

    @classmethod
    def from_env(cls) -> Settings:
        rulesets = os.environ.get("MINOS_RULESETS_DIR")
        return cls(
            database_url=_database_url(os.environ.get("MINOS_DATABASE_URL")),
            rulesets_dir=Path(rulesets) if rulesets else None,
            require_auth=_bool("MINOS_REQUIRE_AUTH", False),
            poll_interval_s=_number("MINOS_POLL_INTERVAL_S", 30, minimum=1),
            cors_origins=tuple(
                o.strip() for o in os.environ.get("MINOS_CORS_ORIGINS", "").split(",") if o.strip()
            ),
            studio_url=os.environ.get("MINOS_STUDIO_URL") or "http://localhost:8080",
            exec_time_limit_ms=_number("MINOS_EXEC_TIME_LIMIT_MS", 1000, minimum=1),
        )
