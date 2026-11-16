#!/usr/bin/env bash
# Fresh database + migrations + combined API, for the end-to-end tests.
set -euo pipefail
cd "$(dirname "$0")/../../backend"
URL="${MINOS_E2E_DATABASE_URL:-postgresql+asyncpg://minos:minos@localhost:5432/minos_e2e}"
uv run python - "$URL" <<'PY'
import asyncio, sys
import asyncpg
url = sys.argv[1].replace("postgresql+asyncpg://", "postgresql://", 1)
base, _, name = url.rpartition("/")
async def main():
    conn = await asyncpg.connect(f"{base}/postgres")
    await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await conn.execute(f'CREATE DATABASE "{name}"')
    await conn.close()
asyncio.run(main())
PY
export MINOS_DATABASE_URL="$URL" MINOS_POLL_INTERVAL_S=2
uv run python -m minos.cli migrate
exec uv run uvicorn minos.api.app:app --port 8000 --log-level warning
