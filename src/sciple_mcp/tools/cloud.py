"""Cloud inventory tools — read-only queries over synced AWS resources.

Wraps the platform's cached AWS inventory REST routes (one connected account
at a time, plus a sweep helper):
  GET /cloud/aws/accounts                              — connected accounts
  GET /cloud/aws/accounts/{id}/{service}               — resource types + counts
  GET /cloud/aws/accounts/{id}/{service}/{table_name}  — paginated rows

Everything here is **read-only** — it reads the platform's last AWS sync, never
calls AWS directly and never mutates anything. Requires the credential to hold
`cloud.view`. There are deliberately no start/stop/terminate tools; mutating
cloud actions are out of scope for this module.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sciple_mcp.client import ScipleClient

# Services exposing the uniform `/{service}` (types) + `/{service}/{table}` (rows)
# shape. Kept as an allow-list so a bad `service` arg fails fast with the valid
# set rather than surfacing a raw 404 from the API.
_TABLE_SERVICES: frozenset[str] = frozenset(
    {
        "cloudfront", "codebuild", "codecommit", "codedeploy", "codepipeline",
        "dynamodb", "ebs", "ec2", "ecr", "ecs", "efs", "eks", "elasticache",
        "iam", "lambda", "rds", "route53", "s3", "vpc",
    }
)

# Row fields that are noise in a text summary: the full AWS describe payload and
# bookkeeping columns. Stripped from generic row rendering.
_ROW_NOISE: frozenset[str] = frozenset(
    {"data", "tenant_id", "created_at", "updated_at"}
)


def _fmt_row(row: dict[str, Any]) -> str:
    """Render one resource row as a compact `key=value` line, sans blobs."""
    parts = []
    for key, val in row.items():
        if key in _ROW_NOISE:
            continue
        if val is None or val == "":
            continue
        if isinstance(val, (dict, list)):
            continue  # nested structures live in `data`; skip in the summary
        parts.append(f"{key}={val}")
    return "- " + ", ".join(parts)


def register(mcp, get_client: Callable[[], ScipleClient]) -> None:

    @mcp.tool()
    async def list_aws_accounts() -> str:
        """List the AWS accounts connected to this tenant.

        Returns each account's internal id (used as `account_id` in the other
        cloud tools), display name, 12-digit AWS account number, synced regions,
        and whether it is the Organizations payer account.
        """
        accts = await get_client().get("/cloud/aws/accounts")
        if not accts:
            return "No AWS accounts connected to this tenant."
        lines = []
        for a in accts:
            payer = " [payer]" if a.get("is_payer") else ""
            regions = ",".join(a.get("regions") or []) or "—"
            lines.append(
                f"- {a['name']} (account_id={a['id']}, "
                f"aws={a['aws_account_id']}, regions={regions}){payer}"
            )
        return "\n".join(lines)

    @mcp.tool()
    async def list_cloud_resource_types(account_id: str, service: str) -> str:
        """List the resource types synced for one AWS service in an account.

        Use this to discover what `resource_type` values `query_cloud_resources`
        accepts for a given service, along with how many rows each holds.

        Args:
            account_id: Internal account id from `list_aws_accounts`.
            service: AWS service area. One of: cloudfront, codebuild, codecommit,
                codedeploy, codepipeline, dynamodb, ebs, ec2, ecr, ecs, efs, eks,
                elasticache, iam, lambda, rds, route53, s3, vpc.
        """
        if service not in _TABLE_SERVICES:
            return (
                f"Unknown service '{service}'. Valid services: "
                + ", ".join(sorted(_TABLE_SERVICES))
            )
        tables = await get_client().get(f"/cloud/aws/accounts/{account_id}/{service}")
        if not tables:
            return f"No {service} resource types synced for account {account_id}."
        lines = [
            f"- {t['table']} ({t.get('label', t['table'])}): {t.get('count', 0)}"
            for t in tables
        ]
        return "\n".join(lines)

    @mcp.tool()
    async def query_cloud_resources(
        account_id: str,
        service: str,
        resource_type: str,
        region: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """Query cached rows from any synced AWS resource table (read-only).

        Generic accessor over every supported service. Call
        `list_cloud_resource_types` first to find valid `resource_type` values.
        Large nested payloads are omitted from the summary; identity/scalar
        fields are shown as `key=value`.

        Args:
            account_id: Internal account id from `list_aws_accounts`.
            service: AWS service area (see `list_cloud_resource_types`).
            resource_type: Table name, e.g. "aws_ec2_instance", "aws_rds_db_instance".
            region: Optional region filter, e.g. "us-east-1" ("global" for S3).
            page: 1-based page number (default 1).
            page_size: Rows per page, 1–500 (default 50).
        """
        if service not in _TABLE_SERVICES:
            return (
                f"Unknown service '{service}'. Valid services: "
                + ", ".join(sorted(_TABLE_SERVICES))
            )
        page_size = max(1, min(page_size, 500))
        params: dict[str, object] = {"page": max(1, page), "page_size": page_size}
        if region:
            params["region"] = region
        result = await get_client().get(
            f"/cloud/aws/accounts/{account_id}/{service}/{resource_type}",
            params=params,
        )
        items = result.get("items", [])
        total = result.get("total", len(items))
        if not items:
            return f"No rows in {resource_type} for account {account_id}."
        header = (
            f"{result.get('label', resource_type)} — {total} total, "
            f"showing page {result.get('page', page)} ({len(items)} rows):"
        )
        return header + "\n" + "\n".join(_fmt_row(r) for r in items)

    @mcp.tool()
    async def list_ec2_instances(
        account_id: str | None = None,
        region: str | None = None,
    ) -> str:
        """Summarize EC2 instances — for one account or across all of them.

        Convenience view over `aws_ec2_instance` formatted as
        `[state] type id name (private_ip)`, grouped per account with a running/
        stopped tally. Omit `account_id` to sweep every connected account.

        Args:
            account_id: Internal account id from `list_aws_accounts`. If omitted,
                every connected account is queried.
            region: Optional region filter, e.g. "us-east-1".
        """
        client = get_client()
        if account_id:
            targets = [{"id": account_id, "name": account_id}]
        else:
            targets = await client.get("/cloud/aws/accounts")
            if not targets:
                return "No AWS accounts connected to this tenant."

        params: dict[str, object] = {"page": 1, "page_size": 500}
        if region:
            params["region"] = region
        blocks: list[str] = []
        grand = 0
        for acct in targets:
            aid = acct["id"]
            result = await client.get(
                f"/cloud/aws/accounts/{aid}/ec2/aws_ec2_instance", params=params
            )
            rows = result.get("items", [])
            grand += len(rows)
            running = sum(1 for r in rows if r.get("state") == "running")
            stopped = sum(1 for r in rows if r.get("state") == "stopped")
            head = (
                f"### {acct.get('name', aid)} (account_id={aid}) — "
                f"{len(rows)} instances ({running} running, {stopped} stopped)"
            )
            if not rows:
                blocks.append(head)
                continue
            lines = [
                f"  [{r.get('state', '?')}] {r.get('instance_type', '?')} "
                f"{r.get('instance_id', '?')} "
                f"{r.get('name') or '(no Name tag)'}"
                + (f" ({r['private_ip_address']})" if r.get("private_ip_address") else "")
                for r in sorted(
                    rows, key=lambda x: (x.get("state") or "", x.get("name") or "")
                )
            ]
            blocks.append(head + "\n" + "\n".join(lines))

        prefix = "" if account_id else f"{grand} EC2 instances across {len(targets)} accounts.\n\n"
        return prefix + "\n\n".join(blocks)
