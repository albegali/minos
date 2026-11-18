"""Who acts: actors, roles, passwords and sign-in tokens.

Passwords are low-entropy secrets, so they get a slow, salted hash (scrypt from the standard
library, ~50 ms): unlike API keys and session tokens, whose 256 random bits make a fast
SHA-256 enough (see ``minos.control.keys``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Final, Literal

type Via = Literal["studio", "api", "mcp", "cli"]
VIAS: Final = frozenset({"studio", "api", "mcp", "cli"})


@dataclass(frozen=True, slots=True)
class Actor:
    """Who makes a change (``user:<email>``, ``apikey:<name>``, ``cli``) and through which
    channel: recorded on every audit event and on the rows a change creates."""

    id: str
    via: Via = "api"

    def __str__(self) -> str:
        return self.id


CLI: Final = Actor("cli", "cli")

# --------------------------------------------------------------------------- roles

ORG_ROLES: Final = ("member", "admin", "owner")
"""Organization roles, weakest first. Owners and admins manage members, invitations and
workspaces, and are admins of every workspace of the organization; only owners manage owners."""

WORKSPACE_ROLES: Final = ("viewer", "author", "publisher", "admin")
"""Workspace roles, weakest first. ``viewer``: read, validate, simulate, run tests.
``author``: edit entities, schemas, drafts and tests, import. ``publisher``: publish, archive,
move environments (``prod`` included). ``admin``: API keys, members, audit."""

type WorkspaceRole = Literal["viewer", "author", "publisher", "admin"]


def at_least(role: str | None, needed: str, ladder: tuple[str, ...] = WORKSPACE_ROLES) -> bool:
    return role is not None and ladder.index(role) >= ladder.index(needed)


# --------------------------------------------------------------------------- e-mail addresses

EMAIL_MAX: Final = 254
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_email(value: str) -> str | None:
    """The canonical (lower-case, trimmed) form of an address, ``None`` if it is not one."""
    email = value.strip().lower()
    if len(email) > EMAIL_MAX or not _EMAIL.match(email):
        return None
    return email


# --------------------------------------------------------------------------- passwords

PASSWORD_MIN: Final = 12
PASSWORD_MAX: Final = 256
_N, _R, _P = 2**14, 8, 1


def password_problem(password: str) -> str | None:
    if len(password) < PASSWORD_MIN:
        return f"the password must have at least {PASSWORD_MIN} characters"
    if len(password) > PASSWORD_MAX:
        return f"the password must have at most {PASSWORD_MAX} characters"
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    enc = base64.urlsafe_b64encode
    return f"scrypt${_N}${_R}${_P}${enc(salt).decode()}${enc(digest).decode()}"


_DUMMY: Final = hash_password(secrets.token_urlsafe(16))


def verify_password(password: str, stored: str | None) -> bool:
    """Constant work whether or not the account exists (``stored=None``), so that timing does
    not tell which addresses have an account."""
    if len(password) > PASSWORD_MAX:
        return False
    try:
        scheme, n, r, p, salt, digest = (stored or _DUMMY).split("$")
        assert scheme == "scrypt"
        dec = base64.urlsafe_b64decode
        got = hashlib.scrypt(
            password.encode(), salt=dec(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
    except ValueError, AssertionError:
        return False
    return stored is not None and hmac.compare_digest(got, dec(digest))


# --------------------------------------------------------------------------- tokens

SESSION_PREFIX: Final = "mss_"
INVITE_PREFIX: Final = "mni_"
_TOKEN = re.compile(r"^m(?:ss|ni)_[A-Za-z0-9_-]{43}$")


def generate_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(token: str) -> str | None:
    """SHA-256 of a well-formed session or invitation token (``None`` otherwise)."""
    if not _TOKEN.match(token):
        return None
    return hashlib.sha256(token.encode()).hexdigest()
