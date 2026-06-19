"""Persistent OAuth credential cache for the local user.

Stored at `~/.sciple/credentials.json` (mode 0600). One file per local user,
not per client — keyed by platform_url to support pointing the CLI at
multiple Sciple deployments from the same machine.

File shape:

    {
      "version": 1,
      "default": "<platform_url>",
      "credentials": {
        "<platform_url>": {
          "platform_url": "...",
          "client_id": "sciple_oac_...",
          "client_name": "sciple-mcp-cli",
          "tenant_id": "Oejcdo",
          "scope": ["environments.view", ...],
          "access_token": "<jwt>",
          "refresh_token": "sciple_oart_...",
          "expires_at": 1781898000,
          "obtained_at": 1781890600
        }
      }
    }

The access_token is allowed to lag — callers refresh when it's within
`REFRESH_LEEWAY_SECONDS` of expiry. Refresh tokens rotate on the AS side,
so the file must be rewritten atomically after every refresh.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen

SCHEMA_VERSION = 1

# When the access token has fewer than this many seconds left we refresh it
# before handing it out. Generous because clock skew + the cost of a fresh
# refresh is trivial vs. the cost of a downstream 401.
REFRESH_LEEWAY_SECONDS = 120


def credentials_path() -> Path:
    """`~/.sciple/credentials.json`. Honors $SCIPLE_HOME if set (for tests)."""
    base = Path(os.environ.get("SCIPLE_HOME", str(Path.home() / ".sciple")))
    return base / "credentials.json"


@dataclass
class Credential:
    """One stored OAuth grant — everything needed to talk to a platform.

    `obtained_at` + `expires_at` are unix-seconds. We keep both so the
    refresh decision doesn't need to trust system clock-skew across the
    AS and the local box.
    """

    platform_url: str
    client_id: str
    client_name: str
    tenant_id: str
    scope: list[str]
    access_token: str
    refresh_token: str
    expires_at: int
    obtained_at: int = field(default_factory=lambda: int(time.time()))

    def is_fresh(self, leeway: int = REFRESH_LEEWAY_SECONDS) -> bool:
        return self.expires_at - leeway > int(time.time())


def load_store() -> dict:
    """Read the credentials file (returns an empty store if missing)."""
    path = credentials_path()
    if not path.exists():
        return {"version": SCHEMA_VERSION, "default": None, "credentials": {}}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_credential(cred: Credential, *, set_default: bool = True) -> None:
    """Atomically merge `cred` into the credentials file.

    Atomicity: write to a tempfile in the same directory, then `os.replace`.
    The file is chmod-ed to 0600 on every write — JWTs + refresh tokens are
    bearer secrets.
    """
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    store = load_store()
    store["version"] = SCHEMA_VERSION
    store.setdefault("credentials", {})
    store["credentials"][cred.platform_url] = asdict(cred)
    if set_default or store.get("default") is None:
        store["default"] = cred.platform_url

    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def get_credential(platform_url: str | None = None) -> Credential | None:
    """Return the credential for `platform_url` (or the default), if any."""
    store = load_store()
    key = platform_url or store.get("default")
    if not key:
        return None
    raw = store.get("credentials", {}).get(key)
    if raw is None:
        return None
    # Tolerate missing optional fields from older schema versions.
    return Credential(
        platform_url=raw["platform_url"],
        client_id=raw["client_id"],
        client_name=raw.get("client_name", "sciple-mcp-cli"),
        tenant_id=raw["tenant_id"],
        scope=list(raw.get("scope", [])),
        access_token=raw["access_token"],
        refresh_token=raw["refresh_token"],
        expires_at=int(raw["expires_at"]),
        obtained_at=int(raw.get("obtained_at", time.time())),
    )


def forget_credential(platform_url: str) -> bool:
    """Drop a stored credential — used by `sciple-mcp logout`. Returns True
    if a credential existed and was removed.
    """
    store = load_store()
    creds = store.get("credentials", {})
    if platform_url not in creds:
        return False
    del creds[platform_url]
    if store.get("default") == platform_url:
        # Promote any remaining credential to default, else clear.
        store["default"] = next(iter(creds), None)
    path = credentials_path()
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return True


# ── Refresh ────────────────────────────────────────────────────────────


def refresh_access_token(cred: Credential) -> Credential:
    """Exchange the refresh token for a new access + refresh pair.

    Raises RuntimeError if the AS rejects the refresh (e.g. revoked,
    expired, rotated by another process). The cache is updated on success.
    """
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": cred.refresh_token,
        "client_id": cred.client_id,
    }).encode()
    req = Request(
        cred.platform_url.rstrip("/") + "/oauth/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(f"Refresh failed: {exc}") from exc

    now = int(time.time())
    refreshed = Credential(
        platform_url=cred.platform_url,
        client_id=cred.client_id,
        client_name=cred.client_name,
        tenant_id=cred.tenant_id,
        scope=cred.scope,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", cred.refresh_token),
        expires_at=now + int(payload["expires_in"]),
        obtained_at=now,
    )
    save_credential(refreshed, set_default=False)
    return refreshed


def ensure_fresh(cred: Credential) -> Credential:
    """Return a credential whose access token has > REFRESH_LEEWAY left."""
    if cred.is_fresh():
        return cred
    return refresh_access_token(cred)
