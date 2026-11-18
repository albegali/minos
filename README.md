<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/minos-logo-dark.png">
    <img alt="Minos" src="docs/brand/minos-logo-light.png" width="360">
  </picture>
</p>

<p align="center"><b>JSON rule engine · visual editor · sub-millisecond API</b></p>

# Minos

**Minos** is a JSON-in / JSON-out rule engine: it evaluates a JSON object against a versioned rule
graph and returns a structured outcome, exit point and feedback, with sub-millisecond latency.
It is generic: the examples cover a university study plan, an e-commerce order and loan
eligibility, but any JSON object with a schema can be validated.

> Like Minos, king and lawgiver of Crete and later judge of souls, Minos judges every object and
> decides which way it goes.

Status: **phases F0–F3 complete** on the [roadmap](docs/spec.md#roadmap): compiled engine, control
plane on PostgreSQL with versions, aliases and effective dates, Execution API with hot reload, Minos
Studio to build, test and publish rules without writing JSON, and an MCP server that lets an AI
assistant write them from a description.

![Minos Studio: a simulated rule set, with the path highlighted on the canvas and messages and output in the panel](docs/screenshots/simulation.png)

## Layout

| Path | Contents |
| --- | --- |
| [`backend/`](backend/) | Python 3.14: engine (`minos.engine`), schemas (`minos.schema`), control plane (`minos.control`, `minos.db`), FastAPI API (`minos.api`), MCP server (`minos.mcp`), tests, benchmarks |
| [`frontend/`](frontend/) | Minos Studio: React 19, Fluent UI 2, React Flow; Vitest and Playwright tests |
| [`examples/`](examples/) | Example rule sets from four domains (study plan, enrollment over several entities, e-commerce order, loan; illustrative values), entity schemas, inputs and test suites |
| [`docs/spec.md`](docs/spec.md) | Functional specification, architecture, API and roadmap |
| [`docs/rgd-format.md`](docs/rgd-format.md) | Rule Graph Document 1.0 format reference |
| [`docs/studio.md`](docs/studio.md) | Minos Studio quick guide |
| [`docs/api.md`](docs/api.md) | Execution and Management API reference |
| [`docs/mcp.md`](docs/mcp.md) | MCP server: rules written by an AI assistant |
| [`docs/benchmarks.md`](docs/benchmarks.md) | Measurements and phase gates |
| [`docs/adr/`](docs/adr/) | Architecture decisions |
| [`docs/improvements.md`](docs/improvements.md) | Known issues and improvements, tracked by ID and status |
| [`docs/brand/`](docs/brand/) | Logo (original, light and dark theme versions, mark) |
| [`docs/screenshots/`](docs/screenshots/) | Studio screenshots used on this page |

## Quick start

With Docker, a single command starts PostgreSQL, the API and the Studio:

```bash
docker compose up --build
```

Open http://localhost:8080 (Studio) and http://localhost:8000/v1/info (API). The installation is
**open**: no login, meant for local use.

On first start the **Esempi** workspace already holds every example in the repo (study plan,
e-commerce order, loan), published to `prod` with their tests: open them in the Studio, simulate,
edit and republish. For example:

```bash
curl -s -H 'Content-Type: application/json' -d "{\"input\": $(cat examples/inputs/order-valid.json)}" http://localhost:8000/v1/exec/esempi/shop.order
```

To start with an empty database set `MINOS_SEED_EXAMPLES: "false"` in `compose.yaml`;
`docker compose down -v` wipes the data and the examples are reloaded on the next start. To require
sign-in (people with e-mail and password, in organizations with roles) and API keys (machines),
set `MINOS_REQUIRE_AUTH=true` (see [`docs/api.md`](docs/api.md)). The
[Studio guide](docs/studio.md) walks through the whole path, from entity to publication.

### With sign-in and organizations

The default installation is open: no sign-in, no organizations to choose. To try users,
organizations, invitations and roles, set in `compose.yaml` under `api.environment`:

```yaml
MINOS_REQUIRE_AUTH: "true"
MINOS_ALLOW_SIGNUP: "true"   # optional: anyone can register a new organization from the Studio
```

then `docker compose up --build`. With `MINOS_ALLOW_SIGNUP` on, open http://localhost:8080 and
choose *Register an organization*. Otherwise create the first organization and its owner from the
command line (the second command asks for a password of at least 12 characters):

```bash
docker compose exec api python -m minos.cli create-organization --slug gsom --name "GSoM"
docker compose exec -it api python -m minos.cli create-user --email you@example.org \
    --name "Your Name" --organization gsom --role owner
```

The examples loaded on first start live in the `default` organization: run `create-user` again
with `--organization default` (an existing account only gets the membership) to see them too.
From the Studio, *Members and invitations* creates invitation links; an account that belongs to
several organizations chooses one after signing in. See [ADR 0008](docs/adr/0008-users-organizations-roles.md).

### Development without Docker

Requirements: [uv](https://docs.astral.sh/uv/), Node.js 22 or later (CI on Node 24 LTS),
PostgreSQL 16 or 17.

```bash
export MINOS_DATABASE_URL=postgresql+asyncpg://minos:minos@localhost:5432/minos
```

```bash
cd backend && uv sync && uv run python -m minos.cli migrate && uv run python -m minos.cli seed-examples && uv run uvicorn minos.api.app:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Studio on http://localhost:5173. Without `MINOS_DATABASE_URL` the API serves the examples in
`examples/rulesets` read-only and the Studio opens the demo (`/demo`).

In a larger installation the Execution API and the Management API run as separate processes
(`minos.api.app:execution_app`, `minos.api.app:management_app`).

## Minos Studio

The Studio is the web rule editor: you build the graph by dragging nodes from the palette,
configure each node with forms driven by the entity schema, simulate on a real input, save
simulations as tests and publish per environment, all without writing JSON. The
[Studio guide](docs/studio.md) walks through the whole path.

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/workspace.png" alt="Workspace page with rule sets and entities"></td>
    <td width="50%"><img src="docs/screenshots/entity.png" alt="Entity schema with fields, types and references"></td>
  </tr>
  <tr>
    <td><b>Workspace.</b> The rule sets and entities of an area, with import from file.</td>
    <td><b>Entity.</b> The schema, inferred from samples or written by hand, with the reference to use in every rule.</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/editor-node.png" alt="Editor with a Compute node selected and its form in the panel"></td>
    <td><img src="docs/screenshots/canvas-full.png" alt="Full-width canvas with the panel closed and the simulated path"></td>
  </tr>
  <tr>
    <td><b>Configuration.</b> Palette on the left, canvas in the middle, the selected node's form on the right; nested expressions stay readable at every level.</td>
    <td><b>Collapsible panel.</b> The panel collapses into an icon bar and leaves all the space to the graph; selecting a node reopens it.</td>
  </tr>
</table>

The Studio follows the operating system theme, light or dark, and adapts to narrow windows and
phones.

![The Studio in dark theme](docs/screenshots/dark.png)

## Visual identity

| | Colour | Use |
| --- | --- | --- |
| <img src="docs/brand/swatch-navy.png" width="16" height="16" alt=""> | Night blue `#0B2D4E` | Brand text, primary actions |
| <img src="docs/brand/swatch-teal.png" width="16" height="16" alt=""> | Teal `#039BB0` | Accents, focus, selection, simulated path |
| <img src="docs/brand/swatch-green.png" width="16" height="16" alt=""> | Green `#01928C` | Positive outcome, passed nodes |

- **Font**: [League Spartan](https://fonts.google.com/specimen/League+Spartan), loaded from Google
  Fonts.
- **Logo**: the original and the versions for light and dark backgrounds are in
  [`docs/brand/`](docs/brand/); in the Studio the mark is drawn in SVG
  ([`Brand.tsx`](frontend/src/components/Brand.tsx)) and changes colour with the theme.
- **Theme**: colours, font, radii and shadows of the Fluent UI components live in
  [`theme.ts`](frontend/src/theme.ts); the CSS variables for canvas and nodes in
  [`styles.css`](frontend/src/styles.css).

## AI assistant (MCP)

Connect an MCP client to `http://localhost:8000/mcp` (or start `python -m minos.mcp` over stdio)
and describe the rules in words: the assistant creates entities and rule sets as drafts, validates
them, tries them out and returns the Studio link for review and publication. For Claude Code:

```bash
claude mcp add --transport http minos http://localhost:8000/mcp
```

Details, Claude Desktop configuration and tools in [`docs/mcp.md`](docs/mcp.md).

## Quality

```bash
cd backend && uv run ruff check . && uv run mypy && uv run pytest && uv run python bench/bench_engine.py && uv run python bench/bench_api.py
```

```bash
cd frontend && npm run lint && npm test && npm run build
```

```bash
cd frontend && npm run e2e   # Playwright: starts the API and the Studio on a fresh database (local PostgreSQL)
```

## License

[MIT](LICENSE).
