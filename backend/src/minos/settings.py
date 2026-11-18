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


def _hosts(raw: str | None) -> tuple[str, ...]:
    local = ("localhost", "127.0.0.1", "::1")
    if not raw:
        return local
    return local + tuple(h.strip().lower() for h in raw.split(",") if h.strip())


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
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")
    """Host names an *open* installation answers to (MINOS_ALLOWED_HOSTS, comma-separated;
    ``*`` for any): a web page cannot reach it through DNS rebinding. Not checked when API
    keys are required."""
    publish_requires_tests: bool = False
    """Refuse to publish a rule set without tests (MINOS_PUBLISH_REQUIRES_TESTS); recommended
    in production."""
    session_hours: float = 12
    """How long a Studio sign-in lasts (MINOS_SESSION_HOURS)."""
    invitation_days: float = 7
    """How long an invitation link can be used (MINOS_INVITATION_DAYS)."""
    audit_retention_days: float = 90
    """``minos.cli prune-audit`` deletes draft-save events older than this
    (MINOS_AUDIT_RETENTION_DAYS); publications, environments, keys and members are kept."""

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
            publish_requires_tests=_bool("MINOS_PUBLISH_REQUIRES_TESTS", False),
            allowed_hosts=_hosts(os.environ.get("MINOS_ALLOWED_HOSTS")),
            session_hours=_number("MINOS_SESSION_HOURS", 12, minimum=0.1),
            invitation_days=_number("MINOS_INVITATION_DAYS", 7, minimum=0.1),
            audit_retention_days=_number("MINOS_AUDIT_RETENTION_DAYS", 90, minimum=1),
        )
