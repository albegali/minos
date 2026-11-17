# 0005 · API keys and authorization

- Status: Accepted; updated in F3 (authentication optional, off by default)
- Date: 2026-11-16

## Context

Third-party systems (Dynamics, portals, ETL) call the Execution API thousands of times a minute;
the Studio and CI use the Management API. Authentication must not add noticeable latency.

## Decision

- Random 256-bit **API keys** with the `mns_` prefix, stored as **SHA-256**. A slow hash (Argon2,
  bcrypt) protects low-entropy secrets such as passwords; for a random token it adds no security
  and would cost milliseconds on every call. This replaces the "Argon2" requirement in the first
  version of the specification (RNF-09).
- **Scopes**: `admin` (global), `manage` and `exec` (bound to a workspace). The plaintext key is
  shown only once; the database keeps the hash and a readable prefix.
- The Execution API keeps an **in-memory cache** key → principal (60 s; 5 s for invalid keys).
  Revocation sends a NOTIFY that evicts the entry in the workers, so it takes effect within a few
  milliseconds, even before expiry.
- The Management API checks the key against the database on every request (it is not on the hot
  path).
- In F2 the Studio also uses an API key (scope `manage`), kept only in `sessionStorage`. Users and
  roles (OIDC with Entra ID or Google, RBAC Owner/Editor/Reviewer/Viewer) are postponed to F3: they
  need a real identity provider to be tested. API keys remain for systems.

## Consequences

- A compromised key is revoked with `DELETE /v1/workspaces/{ws}/api-keys/{id}`.
- **F3 update**: Minos is free software (MIT) meant for local installations without sensitive
  data, so authentication is **optional and off by default** (`MINOS_REQUIRE_AUTH=false`). The
  Studio reads `GET /v1/info` and opens without a login. API keys remain available to anyone who
  exposes the API on a network.
- User login (OIDC) and roles: not planned.
