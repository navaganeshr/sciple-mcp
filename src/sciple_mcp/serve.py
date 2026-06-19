"""Streamable HTTP transport for sciple-mcp (Phase 3 of the OAuth design).

Run via `sciple-mcp serve [--host 127.0.0.1] [--port 8765]`. Wraps the same
FastMCP instance used by stdio mode with two pieces:

  1. A Starlette middleware that pulls the Bearer JWT off every incoming
     /mcp request, validates it against the AS's JWKS, and stashes a
     `BearerContext` in a contextvar so `_get_client()` can build a
     per-request platform client. Rejected tokens get a 401 with the
     standard `WWW-Authenticate: Bearer` challenge.

  2. A uvicorn invocation that serves the resulting ASGI app.

Stdio mode is unchanged and stays the default — this whole module is only
imported when `sciple-mcp serve` is invoked.
"""
from __future__ import annotations

import argparse
import contextvars
import json
import os
from urllib.request import urlopen

import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from sciple_mcp.auth import BearerContext, InvalidToken, JwksCache, validate_jwt

# Per-request bearer set by AuthMiddleware, read by _get_client() in server.py.
bearer_ctx: contextvars.ContextVar[BearerContext | None] = contextvars.ContextVar(
    "sciple_mcp_bearer", default=None
)


def _discover_jwks_url(platform_url: str) -> tuple[str, str, str]:
    """Fetch the AS's discovery metadata; return (jwks_uri, issuer, audience).

    Sciple's AS uses a single-audience model: the discovery `issuer` URL is
    also the JWT's `aud` claim (every Sciple resource server is a facet of
    the same logical service). RFC 8414 doesn't publish an audience field,
    so we adopt the issuer as the audience by contract with the AS.
    """
    meta_url = platform_url.rstrip("/") + "/.well-known/oauth-authorization-server"
    with urlopen(meta_url, timeout=5) as resp:
        doc = json.loads(resp.read())
    issuer = doc.get("issuer", platform_url)
    return doc["jwks_uri"], issuer, issuer


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate incoming Bearer tokens and stash them in `bearer_ctx`."""

    def __init__(self, app, *, jwks: JwksCache, issuer: str, audience: str) -> None:
        super().__init__(app)
        self._jwks = jwks
        self._issuer = issuer
        self._audience = audience

    async def dispatch(self, request: Request, call_next):
        # Health probe / capability discovery — keep public so something can
        # introspect "is sciple-mcp running here?" without auth.
        if request.url.path == "/healthz":
            return JSONResponse({"status": "ok"})

        # RFC 9728 Protected Resource Metadata — public, MCP clients fetch
        # this to discover which AS to drive the OAuth dance against.
        if request.url.path == "/.well-known/oauth-protected-resource":
            return JSONResponse(
                {
                    "resource": f"{request.base_url}".rstrip("/"),
                    "authorization_servers": [self._issuer],
                    "bearer_methods_supported": ["header"],
                    "resource_documentation": "https://github.com/navaganeshr/sciple-mcp",
                }
            )

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return _unauth("Missing Authorization: Bearer header")

        raw = auth.removeprefix("Bearer ").strip()
        try:
            bearer = validate_jwt(
                raw,
                jwks=self._jwks,
                issuer=self._issuer,
                audience=self._audience,
            )
        except InvalidToken as exc:
            return _unauth(str(exc))

        token = bearer_ctx.set(bearer)
        try:
            return await call_next(request)
        finally:
            bearer_ctx.reset(token)


def _unauth(detail: str) -> Response:
    return JSONResponse(
        {"detail": detail},
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="sciple-mcp"'},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sciple-mcp serve",
        description="Run sciple-mcp as a local Streamable HTTP MCP server.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--platform-url",
        default=os.environ.get("SCIPLE_PLATFORM_URL", "http://localhost:5175"),
        help="Sciple platform base URL (used to discover JWKS + as default API URL).",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SCIPLE_API_URL"),
        help="Sciple platform API base URL. Defaults to <platform-url>/api/v1.",
    )
    args = parser.parse_args()

    api_url = args.api_url or (args.platform_url.rstrip("/") + "/api/v1")
    os.environ["SCIPLE_API_URL"] = api_url  # _get_client() reads this

    jwks_uri, issuer, audience = _discover_jwks_url(args.platform_url)
    jwks = JwksCache(jwks_uri)

    # Import after env is set so server.py's module-level state binds correctly.
    from sciple_mcp.server import mcp

    asgi_app = mcp.streamable_http_app()

    # Wrap the FastMCP ASGI app with auth middleware. starlette_apps expose an
    # add_middleware that just stacks; equivalent to Starlette(middleware=...).
    asgi_app.add_middleware(
        AuthMiddleware,
        jwks=jwks,
        issuer=issuer,
        audience=audience,
    )

    print(
        f"sciple-mcp serving on http://{args.host}:{args.port}/mcp\n"
        f"  platform : {args.platform_url}\n"
        f"  api      : {api_url}\n"
        f"  issuer   : {issuer}\n"
        f"  jwks     : {jwks_uri}\n"
        f"  audience : {audience}"
    )
    uvicorn.run(asgi_app, host=args.host, port=args.port, log_level="info")
