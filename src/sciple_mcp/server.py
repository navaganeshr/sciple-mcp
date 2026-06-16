"""Sciple platform MCP server — exposes platform CRUD tools to a local Claude.

Auth: a Sciple personal access token (PAT) in SCIPLE_API_TOKEN. The server's
reach is whatever the PAT's scope grants; out-of-scope writes fail server-side.
"""
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from sciple_mcp.client import ScipleClient
from sciple_mcp.tools import environments, observability, runbooks, services

load_dotenv()

mcp = FastMCP("Sciple Platform")

_client: ScipleClient | None = None


def _get_client() -> ScipleClient:
    global _client
    if _client is None:
        _client = ScipleClient(
            base_url=os.environ["SCIPLE_API_URL"],
            token=os.environ["SCIPLE_API_TOKEN"],
            tenant_id=os.environ["SCIPLE_TENANT_ID"],
        )
    return _client


environments.register(mcp, _get_client)
observability.register(mcp, _get_client)
runbooks.register(mcp, _get_client)
services.register(mcp, _get_client)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
