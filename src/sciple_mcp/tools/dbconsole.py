"""SQL Console tools — query RDS Postgres/MySQL via the platform's `/dbconsole`
API. The platform handles the SSH/SSM tunnel, IAM token minting, profile
gating, and audit emission server-side.

Wraps the REST routes:
  GET    /dbconsole/connections
  GET    /dbconsole/connections/{id}
  GET    /dbconsole/connections/{id}/schema
  POST   /dbconsole/connections/{id}/query
  GET/POST /dbconsole/saved-queries

Permissions: each access profile attached to a connection gates read-only vs
read-write — an INSERT through a read-only profile errors server-side. The
caller must hold one of the connection's profile assignments.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from sciple_mcp.client import ScipleClient


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def db_list_connections() -> str:
        """List SQL Console connections (RDS Postgres / MySQL) in this tenant."""
        conns = await get_client().get("/dbconsole/connections")
        if not conns:
            return "No DB connections. Configure one in /dev-tools/sql/new."
        return "\n".join(
            f"- {c['name']} (id={c['id']}, engine={c['engine']}, host={c['host']})"
            for c in conns
        )

    @mcp.tool()
    async def db_describe_schema(connection_id: str) -> str:
        """Introspect a connection (databases / schemas / tables / columns).

        Args:
            connection_id: The DB Console connection id.
        """
        schemas = await get_client().get(
            f"/dbconsole/connections/{connection_id}/schema"
        )
        return json.dumps(schemas, default=str)

    @mcp.tool()
    async def db_query(connection_id: str, sql: str) -> str:
        """Run a SQL statement synchronously against a SQL Console connection.

        The caller's access profile (server-side) gates read-only vs read-write;
        an INSERT through a read-only profile errors at the platform, not here.

        Args:
            connection_id: The DB Console connection id.
            sql: A single SQL statement to execute.
        """
        return json.dumps(
            await get_client().post(
                f"/dbconsole/connections/{connection_id}/query", {"sql": sql}
            ),
            default=str,
        )

    @mcp.tool()
    async def db_save_query(
        connection_id: str, name: str, sql: str
    ) -> str:
        """Persist a SQL query under the caller's user, scoped to a connection.

        Args:
            connection_id: The DB Console connection id this saved query belongs to.
            name: Short label.
            sql: The SQL text.
        """
        sq = await get_client().post(
            "/dbconsole/saved-queries",
            {"connection_id": connection_id, "name": name, "sql": sql},
        )
        return f"Saved '{sq['name']}' (id={sq['id']})."

    @mcp.tool()
    async def db_list_saved(connection_id: str | None = None) -> str:
        """List the caller's saved DB Console queries.

        Args:
            connection_id: Optional connection id to filter the list.
        """
        params = {"connection_id": connection_id} if connection_id else None
        items = await get_client().get("/dbconsole/saved-queries", params=params)
        if not items:
            return "No saved DB queries."
        return "\n".join(f"- {q['name']} (id={q['id']})" for q in items)
