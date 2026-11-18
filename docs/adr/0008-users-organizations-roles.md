# 0008 · Users, organizations and roles

- Status: Accepted
- Date: 2026-11-17
- Updates: [0005](0005-api-keys-and-authorization.md) (users and roles were "not planned")

## Context

The Studio was used with shared API keys: the audit could not say who changed or published a
rule, MCP writes looked like Studio edits, and anyone with a `manage` key could promote to `prod`
(issue #18, FN-04). Minos is also meant to host several institutions (or schools of one
institution) on one installation, each with its own people and rules.

## Decision

- **Organizations** are the tenants. Every workspace belongs to one; the workspaces that existed
  before move into a `default` organization, which is also where admin keys and open
  installations create workspaces when they name none. Workspace slugs stay unique in the whole
  installation, because execution URLs (`/v1/exec/{workspace}/...`) carry them.
- **Users** are people: one password, **any number of e-mail addresses**, each of which signs in.
  Membership is per user, so whichever address someone types they see all their organizations.
  A session works in **one organization at a time**: chosen at sign-in when the user has only
  one (or names it), otherwise right after; it can be changed without signing in again.
- An address joins an account **through an invitation**: an owner or admin invites an address
  with an organization role (and optional workspace roles); the link carries a random token
  (shown once, stored as SHA-256, valid 7 days, one use). Signed in, accepting adds the invited
  address to the current account; otherwise the password of the account that already uses the
  address, or a new account. Minos sends no e-mail: the inviter sends the link.
- **Roles.** Organization: `owner` > `admin` > `member`; owners and admins manage members,
  invitations and workspaces and are admins of all its workspaces; only owners manage owners,
  and the last owner cannot leave. Workspace: `viewer` (read, validate, simulate, run tests) <
  `author` (entities, schemas, drafts, tests, import) < `publisher` (publish, archive, move
  environments, `prod` included) < `admin` (API keys, members, audit). A user without a role in
  a workspace of their organization gets `403`; workspaces of other organizations answer `404`.
- **Passwords** are hashed with scrypt (standard library, salted, ~50 ms, run off the event loop).
  Unknown addresses cost the same work, and ten failures for one address within 15 minutes block
  it for the rest of the window (per process). Minimum 12 characters.
- **Sessions** are random tokens (`mss_...`, 256 bits) stored as SHA-256, like API keys; they
  last `MINOS_SESSION_HOURS` (12) and are revoked by signing out. The Studio keeps the token in
  `sessionStorage` and sends it as a bearer token, like an API key (no cookies, so no CSRF and the
  Studio can be served from another origin). Roles are read from the database on every request,
  so removing someone takes effect at once.
- **API keys stay for machines** (CI, execution clients, MCP): a key has an owner (`createdBy`)
  and a name unique among the active keys of its workspace. A `manage` key is admin of its
  workspace; `admin` keys administer the installation (organizations included) and remain the
  only installation-wide administrators. Sessions cannot call the Execution API.
- **Audit.** Every event has an actor (`user:<primary e-mail>`, `apikey:<name>`, `cli`), a channel
  `via` (`studio`, `api`, `mcp`, `cli`; the MCP server and the Studio set `X-Minos-Via`, a user
  session is always `studio`), the organization and the workspace. Listings filter by action
  (exact or family `alias.`), target prefix, actor, channel and time, newest first with a cursor;
  organization admins read their organization's events, installation admins everything, events
  of no organization included. Consecutive draft saves of one actor through one channel within
  15 minutes are one event, and `minos.cli prune-audit` deletes draft saves older than
  `MINOS_AUDIT_RETENTION_DAYS` (90); publications, environments, keys and members are kept.
- **Open installations** (`MINOS_REQUIRE_AUTH=false`, the default) are unchanged: everyone is an
  administrator and the Studio needs no sign-in.

## Consequences

- An identity provider (OIDC / Entra ID) can be added later as another way to start the same
  session: accounts without a password (`password_hash` is nullable) and addresses matched to
  users as today.
- No self-service sign-up and no organization creation from the Studio: organizations are created
  by installation administrators (`minos.cli create-organization`, or `POST /v1/organizations`
  with an admin key), and their first owner with `minos.cli create-user ... --role owner`.
- No password reset by e-mail: an administrator re-invites, or sets a password from the command
  line. The login throttle is per process: behind several replicas the limit multiplies.
