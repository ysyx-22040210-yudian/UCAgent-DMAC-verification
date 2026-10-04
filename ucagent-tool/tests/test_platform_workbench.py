"""Readiness and workbench contracts tested without acquiring EDA licenses."""

from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from ucagent.eda import ToolchainProfile
from ucagent.server.platform_main import create_platform_app
from ucagent.server.platform_workbench import run_defaults, run_summary
from ucagent.server.api_platform import RunCreateRequest


@pytest.fixture
def lab(tmp_path: Path):
    """Create a real platform with harmless tool paths and one project input."""

    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "dut.sv").write_text("module tb_top; endmodule\n", encoding="utf-8")
    app = create_platform_app(workspace=tmp_path / "state", import_roots=[workspace])
    runtime = app.state.platform_runtime
    runtime.settings["minimum_free_disk_gb"] = 0
    runtime._profiles["fixture"] = ToolchainProfile(
        id="fixture", tools={tool: sys.executable for tool in ("vcs", "vcf", "urg")},
        minimum_free_bytes=0,
    )
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "DUT", "path": str(workspace)}).json()
        body = {
            "project_id": project["id"], "family": "simulation", "methodology": "uvm",
            "authoring_mode": "guided", "toolchain": "fixture",
            "design": {"top": "tb_top", "sources": ["dut.sv"], "parameters": {"WIDTH": 8}},
            "simulation": {"simulator": "vcs", "suites": ["UT"], "tests": ["smoke"], "seeds": [11, 29], "coverage": ["line"]},
        }
        yield client, runtime, workspace, body
    runtime.shutdown()


def test_preview_plans_exact_matrix_without_writes_or_dispatch(lab, monkeypatch):
    """Preflight must preserve project inputs and create neither jobs nor runtime files."""

    client, runtime, workspace, body = lab
    before = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*"))

    def forbidden(*args, **kwargs):
        """Fail if planning accidentally attempts tool execution."""

        raise AssertionError("preview dispatched a tool")

    monkeypatch.setattr(runtime._runner, "run", forbidden)
    response = client.post("/api/v1/runs/preview", json=body)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["ready"] is True
    assert plan["job_count"] == 4
    assert plan["matrix"] == [{"test": "smoke", "suite": "UT", "seed": 11}, {"test": "smoke", "suite": "UT", "seed": 29}]
    assert "-pvalue+tb_top.WIDTH=8" in plan["jobs"][0]["command"]
    assert runtime.store.list_runs() == []
    assert sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*")) == before


def test_preflight_is_specific_to_selected_tool_and_preserves_unknown_license(lab):
    """VC Formal license failure must not block an otherwise available VCS regression."""

    client, runtime, _, body = lab
    runtime.store.save_toolchain_probe("fixture", "degraded", {"capabilities": [
        {"name": "vcs", "available": True, "license_status": "available"},
        {"name": "vcf", "available": False, "license_status": "unavailable"},
        {"name": "urg", "available": True},
    ]})
    assert client.post("/api/v1/runs/preview", json=body).json()["ready"] is True
    formal = {**body, "family": "formal", "methodology": "systemverilog", "formal": {"engine": "vc_formal", "clock": {"signal": "clk", "period": "10ns"}, "reset": {"signal": "rst_n"}}}
    formal.pop("simulation")
    result = client.post("/api/v1/runs/preview", json=formal).json()
    assert result["ready"] is False
    assert any(item["key"] == "tool:vcf" and item["status"] == "blocked" for item in result["checks"])


@pytest.mark.parametrize("entries,ready", [(["run.tcl"], True), ([], False), (["run.tcl", "other.tcl"], False), (["absent.tcl"], False)])
def test_formalmc_default_preflight_matches_dispatch(lab, entries, ready):
    """Preflight the actual Tcl entry without VCF timing, writes or a VCF license gate."""
    client, runtime, workspace, body = lab
    for name in ("run.tcl", "other.tcl"):
        (workspace / name).write_text("read_design dut.sv\ndef_clk clk\ndef_rst rst_n\nprove\n", encoding="utf-8")
    runtime._profiles["fixture"] = runtime._profiles["fixture"].model_copy(update={"tools": {"formalmc": sys.executable}})
    formal = {**body, "family": "formal", "methodology": "systemverilog", "formal": {"property_sets": entries}}
    formal.pop("simulation")
    before = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*"))
    response = client.post("/api/v1/runs/preview", json=formal)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ready"] is ready
    assert not any(item["key"] == "tool:vcf" for item in result["checks"])
    assert sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*")) == before
    assert runtime.store.list_runs() == []
    if ready:
        assert result["jobs"][0]["tool"] == "formalmc"
        request = RunCreateRequest.model_validate(formal)
        project = runtime.store.get_project(body["project_id"])
        config = runtime.build_project_config(request, project.get("config") or {})
        jobs = runtime._build_formal_requests("test", workspace, config, Path("runs/test"))
        assert jobs[0].command.argv == result["jobs"][0]["command"]
        assert jobs[0].metadata["cacheable"] is False


