"""Shared native-stage AI tools; unit stubs never constitute real CLI or EDA acceptance."""

import json
import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from test_formal_gui_sessions import service, counter, make_session, action
from ucagent.eda.claude import FORMAL_TOOLS, build_claude_request
from ucagent.eda.models import ToolchainProfile
from ucagent.eda.models import ExecutionStatus
from ucagent.eda.claude import REQUIRED_FLAGS, parse_claude_output
from ucagent.server.formal_agent import FormalAgentTurn, common_agent_profile
from ucagent.server.formal_sessions import SessionAction


@pytest.mark.parametrize("engine", ["sby", "formalmc"])
def test_same_agent_tools_use_original_gates(service, counter, engine):
    """Either choice uses native planning, journals, approval and stage advancement."""
    store, _ = service
    row = make_session(store, counter, engine)
    request = SessionAction(action="agent", revision=row["revision"], stage_index=0,
                            request_id=uuid4().hex, timeout=120)
    store.active_id = row["id"]
    turn = FormalAgentTurn(store, row["id"], request)
    try:
        assert turn.call("RoleInfo")["capabilities"]["authoring"] == "shared_agent_with_manual_review"
        assert turn.call("CurrentTips")
        session = store.live[row["id"]]
        for path in session.stage_manager.get_current_stage().reference_files:
            turn.call("ReadTextFile", path=path.replace("\\", "/"))
        opened = turn.call("ReadTextFile", path="formal_out/.formal_records.yaml")
        records = yaml.safe_load(opened["content"])
        records["planning"] = counter[1].planning
        saved = turn.call("EditTextFile", path=opened["path"], content=yaml.safe_dump(records),
                          expected_sha256=opened["sha256"])
        assert saved["sha256"] != opened["sha256"]
        assert "planning" in saved["diff"]
        assert turn.call("Check")["check_pass"]
        turn.call("SetCurrentStageJournal", journal="Checked planning against the source requirements.")
        turn.call("Complete")
        assert session.stage_manager.stage_index == 0
        for forbidden in ("approve", "RunShellCommand", "SetStage", "request_run"):
            with pytest.raises(ValueError, match="not exposed"):
                turn.call(forbidden)
        with pytest.raises(ValueError):
            turn.call("EditTextFile", path="Counter/Counter.sv", content="forged", expected_sha256=None)
        with pytest.raises(ValueError):
            turn.call("ReadTextFile", path=".ucagent/runtime_config.json")
    finally:
        store.active_id = None
    row = store.public(store.load(row["id"]))
    row = action(store, row, "approve", journal="The engineer reviewed scope and risks.")
    store.active_id = row["id"]
    try:
        turn.call("Complete")
        assert session.stage_manager.stage_index == 1
        assert store.load(row["id"])["verification_status"] == "unknown"
        events = store.events(row["id"], 0)["items"]
        assert any(event["type"] == "agent.tool.EditTextFile" for event in events)
    finally:
        store.active_id = None


def test_cancel_and_stall_stop_native_agent_operations(service, counter):
    """A cancelled or repeatedly blocked turn cannot mutate or bypass a stage."""
    store, _ = service
    row = make_session(store, counter)
    request = SessionAction(action="agent", revision=row["revision"], stage_index=0,
                            request_id=uuid4().hex)
    turn = FormalAgentTurn(store, row["id"], request)
    store.active_id = row["id"]
    try:
        for _ in range(3):
            assert not turn.call("Check")["check_pass"]
        with pytest.raises(ValueError, match="Three checks"):
            turn.call("Check")
        store.action(row["id"], SessionAction(action="cancel", revision=row["revision"], stage_index=0,
                                              request_id=uuid4().hex))
        assert store.load(row["id"])["cancel_requested"]
        with pytest.raises(ValueError, match="cancelled"):
            turn.call("SetCurrentStageJournal", journal="Must not clear cancellation.")
        assert store.live[row["id"]].cancelled.is_set()
    finally:
        store.active_id = None


