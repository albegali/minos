"""Run the Minos MCP server over stdio, for desktop clients that launch it as a command.

    MINOS_API_URL=http://localhost:8000 MINOS_STUDIO_URL=http://localhost:8080 \\
        uv run python -m minos.mcp

``MINOS_API_KEY`` is sent to the API when the installation requires keys (scope ``manage``).
"""

from __future__ import annotations

import os

from .server import build_server, http_api


def main() -> None:
    api = os.environ.get("MINOS_API_URL", "http://localhost:8000")
    studio = os.environ.get("MINOS_STUDIO_URL", "http://localhost:8080")
    key = os.environ.get("MINOS_API_KEY") or None
    build_server(http_api(api, key), studio).run("stdio")


if __name__ == "__main__":
    main()