def test_formalmc_missing_installation_does_not_fall_back(lab):
    """Installed VCF cannot satisfy a default FormalMC request."""
    client, _, workspace, body = lab
    (workspace / "run.tcl").write_text("prove\n", encoding="utf-8")
    formal = {**body, "family": "formal", "methodology": "systemverilog", "formal": {"property_sets": ["run.tcl"]}}
    formal.pop("simulation")
    result = client.post("/api/v1/runs/preview", json=formal).json()
    assert result["ready"] is False
    assert any(item["key"] == "tool:formalmc" and item["status"] == "blocked" for item in result["checks"])


@pytest.mark.parametrize("case", ["missing", "traversal", "no_tests", "fsdb", "disk"])
def test_preflight_reports_actionable_blockers(lab, monkeypatch, case):
    """Missing inputs, unsafe paths, missing tests, PLI, and disk prevent readiness."""

    client, _, _, body = lab
    if case == "missing":
        body["design"]["sources"] = ["not-present.sv"]
    elif case == "traversal":
        body["design"]["sources"] = ["../outside.sv"]
    elif case == "no_tests":
        body["simulation"]["tests"] = []
    elif case == "fsdb":
        body["simulation"]["waveform"] = "fsdb"
    else:
        monkeypatch.setattr("ucagent.server.platform_workbench.shutil.disk_usage", lambda _: SimpleNamespace(free=-1))
    response = client.post("/api/v1/runs/preview", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["ready"] is False
    assert any(item["status"] == "blocked" and item["action"] for item in response.json()["checks"])


def test_defaults_keep_parameters_and_distinct_suite_membership():
    """Selecting defaults cannot flatten UT/IT members into an unintended product."""

    project = {"project_id": "p", "config": {"design": {"top": "dut", "parameters": {"WIDTH": 12}}, "workflow": {"family": "simulation", "methodology": "uvm"}, "toolchain": "vcs", "simulation": {"suites": [
        {"name": "unit", "level": "UT", "tests": ["unit_test"], "seeds": [7]},
        {"name": "integration", "level": "IT", "tests": ["integration_test"], "seeds": [23]},
    ]}}}
    defaults = run_defaults(project)
    assert defaults["design"]["parameters"] == {"WIDTH": 12}
    assert defaults["simulation"]["tests"] == ["unit_test"]
    assert defaults["simulation"]["seeds"] == [7]
    assert project["config"]["simulation"]["suites"][1]["tests"] == ["integration_test"]


def test_sby_defaults_are_launchable_without_invented_clock_period():
    """Round-trip a persisted SBY project with null timing fields into the API."""
    project = {"project_id": "p", "config": {"design": {"top": "dut", "sources": ["dut.sv"]}, "toolchain": "bundled_sby", "workflow": {"family": "formal", "methodology": "systemverilog"}, "formal": {"engine": "sby", "clock": {"signal": None, "period_ns": None}, "reset": {"signal": None}}}}
    body = run_defaults(project)
    assert body["formal"]["clock"] == {} and body["formal"]["reset"] == {}
    assert body["formal"]["sby"]["mode"] == "prove"
    RunCreateRequest.model_validate(body)


def test_shutdown_waits_for_cancelled_worker_publication(lab):
    """Release the registry lock before waiting for a cancelled worker to persist evidence."""
    _, runtime, _, _ = lab
    cancel = threading.Event()
    published = threading.Event()

    def finish():
        """Model a worker that must reacquire the runtime lock after cancellation."""
        if cancel.wait(timeout=5):
            with runtime._runtime_lock:
                published.set()

    worker = threading.Thread(target=finish)
    runtime._cancel_events["test"] = cancel
    runtime._threads["test"] = worker
    worker.start()
    runtime.shutdown()
    assert not worker.is_alive() and published.is_set()


def test_summary_uses_real_jobs_and_separates_failure_from_execution_error():
    """A failing test counts as a completed job, while diagnostics preserve tool errors."""

    run = {"result": {"tests": [{"verification_status": "failed"}], "diagnostics": []}}
    jobs = [{"execution_status": "completed", "kind": "vcs"}, {"execution_status": "error", "kind": "vcf", "result": {"diagnostics": [{"error_code": "license_unavailable", "error": "Checkout failed", "next_action": "Probe license"}]}}]
    summary = run_summary(run, jobs)
    assert summary["jobs_finished"] == summary["jobs_total"] == 2
    assert summary["tests_failed"] == 1
    assert summary["tests_passed"] == 0
    assert summary["diagnostic_code"] == "license_unavailable"
