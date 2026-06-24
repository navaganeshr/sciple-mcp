"""`sciple-mcp login` — drive the OAuth browser dance and cache the result.

Flow, end-to-end:

  1. DCR — POST /oauth/register to mint a fresh client_id keyed to this
     machine's hostname. (We register once and reuse; saved into the
     credential cache so subsequent logins to the same platform skip this.)
  2. PKCE — generate a fresh code_verifier + S256 challenge.
  3. Local callback — bind a stdlib http.server on an ephemeral port. The
     bound port is required in the redirect_uri the AS will redirect back
     to.
  4. Browser — open the user's default browser to /oauth/authorize on the
     platform, passing client_id + redirect_uri + tenant_id + scope +
     code_challenge + state (random CSRF token).
  5. Wait for callback — single GET to /cb?code=...&state=... triggered by
     the browser after the user clicks Approve. We verify state, take the
     code, and immediately stop the server.
  6. Exchange — POST /oauth/token with grant_type=authorization_code +
     PKCE verifier. Returns access_token + refresh_token.
  7. Save — write to ~/.sciple/credentials.json (mode 0600).

All interactive prints go through `_say()` which forces `flush=True` so
output is visible immediately under pipes / IDE terminals.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from urllib.request import Request, urlopen

from sciple_mcp.credentials import (
    Credential,
    credentials_path,
    forget_credential,
    get_credential,
    load_store,
    require_secure_url,
    save_credential,
)


def _say(msg: str, *, err: bool = False) -> None:
    """Interactive-CLI print — never buffered."""
    stream = sys.stderr if err else sys.stdout
    print(msg, file=stream, flush=True)


# ── PKCE helpers ────────────────────────────────────────────────────────


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


# ── DCR ─────────────────────────────────────────────────────────────────


def _register_client(platform_url: str, client_name: str, redirect_uri: str) -> dict:
    body = json.dumps({
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
    }).encode()
    req = Request(
        platform_url.rstrip("/") + "/oauth/register",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ── Local callback server ──────────────────────────────────────────────


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot handler that captures the OAuth callback and shuts the
    server down. The captured params are stored on the server instance
    so `login()` can read them after `handle_request` returns.
    """

    def log_message(self, *_args, **_kwargs) -> None:
        # Silence default access-log spam — `_say()` prints what's useful.
        pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/cb":
            self.send_response(404)
            self.end_headers()
            return
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.server.callback_params = params  # type: ignore[attr-defined]

        body = (
            b"<!doctype html><meta charset=utf-8>"
            b"<title>Sciple login complete</title>"
            b"<style>body{font:14px/1.5 -apple-system,sans-serif;"
            b"max-width:640px;margin:80px auto;color:#1f2933;padding:0 20px}"
            b"h1{font-size:18px;margin-bottom:8px}p{color:#52606d}</style>"
            b"<h1>Sciple login complete</h1>"
            b"<p>You can close this tab and return to the terminal.</p>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _ephemeral_port() -> int:
    """Ask the OS for a free port — bind then immediately release."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_callback(server: socketserver.TCPServer, timeout_s: float) -> dict:
    """Run server.handle_request() in a thread; raise on timeout."""
    captured: dict[str, dict] = {}

    def serve_one() -> None:
        server.handle_request()
        captured["params"] = getattr(server, "callback_params", {})

    t = threading.Thread(target=serve_one, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        raise TimeoutError(
            f"No OAuth callback received within {int(timeout_s)}s. "
            "Did you approve the consent screen in your browser?"
        )
    return captured.get("params") or {}


# ── Token exchange ──────────────────────────────────────────────────────


def _exchange_code(
    *,
    platform_url: str,
    code: str,
    verifier: str,
    client_id: str,
    redirect_uri: str,
) -> dict:
    body = json.dumps({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }).encode()
    req = Request(
        platform_url.rstrip("/") + "/oauth/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ── login() ────────────────────────────────────────────────────────────


# Sentinel passed when --scope is omitted. The AS interprets an empty scope
# list as "grant me everything I hold on the tenant" — so the local agent
# inherits the user's role verbatim instead of forcing the user to enumerate
# permissions upfront.
INHERIT_ALL: tuple[str, ...] = ()


def login(
    *,
    platform_url: str,
    tenant_id: str | None,
    scope: list[str],
    client_name: str = "sciple-mcp-cli",
    open_browser: bool = True,
    timeout_s: float = 120.0,
) -> Credential:
    """Drive the full OAuth flow and persist the resulting credential.

    `tenant_id` is optional. If omitted, the dashboard's consent page
    falls back to the user's currently-active tenant — that's the
    typical UX for a personal local agent. Pass it explicitly only when
    the agent has to target a specific tenant the user isn't actively
    using.

    Returns the saved Credential. Raises on any failure.
    """
    require_secure_url(platform_url)
    existing = get_credential(platform_url)
    callback_port = _ephemeral_port()
    redirect_uri = f"http://127.0.0.1:{callback_port}/cb"

    if existing and existing.client_id.startswith("sciple_oac_"):
        client_id = existing.client_id
        _say(f"  using existing client_id={client_id}")
    else:
        _say(f"  registering OAuth client (DCR) → {platform_url}/oauth/register")
        registered = _register_client(platform_url, client_name, redirect_uri)
        client_id = registered["client_id"]
        _say(f"  ✅ client_id={client_id}")

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    server = socketserver.TCPServer(("127.0.0.1", callback_port), _CallbackHandler)
    server.allow_reuse_address = True

    # Build the authorize URL. Drop `tenant_id` when not specified so the
    # consent page resolves it from the user's active dashboard tenant.
    auth_params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(scope),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if tenant_id:
        auth_params["tenant_id"] = tenant_id
    auth_url = (
        platform_url.rstrip("/") + "/oauth/authorize?" + urllib.parse.urlencode(auth_params)
    )
    tenant_label = tenant_id or "(active tenant from dashboard)"
    _say(f"  opening browser to authorize as tenant={tenant_label}, scope={scope}")
    _say(f"  if it doesn't open, visit: {auth_url}")
    if open_browser:
        webbrowser.open(auth_url)

    _say(f"  waiting for callback on http://127.0.0.1:{callback_port}/cb (timeout {int(timeout_s)}s)…")
    try:
        params = _wait_for_callback(server, timeout_s)
    finally:
        server.server_close()

    if params.get("state") != state:
        raise RuntimeError(
            "OAuth state mismatch — possible CSRF. Discarded the callback."
        )
    code = params.get("code")
    if not code:
        err = params.get("error", "no_code")
        desc = params.get("error_description", "")
        raise RuntimeError(f"OAuth denied or failed: {err} {desc}")

    _say("  exchanging authorization code for tokens…")
    token_payload = _exchange_code(
        platform_url=platform_url,
        code=code,
        verifier=verifier,
        client_id=client_id,
        redirect_uri=redirect_uri,
    )

    now = int(time.time())
    # When the CLI didn't pass --tenant-id, the consent page picked one for
    # us. Read the resolved tenant back out of the access token's claims so
    # the cache reflects what the platform actually bound the token to.
    resolved_tenant = tenant_id or _tenant_id_from_jwt(token_payload["access_token"])
    cred = Credential(
        platform_url=platform_url,
        client_id=client_id,
        client_name=client_name,
        tenant_id=resolved_tenant,
        scope=list(scope),
        access_token=token_payload["access_token"],
        refresh_token=token_payload["refresh_token"],
        expires_at=now + int(token_payload["expires_in"]),
        obtained_at=now,
    )
    save_credential(cred, set_default=True)
    _say(f"  ✅ saved to {credentials_path()} (mode 0600), bound to tenant={resolved_tenant}")
    return cred


def _tenant_id_from_jwt(access_token: str) -> str:
    """Decode the JWT payload (no signature verify — we just minted it).

    Falls back to the literal string 'unknown' if the claim is missing.
    """
    try:
        payload_b64 = access_token.split(".")[1]
        # JWT base64url payload may lack padding; add it back.
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        import base64
        import json
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return str(claims.get("tenant_id") or "unknown")
    except Exception:
        return "unknown"


# ── CLI entrypoints ────────────────────────────────────────────────────


def main_login(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sciple-mcp login",
        description="Authenticate to a Sciple platform via OAuth and cache the tokens.",
    )
    parser.add_argument(
        "--platform-url", default="http://localhost:5175",
        help="Sciple platform base URL (default: http://localhost:5175)",
    )
    parser.add_argument(
        "--tenant-id", default=None,
        help=(
            "Tenant the resulting token will be bound to (e.g. Oejcdo). "
            "If omitted, the dashboard's consent page picks your currently-"
            "active tenant — the recommended default for personal local "
            "agents. Pass it explicitly only when targeting a tenant you're "
            "not actively using."
        ),
    )
    parser.add_argument(
        "--scope", action="append", default=None,
        help=(
            "Permission to request. Repeat for multiple. "
            "Default: omit to inherit ALL permissions the user holds on the tenant "
            "(recommended for personal local agents). Pass explicit --scope flags "
            "only when down-scoping (CI bots, shared tooling)."
        ),
    )
    parser.add_argument(
        "--client-name", default="sciple-mcp-cli",
        help="Friendly name shown on the consent screen + Connected apps page.",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open the browser — print the URL only.",
    )
    args = parser.parse_args(argv)

    scope = args.scope if args.scope else list(INHERIT_ALL)
    try:
        login(
            platform_url=args.platform_url,
            tenant_id=args.tenant_id,
            scope=scope,
            client_name=args.client_name,
            open_browser=not args.no_browser,
        )
    except Exception as exc:
        _say(f"\n  ❌ login failed: {exc}", err=True)
        return 1
    return 0


def main_print_token(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sciple-mcp print-token",
        description="Print the current cached access token (refresh if near expiry).",
    )
    parser.add_argument(
        "--platform-url", default=None,
        help="Platform URL (default: the cache's default entry).",
    )
    args = parser.parse_args(argv)

    cred = get_credential(args.platform_url)
    if cred is None:
        target = args.platform_url or "(default)"
        _say(f"No cached credential for {target}. Run `sciple-mcp login` first.", err=True)
        return 1

    if not cred.is_fresh():
        try:
            from sciple_mcp.credentials import refresh_access_token
            cred = refresh_access_token(cred)
        except Exception as exc:
            _say(f"Refresh failed: {exc}", err=True)
            return 2

    sys.stdout.write(cred.access_token)
    sys.stdout.flush()
    return 0


def main_logout(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sciple-mcp logout",
        description="Forget the cached credentials for a platform (does NOT revoke server-side).",
    )
    parser.add_argument(
        "--platform-url", default=None,
        help="Platform URL to forget (default: the cache's default entry).",
    )
    parser.add_argument(
        "--revoke", action="store_true",
        help="Also call POST /oauth/revoke to revoke the refresh token server-side.",
    )
    args = parser.parse_args(argv)

    store = load_store()
    target = args.platform_url or store.get("default")
    if not target:
        _say("No cached credentials.", err=True)
        return 1

    cred = get_credential(target)
    if args.revoke and cred is not None:
        try:
            require_secure_url(target)
            body = json.dumps({
                "token": cred.refresh_token,
                "token_type_hint": "refresh_token",
            }).encode()
            req = Request(
                target.rstrip("/") + "/oauth/revoke",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            urlopen(req, timeout=10).read()
            _say(f"  revoked server-side at {target}")
        except Exception as exc:
            _say(f"  warning: server-side revoke failed ({exc}) — clearing local cache anyway")

    removed = forget_credential(target)
    if removed:
        _say(f"  ✅ forgot {target}")
        return 0
    _say(f"No credential found for {target}.", err=True)
    return 1
