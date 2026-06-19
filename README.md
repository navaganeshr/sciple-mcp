# Sciple Platform MCP Server

MCP server that lets a local Claude populate and manage Sciple platform content — environments, services, observability dashboards, and runbooks — via the Sciple REST API. Engineers use it to bootstrap tenant structure, maintain the service catalog, build dashboards, and author runbooks without leaving their AI coding session.

Published on PyPI: <https://pypi.org/project/sciple-mcp/>
Source: <https://github.com/navaganeshr/sciple-mcp>

## Install

```bash
# Install uv (one-time, only if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`uvx sciple-mcp` resolves the latest version from PyPI and caches it.

## Two ways to authenticate

`sciple-mcp` accepts two credential styles against the same Bearer machinery. Pick by transport:

| Transport | Auth | When to use |
|---|---|---|
| **stdio** — `uvx sciple-mcp` spawned per session | Personal Access Token (`sciple_pat_…`) in env | Simplest. Claude Desktop's default MCP model. |
| **HTTP** — long-running `sciple-mcp serve` | OAuth-issued JWT (browser dance) | Multi-client. Claude Code + any other HTTP-aware MCP client share the same server. Refresh tokens, revocation, Connected apps. |

---

## Stdio + PAT (default)

The server reads three env vars; the PAT is minted under **Profile → Access tokens**:

```
SCIPLE_API_URL=http://localhost:8000/api/v1
SCIPLE_API_TOKEN=sciple_pat_...
SCIPLE_TENANT_ID=<your tenant id>
```

Wire into `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

The PAT is **single-tenant** — its bound tenant must equal `SCIPLE_TENANT_ID`. The Sciple dashboard renders this exact JSON block (with `SCIPLE_API_URL` and `SCIPLE_TENANT_ID` pre-filled) on Profile → Access tokens.

---

## HTTP + OAuth (v0.6.0)

Five CLI subcommands ship the full lifecycle:

```bash
# 1. Authenticate via browser. DCR-registers a client on first run, drives
#    the PKCE dance, caches the tokens to ~/.sciple/credentials.json (0600).
#
# By default, the resulting JWT inherits ALL permissions you hold on the
# tenant — same role as you. Pass --scope only if you want to down-scope
# (CI bots, shared tooling).
sciple-mcp login --tenant-id <your tenant id>

# 2. Start the HTTP MCP server. Accepts OAuth JWTs as Bearer on /mcp.
sciple-mcp serve --port 8765

# 3. (macOS) make `serve` start at user login via launchd.
sciple-mcp install

# 4. One-shot token retrieval — refreshes if within 120s of expiry.
sciple-mcp print-token

# 5. Forget cached credentials. --revoke also kills the refresh server-side.
sciple-mcp logout --revoke
```

Wire Claude Code / any HTTP-aware MCP client at the server:

```json
{
  "mcpServers": {
    "sciple-platform": {
      "url": "http://localhost:8765/mcp",
      "auth": "oauth"
    }
  }
}
```

The MCP client discovers the AS via `/.well-known/oauth-protected-resource` on the running `sciple-mcp serve` and drives its own browser dance. The user can also revoke access at any time from **Profile → Connected apps** on the dashboard.

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
| `add_panel` | Add a panel to a dashboard. Supports **5 shapes** end-to-end (pick one): **PromQL** (`promql`), **CloudWatch Metrics** (`cw_namespace`+`cw_metric_name`+`cw_stat` + optional `cw_dimensions`/`cw_period`), **ElasticSearch/OpenSearch logs** (`es_index` + optional `kql_filter`), **CloudWatch Logs** (`cw_log_group` + optional `cw_filter_pattern`), or **Text** (`text_content` + optional `text_background`). Log panels also accept display options (`log_columns`, `log_limit`, `log_wrap_message`, `log_expandable_rows`, `log_highlight_by_severity`, `log_live_tail`). Always pass `datasource_id` for metric + log panels. |
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

### Projects

| Tool | Description |
|---|---|
| `list_projects` | List all projects in the tenant (id, key, name, classification) |
| `get_project` | Get a single project's details (owner, description, classification) |
| `create_project` | Create a new project (name + uppercase key like "PLAT", optional classification + owner) |
| `list_project_members` | List the user_ids and roles of a project's members (use to find an assignee) |
| `list_project_issue_types` | List a project's issue types (required before `create_project_ticket`) |

### Tickets

| Tool | Description |
|---|---|
| `list_tickets` | List tickets across the tenant with optional filters (service, assignee, status, priority, type, tag, full-text `q`) |
| `get_ticket` | Get a single ticket's full details + activity counts (by internal id) |
| `create_ticket` | Create a **service-level** ticket (not bound to a project) — `tickets.manage` |
| `update_ticket` | PATCH a ticket — change status, priority, assignee, dates, tags, parent |
| `comment_on_ticket` | Add a comment to a ticket — `tickets.comment` |
| `link_tickets` | Relate two tickets (`blocks` / `relates_to` / `duplicates`) |
| `list_project_tickets` | List tickets in a project |
| `get_project_ticket` | Get a project ticket by sequence number (the NNN in KEY-NNN) |
| `create_project_ticket` | **Create a ticket inside a project** — returns a "KEY-NNN" display id. Recommended for most ticket creation. Supports `custom_fields` (JSON string of `{field_id: value}`). Requires `tickets.create`. |

Ticket statuses: `open → in_progress → done` (or `cancelled` from any state). Priorities: `low / medium / high / urgent`. Severities (optional): `minor / major / critical`. Types: `epic / story / task / subtask / bug`.

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
