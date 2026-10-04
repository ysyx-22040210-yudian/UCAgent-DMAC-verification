"""Selectable host VCF and bundled SBY profiles with isolated in-memory licenses."""

import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest
import yaml

from ucagent.eda import CommandSpec, JobRunner, RunRequest, ToolchainProfile
from ucagent.server.platform_main import create_platform_app


def builtin_profiles():
    """Supply configured fixture executables without claiming an actual formal proof."""
    return {"bundled_sby": {"tools": {name: sys.executable for name in ("sby", "yosys", "yosys-smtbmc", "z3")}}}


def test_host_vcf_supplements_bundled_sby_and_keeps_license_out_of_state(tmp_path, monkeypatch):
    """Both engines remain available after reload without serializing license values."""
    monkeypatch.setenv("SNPSLMD_LICENSE_FILE", "test-only-private-endpoint")
    host = tmp_path / "host.yaml"
    host.write_text(yaml.safe_dump({"profiles": {"host_vcf": {"tools": {"vcf": sys.executable}, "license_environment_names": ["SNPSLMD_LICENSE_FILE"]}}}))
    original = host.read_bytes()
    app = create_platform_app(workspace=tmp_path / "state", toolchains_file=host, builtin_toolchains=builtin_profiles())
    runtime = app.state.platform_runtime
    with TestClient(app) as client:
        assert set(runtime._profiles) == {"bundled_sby", "host_vcf"}
        assert runtime._profiles["host_vcf"].environment["SNPSLMD_LICENSE_FILE"] == "test-only-private-endpoint"
        assert "SNPSLMD_LICENSE_FILE" not in runtime._profiles["bundled_sby"].environment
        assert "test-only-private-endpoint" not in client.get("/api/v1/toolchains").text
        runtime.reload_toolchains()
        assert set(runtime._profiles) == {"bundled_sby", "host_vcf"}
    assert host.read_bytes() == original
    for path in (tmp_path / "state").rglob("*"):
        if path.is_file():
            assert b"test-only-private-endpoint" not in path.read_bytes()


@pytest.mark.parametrize("case", ["malformed", "reserved_id", "inline_license", "invalid_profile"])
def test_invalid_host_configuration_cannot_remove_or_replace_sby(tmp_path, monkeypatch, case):
    """Host errors remain diagnostic, preserving the immutable built-in toolchain."""
    monkeypatch.setenv("SNPSLMD_LICENSE_FILE", "private-credential-not-in-errors")
    host = tmp_path / "host.yaml"
    profile = {"tools": {"vcf": sys.executable}, "license_environment_names": ["SNPSLMD_LICENSE_FILE"]}
    key = "host_vcf"
    if case == "reserved_id":
        key = "bundled_sby"
    elif case == "inline_license":
        profile.update(environment={"CUSTOM_ENDPOINT": "private-credential-not-in-errors"}, license_environment_names=["CUSTOM_ENDPOINT"])
    elif case == "invalid_profile":
        profile["tools"] = {}
    host.write_text("profiles: [\n" if case == "malformed" else yaml.safe_dump({"profiles": {key: profile}}))
    app = create_platform_app(workspace=tmp_path / "state", toolchains_file=host, builtin_toolchains=builtin_profiles())
    with TestClient(app):
        runtime = app.state.platform_runtime
        assert set(runtime._profiles) == {"bundled_sby"}
        assert runtime._profiles["bundled_sby"].tools == builtin_profiles()["bundled_sby"]["tools"]
        assert runtime._profile_errors
        assert "private-credential-not-in-errors" not in json.dumps(runtime._profile_errors)


def test_vcf_license_failure_does_not_block_sby_or_change_selected_engine(tmp_path, monkeypatch):
    """One unavailable commercial license is not a global formal-engine failure."""
    monkeypatch.setattr("ucagent.server.platform_workbench.shutil.disk_usage", lambda path: type("Disk", (), {"free": 20 * 1024**3})())
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "dut.sv").write_text("module dut(input clk, input rst_n); endmodule\n")
    host = tmp_path / "host.yaml"
    host.write_text(yaml.safe_dump({"profiles": {"host_vcf": {"tools": {"vcf": sys.executable}}}}))
    app = create_platform_app(workspace=tmp_path / "state", import_roots=[workspace], toolchains_file=host, builtin_toolchains=builtin_profiles())
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        runtime.store.save_toolchain_probe("host_vcf", "degraded", {"capabilities": [{"name": "vcf", "available": False, "license_status": "unavailable"}]})
        project = client.post("/api/v1/projects", json={"name": "engines", "path": str(workspace)}).json()
        body = {"project_id": project["id"], "family": "formal", "methodology": "systemverilog", "toolchain": "host_vcf", "design": {"top": "dut", "sources": ["dut.sv"]}, "formal": {"engine": "vc_formal", "clock": {"signal": "clk", "period": "10ns"}, "reset": {"signal": "rst_n"}}}
        blocked = client.post("/api/v1/runs/preview", json=body).json()
        assert blocked["ready"] is False
        assert any(item["key"] == "tool:vcf" and item["status"] == "blocked" for item in blocked["checks"])
        body.update(toolchain="bundled_sby", formal={"engine": "sby", "sby": {"mode": "prove", "depth": 20}, "clock": {}, "reset": {}})
        opened = client.post("/api/v1/runs/preview", json=body).json()
        assert opened["ready"], opened
        assert runtime.store.list_runs() == []


def test_jobrunner_forwards_only_explicit_license_to_selected_profile(tmp_path, monkeypatch):
    """SBY cannot inherit VCF's license; explicitly configured values are redacted."""
    monkeypatch.setenv("SNPSLMD_LICENSE_FILE", "private-ambient-license")
    monkeypatch.setenv("UNRELATED_API_KEY", "private-ambient-key")
    for selected in (False, True):
        profile = ToolchainProfile(id="engine", tools={"python": sys.executable}, minimum_free_bytes=0, environment={"SNPSLMD_LICENSE_FILE": "private-ambient-license"} if selected else {}, license_environment_names=["SNPSLMD_LICENSE_FILE"] if selected else [])
        code = "import os; print(os.environ.get('SNPSLMD_LICENSE_FILE', 'NOT_INHERITED')); assert 'UNRELATED_API_KEY' not in os.environ"
        request = RunRequest(workspace=tmp_path, output_dir=Path("run-" + str(selected)), command=CommandSpec(tool="python", argv=["python", "-c", code]))
        result = JobRunner(b"test-only-key").run(request, profile)
        assert result.execution_status == "completed", result
        output = (tmp_path / request.output_dir / "stdout.log").read_text()
        assert ("<redacted>" if selected else "NOT_INHERITED") in output
        assert "private-ambient-license" not in output
