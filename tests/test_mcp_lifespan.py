"""MCP-only lifespan helpers."""

from types import SimpleNamespace

from app.web.mcp.lifespan import _dashboard_notify_base_url


def test_dashboard_notify_base_url_prefers_mem_mesh_api_url(monkeypatch) -> None:
    monkeypatch.setenv("MEM_MESH_API_URL", "https://mem.example.com/")
    settings = SimpleNamespace(api_base_url="http://localhost:8000", server_port=9000)

    assert _dashboard_notify_base_url(settings) == "https://mem.example.com"


def test_dashboard_notify_base_url_uses_api_base_url(monkeypatch) -> None:
    monkeypatch.delenv("MEM_MESH_API_URL", raising=False)
    settings = SimpleNamespace(
        api_base_url="http://dashboard.local:8000/", server_port=9000
    )

    assert _dashboard_notify_base_url(settings) == "http://dashboard.local:8000"
