"""Organizations, users with several addresses, invitations, sessions, roles and audit."""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest

from minos.api.app import create_app
from minos.api.management import LoginThrottle
from minos.cli import create_admin_key, create_organization, create_user, main, prune_audit
from minos.control.identity import hash_password, normalise_email, verify_password

from .test_platform import settings

PASSWORD = "correct horse battery"


@pytest.fixture
async def client(clean_db: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings(clean_db))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://minos") as c:
            yield c


@pytest.fixture
async def admin(clean_db: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {await create_admin_key(clean_db, 'ops')}"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def login(c: httpx.AsyncClient, email: str, **extra: Any) -> dict[str, Any]:
    r = await c.post("/v1/auth/login", json={"email": email, "password": PASSWORD, **extra})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def invite(
    c: httpx.AsyncClient, headers: dict[str, str], org: str, email: str, **extra: Any
) -> dict[str, Any]:
    r = await c.post(
        f"/v1/organizations/{org}/invitations", json={"email": email, **extra}, headers=headers
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def accept(
    c: httpx.AsyncClient, token: str, headers: dict[str, str] | None = None, **body: Any
) -> httpx.Response:
    return await c.post(f"/v1/auth/invitations/{token}/accept", json=body, headers=headers or {})


async def test_one_account_many_addresses_many_organizations(
    client: httpx.AsyncClient, clean_db: str, admin: dict[str, str]
) -> None:
    c = client
    await create_organization(clean_db, "acme", "Acme")
    await create_organization(clean_db, "globex", "Globex")
    assert await create_user(clean_db, "Ada@Acme.example", "Ada", PASSWORD, "acme", "owner")

    # one organization: chosen at sign-in, with any letter case of the address
    ada = await login(c, "ada@acme.example")
    assert ada["organization"] == {"slug": "acme", "name": "Acme", "role": "owner"}
    assert ada["user"]["emails"] == ["ada@acme.example"]
    token = ada["token"]
    assert token.startswith("mss_")

    # Globex invites Ada at another address; she accepts while signed in: the address joins
    # her account
    inv = await invite(c, admin, "globex", "ada@globex.example", role="admin")
    assert inv["url"].endswith(f"/invite/{inv['token']}")
    preview = (await c.get(f"/v1/auth/invitations/{inv['token']}")).json()
    assert preview["organization"]["slug"] == "globex"
    assert preview["accountExists"] is False
    r = await accept(c, inv["token"], bearer(token))
    assert r.status_code == 200, r.text
    assert r.json()["organization"]["slug"] == "globex"
    assert sorted(r.json()["user"]["emails"]) == ["ada@acme.example", "ada@globex.example"]

    # the same password with either address: two organizations, none chosen yet
    for address in ("ada@acme.example", "ADA@globex.example"):
        body = await login(c, address)
        assert body["organization"] is None
        assert [(o["slug"], o["role"]) for o in body["organizations"]] == [
            ("acme", "owner"),
            ("globex", "admin"),
        ]
    session = bearer(body["token"])
    assert (await c.get("/v1/workspaces", headers=session)).json() == []

    # choose one at sign-in, or later
    assert (await login(c, "ada@globex.example", organization="acme"))["organization"]["slug"] == (
        "acme"
    )
    r = await c.post("/v1/auth/organization", json={"organization": "globex"}, headers=session)
    assert r.status_code == 200 and r.json()["organization"]["slug"] == "globex"
    me = (await c.get("/v1/auth/me", headers=session)).json()
    assert me["kind"] == "user" and me["organization"]["slug"] == "globex"
    r = await c.post("/v1/auth/organization", json={"organization": "default"}, headers=session)
    assert r.status_code == 403
    r = await c.post(
        "/v1/auth/login",
        json={"email": "ada@acme.example", "password": PASSWORD, "organization": "default"},
    )
    assert r.status_code == 403

    # an invitation works once
    assert (await accept(c, inv["token"], bearer(token))).status_code == 404
    assert (await c.get(f"/v1/auth/invitations/{inv['token']}")).status_code == 404

    # sign out ends the session
    assert (await c.post("/v1/auth/logout", headers=session)).status_code == 204
    assert (await c.get("/v1/workspaces", headers=session)).status_code == 401


async def test_invitations_create_accounts_and_grant_workspace_roles(
    client: httpx.AsyncClient, clean_db: str
) -> None:
    c = client
    await create_organization(clean_db, "acme", "Acme")
    await create_organization(clean_db, "globex", "Globex")
    await create_user(clean_db, "owner@acme.example", "Owner", PASSWORD, "acme", "owner")
    owner = bearer((await login(c, "owner@acme.example"))["token"])

    # the owner creates workspaces in the organization of the session
    r = await c.post("/v1/workspaces", json={"slug": "rules", "name": "Rules"}, headers=owner)
    assert r.status_code == 201 and r.json()["organization"] == "acme"
    await c.post("/v1/workspaces", json={"slug": "other", "name": "Other"}, headers=owner)
    r = await c.post(
        "/v1/workspaces",
        json={"slug": "x", "name": "X", "organization": "globex"},
        headers=owner,
    )
    assert r.status_code == 404  # not her organization

    # new account through an invitation, with a role in one workspace
    inv = await invite(
        c,
        owner,
        "acme",
        "bob@acme.example",
        workspaces=[{"workspace": "rules", "role": "viewer"}],
    )
    assert inv["workspaces"] == [{"workspace": "rules", "role": "viewer"}]
    assert (await accept(c, inv["token"], password=PASSWORD)).status_code == 422  # no name
    assert (await accept(c, inv["token"], name="Bob", password="short")).status_code == 422
    r = await accept(c, inv["token"], name="Bob", password=PASSWORD)
    assert r.status_code == 200, r.text
    bob = bearer(r.json()["token"])
    bob_id = r.json()["user"]["id"]
    listed = (await c.get("/v1/workspaces", headers=bob)).json()
    assert listed == [{"slug": "rules", "name": "Rules", "organization": "acme", "role": "viewer"}]

    # an existing account accepts with its password
    await create_user(clean_db, "carol@globex.example", "Carol", PASSWORD, "globex", "member")
    inv = await invite(c, owner, "acme", "carol@globex.example", role="admin")
    assert (await c.get(f"/v1/auth/invitations/{inv['token']}")).json()["accountExists"]
    assert (await accept(c, inv["token"], password="wrong password!!")).status_code == 401
    r = await accept(c, inv["token"], password=PASSWORD)
    assert r.status_code == 200
    assert [o["slug"] for o in r.json()["organizations"]] == ["acme", "globex"]

    # inviting a member again, or by someone who is not an admin
    r = await c.post(
        "/v1/organizations/acme/invitations", json={"email": "bob@acme.example"}, headers=owner
    )
    assert r.status_code == 409
    r = await c.post(
        "/v1/organizations/acme/invitations", json={"email": "dan@acme.example"}, headers=bob
    )
    assert r.status_code == 403
    r = await c.post(
        "/v1/organizations/acme/invitations",
        json={"email": "dan@acme.example", "workspaces": [{"workspace": "nope", "role": "viewer"}]},
        headers=owner,
    )
    assert r.status_code == 404
    r = await c.post(
        "/v1/organizations/acme/invitations",
        json={"email": "not an address"},
        headers=owner,
    )
    assert r.status_code == 422

    # pending invitations: a new one for the same address replaces the old one; revocation
    first = await invite(c, owner, "acme", "dan@acme.example")
    second = await invite(c, owner, "acme", "dan@acme.example")
    pending = (await c.get("/v1/organizations/acme/invitations", headers=owner)).json()
    assert [p["id"] for p in pending] == [second["id"]]
    assert (await c.get(f"/v1/auth/invitations/{first['token']}")).status_code == 404
    r = await c.delete(f"/v1/organizations/acme/invitations/{second['id']}", headers=owner)
    assert r.status_code == 204
    assert (await c.get(f"/v1/auth/invitations/{second['token']}")).status_code == 404

    # members: list, roles, workspace grants
    members = (await c.get("/v1/organizations/acme/members", headers=bob)).json()
    assert {m["email"]: m["role"] for m in members} == {
        "owner@acme.example": "owner",
        "bob@acme.example": "member",
        "carol@globex.example": "admin",
    }
    bob_row = next(m for m in members if m["id"] == bob_id)
    assert bob_row["workspaces"] == [{"workspace": "rules", "role": "viewer"}]
    r = await c.put(
        f"/v1/workspaces/other/members/{bob_id}", json={"role": "author"}, headers=owner
    )
    assert r.status_code == 200
    ws_members = (await c.get("/v1/workspaces/other/members", headers=bob)).json()
    assert {m["email"]: (m["role"], m["inherited"]) for m in ws_members} == {
        "owner@acme.example": ("admin", True),
        "bob@acme.example": ("author", False),
        "carol@globex.example": ("admin", True),
    }
    r = await c.put(f"/v1/workspaces/other/members/{bob_id}", json={"role": "boss"}, headers=owner)
    assert r.status_code == 422
    assert (
        await c.delete(f"/v1/workspaces/other/members/{bob_id}", headers=owner)
    ).status_code == 204
    assert [w["slug"] for w in (await c.get("/v1/workspaces", headers=bob)).json()] == ["rules"]

    # owners: only owners manage them, and the last one stays
    carol = bearer((await login(c, "carol@globex.example", organization="acme"))["token"])
    owner_id = next(m["id"] for m in members if m["role"] == "owner")
    r = await c.put(
        f"/v1/organizations/acme/members/{bob_id}", json={"role": "owner"}, headers=carol
    )
    assert r.status_code == 403
    r = await c.delete(f"/v1/organizations/acme/members/{owner_id}", headers=carol)
    assert r.status_code == 403
    r = await c.put(
        f"/v1/organizations/acme/members/{owner_id}", json={"role": "admin"}, headers=owner
    )
    assert r.status_code == 409
    r = await c.delete(f"/v1/organizations/acme/members/{owner_id}", headers=owner)
    assert r.status_code == 409
    r = await c.put(
        f"/v1/organizations/acme/members/{bob_id}", json={"role": "admin"}, headers=carol
    )
    assert r.status_code == 200
    assert {w["role"] for w in (await c.get("/v1/workspaces", headers=bob)).json()} == {"admin"}

    # removal (or leaving) takes the access away from running sessions
    r = await c.delete(f"/v1/organizations/acme/members/{bob_id}", headers=carol)
    assert r.status_code == 204
    assert (await c.get("/v1/workspaces", headers=bob)).json() == []
    assert (await c.get("/v1/workspaces/rules/rulesets", headers=bob)).status_code == 403
    carol_id = next(m["id"] for m in members if m["email"] == "carol@globex.example")
    r = await c.delete(f"/v1/organizations/acme/members/{carol_id}", headers=carol)
    assert r.status_code == 204


async def test_workspace_roles_gate_the_api(
    client: httpx.AsyncClient,
    clean_db: str,
    aurora_graph: dict[str, Any],
    valid_plan: dict[str, Any],
) -> None:
    c = client
    await create_organization(clean_db, "acme", "Acme")
    await create_organization(clean_db, "globex", "Globex")
    await create_user(clean_db, "owner@acme.example", "Owner", PASSWORD, "acme", "owner")
    await create_user(clean_db, "eve@globex.example", "Eve", PASSWORD, "globex", "owner")
    owner = bearer((await login(c, "owner@acme.example"))["token"])
    eve = bearer((await login(c, "eve@globex.example"))["token"])
    ws = "/v1/workspaces/rules"
    rs = f"{ws}/rulesets/emba"
    await c.post("/v1/workspaces", json={"slug": "rules", "name": "Rules"}, headers=owner)
    await c.post(f"{ws}/entities", json={"key": "Plan", "name": "Plan"}, headers=owner)
    await c.post(f"{ws}/entities/Plan/schemas", json={"samples": [valid_plan]}, headers=owner)
    body = {"key": "emba", "name": "EMBA", "entity": "Plan", "graph": aurora_graph}
    assert (await c.post(f"{ws}/rulesets", json=body, headers=owner)).status_code == 201

    people: dict[str, dict[str, str]] = {}
    for role in ("viewer", "author", "publisher"):
        inv = await invite(
            c,
            owner,
            "acme",
            f"{role}@acme.example",
            workspaces=[{"workspace": "rules", "role": role}],
        )
        r = await accept(c, inv["token"], name=role, password=PASSWORD)
        people[role] = bearer(r.json()["token"])
    viewer, author, publisher = people["viewer"], people["author"], people["publisher"]

    # viewers read, validate, simulate and run tests
    assert (await c.get(f"{rs}/draft", headers=viewer)).status_code == 200
    assert (await c.post(f"{rs}/validate", headers=viewer)).status_code == 200
    r = await c.post(f"{rs}/simulate", json={"input": valid_plan}, headers=viewer)
    assert r.status_code == 200
    draft = (await c.get(f"{rs}/draft", headers=viewer)).json()
    r = await c.put(f"{rs}/draft", json={"graph": draft["graph"]}, headers=viewer)
    assert r.status_code == 403 and "'author'" in r.json()["detail"]

    # authors edit, but do not publish
    r = await c.put(f"{rs}/draft", json={"graph": draft["graph"]}, headers=author)
    assert r.status_code == 200
    r = await c.post(f"{rs}/publish", json={"promoteTo": "prod"}, headers=author)
    assert r.status_code == 403 and "'publisher'" in r.json()["detail"]

    # publishers publish and promote to production; keys and audit are for admins
    r = await c.post(f"{rs}/publish", json={"promoteTo": "prod"}, headers=publisher)
    assert r.status_code == 201, r.text
    assert r.json()["publishedBy"] == "user:publisher@acme.example"
    r = await c.put(f"{rs}/aliases/test", json={"version": "0.1.0"}, headers=author)
    assert r.status_code == 403
    assert (await c.get(f"{ws}/api-keys", headers=publisher)).status_code == 403
    assert (await c.get(f"{ws}/audit", headers=publisher)).status_code == 403

    # other tenants do not see the workspace at all, and users are not installation admins
    assert (await c.get(f"{rs}/draft", headers=eve)).status_code == 404
    assert (await c.get("/v1/workspaces", headers=eve)).json() == []
    assert (await c.get("/v1/admin/api-keys", headers=owner)).status_code == 403
    r = await c.post("/v1/organizations", json={"slug": "new", "name": "New"}, headers=owner)
    assert r.status_code == 403

    # API keys: unique names among the active keys of a workspace, with an owner
    r = await c.post(f"{ws}/api-keys", json={"name": "ci", "scopes": ["manage"]}, headers=owner)
    assert r.status_code == 201
    ci_id, ci = r.json()["id"], {"X-Api-Key": r.json()["key"]}
    r = await c.post(f"{ws}/api-keys", json={"name": "ci", "scopes": ["exec"]}, headers=owner)
    assert r.status_code == 409
    keys = (await c.get(f"{ws}/api-keys", headers=owner)).json()
    assert keys[0]["createdBy"] == "user:owner@acme.example"
    await touch(c, rs, ci)

    # the audit names people and keys, and the channel
    events = (await c.get(f"{ws}/audit", headers=owner)).json()["items"]
    by_action = {(e["action"], e["actor"], e["via"]) for e in events}
    assert ("ruleset.publish", "user:publisher@acme.example", "studio") in by_action
    assert ("draft.save", "user:author@acme.example", "studio") in by_action
    assert ("draft.save", "apikey:ci", "api") in by_action
    assert ("apikey.create", "user:owner@acme.example", "studio") in by_action

    # revoked names can be used again
    assert (await c.delete(f"{ws}/api-keys/{ci_id}", headers=owner)).status_code == 204
    r = await c.post(f"{ws}/api-keys", json={"name": "ci", "scopes": ["exec"]}, headers=owner)
    assert r.status_code == 201


async def touch(c: httpx.AsyncClient, rs: str, headers: dict[str, str], via: str = "") -> None:
    draft = (await c.get(f"{rs}/draft", headers=headers)).json()
    graph = {**draft["graph"], "constants": {"rev": draft["lockVersion"]}}
    extra = {"X-Minos-Via": via} if via else {}
    r = await c.put(f"{rs}/draft", json={"graph": graph}, headers={**headers, **extra})
    assert r.status_code == 200, r.text


async def test_audit_filters_pages_and_retention(
    client: httpx.AsyncClient, clean_db: str, admin: dict[str, str], aurora_graph: dict[str, Any]
) -> None:
    c = client
    ws = "/v1/workspaces/rules"
    rs = f"{ws}/rulesets/emba"
    await c.post("/v1/workspaces", json={"slug": "rules", "name": "Rules"}, headers=admin)
    await c.post(f"{ws}/entities", json={"key": "Plan", "name": "Plan"}, headers=admin)
    await c.post(f"{ws}/entities/Plan/schemas", json={"samples": [{"a": 1}]}, headers=admin)
    body = {"key": "emba", "name": "EMBA", "entity": "Plan", "graph": aurora_graph}
    await c.post(f"{ws}/rulesets", json=body, headers=admin)
    for _ in range(3):
        await touch(c, rs, admin)
    await touch(c, rs, admin, via="mcp")
    for i in range(3):
        test = {"name": f"t{i}", "input": {"a": 1}, "expected": {"outcome": "valid"}}
        assert (await c.post(f"{rs}/tests", json=test, headers=admin)).status_code == 201

    # consecutive draft saves of one actor through one channel are one event
    saves = (await c.get(f"{ws}/audit?action=draft.save", headers=admin)).json()["items"]
    assert [(e["via"], e["detail"].get("saves", 1)) for e in saves] == [
        ("mcp", 1),
        ("api", 3),
    ]
    assert saves[1]["detail"]["firstLock"] == 2 and saves[1]["detail"]["lock"] == 4

    # filters: action family, target prefix, actor, channel, time
    tests = (await c.get(f"{ws}/audit?action=test.", headers=admin)).json()["items"]
    assert [e["target"] for e in tests] == ["rules/emba/t2", "rules/emba/t1", "rules/emba/t0"]
    r = await c.get(f"{ws}/audit?target=rules/emba/t1", headers=admin)
    assert [e["target"] for e in r.json()["items"]] == ["rules/emba/t1"]
    r = await c.get(f"{ws}/audit?via=mcp", headers=admin)
    assert [e["action"] for e in r.json()["items"]] == ["draft.save"]
    assert (await c.get(f"{ws}/audit?actor=apikey:nobody", headers=admin)).json()["items"] == []
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).date().isoformat()
    assert (await c.get(f"{ws}/audit?since={future}", headers=admin)).json()["items"] == []
    assert (await c.get(f"{ws}/audit?since=yesterday", headers=admin)).status_code == 422
    assert (await c.get(f"{ws}/audit?cursor=x", headers=admin)).status_code == 422

    # cursor pagination
    seen: list[int] = []
    cursor: int | None = None
    while True:
        url = f"{ws}/audit?limit=3" + (f"&cursor={cursor}" if cursor else "")
        page = (await c.get(url, headers=admin)).json()
        seen += [e["id"] for e in page["items"]]
        cursor = page["next"]
        if cursor is None:
            break
    everything = (await c.get(f"{ws}/audit?limit=1000", headers=admin)).json()["items"]
    assert seen == [e["id"] for e in everything] and len(seen) == len(set(seen))

    # the organization's and the installation's views
    org = (await c.get("/v1/organizations/default/audit", headers=admin)).json()["items"]
    assert {e["workspace"] for e in org} == {"rules"}
    key = await c.post(
        "/v1/admin/api-keys", json={"name": "ops2", "scopes": ["admin"]}, headers=admin
    )
    assert key.status_code == 201
    glob = (await c.get("/v1/admin/audit?scope=global", headers=admin)).json()["items"]
    assert [(e["action"], e["actor"]) for e in glob] == [
        ("apikey.create", "apikey:ops"),
        ("apikey.create", "cli"),
    ]
    assert (await c.get("/v1/admin/audit?scope=x", headers=admin)).status_code == 422
    assert len((await c.get("/v1/admin/audit", headers=admin)).json()["items"]) > len(glob)

    # retention: old draft saves go, the rest stays
    dsn = clean_db.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("UPDATE audit_event SET ts = ts - interval '200 days'")
    finally:
        await conn.close()
    assert await prune_audit(clean_db, 90, everything=False) == 2
    left = (await c.get(f"{ws}/audit?limit=1000", headers=admin)).json()["items"]
    assert "draft.save" not in {e["action"] for e in left} and left
    assert await prune_audit(clean_db, 1, everything=True) > 0
    assert (await c.get(f"{ws}/audit", headers=admin)).json()["items"] == []


async def test_sign_in_protection(client: httpx.AsyncClient, clean_db: str) -> None:
    c = client
    await create_user(clean_db, "ada@acme.example", "Ada", PASSWORD, None, "member")
    bad = {"email": "ada@acme.example", "password": "not the password"}
    assert (await c.post("/v1/auth/login", json=bad)).status_code == 401
    unknown = {"email": "nobody@acme.example", "password": PASSWORD}
    assert (await c.post("/v1/auth/login", json=unknown)).status_code == 401
    # an account with no organization signs in and sees nothing
    body = await login(c, "ada@acme.example")
    assert body["organization"] is None and body["organizations"] == []
    session = bearer(body["token"])
    assert (await c.get("/v1/workspaces", headers=session)).json() == []
    r = await c.post("/v1/workspaces", json={"slug": "w", "name": "W"}, headers=session)
    assert r.status_code == 422

    # password change
    r = await c.put("/v1/auth/password", json={"current": "nope", "new": "x" * 12}, headers=session)
    assert r.status_code == 403
    r = await c.put(
        "/v1/auth/password", json={"current": PASSWORD, "new": "short"}, headers=session
    )
    assert r.status_code == 422
    new = "a brand new passphrase"
    r = await c.put("/v1/auth/password", json={"current": PASSWORD, "new": new}, headers=session)
    assert r.status_code == 204
    assert (await c.post("/v1/auth/login", json={**bad, "password": new})).status_code == 200

    # forged, malformed and missing tokens
    for token in ("mss_" + "A" * 43, "mss_short", "mni_" + "A" * 43):
        assert (await c.get("/v1/workspaces", headers=bearer(token))).status_code == 401
    assert (await c.get("/v1/auth/me", headers=bearer("mss_" + "A" * 43))).status_code == 401
    assert (await c.post("/v1/auth/logout")).status_code == 401
    assert (await c.get("/v1/auth/invitations/mni_nope")).status_code == 404

    # too many failures for one address
    for _ in range(10):
        await c.post("/v1/auth/login", json=bad)
    assert (await c.post("/v1/auth/login", json={**bad, "password": new})).status_code == 429

    # an existing address cannot be given to a second account
    assert not await create_user(clean_db, "ADA@acme.example", "Other", PASSWORD, None, "member")


async def test_api_keys_and_open_installations(clean_db: str, admin: dict[str, str]) -> None:
    app = create_app(settings(clean_db, require_auth=False))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://minos") as c:
            # open installation: everyone administers, the Studio says so in the audit
            r = await c.post("/v1/workspaces", json={"slug": "w", "name": "W"})
            assert r.json()["organization"] == "default"
            orgs = (await c.get("/v1/organizations")).json()
            assert [o["slug"] for o in orgs] == ["default"]
            r = await c.post("/v1/organizations", json={"slug": "acme", "name": "Acme"})
            assert r.status_code == 201
            r = await c.post(
                "/v1/workspaces",
                json={"slug": "a", "name": "A", "organization": "acme"},
                headers={"X-Minos-Via": "studio"},
            )
            assert r.status_code == 201
            event = (await c.get("/v1/workspaces/a/audit")).json()["items"][0]
            assert (event["actor"], event["via"]) == ("apikey:dev", "studio")
            me = (await c.get("/v1/auth/me")).json()
            assert me["kind"] == "apikey" and me["admin"] is True

    await create_user(clean_db, "z@acme.example", "Z", PASSWORD, "acme", "admin")
    app = create_app(settings(clean_db))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://minos") as c:
            # API keys do not see organizations nor create workspaces, unless they are admin keys
            r = await c.post(
                "/v1/workspaces/w/api-keys", json={"name": "m", "scopes": ["manage"]}, headers=admin
            )
            manage = {"X-Api-Key": r.json()["key"]}
            assert (await c.get("/v1/organizations", headers=manage)).json() == []
            r = await c.post("/v1/workspaces", json={"slug": "n", "name": "N"}, headers=manage)
            assert r.status_code == 403
            me = (await c.get("/v1/auth/me", headers=manage)).json()
            assert me == {"kind": "apikey", "name": "m", "scopes": ["manage"], "admin": False}
            members = (await c.get("/v1/organizations/acme/members", headers=admin)).json()
            assert [(m["email"], m["role"]) for m in members] == [("z@acme.example", "admin")]
            assert (
                await c.get("/v1/organizations/acme/members", headers=manage)
            ).status_code == 404
            z = await login(c, "z@acme.example")
            assert [
                w["slug"]
                for w in (await c.get("/v1/workspaces", headers=bearer(z["token"]))).json()
            ] == ["a"]


def test_identity_helpers() -> None:
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and verify_password(PASSWORD, stored)
    assert not verify_password("other", stored)
    assert not verify_password(PASSWORD, None)
    assert not verify_password(PASSWORD, "garbage")
    assert not verify_password("x" * 300, stored)
    assert normalise_email("  Ada@Example.COM ") == "ada@example.com"
    assert normalise_email("nope") is None

    throttle = LoginThrottle(attempts=2, window_s=0)
    throttle.failed("a")
    throttle.failed("a")
    assert not throttle.blocked("a")  # the window has passed
    throttle = LoginThrottle(attempts=1, window_s=60)
    throttle.MAX_ENTRIES = 1  # type: ignore[misc]
    throttle.failed("a")
    assert throttle.blocked("a")
    throttle.failed("b")  # full: forget the others
    assert not throttle.blocked("a")


def test_cli_accounts(
    clean_db: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MINOS_DATABASE_URL", clean_db)
    monkeypatch.setenv("MINOS_PASSWORD", PASSWORD)
    assert main(["create-organization", "--slug", "acme", "--name", "Acme"]) == 0
    assert main(["create-organization", "--slug", "acme", "--name", "Again"]) == 1
    assert main(["create-organization", "--slug", "Bad Slug", "--name", "x"]) == 1
    args = ["create-user", "--email", "a@acme.example", "--name", "A", "--organization", "acme"]
    assert main([*args, "--role", "owner"]) == 0
    assert main(args) == 0  # existing account: membership kept (never lowered)
    assert "already exists" in capsys.readouterr().out
    assert main([*args[:-1], "nope"]) == 1
    monkeypatch.setenv("MINOS_PASSWORD", "short")
    assert main(["create-user", "--email", "b@acme.example", "--name", "B"]) == 1
    assert main(["prune-audit"]) == 0
    assert "0 audit event(s) older than 90 days" in capsys.readouterr().out
