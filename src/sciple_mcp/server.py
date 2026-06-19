"""Sciple platform MCP server — exposes platform CRUD tools to a local Claude.

Two transports are supported by the same FastMCP instance and tool registry:

  stdio (default)
      Spawned by Claude Desktop / Claude Code per session. Reads
      SCIPLE_API_URL + SCIPLE_API_TOKEN + SCIPLE_TENANT_ID from the env;
      the token is a `sciple_pat_...` PAT minted under Profile → Access
      tokens. Single user, one tenant.

      Invoke:  uvx sciple-mcp        (no args)

  HTTP (Streamable HTTP, Phase 3)
      Long-running local server. Each incoming MCP request carries a
      Bearer JWT issued by the Sciple platform's OAuth AS at
      /oauth/authorize → /oauth/token. The serve module validates the
      JWT against the AS's JWKS, stashes a per-request BearerContext in
      a contextvar, and `_get_client()` reads it to build a request-
      scoped platform client. Stdio env vars are ignored in this mode.

      Invoke:  uvx sciple-mcp serve --port 8765
"""
import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from sciple_mcp.client import ScipleClient
from sciple_mcp.tools import (
    environments,
    observability,
    projects,
    runbooks,
    services,
    tickets,
)

load_dotenv()

mcp = FastMCP("Sciple Platform")


def _get_client() -> ScipleClient:
    """Return the platform client for the current request.

    HTTP transport: per-request, constructed from the BearerContext set by
    `serve.AuthMiddleware`. Tenant + token come from the JWT claims.

    Stdio transport: cached singleton built from the SCIPLE_* env vars
    (PAT-based, single tenant).
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

    global _stdio_client
    if _stdio_client is None:
        _stdio_client = ScipleClient(
            base_url=os.environ["SCIPLE_API_URL"],
            token=os.environ["SCIPLE_API_TOKEN"],
            tenant_id=os.environ["SCIPLE_TENANT_ID"],
        )
    return _stdio_client


_stdio_client: ScipleClient | None = None


environments.register(mcp, _get_client)
observability.register(mcp, _get_client)
projects.register(mcp, _get_client)
runbooks.register(mcp, _get_client)
services.register(mcp, _get_client)
tickets.register(mcp, _get_client)


def main() -> None:
    # Subcommand dispatch — first positional arg picks the mode:
    #   sciple-mcp                stdio MCP server (backward-compat default)
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
