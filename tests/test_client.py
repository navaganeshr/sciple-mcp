"""ScipleClient sends auth + tenant headers and parses JSON."""
import httpx
import pytest
import respx

from sciple_mcp.client import ScipleClient


@pytest.mark.asyncio
async def test_get_sends_headers_and_returns_json():
    client = ScipleClient(
        base_url="http://api.test/api/v1",
        token="sciple_pat_abc",
        tenant_id="t00001",
    )
    with respx.mock:
        route = respx.get("http://api.test/api/v1/environments").mock(
            return_value=httpx.Response(200, json=[{"id": "e1", "name": "prod"}])
        )
        out = await client.get("/environments")
        assert out == [{"id": "e1", "name": "prod"}]
        sent = route.calls.last.request
        assert sent.headers["Authorization"] == "Bearer sciple_pat_abc"
        assert sent.headers["X-Tenant-ID"] == "t00001"


@pytest.mark.asyncio
async def test_post_sends_body():
    client = ScipleClient(base_url="http://api.test/api/v1", token="t", tenant_id="x")
    with respx.mock:
        route = respx.post("http://api.test/api/v1/environments").mock(
            return_value=httpx.Response(201, json={"id": "e2"})
        )
        out = await client.post("/environments", {"name": "staging"})
        assert out == {"id": "e2"}
        import json as _json
        assert _json.loads(route.calls.last.request.content)["name"] == "staging"
