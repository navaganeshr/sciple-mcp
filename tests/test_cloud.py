"""Cloud inventory tools — formatting, the service allow-list guard, and the
multi-account EC2 sweep, with the REST API mocked via respx."""
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from sciple_mcp.client import ScipleClient
from sciple_mcp.tools import cloud

BASE = "http://api.test/api/v1"


def _register():
    client = ScipleClient(base_url=BASE, token="t", tenant_id="t00001")
    mcp = FastMCP("test")
    cloud.register(mcp, lambda: client)
    return mcp


async def _call(mcp, name, args):
    res = await mcp.call_tool(name, args)
    parts = res[0] if isinstance(res, tuple) else res
    return "\n".join(getattr(c, "text", "") for c in parts)


async def test_list_aws_accounts_marks_payer_and_account_id():
    mcp = _register()
    with respx.mock:
        respx.get(f"{BASE}/cloud/aws/accounts").mock(
            return_value=httpx.Response(200, json=[
                {"id": "A1", "name": "Prod", "aws_account_id": "111", "regions": ["us-east-1"], "is_payer": False},
                {"id": "A2", "name": "Mgmt", "aws_account_id": "222", "regions": ["us-east-1"], "is_payer": True},
            ])
        )
        out = await _call(mcp, "list_aws_accounts", {})
    assert "account_id=A1" in out and "aws=111" in out
    assert "[payer]" in out
    # only the payer account is flagged
    assert out.count("[payer]") == 1


async def test_list_aws_accounts_empty():
    mcp = _register()
    with respx.mock:
        respx.get(f"{BASE}/cloud/aws/accounts").mock(return_value=httpx.Response(200, json=[]))
        out = await _call(mcp, "list_aws_accounts", {})
    assert "No AWS accounts" in out


async def test_list_cloud_resource_types_renders_counts():
    mcp = _register()
    with respx.mock:
        respx.get(f"{BASE}/cloud/aws/accounts/A1/ec2").mock(
            return_value=httpx.Response(200, json=[
                {"table": "aws_ec2_instance", "label": "EC2 Instances", "count": 3},
            ])
        )
        out = await _call(mcp, "list_cloud_resource_types", {"account_id": "A1", "service": "ec2"})
    assert "aws_ec2_instance (EC2 Instances): 3" in out


async def test_bad_service_guard_makes_no_http_call():
    mcp = _register()
    with respx.mock:
        # No routes registered: any HTTP call would raise, proving the guard
        # short-circuits before touching the API.
        out = await _call(mcp, "list_cloud_resource_types", {"account_id": "A1", "service": "nope"})
    assert "Unknown service 'nope'" in out
    assert "ec2" in out  # valid set is surfaced


async def test_query_cloud_resources_strips_blob_and_nested():
    mcp = _register()
    with respx.mock:
        respx.get(f"{BASE}/cloud/aws/accounts/A1/ec2/aws_ec2_instance").mock(
            return_value=httpx.Response(200, json={
                "label": "EC2 Instances", "total": 1, "page": 1, "page_size": 50,
                "items": [{
                    "instance_id": "i-123", "state": "running", "name": "web",
                    "tenant_id": "t00001",                 # noise — dropped
                    "data": {"huge": "blob"},              # blob — dropped
                    "tags": [{"k": "v"}],                  # nested — skipped
                    "private_ip_address": None,            # empty — skipped
                }],
            })
        )
        out = await _call(mcp, "query_cloud_resources",
                          {"account_id": "A1", "service": "ec2", "resource_type": "aws_ec2_instance"})
    assert "instance_id=i-123" in out and "state=running" in out
    assert "huge" not in out and "tenant_id" not in out and "tags" not in out
    assert "1 total" in out


async def test_query_cloud_resources_clamps_page_size():
    mcp = _register()
    with respx.mock:
        route = respx.get(f"{BASE}/cloud/aws/accounts/A1/s3/aws_s3_bucket").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )
        await _call(mcp, "query_cloud_resources",
                    {"account_id": "A1", "service": "s3", "resource_type": "aws_s3_bucket", "page_size": 99999})
    assert "page_size=500" in str(route.calls.last.request.url)


async def test_list_ec2_instances_sweeps_all_accounts_with_tallies():
    mcp = _register()
    with respx.mock:
        respx.get(f"{BASE}/cloud/aws/accounts").mock(
            return_value=httpx.Response(200, json=[
                {"id": "A1", "name": "Prod"}, {"id": "A2", "name": "Dev"},
            ])
        )
        respx.get(f"{BASE}/cloud/aws/accounts/A1/ec2/aws_ec2_instance").mock(
            return_value=httpx.Response(200, json={"items": [
                {"instance_id": "i-1", "state": "running", "instance_type": "t3.small", "name": "api", "private_ip_address": "10.0.0.1"},
                {"instance_id": "i-2", "state": "stopped", "instance_type": "t3.micro", "name": "batch"},
            ]})
        )
        respx.get(f"{BASE}/cloud/aws/accounts/A2/ec2/aws_ec2_instance").mock(
            return_value=httpx.Response(200, json={"items": [
                {"instance_id": "i-3", "state": "running", "instance_type": "t3.nano", "name": None},
            ]})
        )
        out = await _call(mcp, "list_ec2_instances", {})
    assert "3 EC2 instances across 2 accounts" in out
    assert "Prod (account_id=A1) — 2 instances (1 running, 1 stopped)" in out
    assert "(10.0.0.1)" in out
    assert "(no Name tag)" in out  # i-3 has no name


async def test_list_ec2_instances_single_account_no_sweep_header():
    mcp = _register()
    with respx.mock:
        route = respx.get(f"{BASE}/cloud/aws/accounts/A1/ec2/aws_ec2_instance").mock(
            return_value=httpx.Response(200, json={"items": [
                {"instance_id": "i-1", "state": "running", "instance_type": "t3.small", "name": "api"},
            ]})
        )
        out = await _call(mcp, "list_ec2_instances", {"account_id": "A1"})
    # account_id given → does not list all accounts, no cross-account prefix
    assert "across" not in out
    assert route.called
    assert "i-1" in out
