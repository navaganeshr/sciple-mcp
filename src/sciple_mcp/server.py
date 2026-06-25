"""Sciple platform MCP server — exposes platform CRUD tools to a local Claude.

Two transports are supported by the same FastMCP instance and tool registry,
and **both use the same OAuth credential** — PAT-based MCP was dropped in
v0.7.0 (see the v0.7.0 entry below).

  stdio (default)
      Spawned by Claude Desktop / Claude Code per session. Reads the cached
      OAuth credential from `~/.sciple/credentials.json` (mode 0600,
      populated by `sciple-mcp login`). If the access token is within
      `REFRESH_LEEWAY_SECONDS` of expiry it is refreshed automatically
      using the cached refresh token. Stdio mode raises a clear "run
      sciple-mcp login first" error when no cache exists.

      Invoke:  uvx sciple-mcp        (no args)
      Prereq:  sciple-mcp login --platform-url <https://your.sciple.cloud>

  HTTP (Streamable HTTP, Phase 3)
      Long-running local server (legacy fallback now that the platform
      hosts /mcp itself). Each incoming request carries a Bearer JWT
      issued by the Sciple AS. The `serve` module validates the JWT,
      stashes a per-request BearerContext in a contextvar, and
      `_get_client()` reads it to build a request-scoped client.

      Invoke:  uvx sciple-mcp serve --port 8765

Why no PAT path:
  PAT-in-config (the old `SCIPLE_API_TOKEN` env var) forced users to mint
  a long-lived high-trust credential, paste it into a plaintext JSON config
  file, manually rotate it on every scope change, and revoke it from a
  separate UI when their laptop went missing. The OAuth path is strictly
  better: browser login (no token to copy), refresh-rotation built in,
  one-click revoke from Profile → Connected apps, and the JWT inherits
  the user's *current* role on the tenant (revoking a permission removes
  it from the next refresh automatically).
"""
import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from sciple_mcp.client import ScipleClient
from sciple_mcp.tools import (
    athena,
    cloud,
    dbconsole,
    environments,
    observability,
    projects,
    runbooks,
    services,
    tickets,
)

load_dotenv()

mcp = FastMCP("Sciple Platform")


class _NotLoggedInError(RuntimeError):
    """Raised when stdio mode can't find a cached OAuth credential.

    The MCP host (Claude Desktop / Code) shows this back to the user when
    a tool is invoked, so the message has to actually tell them what to do
    next rather than leaking a stack trace.
    """


def _get_client() -> ScipleClient:
    """Return the platform client for the current request.

    HTTP transport: per-request, constructed from the BearerContext set by
    `serve.AuthMiddleware`. Tenant + token come from the JWT claims.

    Stdio transport: per-request, constructed from the OAuth credential
    cache (`~/.sciple/credentials.json`). The access token is refreshed
    automatically when it's near expiry. There is no env-var-PAT fallback;
    `sciple-mcp login` must have been run at least once on this machine.
    """
    # Lazy import — serve.bearer_ctx pulls in uvicorn/starlette which we
    # don't want on the stdio path.
    try:
        from sciple_mcp.serve import bearer_ctx
        bearer = bearer_ctx.get()
    except Exception:
        bearer = None

    if bearer is not None:
        return ScipleClient(
            base_url=os.environ["SCIPLE_API_URL"],
            token=bearer.token,
            tenant_id=bearer.tenant_id,
        )

    # Stdio: load + refresh the cached OAuth credential. SCIPLE_PLATFORM_URL
    # picks which platform's cache entry to use when the user has more
    # than one — falls back to the cache's default.
    from sciple_mcp.credentials import ensure_fresh, get_credential
    cred = get_credential(os.environ.get("SCIPLE_PLATFORM_URL"))
    if cred is None:
        raise _NotLoggedInError(
            "No cached Sciple credentials. Run:\n"
            "    sciple-mcp login --platform-url <https://your.sciple.cloud>\n"
            "then restart this MCP server."
        )
    cred = ensure_fresh(cred)
    return ScipleClient(
        base_url=cred.platform_url.rstrip("/") + "/api/v1",
        token=cred.access_token,
        tenant_id=cred.tenant_id,
    )


athena.register(mcp, _get_client)
cloud.register(mcp, _get_client)
dbconsole.register(mcp, _get_client)
environments.register(mcp, _get_client)
observability.register(mcp, _get_client)
projects.register(mcp, _get_client)
runbooks.register(mcp, _get_client)
services.register(mcp, _get_client)
tickets.register(mcp, _get_client)


def main() -> None:
    # Subcommand dispatch — first positional arg picks the mode:
    #   sciple-mcp                stdio MCP server (uses OAuth cache)
    #   sciple-mcp serve [...]    long-running Streamable HTTP MCP server
    #   sciple-mcp login [...]    OAuth browser dance, cache tokens
    #   sciple-mcp logout [...]   clear cached tokens (optionally revoke AS-side)
    #   sciple-mcp print-token    print the current valid access token
    if len(sys.argv) >= 2:
        cmd = sys.argv[1]
        if cmd in ("serve", "login", "logout", "print-token", "install", "uninstall"):
            sys.argv.pop(1)
            if cmd == "serve":
                from sciple_mcp import serve
                serve.main()
                return
            if cmd == "login":
                from sciple_mcp.login import main_login
                sys.exit(main_login())
            if cmd == "logout":
                from sciple_mcp.login import main_logout
                sys.exit(main_logout())
            if cmd == "print-token":
                from sciple_mcp.login import main_print_token
                sys.exit(main_print_token())
            if cmd in ("install", "uninstall"):
                from sciple_mcp.daemon import main_install, main_uninstall
                sys.exit((main_install if cmd == "install" else main_uninstall)())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
