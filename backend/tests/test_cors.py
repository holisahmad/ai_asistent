"""Test CORS (Fase 8): frontend di :3000 boleh memanggil API dengan Authorization."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_cors_preflight_allows_frontend_origin() -> None:
    with TestClient(create_app()) as client:
        r = client.options(
            "/api/v1/workspaces/x/chat/stream",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "POST" in (r.headers.get("access-control-allow-methods") or "")
    assert "authorization" in (r.headers.get("access-control-allow-headers") or "").lower()


def test_cors_rejects_unknown_origin() -> None:
    """Request tetap dilayani server-side, tapi tanpa header allow-origin
    sehingga browser memblokir aksesnya."""
    with TestClient(create_app()) as client:
        r = client.get("/health/live", headers={"Origin": "http://evil.example"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") is None


def test_health_still_public() -> None:
    """Sanity: middleware CORS tidak mengganggu endpoint publik."""
    with TestClient(create_app()) as client:
        assert client.get("/health/live").status_code == 200
