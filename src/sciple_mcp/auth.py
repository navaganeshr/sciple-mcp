"""JWT validation for Streamable HTTP transport.

Fetches the JWKS from the Sciple platform's discovery metadata once at
startup, caches the parsed public keys keyed by `kid`, and validates
incoming Bearer tokens against them. The JWKS is refreshed lazily when a
JWT presents an unknown `kid` (covers key rotation).

For stdio mode this module is unused — that path keeps the env-var-PAT
shape from v0.5.0.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from urllib.request import urlopen

import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm


@dataclass(frozen=True)
class BearerContext:
    """Validated OAuth bearer extracted from an incoming HTTP request.

    The raw `token` is passed through verbatim to the Sciple platform API as
    `Authorization: Bearer <token>`. The platform API independently
    re-validates it (defence in depth) and enforces scope + tenant binding
    from the JWT claims.
    """

    token: str         # the raw JWT, for forwarding to the platform API
    user_id: str       # sub claim
    tenant_id: str     # tenant_id claim
    scope: tuple[str, ...]
    client_id: str | None
    expires_at: int    # epoch seconds


class JwksCache:
    """Thread-safe JWKS cache keyed by `kid`."""

    def __init__(self, jwks_url: str, refresh_after: float = 300.0) -> None:
        self._url = jwks_url
        self._refresh_after = refresh_after
        self._lock = threading.Lock()
        self._keys: dict[str, object] = {}
        self._fetched_at: float = 0.0

    def get(self, kid: str) -> object:
        """Return the public key for the given `kid`, refreshing if unknown."""
        with self._lock:
            key = self._keys.get(kid)
            if key is not None and time.time() - self._fetched_at < self._refresh_after:
                return key
            # Either unknown kid or cache is stale — refresh.
            self._fetch_locked()
            key = self._keys.get(kid)
            if key is None:
                raise InvalidToken(f"Unknown key id (kid={kid})")
            return key

    def _fetch_locked(self) -> None:
        try:
            with urlopen(self._url, timeout=5) as resp:
                doc = json.loads(resp.read())
        except Exception as exc:
            # Surface as InvalidToken so AuthMiddleware turns it into a 401
            # instead of a Starlette 500. From the caller's perspective the
            # token can't be validated — same outcome either way.
            raise InvalidToken(f"JWKS fetch failed ({self._url}): {exc}") from exc
        keys: dict[str, object] = {}
        for jwk in doc.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            keys[kid] = RSAAlgorithm.from_jwk(json.dumps(jwk))
        self._keys = keys
        self._fetched_at = time.time()


class InvalidToken(Exception):
    """Raised when an incoming Bearer token is rejected."""


def validate_jwt(
    raw: str,
    *,
    jwks: JwksCache,
    issuer: str,
    audience: str,
) -> BearerContext:
    """Validate `raw` against the AS's public key set and return a context.

    Raises `InvalidToken` on any failure (bad signature, expired, wrong
    audience, missing required claim).
    """
    try:
        header = pyjwt.get_unverified_header(raw)
    except pyjwt.PyJWTError as exc:
        raise InvalidToken(f"Malformed JWT: {exc}") from exc

    kid = header.get("kid")
    if not kid:
        raise InvalidToken("JWT missing kid header")

    key = jwks.get(kid)

    try:
        claims = pyjwt.decode(
            raw,
            key,
            algorithms=[header.get("alg", "RS256")],
            audience=audience,
            issuer=issuer,
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise InvalidToken("Token expired") from exc
    except pyjwt.PyJWTError as exc:
        raise InvalidToken(f"JWT validation failed: {exc}") from exc

    if claims.get("token_use") != "access":
        raise InvalidToken("Wrong token_use")

    user_id = claims.get("sub")
    tenant_id = claims.get("tenant_id")
    if not user_id or not tenant_id:
        raise InvalidToken("JWT missing sub or tenant_id claim")

    scope_str = claims.get("scope") or ""
    return BearerContext(
        token=raw,
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        scope=tuple(s for s in scope_str.split(" ") if s),
        client_id=claims.get("client_id"),
        expires_at=int(claims.get("exp", 0)),
    )
