"""Thin async HTTP client wrapping the Sciple REST API.

Authenticates with a Sciple personal access token (PAT). The PAT is sent as a
Bearer token; the API's get_bearer resolves it on data routes, and X-Tenant-ID
selects the tenant (which must match the PAT's bound tenant).
"""
import httpx


class ScipleClient:
    def __init__(self, base_url: str, token: str, tenant_id: str) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": tenant_id,
            "Content-Type": "application/json",
        }

    async def get(self, path: str) -> object:
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{self._base}{path}", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def post(self, path: str, body: dict | None = None) -> object:
        async with httpx.AsyncClient() as http:
            r = await http.post(f"{self._base}{path}", headers=self._headers, json=body or {})
            r.raise_for_status()
            return r.json()

    async def patch(self, path: str, body: dict) -> object:
        async with httpx.AsyncClient() as http:
            r = await http.patch(f"{self._base}{path}", headers=self._headers, json=body)
            r.raise_for_status()
            return r.json()

    async def put(self, path: str, body: dict) -> object:
        async with httpx.AsyncClient() as http:
            r = await http.put(f"{self._base}{path}", headers=self._headers, json=body)
            r.raise_for_status()
            return r.json()

    async def delete(self, path: str) -> None:
        async with httpx.AsyncClient() as http:
            r = await http.delete(f"{self._base}{path}", headers=self._headers)
            r.raise_for_status()
