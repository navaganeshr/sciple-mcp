"""Runbook authoring tools — runbook CRUD + lifecycle, plus cell editing.

Wraps the REST routes:
  GET/POST   /runbooks                    GET/PATCH/DELETE /runbooks/{id}
  POST       /runbooks/{id}/promote
  POST       /runbooks/{id}/deprecate
  POST       /runbooks/{id}/cells         PATCH/DELETE /runbooks/{id}/cells/{cell_id}
  POST       /runbooks/{id}/cells/reorder

Requires the PAT to hold observability.view (reads) / observability.manage (writes).

Runbook lifecycle: draft -> reviewed -> standard. Deprecation is one-way from any state.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from sciple_mcp.client import ScipleClient


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def list_runbooks() -> str:
        """List all runbooks in the tenant with their lifecycle status and cell count."""
        runbooks = await get_client().get("/runbooks")
        if not runbooks:
            return "No runbooks found."
        lines = []
        for r in runbooks:
            cell_count = len(r.get("cells", []))
            lines.append(
                f"- [{r['status'].upper()}] {r['name']} (id={r['id']}, cells={cell_count})"
            )
        return "\n".join(lines)

    @mcp.tool()
    async def get_runbook(runbook_id: str) -> str:
        """Get a runbook with all its cells. Returns name, status, and each cell's type/target/content preview.

        Args:
            runbook_id: The runbook id to fetch.
        """
        r = await get_client().get(f"/runbooks/{runbook_id}")
        lines = [
            f"Runbook: {r['name']} (id={r['id']})",
            f"Status: {r['status']}",
            f"Description: {r['description'] or '(none)'}",
            "",
            "Cells:",
        ]
        for c in sorted(r.get("cells", []), key=lambda x: x["order"]):
            target = f" [{c['target_type']}]" if c.get("target_type") else ""
            lines.append(f"  [{c['order']}] {c['cell_type']}{target} (id={c['id']})")
            preview = c["content"][:120].replace("\n", " ")
            lines.append(f"      {preview}")
        return "\n".join(lines)

    @mcp.tool()
    async def create_runbook(name: str, description: str = "", tags: list[str] | None = None) -> str:
        """Create a new runbook in draft status. Returns the runbook id.

        Args:
            name: Short, descriptive name (e.g. "Restart failing pods in production").
            description: Markdown description of what this runbook does and when to use it.
            tags: Optional list of tags for categorisation (e.g. ["k8s", "incident"]).
        """
        body = {"name": name, "description": description, "tags": tags or []}
        r = await get_client().post("/runbooks", body)
        return f"Created runbook '{r['name']}' (id={r['id']}, status=draft)."

    @mcp.tool()
    async def add_cell(
        runbook_id: str,
        cell_type: str,
        content: str,
        order: int,
        target_type: str | None = None,
        target_config: str | None = None,
    ) -> str:
        """Add a cell to a runbook.

        Args:
            runbook_id: The runbook to add the cell to.
            cell_type: One of: 'markdown' (documentation), 'shell' (bash script), 'http' (HTTP request).
            content: The cell content — markdown text, bash script, or HTTP request body.
            order: Position in the notebook (0-indexed). Cells execute in ascending order.
            target_type: Execution target — 'k8s', 'ecs', or 'ec2'. Null for markdown cells.
            target_config: JSON string with target config:
                k8s:  {"namespace": "production", "pod_selector": "app=api"}
                ecs:  {"cluster_arn": "arn:aws:ecs:...", "task_definition": "my-task:5"}
                ec2:  {"instance_id": "i-0abc123def456"}
        """
        body: dict = {"cell_type": cell_type, "content": content, "order": order}
        if target_type is not None:
            body["target_type"] = target_type
        if target_config is not None:
            try:
                body["target_config"] = json.loads(target_config)
            except json.JSONDecodeError as exc:
                return f"Error: target_config is not valid JSON — {exc}"
        cell = await get_client().post(f"/runbooks/{runbook_id}/cells", body)
        target_info = f" -> {cell['target_type']}" if cell.get("target_type") else ""
        return f"Added {cell['cell_type']}{target_info} cell at order={cell['order']} (id={cell['id']})."

    @mcp.tool()
    async def update_cell(
        runbook_id: str,
        cell_id: str,
        content: str | None = None,
        target_type: str | None = None,
        target_config: str | None = None,
    ) -> str:
        """Update cell content or execution target. Only provided fields change.

        Args:
            runbook_id: The parent runbook id.
            cell_id: The cell id to update.
            content: New cell content (leave None to keep current).
            target_type: New target type — 'k8s', 'ecs', 'ec2', or None.
            target_config: JSON string with new target config, or None to keep current.
        """
        fields: dict = {}
        if content is not None:
            fields["content"] = content
        if target_type is not None:
            fields["target_type"] = target_type
        if target_config is not None:
            try:
                fields["target_config"] = json.loads(target_config)
            except json.JSONDecodeError as exc:
                return f"Error: target_config is not valid JSON — {exc}"
        if not fields:
            return "Nothing to update — provide at least one field."
        cell = await get_client().patch(f"/runbooks/{runbook_id}/cells/{cell_id}", fields)
        return f"Updated cell {cell['id']} (type={cell['cell_type']}, order={cell['order']})."

    @mcp.tool()
    async def delete_cell(runbook_id: str, cell_id: str) -> str:
        """Remove a cell from a runbook.

        Args:
            runbook_id: The parent runbook id.
            cell_id: The cell id to delete.
        """
        await get_client().delete(f"/runbooks/{runbook_id}/cells/{cell_id}")
        return f"Deleted cell {cell_id}."

    @mcp.tool()
    async def reorder_cells(runbook_id: str, cell_ids: list[str]) -> str:
        """Set the execution order of cells. Provide all cell ids in the desired sequence.

        Args:
            runbook_id: The runbook to reorder.
            cell_ids: All cell ids in the desired order, e.g. ["c3", "c1", "c2"].
        """
        cells = await get_client().post(
            f"/runbooks/{runbook_id}/cells/reorder", {"cell_ids": cell_ids}
        )
        lines = [f"Reordered {len(cells)} cells:"]
        for c in cells:
            lines.append(f"  [{c['order']}] {c['cell_type']} id={c['id']}")
        return "\n".join(lines)

    @mcp.tool()
    async def promote_runbook(runbook_id: str) -> str:
        """Advance the runbook lifecycle: draft -> reviewed -> standard.

        Call this when authoring is finished and the runbook is ready for engineer
        review (draft->reviewed), or when an engineer has approved it as a Standard
        Operating Procedure (reviewed->standard).

        Args:
            runbook_id: The runbook to promote.
        """
        r = await get_client().post(f"/runbooks/{runbook_id}/promote")
        if r["status"] == "reviewed":
            tail = "Engineers can now review and approve it in the Sciple UI."
        else:
            tail = "This runbook is now a Standard Operating Procedure."
        return f"Runbook '{r['name']}' promoted to '{r['status']}'. {tail}"

    @mcp.tool()
    async def deprecate_runbook(runbook_id: str) -> str:
        """Mark a runbook as deprecated. Use when a procedure is no longer safe or relevant.

        Args:
            runbook_id: The runbook to deprecate.
        """
        r = await get_client().post(f"/runbooks/{runbook_id}/deprecate")
        return f"Runbook '{r['name']}' (id={r['id']}) is now deprecated."
