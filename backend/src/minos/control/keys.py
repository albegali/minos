"""API keys.

Keys are 256-bit random tokens (``mns_<43 chars>``). Because they are high-entropy, a fast
SHA-256 digest is a safe storage format (slow password hashes such as Argon2 protect
low-entropy secrets and would add milliseconds to every call on the hot path). The first
characters are kept in clear (``key_prefix``) so that people can recognise a key.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

PREFIX: Final = "mns_"
SCOPES: Final = frozenset({"admin", "manage", "exec"})
"""``admin``: everything, all workspaces. ``manage``: control plane of one workspace.
``exec``: execution API of one workspace."""


def generate_key() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def display_prefix(key: str) -> str:
    return key[: len(PREFIX) + 6]
