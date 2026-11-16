"""Minos MCP server: AI clients turn a description of rules into entities and rule set drafts.

Two ways to connect:

* Streamable HTTP at ``/mcp`` on the Minos API (``docker compose up`` → http://localhost:8000/mcp);
* stdio, ``python -m minos.mcp``, talking to the API at ``MINOS_API_URL``.
"""

from .server import build_server, guide_text, http_api

__all__ = ["build_server", "guide_text", "http_api"]
