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

import json
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
        cw_namespace: str | None = None,
        cw_metric_name: str | None = None,
        cw_stat: str | None = None,
        cw_dimensions: str | None = None,
        cw_period: int | None = None,
    ) -> str:
        """Add a panel to a dashboard.

        Valid panel_type values: line, bar, stat, gauge, logs, log_table, text.

        A panel may carry a single query in one of two shapes, never both:

          PromQL          set `promql`
          CloudWatch      set `cw_namespace` + `cw_metric_name` + `cw_stat`
                          (and optionally `cw_dimensions`, `cw_period`)

        For panels with no query (e.g. `text` panels) omit all query parameters.

        Note on log panels: `panel_type="logs"` and `"log_table"` are accepted by
        the panel-type enum, but the API's PanelQueryWrite schema does not yet
        carry log-query fields (no log expression, no log group / index, no data
        source reference). Log panels created via this tool will not have a
        query — author them in the UI for now.

        Args:
            dashboard_id: The dashboard id to add the panel to.
            title: Panel title (1-200 characters).
            panel_type: One of: line, bar, stat, gauge, logs, log_table, text.
                        Defaults to "line".
            unit: Display unit string (e.g. "none", "bytes", "percent").
                  Defaults to "none".
            promql: PromQL expression string. Mutually exclusive with the
                    cw_* parameters.
            legend_label: Legend label for the query. Falls back to `title` when
                          a query is provided and legend_label is omitted.
            cw_namespace: CloudWatch namespace (e.g. "AWS/EC2", "AWS/RDS").
                          Required when adding a CloudWatch query.
            cw_metric_name: CloudWatch metric name (e.g. "CPUUtilization").
                            Required when adding a CloudWatch query.
            cw_stat: CloudWatch statistic (e.g. "Average", "Sum", "Maximum",
                     "p99"). Required when adding a CloudWatch query.
            cw_dimensions: Optional CloudWatch dimensions as a JSON string of a
                           list of {"Name": ..., "Value": ...} dicts, e.g.
                           '[{"Name": "InstanceId", "Value": "i-0abc..."}]'.
            cw_period: Optional CloudWatch period in seconds (integer >= 1,
                       e.g. 60 for 1-minute granularity).
        """
        is_promql = promql is not None and promql.strip() != ""
        is_cloudwatch = any(
            v is not None for v in (cw_namespace, cw_metric_name, cw_stat)
        )

        # Friendly tool-level validation; the API also enforces these but the
        # error message there is less specific.
        if is_promql and is_cloudwatch:
            return (
                "Error: a panel query is either PromQL OR CloudWatch, not both. "
                "Got both `promql` and one of `cw_namespace`/`cw_metric_name`/`cw_stat`."
            )
        if is_cloudwatch and not (cw_namespace and cw_metric_name and cw_stat):
            missing = [
                name for name, val in
                (("cw_namespace", cw_namespace),
                 ("cw_metric_name", cw_metric_name),
                 ("cw_stat", cw_stat))
                if not val
            ]
            return (
                f"Error: CloudWatch queries require cw_namespace + cw_metric_name + "
                f"cw_stat. Missing: {', '.join(missing)}."
            )

        body: dict = {
            "title": title,
            "type": panel_type,
            "unit": unit,
        }
        if legend_label is not None:
            body["legend_label"] = legend_label

        if is_promql:
            body["queries"] = [
                {
                    "label": legend_label if legend_label is not None else title,
                    "expr": promql,
                    "order": 0,
                }
            ]
        elif is_cloudwatch:
            query: dict = {
                "label": legend_label if legend_label is not None else title,
                "namespace": cw_namespace,
                "metric_name": cw_metric_name,
                "stat": cw_stat,
                "order": 0,
            }
            if cw_dimensions is not None:
                try:
                    parsed = json.loads(cw_dimensions)
                except json.JSONDecodeError as exc:
                    return f"Error: cw_dimensions is not valid JSON — {exc}"
                if not isinstance(parsed, list):
                    return (
                        "Error: cw_dimensions must be a JSON list of "
                        "{Name, Value} objects."
                    )
                query["dimensions"] = parsed
            if cw_period is not None:
                query["period"] = cw_period
            body["queries"] = [query]
        # When neither shape is provided, omit "queries" — server defaults to [].

        p = await get_client().post(
            f"/observability/dashboards/{dashboard_id}/panels", body
        )
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
