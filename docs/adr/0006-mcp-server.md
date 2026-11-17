# 0006 · MCP server on top of the Management API, drafts only

- Status: Accepted
- Date: 2026-11-16

## Context

We want domain experts to describe rules in plain words in an AI client (Claude Desktop, Claude
Code, others) and have the assistant turn them into Minos entities and rule sets, leaving the
review in the Studio to a person. The standard protocol for giving tools to an assistant is MCP
(Model Context Protocol).

## Decision

- **Thin layer over the Management API.** The tools (`minos.mcp`, `mcp` SDK 2.x) call the existing
  HTTP endpoints instead of the service layer: the same validation, optimistic draft locking
  (`If-Match`), audit and API key scopes apply, and the same server works against any
  installation.
- **Two transports.** Streamable HTTP on `/mcp` of the combined API (calls stay in-process through
  ASGI, forwarding the client's key); stdio with `python -m minos.mcp` against `MINOS_API_URL`
  (key from `MINOS_API_KEY`).
- **Drafts only.** The tools create and edit workspaces, entities, schemas, drafts and tests, and
  validate and simulate; they **do not publish** and do not move environments. Every write returns
  the Studio link (`MINOS_STUDIO_URL`), where a person reviews and publishes; saved tests remain
  the gate.
- **The model learns the format from the server.** The `guide` tool returns the workflow, a full
  example and `docs/rgd-format.md` (a copy shipped in the package, checked identical by a test);
  validation responses say what to fix.
- HTTP endpoint with the SDK's DNS rebinding protection: it accepts only local hosts, consistent
  with a local installation.

## Consequences

- An assistant cannot put unreviewed rules into production; with API keys enabled, it can do only
  what the key it uses allows.
- No duplicated logic: a new Management API feature becomes a tool in a few lines.
- Exposing `/mcp` beyond `localhost` will require configuring the allowed hosts (not planned
  today).
