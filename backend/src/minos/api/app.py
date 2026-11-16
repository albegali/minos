"""Combined application for development and small installations.

Production runs the two planes as separate processes so they scale independently:

* ``minos.api.app:execution_app`` — execution API (stateless workers, in-memory rule sets);
* ``minos.api.app:management_app`` — management API (Studio, CI, administrators).

``minos.api.app:app`` serves both from one process. Configuration comes from ``MINOS_*``
environment variables (see :mod:`minos.settings`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from minos import __version__
from minos.db import make_sessionmaker
from minos.settings import Settings

from .execution import ExecutionRuntime, create_execution_app, execution_router
from .execution import install_problem_handler as install_execution_handlers
from .management import create_management_app, install_error_handlers, management_router


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    if cfg.database_url is None and cfg.rulesets_dir is None:
        default = Settings.from_env()
        cfg = Settings(
            database_url=None,
            rulesets_dir=_examples_dir(),
            require_auth=False,
            poll_interval_s=default.poll_interval_s,
        )
    rt = ExecutionRuntime.from_settings(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await rt.start()
        try:
            yield
        finally:
            await rt.stop()

    app = FastAPI(title="Minos", version=__version__, lifespan=lifespan)
    app.state.runtime = rt
    app.include_router(execution_router(rt.registry, rt.sync, cfg.require_auth))
    if rt.engine is not None:
        app.include_router(management_router(make_sessionmaker(rt.engine), cfg.require_auth))
        install_error_handlers(app)
    else:
        install_execution_handlers(app)
    return app


def _examples_dir() -> Path | None:
    candidate = Path(__file__).resolve().parents[4] / "examples" / "rulesets"
    return candidate if candidate.is_dir() else None


def __getattr__(name: str) -> FastAPI:
    # Lazily built so that importing the module never needs a database or the network.
    if name == "app":
        return create_app()
    if name == "execution_app":
        return create_execution_app()
    if name == "management_app":
        return create_management_app()
    raise AttributeError(name)
