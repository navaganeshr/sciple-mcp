"""Observability dashboard + panel tools — manage dashboards and their panels.

Wraps the REST routes:
  GET/POST   /observability/dashboards
  GET/PUT/DELETE /observability/dashboards/{id}
  POST/DELETE    /observability/dashboards/{id}/panels/{panel_id}

Requires the PAT to hold observability.view (reads) / observability.manage (writes).

Verified shapes:
  DashboardListResponse  — {"items": [DashboardSummary, ...], "total": int}
    each DashboardSummary has: id, name, description, panel_count, created_at, updated_at
  update_dashboard payload — PUT /{id} takes DashboardWrite = {"name": str (required,
    1-200 chars), "description": str|null (optional)}. This is a full-replace, NOT a
    partial patch — name is always required.
"""
from __future__ import annotations

from collections.abc import Callable

from sciple_mcp.client import ScipleClient


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def list_dashboards() -> str:
        """List all observability dashboards in the tenant (id, name, panel count)."""
        data = await get_client().get("/observability/dashboards")
        # DashboardListResponse shape: {"items": [...], "total": int}
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            return "No dashboards found."
        lines = []
        for d in items:
            lines.append(f"- {d['name']} (id={d['id']}, panels={d['panel_count']})")
        return "\n".join(lines)

    @mcp.tool()
    async def get_dashboard(dashboard_id: str) -> str:
        """Get a single dashboard's name, description, and panel list.

        Args:
            dashboard_id: The dashboard id to retrieve.
        """
        d = await get_client().get(f"/observability/dashboards/{dashboard_id}")
        desc = d.get("description") or "(no description)"
        header = f"{d['name']} (id={d['id']})\n{desc}"
        panels = d.get("panels", [])
        if not panels:
            return f"{header}\nNo panels."
        panel_lines = [f"  [{p['type']}] {p['title']} (id={p['id']})" for p in panels]
        return header + "\n" + "\n".join(panel_lines)

    @mcp.tool()
    async def create_dashboard(
        name: str,
        description: str | None = None,
    ) -> str:
        """Create a new observability dashboard.

        Args:
            name: Dashboard display name (1-200 characters, must be unique within tenant).
            description: Optional human-readable description.
        """
        body: dict = {"name": name}
        if description is not None:
            body["description"] = description
        d = await get_client().post("/observability/dashboards", body)
        return f"Created dashboard '{d['name']}' (id={d['id']})."

    @mcp.tool()
    async def update_dashboard(
        dashboard_id: str,
        name: str,
        description: str | None = None,
    ) -> str:
        """Replace a dashboard's name and description (full PUT — name is required).

        The API uses PUT with DashboardWrite: name is always required; description is
        optional (omitting it sets it to null on the server).

        Args:
            dashboard_id: The dashboard id to update.
            name: New display name (1-200 characters, must be unique within tenant).
            description: New description; pass null/omit to clear it.
        """
        # PUT /observability/dashboards/{id} takes DashboardWrite:
        #   {"name": str (required), "description": str|null (optional)}
        # This is a full replace — not a partial patch.
        body: dict = {"name": name}
        if description is not None:
            body["description"] = description
        d = await get_client().put(f"/observability/dashboards/{dashboard_id}", body)
        return f"Updated dashboard '{d['name']}' (id={d['id']})."

    @mcp.tool()
    async def delete_dashboard(dashboard_id: str) -> str:
        """Delete a dashboard and all its panels. This cannot be undone.

        Args:
            dashboard_id: The dashboard id to delete.
        """
        await get_client().delete(f"/observability/dashboards/{dashboard_id}")
        return f"Deleted dashboard {dashboard_id}."

    @mcp.tool()
    async def add_panel(
        dashboard_id: str,
        title: str,
        panel_type: str = "line",
        unit: str = "none",
        promql: str | None = None,
        legend_label: str | None = None,
    ) -> str:
        """Add a panel to a dashboard.

        Valid panel_type values: line, bar, stat, gauge, logs, log_table, text.

        When promql is provided the panel is created with a single PromQL query.
        For panels with no query (e.g. text panels) omit promql.

        Args:
            dashboard_id: The dashboard id to add the panel to.
            title: Panel title (1-200 characters).
            panel_type: One of: line, bar, stat, gauge, logs, log_table, text.
                        Defaults to "line".
            unit: Display unit string (e.g. "none", "bytes", "percent"). Defaults to "none".
            promql: Optional PromQL expression string. When provided, creates a single
                    query row for this panel.
            legend_label: Optional legend label for the query. Falls back to title when
                          promql is provided and legend_label is omitted.
        """
        body: dict = {
            "title": title,
            "type": panel_type,
            "unit": unit,
        }
        if legend_label is not None:
            body["legend_label"] = legend_label
        if promql is not None:
            body["queries"] = [
                {
                    "label": legend_label if legend_label is not None else title,
                    "expr": promql,
                    "order": 0,
                }
            ]
        # When promql is None, omit "queries" entirely — server defaults to [].
        p = await get_client().post(f"/observability/dashboards/{dashboard_id}/panels", body)
        return f"Added panel '{p['title']}' (id={p['id']}) to dashboard {dashboard_id}."

    @mcp.tool()
    async def delete_panel(dashboard_id: str, panel_id: str) -> str:
        """Delete a panel from a dashboard. This cannot be undone.

        Args:
            dashboard_id: The dashboard id that owns the panel.
            panel_id: The panel id to delete.
        """
        await get_client().delete(f"/observability/dashboards/{dashboard_id}/panels/{panel_id}")
        return f"Deleted panel {panel_id} from dashboard {dashboard_id}."
