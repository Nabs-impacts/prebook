from uuid import UUID

from httpx import AsyncClient


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/api/v1/unknown", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req-123"
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == "req-123"


async def test_request_id_is_generated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/unknown")

    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4


async def test_cors_preflight_is_allowed(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
