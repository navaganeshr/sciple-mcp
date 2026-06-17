# Sciple Platform MCP Server

MCP server that lets a local Claude populate and manage Sciple platform content — environments, services, observability dashboards, and runbooks — via the Sciple REST API. Engineers use it to bootstrap tenant structure, maintain the service catalog, build dashboards, and author runbooks without leaving their AI coding session.

Published on PyPI: <https://pypi.org/project/sciple-mcp/>
Source: <https://github.com/navaganeshr/sciple-mcp>

## Install

The recommended install is via [`uv`](https://docs.astral.sh/uv/) — it's a one-time setup that gives you `uvx`, which fetches and caches `sciple-mcp` on demand. No clone required.

```bash
# Install uv (one-time, only if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`uvx sciple-mcp` will resolve the latest version from PyPI on first run and cache it locally.

## Configuration

The server reads three environment variables:

```
SCIPLE_API_URL=http://localhost:8000/api/v1
SCIPLE_API_TOKEN=sciple_pat_...
SCIPLE_TENANT_ID=<your tenant id>
```

`SCIPLE_API_TOKEN` is a **personal access token** minted under **Profile → Access tokens** in the Sciple dashboard, scoped to the permissions the server should have:

| Domain | Permissions |
|---|---|
| Environments | `environments.view`, `environments.manage` |
| Services | `services.view`, `services.manage` |
| Observability | `observability.view`, `observability.manage` |
| Runbooks | `observability.view`, `observability.manage` (runbooks live under the observability permission family) |

The PAT is **single-tenant** — its bound tenant must equal `SCIPLE_TENANT_ID`. Calls against a different tenant return 403.

## Wire into Claude Desktop / Claude Code

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (Claude Desktop) or your Claude Code MCP config:

```json
{
  "mcpServers": {
    "sciple-platform": {
      "command": "uvx",
      "args": ["sciple-mcp"],
      "env": {
        "SCIPLE_API_URL": "http://localhost:8000/api/v1",
        "SCIPLE_API_TOKEN": "sciple_pat_...",
        "SCIPLE_TENANT_ID": "..."
      }
    }
  }
}
```

Then restart Claude. You should see **26 platform tools** available.

> The Sciple dashboard also renders this exact JSON block — with `SCIPLE_API_URL` and `SCIPLE_TENANT_ID` pre-filled from the running environment — inside the **"How to use this token with Claude"** panel on Profile → Access tokens. Generate a token there and copy the snippet directly.

## Tools

### Environments

| Tool | Description |
|---|---|
| `list_environments` | List all environments in the tenant (id, name, slug, group, default flag) |
| `create_environment` | Create an environment with optional group assignment and default flag |
| `update_environment` | Update an environment's name, description, group, or sort order |
| `delete_environment` | Delete an environment by id (irreversible) |
| `list_environment_groups` | List environment groups (id, name, slug, AWS account binding) |
| `create_environment_group` | Create an environment group with optional AWS account binding |

### Services

| Tool | Description |
|---|---|
| `list_services` | List all services in the tenant catalog (id, name, slug) |
| `create_service` | Create a service in the catalog with kind, language, SCM provider, and repository |
| `update_service` | Update a service's metadata, lifecycle, owner, tags, links, or environment associations |
| `delete_service` | Delete a service from the catalog by id (irreversible) |

### Observability

| Tool | Description |
|---|---|
| `list_dashboards` | List all observability dashboards in the tenant (id, name, panel count) |
| `get_dashboard` | Get a dashboard's name, description, and panel list |
| `create_dashboard` | Create a new dashboard with optional description |
| `update_dashboard` | Replace a dashboard's name and description (full PUT; name required) |
| `delete_dashboard` | Delete a dashboard and all its panels (irreversible) |
| `add_panel` | Add a panel to a dashboard with an optional **PromQL** or **CloudWatch Metrics** query (mutually exclusive). Log panels (`logs`/`log_table` types) are accepted but the API doesn't yet carry log-query content — author those in the UI. |
| `delete_panel` | Delete a panel from a dashboard (irreversible) |

### Runbooks

| Tool | Description |
|---|---|
| `list_runbooks` | List all runbooks in the tenant with lifecycle status and cell count |
| `get_runbook` | Get a runbook with its cells (name, status, content preview per cell) |
| `create_runbook` | Create a new runbook in draft status |
| `add_cell` | Add a markdown / shell / http cell to a runbook with optional k8s/ecs/ec2 target |
| `update_cell` | Update a cell's content or execution target |
| `delete_cell` | Remove a cell from a runbook |
| `reorder_cells` | Set the execution order of all cells in a runbook |
| `promote_runbook` | Advance the runbook lifecycle: draft → reviewed → standard |
| `deprecate_runbook` | Mark a runbook as deprecated |

Runbook lifecycle: `draft → reviewed → standard`. Deprecation is one-way from any state.

## Security

The server can only do what the PAT's scope allows. Attempts to write without the relevant `manage` permission return a 403 from the API and are surfaced as an error in Claude's response. The PAT is revocable at any time from **Profile → Access tokens** in the Sciple dashboard — revoking it immediately cuts off the server's access without any config change.

## Development

To work on the server itself:

```bash
git clone https://github.com/navaganeshr/sciple-mcp
cd sciple-mcp
uv sync --all-groups
uv run python -m pytest -q
```

Releases are tag-driven via a GitHub Actions workflow using PyPI Trusted Publishing (OIDC). To cut a release:

1. Bump `version` in `pyproject.toml`.
2. Commit, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. Approve the `pypi` environment deployment in the Actions UI.