def test_formal_cli_scope_and_exact_resume(tmp_path):
    """Both engines share one bounded scope; neither shell nor approval is exposed."""
    identifier = str(uuid4())
    request = build_claude_request(workspace=tmp_path, output_dir=Path("out"),
        prompt_path=Path("p"), mcp_path=Path("m"), settings_path=Path("s"),
        session_id=identifier, resume=True, model="gpt-5.4", tool_scope="formal")
    argv = request.command.argv
    assert argv[argv.index("--resume") + 1] == identifier
    assert "--tools=" in argv and "--continue" not in argv
    assert argv[argv.index("--allowedTools") + 1].split(",") == ["mcp__formal__" + name for name in FORMAL_TOOLS]
    assert "approve" not in " ".join(argv).lower()
    assert request.resource_class == "claude"


@pytest.mark.parametrize("selected,configured", [(None, "gpt-5.4"), ("gpt-5.6-sol", "gpt-5.4"), ("gpt-5.6-sol", None)])
def test_private_profile_secrets_not_in_public_snapshot(tmp_path, selected, configured):
    """Private host credentials are used in memory only and unsafe settings are rejected."""
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"model": configured, "env": {"ANTHROPIC_AUTH_TOKEN": "unit-secret-not-a-credential"}}))
    settings.chmod(0o600)
    before = settings.read_bytes()
    profile = ToolchainProfile(id="shared", tools={"claude": str(tmp_path / "claude")},
                              environment={"HOME": str(tmp_path)}, claude_model=selected)
    runtime = SimpleNamespace(_profiles={"shared": profile}, reload_toolchains=lambda: None)
    resolved, model, path = common_agent_profile(runtime)
    assert model == (selected or configured) and path == settings
    assert settings.read_bytes() == before
    assert resolved.public_view()["claude_model"] == selected
    assert "unit-secret-not-a-credential" not in json.dumps(resolved.public_view())
    assert "ANTHROPIC_AUTH_TOKEN" not in profile.environment
    assert resolved.environment["ANTHROPIC_AUTH_TOKEN"] == "unit-secret-not-a-credential"
    runtime._profiles = {}
    with pytest.raises(ValueError, match="exactly one"):
        common_agent_profile(runtime)


@pytest.mark.parametrize("model", ["", "--model=x", "a b", "x\ny", "x" * 201, 54])
def test_profile_model_rejects_invalid_identifiers(model):
    """Host-level model selection cannot inject CLI flags or unbounded identifiers."""
    with pytest.raises(ValueError):
        ToolchainProfile(id="shared", tools={"claude": "claude"}, claude_model=model)


@pytest.mark.parametrize("engine", ["sby", "formalmc"])
def test_missing_agent_runtime_does_not_claim_progress(service, counter, engine):
    """Both engines fail the same preflight without changing native checkpoints."""
    store, _ = service
    row = make_session(store, counter, engine)
    with pytest.raises(ValueError, match="shared Claude"):
        action(store, row, "agent")
    assert store.load(row["id"])["revision"] == row["revision"]
    assert store.active_id is None


