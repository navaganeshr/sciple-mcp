"""Environment + environment-group tools — populate the platform's env structure.

Wraps the REST routes:
  GET/POST   /environments          GET/PATCH/DELETE /environments/{id}
  GET/POST   /envgroups             GET/PATCH/DELETE /envgroups/{id}
Requires the PAT to hold environments.view (reads) / environments.manage (writes).
"""
from __future__ import annotations

from collections.abc import Callable

from sciple_mcp.client import ScipleClient


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def list_environments() -> str:
        """List all environments in the tenant (id, name, slug, group, default flag)."""
        envs = await get_client().get("/environments")
        if not envs:
            return "No environments found."
        lines = []
        for e in envs:
            default = " [default]" if e.get("is_default") else ""
            grp = f" group={e['environment_group_id']}" if e.get("environment_group_id") else ""
            lines.append(f"- {e['name']} (id={e['id']}, slug={e['slug']}){default}{grp}")
        return "\n".join(lines)

    @mcp.tool()
    async def create_environment(
        name: str,
        slug: str | None = None,
        environment_group_id: str | None = None,
        description: str | None = None,
        is_default: bool = False,
        display_order: int = 0,
    ) -> str:
        """Create an environment.

        Args:
            name: Display name, e.g. "Production".
            slug: URL-safe id; server generates one from name if omitted.
            environment_group_id: Optional parent environment-group id.
            description: Optional human description.
            is_default: Mark this the tenant's default environment.
            display_order: Sort order in the UI (lower = earlier).
        """
        body: dict = {"name": name, "is_default": is_default, "display_order": display_order}
        if slug is not None:
            body["slug"] = slug
        if environment_group_id is not None:
            body["environment_group_id"] = environment_group_id
        if description is not None:
            body["description"] = description
        e = await get_client().post("/environments", body)
        return f"Created environment '{e['name']}' (id={e['id']}, slug={e['slug']})."

    @mcp.tool()
    async def update_environment(
        env_id: str,
        name: str | None = None,
        description: str | None = None,
        environment_group_id: str | None = None,
        is_default: bool | None = None,
        display_order: int | None = None,
    ) -> str:
        """Update an environment. Only provided fields change.

        Args:
            env_id: The environment id to update.
            name: New display name.
            description: New description.
            environment_group_id: Move to a different environment group.
            is_default: Set/unset default.
            display_order: New sort order.
        """
        body: dict = {}
        for key, val in (
            ("name", name), ("description", description),
            ("environment_group_id", environment_group_id),
            ("is_default", is_default), ("display_order", display_order),
        ):
            if val is not None:
                body[key] = val
        if not body:
            return "Nothing to update — provide at least one field."
        e = await get_client().patch(f"/environments/{env_id}", body)
        return f"Updated environment '{e['name']}' (id={e['id']})."

    @mcp.tool()
    async def delete_environment(env_id: str) -> str:
        """Delete an environment by id. This cannot be undone.

        Args:
            env_id: The environment id to delete.
        """
        await get_client().delete(f"/environments/{env_id}")
        return f"Deleted environment {env_id}."

    @mcp.tool()
    async def list_environment_groups() -> str:
        """List environment groups (id, name, slug, aws account binding)."""
        groups = await get_client().get("/envgroups")
        if not groups:
            return "No environment groups found."
        lines = []
        for g in groups:
            acct = f" aws={g['aws_account_id']}" if g.get("aws_account_id") else ""
            lines.append(f"- {g['name']} (id={g['id']}, slug={g['slug']}){acct}")
        return "\n".join(lines)

    @mcp.tool()
    async def create_environment_group(
        name: str,
        slug: str | None = None,
        description: str | None = None,
        display_order: int = 0,
        aws_account_id: str | None = None,
    ) -> str:
        """Create an environment group.

        Args:
            name: Display name, e.g. "Production accounts".
            slug: URL-safe id; generated from name if omitted.
            description: Optional description.
            display_order: Sort order in the UI.
            aws_account_id: Optional AWS account id to bind the group to.
        """
        body: dict = {"name": name, "display_order": display_order}
        if slug is not None:
            body["slug"] = slug
        if description is not None:
            body["description"] = description
        if aws_account_id is not None:
            body["aws_account_id"] = aws_account_id
        g = await get_client().post("/envgroups", body)
        return f"Created environment group '{g['name']}' (id={g['id']}, slug={g['slug']})."
