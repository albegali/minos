# Minos API (execution + management) — Python 3.14, dependencies managed by uv.
FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH" MINOS_RULESETS_DIR=""
EXPOSE 8000
# Apply migrations, then serve both planes from one process (fine for local use).
CMD ["sh", "-c", "python -m minos.cli migrate && exec uvicorn minos.api.app:app --host 0.0.0.0 --port 8000"]
