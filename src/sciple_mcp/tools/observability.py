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
        legend_label: str | None = None,
        datasource_id: str | None = None,
        # ── Metrics: PromQL ──
        promql: str | None = None,
        # ── Metrics: CloudWatch ──
        cw_namespace: str | None = None,
        cw_metric_name: str | None = None,
        cw_stat: str | None = None,
        cw_dimensions: str | None = None,
        cw_period: int | None = None,
        # ── Logs: ElasticSearch / OpenSearch ──
        es_index: str | None = None,
        kql_filter: str | None = None,
        # ── Logs: CloudWatch Logs ──
        cw_log_group: str | None = None,
        cw_filter_pattern: str | None = None,
        # ── Log display options (apply to both log kinds) ──
        log_columns: list[str] | None = None,
        log_limit: int | None = None,
        log_wrap_message: bool | None = None,
        log_expandable_rows: bool | None = None,
        log_highlight_by_severity: bool | None = None,
        log_live_tail: bool | None = None,
        # ── Text panel ──
        text_content: str | None = None,
        text_background: str | None = None,
    ) -> str:
        """Add a panel to a dashboard.

        A panel belongs to ONE of five shapes — pick one based on what the user
        wants and supply only that shape's parameters:

          1. PromQL metric           promql=<expr>
          2. CloudWatch metric       cw_namespace + cw_metric_name + cw_stat
                                     (optional cw_dimensions JSON, cw_period)
          3. ElasticSearch/OpenSearch
             logs                    panel_type='logs' (or 'log_table')
                                     + es_index + optional kql_filter
                                     + optional log_* display options
          4. CloudWatch Logs         panel_type='logs' (or 'log_table')
                                     + cw_log_group + optional cw_filter_pattern
                                     + optional log_* display options
          5. Text                    panel_type='text' + text_content
                                     (optional text_background hex color)

        ALWAYS pass `datasource_id` (the observability data source id from the
        Sciple UI → Data sources) for metric + log panels — without it the
        panel binds to the dashboard's default and may render empty. Text
        panels never need a data source.

        Recommended panel_type per shape:
          line / bar / stat / gauge → metric panels
          logs / log_table          → log panels
          text                      → text panels

        Args:
            dashboard_id: The dashboard id to add the panel to.
            title: Panel title (1-200 characters).
            panel_type: One of: line, bar, stat, gauge, logs, log_table, text.
                        Defaults to "line".
            unit: Display unit string (e.g. "none", "bytes", "percent",
                  "bits/s"). Defaults to "none".
            legend_label: Legend label for metric queries. Ignored for log
                          panels (use `log_columns` instead) and text panels.
            datasource_id: Id of the observability data source. Required for
                           metric + log panels.
            promql: PromQL expression. Use for shape #1.
            cw_namespace, cw_metric_name, cw_stat: CloudWatch metric triple
                (e.g. "AWS/EC2", "CPUUtilization", "Average"). Use for shape #2.
            cw_dimensions: JSON string of CloudWatch dimensions, e.g.
                '[{"Name": "InstanceId", "Value": "i-0abc..."}]'.
            cw_period: CloudWatch period in seconds (e.g. 60).
            es_index: ElasticSearch / OpenSearch index pattern, e.g.
                "production-eks-pods-logs" or "logs-*". Use for shape #3.
            kql_filter: Optional KQL filter for ES, e.g. 'level:error AND
                service:"api"'. Use for shape #3 (paired with es_index).
            cw_log_group: CloudWatch Logs log group, e.g. "/aws/lambda/my-fn".
                Use for shape #4.
            cw_filter_pattern: Optional CloudWatch Logs filter pattern, e.g.
                "?ERROR ?WARN" or "[..., status_code=5*, ...]". Use for shape
                #4 (paired with cw_log_group).
            log_columns: Ordered list of column names to display in the log
                table, e.g. ["timestamp", "level", "message"]. Defaults to the
                editor's default if omitted.
            log_limit: Max rows to fetch (defaults match the UI; typical 200).
            log_wrap_message: Wrap long log messages (default false).
            log_expandable_rows: Allow row expansion (default true).
            log_highlight_by_severity: Color rows by severity (default true).
            log_live_tail: Enable live-tail mode (default false).
            text_content: Markdown body for a text panel. Required when
                          panel_type='text'.
            text_background: Optional CSS color string for the text panel
                             background, e.g. "#dcfce7", "rgb(220, 252, 231)".
        """
        # Classify which shape was used.
        is_promql = promql is not None and promql.strip() != ""
        is_cw_metric = any(
            v is not None for v in (cw_namespace, cw_metric_name, cw_stat)
        )
        is_es_logs = es_index is not None
        is_cw_logs = cw_log_group is not None
        is_text = text_content is not None
        shapes_used = sum(
            (is_promql, is_cw_metric, is_es_logs, is_cw_logs, is_text)
        )

        # ── Validation ──────────────────────────────────────────────────────
        if shapes_used > 1:
            return (
                "Error: a panel carries exactly one shape. Pick ONE of: "
                "PromQL (promql), CloudWatch metric (cw_namespace/cw_metric_name/"
                "cw_stat), ES logs (es_index), CW logs (cw_log_group), or text "
                "(text_content)."
            )
        if is_cw_metric and not (cw_namespace and cw_metric_name and cw_stat):
            missing = [
                name for name, val in
                (("cw_namespace", cw_namespace),
                 ("cw_metric_name", cw_metric_name),
                 ("cw_stat", cw_stat))
                if not val
            ]
            return (
                "Error: CloudWatch metric queries require cw_namespace + "
                f"cw_metric_name + cw_stat. Missing: {', '.join(missing)}."
            )
        if is_text and panel_type != "text":
            return (
                f"Error: text_content was provided but panel_type='{panel_type}'. "
                "Set panel_type='text' for a text panel."
            )
        if panel_type == "text" and not is_text:
            return "Error: panel_type='text' requires `text_content`."
        if (is_es_logs or is_cw_logs) and panel_type not in ("logs", "log_table"):
            return (
                "Error: log parameters require panel_type='logs' or 'log_table' "
                f"(got '{panel_type}')."
            )
        if panel_type in ("logs", "log_table") and not (is_es_logs or is_cw_logs):
            return (
                "Error: log panels require either `es_index` (ElasticSearch) "
                "or `cw_log_group` (CloudWatch Logs)."
            )

        # ── Build the request body ──────────────────────────────────────────
        body: dict = {
            "title": title,
            "type": panel_type,
            "unit": unit,
        }
        if datasource_id is not None:
            body["datasource_id"] = datasource_id

        if is_text:
            options: dict = {"content": text_content}
            if text_background is not None:
                options["background"] = text_background
            body["options"] = options
            body["queries"] = []
            # legend_label intentionally not set for text panels.

        elif is_promql:
            if legend_label is not None:
                body["legend_label"] = legend_label
            body["queries"] = [
                {
                    "label": legend_label if legend_label is not None else title,
                    "expr": promql,
                    "order": 0,
                }
            ]

        elif is_cw_metric:
            if legend_label is not None:
                body["legend_label"] = legend_label
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

        elif is_es_logs or is_cw_logs:
            # Log panels overload the metric-query row:
            #   queries[0].label = ES index OR CW log-group name
            #   queries[0].expr  = KQL filter OR CW filter pattern (may be empty)
            label = es_index if is_es_logs else cw_log_group
            expr = (kql_filter if is_es_logs else cw_filter_pattern) or ""
            body["queries"] = [{"label": label, "expr": expr, "order": 0}]
            # Selected columns ride on legend_label as a comma-separated string;
            # if both log_columns and legend_label are supplied, log_columns wins.
            if log_columns:
                body["legend_label"] = ",".join(log_columns)
            elif legend_label is not None:
                body["legend_label"] = legend_label
            # Display options
            log_options: dict = {}
            if log_wrap_message is not None:
                log_options["wrap_message"] = log_wrap_message
            if log_expandable_rows is not None:
                log_options["expandable_rows"] = log_expandable_rows
            if log_highlight_by_severity is not None:
                log_options["highlight_by_severity"] = log_highlight_by_severity
            if log_live_tail is not None:
                log_options["live_tail"] = log_live_tail
            if log_limit is not None:
                log_options["limit"] = log_limit
            if log_options:
                body["options"] = log_options

        else:
            # No query / no content (rare — typically a stat panel without a
            # source set yet). Keep behaviour from previous versions.
            if legend_label is not None:
                body["legend_label"] = legend_label

        p = await get_client().post(
            f"/observability/dashboards/{dashboard_id}/panels", body
        )
        return (
            f"Added {p['type']} panel '{p['title']}' "
            f"(id={p['id']}) to dashboard {dashboard_id}."
        )

    @mcp.tool()
    async def delete_panel(dashboard_id: str, panel_id: str) -> str:
        """Delete a panel from a dashboard. This cannot be undone.

        Args:
            dashboard_id: The dashboard id that owns the panel.
            panel_id: The panel id to delete.
        """
        await get_client().delete(f"/observability/dashboards/{dashboard_id}/panels/{panel_id}")
        return f"Deleted panel {panel_id} from dashboard {dashboard_id}."
