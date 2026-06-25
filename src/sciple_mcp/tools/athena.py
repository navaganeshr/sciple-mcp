"""Athena query tools — write, run, store SQL against AWS Athena via the
platform's `/athena` API. Server-side enforces the read-only parser gate,
per-query bytes-scanned cap, and the audit trail; nothing security-critical
lives here.

Wraps the REST routes:
  GET    /athena/workspaces
  GET    /athena/workspaces/{id}/databases
  GET    /athena/workspaces/{id}/databases/{db}/tables
  GET    /athena/workspaces/{id}/databases/{db}/tables/{t}
  POST   /athena/workspaces/{id}/executions
  GET    /athena/executions/{exec_id}
  GET    /athena/executions/{exec_id}/results
  POST   /athena/executions/{exec_id}/cancel
  GET/POST /athena/saved-queries
  GET    /athena/history

Permissions:
  dev_tools.athena.view   — list workspaces / browse catalog / history
  dev_tools.athena.run    — execute queries, manage own saved queries
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from sciple_mcp.client import ScipleClient


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def athena_list_workspaces() -> str:
        """List Athena workspaces in this tenant.

        Each workspace pins an AWS account + region + Athena workgroup as a
        query target. The returned id is the value to pass as `workspace_id`
        on every other Athena tool.
        """
        ws = await get_client().get("/athena/workspaces")
        if not ws:
            return "No Athena workspaces. Create one in /dev-tools/athena/new."
        return "\n".join(
            f"- {w['name']} (id={w['id']}, account={w['aws_account_id']}, "
            f"region={w['region']}, workgroup={w['workgroup']}, "
            f"mode={'READ-ONLY' if w['read_only'] else 'READ-WRITE'})"
            for w in ws
        )

    @mcp.tool()
    async def athena_list_databases(workspace_id: str) -> str:
        """List Glue databases visible to a workspace.

        Args:
            workspace_id: The Athena workspace id (from athena_list_workspaces).
        """
        dbs = await get_client().get(
            f"/athena/workspaces/{workspace_id}/databases"
        )
        return "\n".join(f"- {d['name']}" for d in dbs) or "No databases."

    @mcp.tool()
    async def athena_list_tables(workspace_id: str, database: str) -> str:
        """List tables in a Glue database.

        Args:
            workspace_id: The Athena workspace id.
            database: The Glue database name.
        """
        tables = await get_client().get(
            f"/athena/workspaces/{workspace_id}/databases/{database}/tables"
        )
        return "\n".join(f"- {t['name']}" for t in tables) or "No tables."

    @mcp.tool()
    async def athena_describe_table(
        workspace_id: str, database: str, table: str
    ) -> str:
        """Show columns and partition keys for a single table.

        Args:
            workspace_id: The Athena workspace id.
            database: The Glue database name.
            table: The table name.
        """
        t = await get_client().get(
            f"/athena/workspaces/{workspace_id}/databases/{database}/tables/{table}"
        )
        out = [f"Table: {database}.{table}", "Columns:"]
        out += [f"  {c['name']} {c['type']}" for c in t.get("columns", [])] or ["  (none)"]
        parts = t.get("partition_keys", [])
        if parts:
            out += ["Partition keys:"]
            out += [f"  {c['name']} {c['type']}" for c in parts]
        return "\n".join(out)

    @mcp.tool()
    async def athena_run_query(
        workspace_id: str, sql: str, max_wait_seconds: int = 60
    ) -> str:
        """Run a SQL query against an Athena workspace; polls until SUCCEEDED /
        FAILED / CANCELLED or `max_wait_seconds` elapses, then returns the
        execution id, status, and the first 1000-row page on success.

        Read-only / multi-statement / UNLOAD violations come back as 400 with a
        structured `code` (READ_ONLY_VIOLATION, MULTI_STATEMENT, etc).
        BYTES_CAP_EXCEEDED is the same path — the platform auto-cancels the
        execution and surfaces the code on the next poll.

        Args:
            workspace_id: The Athena workspace id.
            sql: A single SQL statement (the parser gate rejects multi-statement).
            max_wait_seconds: How long to poll before timing out (caller can
                resume with athena_get_execution_status). Default 60.
        """
        started = await get_client().post(
            f"/athena/workspaces/{workspace_id}/executions",
            {"query_text": sql},
        )
        exec_id = started["query_execution_id"]
        remaining = max_wait_seconds
        while remaining > 0:
            status = await get_client().get(f"/athena/executions/{exec_id}")
            s = status["status"]
            if s in ("SUCCEEDED", "FAILED", "CANCELLED"):
                if s != "SUCCEEDED":
                    return (
                        f"execution_id={exec_id} status={s} "
                        f"error_code={status.get('error_code')} "
                        f"error={status.get('error_message') or '(none)'}"
                    )
                results = await get_client().get(
                    f"/athena/executions/{exec_id}/results"
                )
                return json.dumps(
                    {
                        "execution_id": exec_id,
                        "status": s,
                        "bytes_scanned": status.get("bytes_scanned"),
                        "runtime_ms": status.get("runtime_ms"),
                        "columns": results.get("columns", []),
                        "rows": results.get("rows", []),
                        "next_token": results.get("next_token"),
                    },
                    default=str,
                )
            await asyncio.sleep(1)
            remaining -= 1
        return (
            f"execution_id={exec_id} status=TIMEOUT after {max_wait_seconds}s — "
            f"resume with athena_get_execution_status(execution_id={exec_id!r})."
        )

    @mcp.tool()
    async def athena_get_execution_status(execution_id: str) -> str:
        """Poll a single tick. Use when athena_run_query timed out.

        Args:
            execution_id: The Athena execution id.
        """
        return json.dumps(
            await get_client().get(f"/athena/executions/{execution_id}"),
            default=str,
        )

    @mcp.tool()
    async def athena_get_results(
        execution_id: str, next_token: str | None = None
    ) -> str:
        """Fetch the next 1000-row page of results from a SUCCEEDED execution.

        Args:
            execution_id: The Athena execution id.
            next_token: Optional page token returned by a previous call.
        """
        params = {"next_token": next_token} if next_token else None
        return json.dumps(
            await get_client().get(
                f"/athena/executions/{execution_id}/results", params=params
            ),
            default=str,
        )

    @mcp.tool()
    async def athena_cancel(execution_id: str) -> str:
        """Cancel an in-flight Athena execution (StopQueryExecution server-side).

        Args:
            execution_id: The Athena execution id.
        """
        await get_client().post(f"/athena/executions/{execution_id}/cancel")
        return f"Cancelled {execution_id}."

    @mcp.tool()
    async def athena_save_query(
        workspace_id: str, name: str, sql: str
    ) -> str:
        """Persist a SQL query under the caller's user, scoped to a workspace.

        Args:
            workspace_id: The Athena workspace id this saved query belongs to.
            name: Short label for the saved query.
            sql: The SQL text to save.
        """
        sq = await get_client().post(
            "/athena/saved-queries",
            {"workspace_id": workspace_id, "name": name, "query_text": sql},
        )
        return f"Saved '{sq['name']}' (id={sq['id']})."

    @mcp.tool()
    async def athena_list_saved(workspace_id: str | None = None) -> str:
        """List the caller's saved Athena queries, optionally filtered to a workspace.

        Args:
            workspace_id: Optional Athena workspace id to filter the list.
        """
        params = {"workspace_id": workspace_id} if workspace_id else None
        items = await get_client().get("/athena/saved-queries", params=params)
        if not items:
            return "No saved Athena queries."
        return "\n".join(f"- {q['name']} (id={q['id']})" for q in items)

    @mcp.tool()
    async def athena_history(
        workspace_id: str | None = None, limit: int = 20
    ) -> str:
        """Recent Athena executions for the caller (per-user history).

        Args:
            workspace_id: Optional Athena workspace id to filter the list.
            limit: Max rows to return (1-500). Default 20.
        """
        params: dict = {"limit": limit}
        if workspace_id:
            params["workspace_id"] = workspace_id
        items = await get_client().get("/athena/history", params=params)
        if not items:
            return "No history yet."
        return "\n".join(
            f"- [{h['status']}] {h['query_text'][:80].rstrip()} "
            f"(exec_id={h['query_execution_id']}, at {h['submitted_at']})"
            for h in items
        )
