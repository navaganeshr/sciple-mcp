"""Project tools — the primary work container that groups services and owns issue types + tickets.

Wraps the REST routes:
  GET/POST   /projects                          GET/PATCH/DELETE /projects/{id}
  GET        /projects/{id}/members             POST /projects/{id}/members
  GET        /projects/{id}/issue-types
  GET        /projects/{id}/services            (link/unlink also available — not wrapped here)

Requires the PAT to hold projects.view (reads) / projects.manage (writes).
"""
from __future__ import annotations

from collections.abc import Callable

from sciple_mcp.client import ScipleClient


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def list_projects() -> str:
        """List all projects in the tenant (id, key, name, classification)."""
        data = await get_client().get("/projects")
        items = data.get("items", []) if isinstance(data, dict) else (data or [])
        if not items:
            return "No projects found."
        lines = []
        for p in items:
            cls = f" [{p.get('classification')}]" if p.get("classification") else ""
            lines.append(
                f"- {p['key']}: {p['name']} (id={p['id']}){cls}"
            )
        return "\n".join(lines)

    @mcp.tool()
    async def get_project(project_id: str) -> str:
        """Get a single project's full details.

        Args:
            project_id: The project id (NOT the key — use `list_projects` first to find it).
        """
        p = await get_client().get(f"/projects/{project_id}")
        desc = p.get("description") or "(no description)"
        owner = p.get("owner_user_id") or "(unassigned)"
        return (
            f"{p['key']}: {p['name']} (id={p['id']})\n"
            f"  classification : {p.get('classification') or '-'}\n"
            f"  owner          : {owner}\n"
            f"  description    : {desc}"
        )

    @mcp.tool()
    async def create_project(
        name: str,
        key: str,
        description: str | None = None,
        classification: str = "other",
        owner_user_id: str | None = None,
    ) -> str:
        """Create a new project.

        Args:
            name: Display name (1-200 chars), e.g. "Platform Reliability".
            key: Short uppercase key used in ticket display ids
                 (2-10 chars, A-Z + 0-9 only), e.g. "PLAT". Becomes part of the
                 ticket display id like "PLAT-123".
            description: Optional human-readable description.
            classification: One of: "software", "operations", "security",
                            "infrastructure", "data", "other". Defaults to "other".
            owner_user_id: Optional user id of the project owner.
        """
        body: dict = {
            "name": name,
            "key": key,
            "classification": classification,
        }
        if description is not None:
            body["description"] = description
        if owner_user_id is not None:
            body["owner_user_id"] = owner_user_id
        p = await get_client().post("/projects", body)
        return f"Created project '{p['key']}: {p['name']}' (id={p['id']})."

    @mcp.tool()
    async def list_project_members(project_id: str) -> str:
        """List the members of a project (id, user id, role).

        Use this to find user ids you can later pass as `assignee_user_id` when
        creating or updating tickets in this project.

        Args:
            project_id: The project id.
        """
        data = await get_client().get(f"/projects/{project_id}/members")
        items = data.get("items", []) if isinstance(data, dict) else (data or [])
        if not items:
            return "No members on this project."
        lines = [f"- {m['user_id']}  role={m['role']}  (member_id={m['id']})" for m in items]
        return "\n".join(lines)

    @mcp.tool()
    async def list_project_issue_types(project_id: str) -> str:
        """List the issue types defined in a project (id, name, parent_type_id).

        Required before calling `create_project_ticket` — the ticket needs a
        valid `issue_type_id` from this list.

        Args:
            project_id: The project id.
        """
        data = await get_client().get(f"/projects/{project_id}/issue-types")
        items = data.get("items", []) if isinstance(data, dict) else (data or [])
        if not items:
            return "No issue types defined on this project."
        lines = []
        for t in items:
            parent = f" (child of {t['parent_type_id']})" if t.get("parent_type_id") else ""
            lines.append(f"- {t['name']} (id={t['id']}){parent}")
        return "\n".join(lines)
