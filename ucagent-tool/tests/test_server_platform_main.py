"""Tests for the platform-only deployment entry point."""

from __future__ import annotations

from base64 import b64encode
from pathlib import Path

from fastapi.testclient import TestClient

from ucagent.server.platform_main import PlatformServerConfig, create_platform_app


def test_standalone_app_serves_platform_without_legacy_master_routes(tmp_path: Path) -> None:
    """Expose the versioned API and SPA while omitting the old Master task surface."""

    state = tmp_path / "state"
    projects = tmp_path / "projects"
    projects.mkdir()
    app = create_platform_app(workspace=state, import_roots=[projects])

    with TestClient(app) as client:
        assert client.get("/", follow_redirects=False).headers["location"] == "/platform/"
        assert client.get("/platform/").status_code == 200
        assert client.get("/api/v1/workflows").status_code == 200
        assert client.get("/api/agents").status_code == 404


def test_standalone_app_uses_optional_password_without_persisting_it(tmp_path: Path) -> None:
    """Require Basic authentication while keeping the credential outside config/state."""

    app = create_platform_app(workspace=tmp_path / "state", password="temporary-password")
    token = b64encode(b"user:temporary-password").decode("ascii")

    with TestClient(app) as client:
        assert client.get("/api/v1/overview").status_code == 401
        response = client.get(
            "/api/v1/overview",
            headers={"Authorization": f"Basic {token}"},
        )
        assert response.status_code == 200
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (tmp_path / "state").rglob("*")
        if path.is_file()
    )
    assert "temporary-password" not in persisted


def test_standalone_config_resolves_only_declared_values(tmp_path: Path) -> None:
    """Return explicit platform and MCP values through the dotted config interface."""

    toolchains = tmp_path / "toolchains.yaml"
    toolchains.write_text("profiles: {}\n", encoding="utf-8")
    config = PlatformServerConfig(toolchains, mcp_enabled=True)

    assert config.get_value("platform.toolchains_file") == str(toolchains.resolve())
    assert config.get_value("mcp_server.enabled") is True
    assert config.get_value("missing.value", "fallback") == "fallback"


def test_retention_setting_can_be_explicitly_cleared(tmp_path: Path) -> None:
    """Treat JSON null as the canonical request to disable automatic retention."""

    app = create_platform_app(workspace=tmp_path / "state")
    with TestClient(app) as client:
        response = client.put("/api/v1/settings", json={"retention_days": 30})
        assert response.status_code == 200
        assert response.json()["retention_days"] == 30

        response = client.put("/api/v1/settings", json={"retention_days": None})
        assert response.status_code == 200
        assert response.json()["retention_days"] is None
