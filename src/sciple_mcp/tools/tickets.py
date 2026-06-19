"""Ticket tools — service-level + project-scoped tickets, comments, and links.

Wraps the REST routes:
  POST/GET   /tickets                       GET/PATCH/DELETE /tickets/{id}
  GET/POST   /tickets/{id}/comments
  GET/POST   /tickets/{id}/links
  GET/POST   /projects/{project_id}/tickets
  GET/PATCH  /projects/{project_id}/tickets/{number}

Permissions:
  tickets.view     — list / get
  tickets.create   — create_project_ticket
  tickets.manage   — create_ticket, update_*, link_tickets
  tickets.comment  — comment_on_ticket
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sciple_mcp.client import ScipleClient


_TICKET_TYPES = ("epic", "story", "task", "subtask", "bug")
_PRIORITIES = ("low", "medium", "high", "urgent")
_SEVERITIES = ("minor", "major", "critical")
_STATUSES = ("open", "in_progress", "done", "cancelled")
_LINK_TYPES = ("blocks", "relates_to", "duplicates")


def _format_ticket_line(t: dict) -> str:
    """Compact one-line summary used by list_tickets / list_project_tickets."""
    display = t.get("display_id") or t["id"]
    status = (t.get("status") or "?").upper()
    prio = t.get("priority") or "-"
    assignee = t.get("assignee_user_id") or "unassigned"
    return f"- {display}  [{status}]  ({prio})  {t['title']}  assignee={assignee}"


def _format_ticket_detail(t: dict) -> str:
    """Multi-line detailed view used by get_ticket / get_project_ticket."""
    lines = [
        f"{t.get('display_id') or t['id']}: {t['title']}",
        f"  id          : {t['id']}",
        f"  status      : {t.get('status')}",
        f"  type        : {t.get('ticket_type') or t.get('issue_type_id') or '-'}",
        f"  priority    : {t.get('priority')}",
        f"  severity    : {t.get('severity') or '-'}",
        f"  assignee    : {t.get('assignee_user_id') or '(unassigned)'}",
        f"  primary svc : {t.get('primary_service_id') or '-'}",
        f"  parent      : {t.get('parent_ticket_id') or '-'}",
        f"  due date    : {t.get('due_date') or '-'}",
        f"  tags        : {t.get('tags') or []}",
    ]
    counts = t.get("counts")
    if counts:
        lines.append(
            f"  counts      : comments={counts.get('comments')} "
            f"links={counts.get('links_total')} "
            f"affected={counts.get('affected_services')} "
            f"refs={counts.get('entity_refs')}"
        )
    desc = t.get("description")
    if desc:
        preview = desc[:280].replace("\n", " ")
        lines.append(f"  description : {preview}")
    return "\n".join(lines)


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    # ── Service-level tickets ────────────────────────────────────────────────

    @mcp.tool()
    async def list_tickets(
        service_id: str | None = None,
        assignee_user_id: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        ticket_type: str | None = None,
        parent_ticket_id: str | None = None,
        tag: str | None = None,
        q: str | None = None,
        include_affected: bool = False,
        limit: int = 50,
    ) -> str:
        """List tickets across the tenant with optional filters.

        Filters compose with AND. All are optional; with no filters, returns the
        most recent tickets up to `limit`.

        Args:
            service_id: Filter by primary_service_id.
            assignee_user_id: Filter by assignee.
            status: One of open / in_progress / done / cancelled.
            priority: One of low / medium / high / urgent.
            ticket_type: One of epic / story / task / subtask / bug.
            parent_ticket_id: Only direct children of this parent.
            tag: Filter by a single tag.
            q: Full-text search across title/description.
            include_affected: When True with service_id, also include tickets
                              where the service appears in affected_services.
            limit: Max rows (1-200, default 50).
        """
        params: list[str] = []
        if service_id is not None:
            params.append(f"service_id={service_id}")
        if assignee_user_id is not None:
            params.append(f"assignee_user_id={assignee_user_id}")
        if status is not None:
            params.append(f"status={status}")
        if priority is not None:
            params.append(f"priority={priority}")
        if ticket_type is not None:
            params.append(f"ticket_type={ticket_type}")
        if parent_ticket_id is not None:
            params.append(f"parent_ticket_id={parent_ticket_id}")
        if tag is not None:
            params.append(f"tag={tag}")
        if q is not None:
            params.append(f"q={q}")
        if include_affected:
            params.append("include_affected=true")
        params.append(f"limit={limit}")
        path = "/tickets" + ("?" + "&".join(params) if params else "")
        data = await get_client().get(path)
        items = data.get("items", []) if isinstance(data, dict) else (data or [])
        if not items:
            return "No tickets match those filters."
        lines = [_format_ticket_line(t) for t in items]
        more = data.get("next_cursor") if isinstance(data, dict) else None
        if more:
            lines.append(f"(more results available; cursor={more})")
        return "\n".join(lines)

    @mcp.tool()
    async def get_ticket(ticket_id: str) -> str:
        """Get a single ticket's full details + activity counts.

        Args:
            ticket_id: The internal ticket id (NOT the display id like KEY-NNN —
                       use `list_tickets` first or `list_project_tickets` to find it,
                       or use `get_project_ticket` if you have the project key + number).
        """
        t = await get_client().get(f"/tickets/{ticket_id}")
        return _format_ticket_detail(t)

    @mcp.tool()
    async def create_ticket(
        title: str,
        ticket_type: str = "task",
        description: str | None = None,
        priority: str = "medium",
        severity: str | None = None,
        primary_service_id: str | None = None,
        parent_ticket_id: str | None = None,
        assignee_user_id: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        tags: list[str] | None = None,
        affected_service_ids: list[str] | None = None,
    ) -> str:
        """Create a SERVICE-LEVEL ticket (not bound to a project).

        Use this when the user explicitly wants a service-scoped ticket. For
        tickets that should live in a project, use `create_project_ticket`
        instead — it returns a display id like "KEY-NNN" and supports custom
        fields.

        Args:
            title: Short summary (1-200 chars).
            ticket_type: One of epic / story / task / subtask / bug. Default task.
            description: Optional longer body (markdown).
            priority: One of low / medium / high / urgent. Default medium.
            severity: One of minor / major / critical, or None.
            primary_service_id: Service the ticket is primarily about.
            parent_ticket_id: Parent ticket id (for subtasks under a story, etc.).
            assignee_user_id: User id to assign to.
            start_date: ISO 8601 date string "YYYY-MM-DD".
            due_date: ISO 8601 date string "YYYY-MM-DD".
            tags: Optional list of tag strings.
            affected_service_ids: List of additional service ids affected.
        """
        body: dict[str, Any] = {
            "title": title,
            "ticket_type": ticket_type,
            "priority": priority,
        }
        if description is not None:
            body["description"] = description
        if severity is not None:
            body["severity"] = severity
        if primary_service_id is not None:
            body["primary_service_id"] = primary_service_id
        if parent_ticket_id is not None:
            body["parent_ticket_id"] = parent_ticket_id
        if assignee_user_id is not None:
            body["assignee_user_id"] = assignee_user_id
        if start_date is not None:
            body["start_date"] = start_date
        if due_date is not None:
            body["due_date"] = due_date
        if tags is not None:
            body["tags"] = tags
        if affected_service_ids is not None:
            body["affected_service_ids"] = affected_service_ids
        t = await get_client().post("/tickets", body)
        return (
            f"Created service-level {t.get('ticket_type', 'ticket')} "
            f"'{t['title']}' (id={t['id']})."
        )

    @mcp.tool()
    async def update_ticket(
        ticket_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        severity: str | None = None,
        assignee_user_id: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        tags: list[str] | None = None,
        parent_ticket_id: str | None = None,
    ) -> str:
        """Update a service-level ticket (PATCH semantics — only provided fields change).

        Use this for status transitions, reassignment, priority bumps, etc.

        Args:
            ticket_id: The internal ticket id (NOT the display id).
            title: New title (1-200 chars).
            description: New description.
            status: New status — open / in_progress / done / cancelled.
            priority: New priority — low / medium / high / urgent.
            severity: New severity — minor / major / critical or null.
            assignee_user_id: New assignee user id (pass empty string to unassign? Use null).
            start_date: ISO date "YYYY-MM-DD".
            due_date: ISO date "YYYY-MM-DD".
            tags: New full list of tags (replaces existing).
            parent_ticket_id: New parent ticket id.
        """
        body: dict[str, Any] = {}
        for k, v in (
            ("title", title),
            ("description", description),
            ("status", status),
            ("priority", priority),
            ("severity", severity),
            ("assignee_user_id", assignee_user_id),
            ("start_date", start_date),
            ("due_date", due_date),
            ("tags", tags),
            ("parent_ticket_id", parent_ticket_id),
        ):
            if v is not None:
                body[k] = v
        if not body:
            return "Nothing to update — provide at least one field."
        t = await get_client().patch(f"/tickets/{ticket_id}", body)
        return f"Updated ticket {t.get('display_id') or t['id']} (status={t.get('status')})."

    @mcp.tool()
    async def comment_on_ticket(ticket_id: str, body: str) -> str:
        """Add a comment to a ticket.

        Args:
            ticket_id: The internal ticket id.
            body: The comment body (markdown supported, min 1 char).
        """
        c = await get_client().post(f"/tickets/{ticket_id}/comments", {"body": body})
        return f"Added comment {c['id']} on ticket {ticket_id}."

    @mcp.tool()
    async def link_tickets(
        ticket_id: str,
        target_ticket_id: str,
        link_type: str = "relates_to",
    ) -> str:
        """Create a relationship between two tickets.

        Args:
            ticket_id: The ticket that the link originates from.
            target_ticket_id: The ticket on the other end of the link.
            link_type: One of blocks / relates_to / duplicates.
                       Default relates_to.
        """
        if link_type not in _LINK_TYPES:
            return f"Error: link_type must be one of {_LINK_TYPES}."
        r = await get_client().post(
            f"/tickets/{ticket_id}/links",
            {"target_ticket_id": target_ticket_id, "link_type": link_type},
        )
        return (
            f"Linked {ticket_id} -[{link_type}]-> {target_ticket_id} "
            f"(link_id={r.get('id', '?')})."
        )

    # ── Project-scoped tickets ───────────────────────────────────────────────

    @mcp.tool()
    async def list_project_tickets(project_id: str) -> str:
        """List tickets in a project (display id, status, priority, title, assignee).

        Args:
            project_id: The project id (use `list_projects` to find it).
        """
        data = await get_client().get(f"/projects/{project_id}/tickets")
        items = data.get("items", []) if isinstance(data, dict) else (data or [])
        if not items:
            return "No tickets in this project."
        return "\n".join(_format_ticket_line(t) for t in items)

    @mcp.tool()
    async def get_project_ticket(project_id: str, number: int) -> str:
        """Get a project ticket by its per-project sequence number.

        The display id "KEY-NNN" means: project with that KEY, ticket number NNN.
        For example "PLAT-42" -> project_id of "PLAT", number=42.

        Args:
            project_id: The project id (NOT the project key — use `list_projects`).
            number: The per-project ticket number (the NNN in KEY-NNN).
        """
        t = await get_client().get(f"/projects/{project_id}/tickets/{number}")
        return _format_ticket_detail(t)

    @mcp.tool()
    async def create_project_ticket(
        project_id: str,
        issue_type_id: str,
        title: str,
        description: str | None = None,
        priority: str = "medium",
        severity: str | None = None,
        assignee_user_id: str | None = None,
        primary_service_id: str | None = None,
        parent_ticket_id: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        tags: list[str] | None = None,
        custom_fields: str | None = None,
    ) -> str:
        """Create a ticket within a project. Returns a display id like "KEY-NNN".

        This is the recommended path for most ticket creation — project tickets
        get an auto-incremented per-project number and a human-friendly display
        id. Prerequisites: you need the `project_id` (from `list_projects`) and
        a valid `issue_type_id` (from `list_project_issue_types`).

        Args:
            project_id: The project id to create the ticket in.
            issue_type_id: A valid issue type id for this project. Use
                           `list_project_issue_types` to get one.
            title: Short summary (1-200 chars).
            description: Optional longer body (markdown).
            priority: One of low / medium / high / urgent. Default medium.
            severity: One of minor / major / critical, or None.
            assignee_user_id: User id to assign to (use `list_project_members`).
            primary_service_id: Optional service the ticket relates to.
            parent_ticket_id: Optional parent ticket (for nesting).
            start_date: ISO date "YYYY-MM-DD".
            due_date: ISO date "YYYY-MM-DD".
            tags: Optional list of tag strings.
            custom_fields: Optional JSON string of a {field_id: value} dict for
                           project-defined custom fields. Use
                           `list_project_issue_types` first to see which fields
                           exist, e.g.
                           '{"f_abc123": "RCA pending", "f_def456": ["a","b"]}'.
        """
        body: dict[str, Any] = {
            "issue_type_id": issue_type_id,
            "title": title,
            "priority": priority,
        }
        if description is not None:
            body["description"] = description
        if severity is not None:
            body["severity"] = severity
        if assignee_user_id is not None:
            body["assignee_user_id"] = assignee_user_id
        if primary_service_id is not None:
            body["primary_service_id"] = primary_service_id
        if parent_ticket_id is not None:
            body["parent_ticket_id"] = parent_ticket_id
        if start_date is not None:
            body["start_date"] = start_date
        if due_date is not None:
            body["due_date"] = due_date
        if tags is not None:
            body["tags"] = tags
        if custom_fields is not None:
            try:
                parsed = json.loads(custom_fields)
            except json.JSONDecodeError as exc:
                return f"Error: custom_fields is not valid JSON — {exc}"
            if not isinstance(parsed, dict):
                return "Error: custom_fields must be a JSON object {field_id: value}."
            body["custom_fields"] = parsed
        t = await get_client().post(f"/projects/{project_id}/tickets", body)
        return (
            f"Created project ticket {t.get('display_id') or t['id']}: "
            f"'{t['title']}' (id={t['id']})."
        )
