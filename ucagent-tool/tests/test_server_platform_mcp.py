"""Focused contracts for public MCP metadata in the verification platform."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from ucagent.server.api_master import PdbMasterApiServer
from ucagent.server.platform_main import create_platform_app


class _Config:
    """Provide a bounded launch root and an optional MCP mapping."""

    def __init__(self, root: Path, mcp: dict | None = None) -> None:
        """Store deterministic values for the Master API test fixture."""

        self.root = root
        self.mcp = mcp or {}

    def get_value(self, key: str, default=None):
        """Resolve only values needed by the platform test server."""

        if key == "launch.file_browser_roots":
            return [{"name": "tests", "path": str(self.root)}]
        if key == "platform.toolchains_file":
            return str(self.root / "missing-toolchains.yaml")
        if key == "mcp_server":
            return dict(self.mcp)
        return default


class _ToolInput(BaseModel):
    """Represent a real MCP-compatible Pydantic input contract."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(description="Workspace-relative target.")
    api_key: str = Field(default="schema-secret-value", description="Optional service credential.")


class _Tool:
    """Expose metadata without providing or invoking executable behavior."""

    def __init__(self, name: str, description: str = "Read verification state.") -> None:
        """Initialize inert tool metadata used by the public-schema projection."""

        self.name = name
        self.description = description
        self.tool_call_schema = _ToolInput


class _McpServer:
    """Model a running in-process MCP server without opening a socket."""

    is_running = True
    no_file_ops = True

    @staticmethod
    def url() -> str:
        """Return the base address reported by the real lifecycle wrapper."""

        return "http://127.0.0.1:5000"


def _agent() -> SimpleNamespace:
    """Build all tool buckets consumed by the canonical MCP collector."""

    return SimpleNamespace(
        tool_list_base=[_Tool("RoleInfo", "password=hunter2 must never be returned")],
        tool_list_task=[_Tool("Check")],
        tool_list_ext=[],
        tool_list_waveform=[_Tool("WaveInfo")],
        tool_list_file=[_Tool("ReadTextFile")],
    )


def test_integrated_master_projects_actual_agent_tools_without_secrets(tmp_path: Path) -> None:
    """List active MCP schemas, honor no-file-ops, and redact secret defaults."""

    server = PdbMasterApiServer(
        workspace=str(tmp_path),
        cfg=_Config(tmp_path),
        password="",
        sock="",
    )
    server.pdb = SimpleNamespace(agent=_agent(), _mcp_server=_McpServer())

    with TestClient(server._app) as client:
        response = client.get("/api/v1/mcp")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["hosted_here"] is True
    assert body["service_mode"] == "embedded_agent"
    assert body["protocol_url"] == "http://127.0.0.1:5000/mcp"
    assert body["schema_source"] == "active_agent"
    assert body["tool_count"] == 3
    assert [tool["name"] for tool in body["tools"]] == ["RoleInfo", "Check", "WaveInfo"]
    assert "ReadTextFile" not in {tool["name"] for tool in body["tools"]}
    public_text = json.dumps(body, ensure_ascii=False)
    assert "hunter2" not in public_text
    assert "schema-secret-value" not in public_text
    api_key_schema = body["tools"][0]["input_schema"]["properties"]["api_key"]
    assert api_key_schema["type"] == "string"
    assert "default" not in api_key_schema


def test_standalone_reports_no_mcp_route_when_unconfigured(tmp_path: Path) -> None:
    """Keep standalone MCP unavailable instead of inventing a local endpoint."""

    app = create_platform_app(workspace=tmp_path / "state")
    with TestClient(app) as client:
        response = client.get("/api/v1/mcp")
        protocol_response = client.get("/mcp")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "status": "unavailable",
        "service_mode": "none",
        "hosted_here": False,
        "protocol_url": None,
        "transport": None,
        "tools": [],
        "tool_count": 0,
        "schema_source": None,
        "client_config": None,
        "message": "No MCP protocol service is hosted by this platform process.",
    }
    assert protocol_response.status_code == 404


def test_standalone_mcp_flag_mounts_typed_platform_protocol(tmp_path: Path) -> None:
    """Host the platform MCP endpoint and expose its exact registered schemas."""

    app = create_platform_app(workspace=tmp_path / "state", mcp_enabled=True)
    with TestClient(app, base_url="http://127.0.0.1:8800") as client:
        response = client.get("/api/v1/mcp")
        protocol_response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["status"] == "healthy"
    assert body["service_mode"] == "embedded_platform"
    assert body["hosted_here"] is True
    assert body["protocol_url"] == "http://127.0.0.1:8800/mcp"
    assert body["client_config"] == {
        "mcpServers": {"ucagent": {"url": "http://127.0.0.1:8800/mcp"}}
    }
    assert body["schema_source"] == "platform_runtime"
    assert body["tool_count"] == 24
    assert {tool["name"] for tool in body["tools"]} >= {
        "create_project",
        "create_run",
        "cancel_run",
        "list_workflows",
        "list_run_results",
        "start_counterexample_replay",
        "approve_stage",
        "list_campaigns",
        "get_campaign",
        "list_capabilities",
        "get_npi_query",
    }
    assert protocol_response.status_code == 200
    protocol_tools = protocol_response.json()["result"]["tools"]
    assert {tool["name"] for tool in protocol_tools} == {
        tool["name"] for tool in body["tools"]
    }


def test_standalone_mcp_uses_the_platform_basic_auth_boundary(tmp_path: Path) -> None:
    """Do not let the mounted protocol bypass optional single-user authentication."""

    app = create_platform_app(
        workspace=tmp_path / "state",
        mcp_enabled=True,
        password="local-only-password",
    )
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app, base_url="http://127.0.0.1:8800") as client:
        rejected = client.post("/mcp", json=request, headers=headers)
        accepted = client.post(
            "/mcp",
            json=request,
            headers=headers,
            auth=("ucagent", "local-only-password"),
        )

    assert rejected.status_code == 401
    assert rejected.headers["www-authenticate"] == 'Basic realm="UCAgent Platform"'
    assert accepted.status_code == 200
    assert accepted.json()["result"]["tools"]
