"""Combined application for development and small installations.

Production runs the two planes as separate processes so they scale independently:

* ``minos.api.app:execution_app`` — execution API (stateless workers, in-memory rule sets);
* ``minos.api.app:management_app`` — management API (Studio, CI, administrators).

``minos.api.app:app`` serves both from one process, plus the MCP server at ``/mcp`` (AI clients
writing rule set drafts through the management API) when a database is configured.
Configuration comes from ``MINOS_*`` environment variables (see :mod:`minos.settings`).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from mcp.server import MCPServer

from minos import __version__
from minos.db import make_sessionmaker
from minos.mcp import build_server
from minos.settings import Settings

from .common import install_cors
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
    mcp: MCPServer | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await rt.start()
            stack.push_async_callback(rt.stop)
            if mcp is not None:
                await stack.enter_async_context(_in_own_task(mcp.session_manager.run))
            yield

    app = FastAPI(title="Minos", version=__version__, lifespan=lifespan)
    app.state.runtime = rt
    app.include_router(
        execution_router(rt.registry, rt.sync, cfg.require_auth, management=rt.engine is not None)
    )
    if rt.engine is not None:
        app.include_router(management_router(make_sessionmaker(rt.engine), cfg.require_auth))
        install_error_handlers(app)
        mcp = _mount_mcp(app, cfg)
    else:
        install_execution_handlers(app)
    install_cors(app, cfg)
    return app


@asynccontextmanager
async def _in_own_task(
    open_cm: Callable[[], AbstractAsyncContextManager[object]],
) -> AsyncIterator[None]:
    """Keep a context manager open in a task of its own: the MCP session manager holds a task
    group, which must be entered and left by the same task, while servers and test clients may
    run startup and shutdown in different tasks."""
    ready, done = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        async with open_cm():
            ready.set()
            await done.wait()

    task = asyncio.create_task(hold())
    waiter = asyncio.create_task(ready.wait())
    await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    waiter.cancel()
    if task.done():
        task.result()  # failed to start: raise its error
    try:
        yield
    finally:
        done.set()
        await task


def _mount_mcp(app: FastAPI, cfg: Settings) -> MCPServer:
    """Serve the MCP server at ``/mcp`` (Streamable HTTP). Its tools call this same app
    in-process, forwarding the caller's API key when the installation requires one."""

    @asynccontextmanager
    async def in_process(headers: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://minos", headers=headers, timeout=30
        ) as client:
            yield client

    mcp = build_server(in_process, cfg.studio_url)
    app.router.routes.extend(mcp.streamable_http_app(streamable_http_path="/mcp").routes)
    return mcp


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
