# Minos API (execution + management) — Python 3.14, dependencies managed by uv.
FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev
# The repository examples, from the "examples" build context (see compose.yaml).
COPY --from=examples . ./examples

# The examples are served read-only in workspace "local" (the Studio /demo page) and, on the
# first start, loaded into workspace "esempi" to open and change in the Studio.
ENV PATH="/app/.venv/bin:$PATH" MINOS_RULESETS_DIR=/app/examples/rulesets \
    MINOS_EXAMPLES_DIR=/app/examples MINOS_SEED_EXAMPLES=true
EXPOSE 8000
# Apply migrations, load the examples once, then serve both planes from one process.
CMD ["sh", "-c", "python -m minos.cli migrate && if [ \"$MINOS_SEED_EXAMPLES\" = true ]; then python -m minos.cli seed-examples; fi && exec uvicorn minos.api.app:app --host 0.0.0.0 --port 8000"]
