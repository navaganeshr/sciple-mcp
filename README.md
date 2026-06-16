# Sciple Platform MCP Server

MCP server that lets a local Claude populate and manage Sciple platform content — environments, environment groups, and services — via the Sciple REST API. Engineers use it to bootstrap tenant structure and maintain the service catalog without leaving their AI coding session.

## Setup

```bash
cd services/sciple-mcp
uv sync
```

**Environment variables** (`.env` or shell):

```
SCIPLE_API_URL=http://localhost:8000/api/v1
SCIPLE_API_TOKEN=sciple_pat_...
SCIPLE_TENANT_ID=<your tenant id>
```

`SCIPLE_API_TOKEN` is a personal access token minted under **Profile → Access tokens** in the dashboard, scoped to the permissions the server should have (e.g. `environments.view`, `environments.manage`, `services.view`, `services.manage`, `observability.view`, `observability.manage`). The PAT is single-tenant — its bound tenant must equal `SCIPLE_TENANT_ID`.

## Wire into Claude Desktop / Claude Code

Add to `~/.claude/claude_desktop_config.json` (or your Claude Code MCP config):

```json
{
  "mcpServers": {
    "sciple-platform": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/services/sciple-mcp", "sciple-mcp"],
      "env": {
        "SCIPLE_API_URL": "http://localhost:8000/api/v1",
        "SCIPLE_API_TOKEN": "sciple_pat_...",
        "SCIPLE_TENANT_ID": "..."
      }
    }
  }
}
```

Then restart Claude Desktop or Claude Code. You should see 17 platform tools available.

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

### Observability

| Tool | Description |
|---|---|
| `list_dashboards` | List all observability dashboards in the tenant (id, name, panel count) |
| `get_dashboard` | Get a dashboard's name, description, and panel list |
| `create_dashboard` | Create a new dashboard with optional description |
| `update_dashboard` | Replace a dashboard's name and description (full PUT; name required) |
| `delete_dashboard` | Delete a dashboard and all its panels (irreversible) |
| `add_panel` | Add a panel to a dashboard with optional PromQL query |
| `delete_panel` | Delete a panel from a dashboard (irreversible) |

### Services

| Tool | Description |
|---|---|
| `list_services` | List all services in the tenant catalog (id, name, slug) |
| `create_service` | Create a service in the catalog with kind, language, SCM provider, and repository |
| `update_service` | Update a service's metadata, lifecycle, owner, tags, links, or environment associations |
| `delete_service` | Delete a service from the catalog by id (irreversible) |

## Security

The server can only do what the PAT's scope allows. Attempts to write without the relevant manage permission return a 403 from the API and are surfaced as an error in Claude's response. The PAT is revocable at any time from **Profile → Access tokens** in the Sciple dashboard — revoking it immediately cuts off the server's access without any config change.
