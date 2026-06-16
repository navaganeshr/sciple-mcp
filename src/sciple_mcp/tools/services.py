"""Service catalog tools — create and manage services in the Sciple catalog.

Wraps the REST routes:
  GET/POST   /services              GET/PATCH/DELETE /services/{id}
Requires the PAT to hold services.view (reads) / services.manage (writes).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sciple_mcp.client import ScipleClient


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def list_services() -> str:
        """List all services in the tenant catalog (id, name, slug)."""
        svcs = await get_client().get("/services")
        if not svcs:
            return "No services found."
        lines = []
        for s in svcs:
            lines.append(f"- {s['name']} (id={s['id']}, slug={s['slug']})")
        return "\n".join(lines)

    @mcp.tool()
    async def create_service(
        name: str,
        kind: str,
        language: str,
        scm_provider_id: str,
        repository_url: str,
        slug: str | None = None,
        language_version: str | None = None,
        default_branch: str = "main",
        description: str | None = None,
        lifecycle: str = "active",
        owner_group_id: str | None = None,
        tier: str | None = None,
        runtime: str | None = None,
        tags: list[str] | None = None,
        links: list[dict[str, Any]] | None = None,
    ) -> str:
        """Create a service in the catalog.

        Args:
            name: Display name, e.g. "Payments API".
            kind: One of service|library|worker|job|frontend|mobile_app|other.
            language: Primary language, e.g. "python".
            scm_provider_id: ID of the SCM provider (GitHub, GitLab, etc.) integration.
            repository_url: Full URL to the source repository.
            slug: URL-safe id; server generates one from name if omitted.
            language_version: Language runtime version, e.g. "3.12".
            default_branch: Default VCS branch (default "main").
            description: Optional human-readable description.
            lifecycle: One of active|deprecated|archived (default "active").
            owner_group_id: Optional owning group id.
            tier: Optional criticality tier — tier1|tier2|tier3.
            runtime: Optional runtime identifier, e.g. "docker".
            tags: Optional list of tag strings.
            links: Optional list of link dicts (e.g. [{"label": "Docs", "url": "..."}]).
        """
        body: dict = {
            "name": name,
            "kind": kind,
            "language": language,
            "scm_provider_id": scm_provider_id,
            "repository_url": repository_url,
            "default_branch": default_branch,
            "lifecycle": lifecycle,
        }
        if slug is not None:
            body["slug"] = slug
        if language_version is not None:
            body["language_version"] = language_version
        if description is not None:
            body["description"] = description
        if owner_group_id is not None:
            body["owner_group_id"] = owner_group_id
        if tier is not None:
            body["tier"] = tier
        if runtime is not None:
            body["runtime"] = runtime
        if tags is not None:
            body["tags"] = tags
        if links is not None:
            body["links"] = links
        s = await get_client().post("/services", body)
        return f"Created service '{s['name']}' (id={s['id']}, slug={s['slug']})."

    @mcp.tool()
    async def update_service(
        service_id: str,
        name: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        language_version: str | None = None,
        scm_provider_id: str | None = None,
        repository_url: str | None = None,
        default_branch: str | None = None,
        lifecycle: str | None = None,
        owner_group_id: str | None = None,
        clear_owner: bool = False,
        tier: str | None = None,
        clear_tier: bool = False,
        runtime: str | None = None,
        tags: list[str] | None = None,
        links: list[dict[str, Any]] | None = None,
        add_environments: list[str] | None = None,
        remove_environments: list[str] | None = None,
    ) -> str:
        """Update a service. Only provided fields change.

        Args:
            service_id: The service id to update.
            name: New display name.
            description: New description.
            kind: New kind — service|library|worker|job|frontend|mobile_app|other.
            language: New primary language.
            language_version: New language version.
            scm_provider_id: New SCM provider integration id.
            repository_url: New repository URL.
            default_branch: New default branch.
            lifecycle: New lifecycle — active|deprecated|archived.
            owner_group_id: Move ownership to a different group.
            clear_owner: Set True to remove the owner assignment.
            tier: New criticality tier — tier1|tier2|tier3.
            clear_tier: Set True to remove the tier assignment.
            runtime: New runtime identifier.
            tags: Replace the tags list entirely.
            links: Replace the links list entirely.
            add_environments: List of environment ids to associate with the service.
            remove_environments: List of environment ids to disassociate from the service.
        """
        body: dict = {}
        for key, val in (
            ("name", name),
            ("description", description),
            ("kind", kind),
            ("language", language),
            ("language_version", language_version),
            ("scm_provider_id", scm_provider_id),
            ("repository_url", repository_url),
            ("default_branch", default_branch),
            ("lifecycle", lifecycle),
            ("owner_group_id", owner_group_id),
            ("tier", tier),
            ("runtime", runtime),
            ("tags", tags),
            ("links", links),
        ):
            if val is not None:
                body[key] = val
        # bool flags only included when True so they're opt-in
        if clear_owner:
            body["clear_owner"] = True
        if clear_tier:
            body["clear_tier"] = True
        if add_environments:
            body["add_environments"] = add_environments
        if remove_environments:
            body["remove_environments"] = remove_environments
        if not body:
            return "Nothing to update — provide at least one field."
        s = await get_client().patch(f"/services/{service_id}", body)
        return f"Updated service '{s['name']}' (id={s['id']})."

    @mcp.tool()
    async def delete_service(service_id: str) -> str:
        """Delete a service from the catalog by id. This cannot be undone.

        Args:
            service_id: The service id to delete.
        """
        await get_client().delete(f"/services/{service_id}")
        return f"Deleted service {service_id}."
