"""Runtime configuration from environment variables (prefix ``MINOS_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

    @classmethod
    def from_env(cls) -> Settings:
        rulesets = os.environ.get("MINOS_RULESETS_DIR")
        return cls(
            database_url=os.environ.get("MINOS_DATABASE_URL") or None,
            rulesets_dir=Path(rulesets) if rulesets else None,
            require_auth=_bool("MINOS_REQUIRE_AUTH", False),
            poll_interval_s=float(os.environ.get("MINOS_POLL_INTERVAL_S", "30")),
            cors_origins=tuple(
                o.strip() for o in os.environ.get("MINOS_CORS_ORIGINS", "").split(",") if o.strip()
            ),
        )