def test_real_mcp_auth_and_exact_resume_with_stub_cli(service, counter, tmp_path, monkeypatch):
    """Use real HTTP/MCP with an explicit CLI stub; verify authentication, scope and no fake pass."""
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    store, _ = service
    row = make_session(store, counter)
    settings = tmp_path / "host/.claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"model":"unit-model"}')
    profile = ToolchainProfile(id="test-agent", tools={"claude": str(tmp_path / "cli")},
        environment={"HOME": str(settings.parent.parent), "DISABLE_AUTOUPDATER": "1",
                     "ANTHROPIC_AUTH_TOKEN": "unit-secret-value", "VENDOR_ENDPOINT": "unit-license-value"},
        license_environment_names=["VENDOR_ENDPOINT"])
    exists = Path.exists

    def isolated_fixture_exists(path):
        """Model a clean host without inheriting this developer's personal Claude customization."""
        if path.name in {".claude", "CLAUDE.md", ".mcp.json"} and not path.is_relative_to(tmp_path):
            return False
        return exists(path)

    monkeypatch.setattr(Path, "exists", isolated_fixture_exists)
    monkeypatch.setattr("ucagent.server.formal_agent.common_agent_profile", lambda runtime: (profile, "unit-model", settings))
    seen = []

    class StubCliRunner:
        """Replace only the model process, leaving the real MCP server and native tools intact."""

        def run(self, request, profile, **kwargs):
            """Probe capabilities or exercise the authenticated endpoint and return labelled fixture output."""
            output = tmp_path / ("stub-" + uuid4().hex + ".log")
            if request.metadata["adapter"] == "claude_probe":
                output.write_text(" ".join(REQUIRED_FLAGS))
            else:
                config_path = Path(request.workspace) / request.session_inputs[1].source
                config_text = config_path.read_text()
                token = profile.environment["UCAGENT_FORMAL_MCP_TOKEN"]
                assert token not in config_text
                config = json.loads(config_text)["mcpServers"]["formal"]
                assert config["headers"]["Authorization"] == "Bearer ${UCAGENT_FORMAL_MCP_TOKEN}"
                assert httpx.post(config["url"], headers={"Authorization": "Bearer incorrect"}).status_code == 401

                async def exercise():
                    """Invoke actual MCP transport and verify the same bounded stage-tool schemas."""
                    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}) as http, streamable_http_client(config["url"], http_client=http) as (read, write, _):
                        async with ClientSession(read, write) as client:
                            await client.initialize()
                            listing = await client.list_tools()
                            assert {tool.name for tool in listing.tools} == set(FORMAL_TOOLS)
                            for name, args in (("RoleInfo", {}), ("CurrentTips", {}),
                                               ("ReadTextFile", {"path": "formal_out/.formal_records.yaml"}),
                                               ("SetCurrentStageJournal", {"journal": "Transport fixture only; not verification evidence."})):
                                response = await client.call_tool(name, args)
                                assert not response.isError, response
                asyncio.run(exercise())
                seen.append((request.metadata["session_id"], request.metadata["resume"], config["url"], token))
                output.write_text(json.dumps({"type": "result", "session_id": request.metadata["session_id"],
                                               "result": "STUB ONLY: stage 01, 1-bit input; " + token + " unit-secret-value unit-license-value"}))
            return SimpleNamespace(execution_status=ExecutionStatus.COMPLETED, stdout_log=output, manifest_path=None, diagnostics=[])

    monkeypatch.setattr(store.runtime, "_runner", StubCliRunner())
    for _ in range(2):
        row = action(store, row, "agent", timeout=120)
        assert row["execution_status"] == "completed", row["last_result"]
        assert row["verification_status"] == "unknown" and row["view"]["current_index"] == 0
        assert "stage 01, 1-bit input" in row["agent"]["message"]
        assert "unit-secret-value" not in row["agent"]["message"]
        assert "unit-license-value" not in row["agent"]["message"]
    assert seen[0][0] == seen[1][0] and [item[1] for item in seen] == [False, True]
    assert seen[0][3] != seen[1][3]
    for _, _, url, token in seen:
        assert token not in json.dumps(store.load(row["id"]))
        with pytest.raises(httpx.TransportError):
            httpx.post(url, timeout=1)


@pytest.mark.parametrize("message,subtype,code", [("API Error: 503 Service unavailable", "error_during_execution", "claude_service_unavailable"),
                                                   ("", "error_max_turns", "claude_budget_exhausted")])
def test_provider_or_budget_failure_is_not_a_proof(message, subtype, code):
    """Expose actionable service/budget diagnostics separately from DUT conclusions."""
    event = {"type": "result", "session_id": "id", "is_error": True, "subtype": subtype, "result": message}
    result = parse_claude_output(json.dumps(event), return_code=1, session_id="id")
    assert result.verification_status == "unknown"
    assert result.diagnostics[0]["error_code"] == code


def test_cli_synthetic_error_does_not_hide_provider_failure():
    """A failed API call remains unavailable, not a successful answer from another model."""
    events = [{"type": "assistant", "session_id": "id", "message": {"model": "<synthetic>"}},
              {"type": "result", "session_id": "id", "is_error": True, "subtype": "error_during_execution",
               "result": "API Error: 503", "modelUsage": {}}]
    result = parse_claude_output("\n".join(map(json.dumps, events)), return_code=1, session_id="id", expected_model="gpt-5.4")
    assert result.diagnostics[0]["error_code"] == "claude_service_unavailable"
