"""Contract tests for the visual platform's versioned HTTP API."""

from __future__ import annotations

from pathlib import Path
import os
import sys
import time

from fastapi.testclient import TestClient
import pytest

from ucagent.eda import CommandSpec, RunRequest, VerificationStatus
from ucagent.server import api_platform
from ucagent.server.api_master import PdbMasterApiServer


class _Config:
    """Supply the minimal configuration interface consumed by the master server."""

    def __init__(self, root: Path) -> None:
        """Remember the only project import root allowed in this test."""

        self.root = root

    def get_value(self, key: str, default=None):
        """Return deterministic launch roots and otherwise preserve defaults."""

        if key == "launch.file_browser_roots":
            return [{"name": "tests", "path": str(self.root)}]
        if key == "platform.toolchains_file":
            return str(self.root / "missing-toolchains.yaml")
        return default


class _FakePicker:
    """Create a harmless Python job while exercising the real JobRunner."""

    def __init__(self, verification_failure: bool = False) -> None:
        """Select whether the deterministic parser should report a DUT failure."""

        self.verification_failure = verification_failure

    def build_export_request(self, **kwargs) -> RunRequest:
        """Return a workspace-scoped request without invoking a shell."""

        text = "UVM_ERROR : 1" if self.verification_failure else "TEST PASSED"
        dut_name = kwargs["dut_name"]
        return RunRequest(
            run_id=kwargs["run_id"],
            workspace=kwargs["workspace"],
            output_dir=kwargs["output_dir"],
            command=CommandSpec(
                argv=[
                    "python",
                    "-c",
                    (
                        "import pathlib,sys; "
                        "pathlib.Path(sys.argv[1]).mkdir(parents=True); "
                        f"print({text!r})"
                    ),
                    f"{{SESSION_DIR}}/{dut_name}",
                ],
                tool="python",
                timeout_seconds=10,
            ),
            input_paths=[kwargs["source"]],
            artifact_paths=[Path(dut_name)],
            parser="uvm",
            test_name="platform_smoke",
            verification_hint=VerificationStatus.PASSED,
            metadata={"adapter": "picker"},
        )


def _create_server(tmp_path: Path) -> PdbMasterApiServer:
    """Create an in-process master server rooted in a temporary directory."""

    server = PdbMasterApiServer(
        workspace=str(tmp_path),
        cfg=_Config(tmp_path),
        password="",
        sock="",
    )
    profile = server._platform_runtime._profiles["local"]
    server._platform_runtime._profiles["local"] = profile.model_copy(
        update={
            "tools": {
                **profile.tools,
                "picker": profile.tools["python"],
                "verilator": profile.tools["python"],
            },
            "minimum_free_bytes": 0,
        }
    )
    return server


def _create_project(client: TestClient, project_root: Path) -> dict:
    """Import one project through the public API and return its response."""

    tests_dir = project_root / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )
    response = client.post(
        "/api/v1/projects",
        json={"name": "Adder", "path": str(project_root)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_workflow_api_previews_explicit_sby_without_changing_default(tmp_path):
    """The desktop catalog can inspect SBY's original-stage workflow without changing saved defaults."""
    server = _create_server(tmp_path)
    with TestClient(server._app) as client:
        response = client.get("/api/v1/workflows?formal_engine=sby")
        assert response.status_code == 200, response.text
        selected = next(item for item in response.json()["items"] if item["id"] == "formal-guided")
        assert selected["name"] == "SBY Guided"
        assert "COI" in selected["stages"][6]["description"]
        default = client.get("/api/v1/workflows").json()
        assert next(item for item in default["items"] if item["id"] == "formal-guided")["name"] == "FormalMC Guided"
        assert client.get("/api/v1/workflows?formal_engine=auto").status_code == 422


def test_default_python_preserves_virtual_environment_symlink(tmp_path, monkeypatch):
    """Child Python jobs must retain the running venv rather than its base interpreter."""

    executable = tmp_path / "venv-python"
    try:
        executable.symlink_to(sys.executable)
    except OSError:
        pytest.skip("The host does not permit executable symlinks.")
    monkeypatch.setattr(sys, "executable", str(executable))
    server = _create_server(tmp_path)
    try:
        profile = server._platform_runtime._profiles["local"]
        assert profile.tools["python"] == os.path.abspath(executable)
        assert profile.tools["python"] != str(executable.resolve())
    finally:
        server._platform_runtime.shutdown()


def _run_body(project_id: str) -> dict:
    """Build the canonical structured UnityTest run request used by API tests."""

    return {
        "project_id": project_id,
        "family": "simulation",
        "methodology": "unitytest",
        "authoring_mode": "guided",
        "toolchain": "local",
        "design": {
            "top": "adder",
            "filelists": [],
            "sources": ["adder.sv"],
            "include_dirs": [],
            "defines": [],
            "parameters": {},
        },
        "simulation": {
            "simulator": "verilator",
            "uvm_version": "1.2",
            "suites": ["UT"],
            "unitytest_tests": ["tests/test_smoke.py"],
            "tests": [],
            "seeds": [1],
            "coverage": [],
            "waveform": "none",
            "plusargs": [],
        },
    }


def _wait_for_terminal(client: TestClient, run_id: str) -> dict:
    """Poll a bounded amount of time for the background runner to finish."""

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["execution_status"] in {"completed", "error", "timeout", "cancelled"}:
            return run
        time.sleep(0.02)
    raise AssertionError("platform run did not reach a terminal state")


def test_catalog_project_csrf_and_disabled_stages(tmp_path):
    """The API exposes full workflow DAGs and rejects cross-origin mutations."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    server = _create_server(tmp_path)
    with TestClient(server._app) as client:
        workflows = client.get("/api/v1/workflows")
        assert workflows.status_code == 200
        items = workflows.json()["items"]
        assert {item["id"] for item in items} >= {"uvm-vcs", "systemverilog-vcs", "formal-guided"}
        assert any(
            stage["enabled"] is False and stage["disabled_reason"]
            for workflow in items
            for stage in workflow["stages"]
        )

        blocked = client.post(
            "/api/v1/projects",
            headers={"Origin": "https://attacker.invalid"},
            json={"name": "Adder", "path": str(project_root)},
        )
        assert blocked.status_code == 403
        assert _create_project(client, project_root)["name"] == "Adder"


def test_run_persists_separate_verification_status_and_range_artifact(tmp_path, monkeypatch):
    """A verification failure completes normally and its evidence supports HTTP Range."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "adder.sv").write_text("module adder; endmodule\n", encoding="utf-8")
    server = _create_server(tmp_path)
    real_get_adapter = api_platform.get_adapter

    def get_adapter(name: str):
        """Replace only Picker while preserving all catalog adapter lookups."""

        return _FakePicker(verification_failure=True) if name == "picker" else real_get_adapter(name)

    monkeypatch.setattr(api_platform, "get_adapter", get_adapter)
    with TestClient(server._app) as client:
        project = _create_project(client, project_root)
        created = client.post("/api/v1/runs", json=_run_body(project["id"]))
        assert created.status_code == 200, created.text
        run = _wait_for_terminal(client, created.json()["id"])
        assert run["execution_status"] == "completed", run
        assert run["verification_status"] == "failed"

        artifacts = client.get(f"/api/v1/runs/{run['id']}/artifacts").json()["items"]
        stdout = next(item for item in artifacts if item["name"] == "stdout.log")
        partial = client.get(
            f"/api/v1/artifacts/{stdout['id']}/download",
            headers={"Range": "bytes=0-2"},
        )
        assert partial.status_code == 206
        assert partial.headers["content-range"].startswith("bytes 0-2/")
        assert len(partial.content) == 3
        assert any(item["name"] == "manifest.json" for item in artifacts)
        invalid_range = client.get(
            f"/api/v1/artifacts/{stdout['id']}/download",
            headers={"Range": "bytes=999999-"},
        )
        assert invalid_range.status_code == 416
        assert invalid_range.headers["content-range"].startswith("bytes */")

        Path(stdout["path"]).write_text("tampered", encoding="utf-8")
        tampered = client.get(f"/api/v1/artifacts/{stdout['id']}/download")
        assert tampered.status_code == 409
        assert "recorded digest" in tampered.json()["detail"]

        jobs = client.get(f"/api/v1/runs/{run['id']}/jobs").json()["items"]
        assert jobs[0]["execution_status"] == "completed"
        assert jobs[0]["attempt"] == 1


def test_project_path_cannot_escape_configured_roots(tmp_path):
    """Server-side project import rejects paths outside the configured allowlist."""

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    server = PdbMasterApiServer(
        workspace=str(allowed),
        cfg=_Config(allowed),
        password="",
        sock="",
    )
    with TestClient(server._app) as client:
        response = client.post(
            "/api/v1/projects",
            json={"name": "Outside", "path": str(outside)},
        )
        assert response.status_code == 400
        assert "outside configured roots" in response.json()["detail"]


def test_vc_formal_generated_inputs_are_content_addressed_across_runs(tmp_path):
    """Keep generated Tcl paths stable so exact-input proof caching can be reused."""

    project_root = tmp_path / "formal-project"
    project_root.mkdir()
    (project_root / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    (project_root / "properties.sv").write_text(
        "assert property (@(posedge clk) 1'b1);\n", encoding="utf-8"
    )
    server = _create_server(tmp_path)
    runtime = server._platform_runtime
    body = api_platform.RunCreateRequest.model_validate(
        {
            "project_id": "unused",
            "family": "formal",
            "methodology": "systemverilog",
            "authoring_mode": "guided",
            "toolchain": "local",
            "design": {
                "top": "dut",
                "filelists": [],
                "sources": ["dut.sv"],
                "include_dirs": [],
                "defines": [],
                "parameters": {},
            },
            "formal": {
                "engine": "vc_formal",
                "property_sets": ["properties.sv"],
                "clock": {"signal": "clk", "period": "10ns"},
                "reset": {"signal": "rst_n", "active": "low"},
                "cex_replay": {"enabled": True, "methodology": "uvm"},
            },
        }
    )
    config = runtime.build_project_config(body)

    first = runtime._build_formal_requests(
        "run-one", project_root, config, Path(".ucagent/platform-runs/run-one")
    )[0]
    second = runtime._build_formal_requests(
        "run-two", project_root, config, Path(".ucagent/platform-runs/run-two")
    )[0]

    assert first.command.argv[-1] == second.command.argv[-1]
    assert first.input_paths == second.input_paths
    assert first.metadata["cacheable"] is True
    generated_filelist = (project_root / first.input_paths[1]).read_text(encoding="utf-8")
    assert project_root.as_posix() in generated_filelist
    assert "dut.sv" in generated_filelist


def test_imported_make_recipe_expands_an_explicit_test_seed_matrix(tmp_path):
    """Build one isolated argv-only job per declared suite, test, and seed."""

    project_root = tmp_path / "imported-uvm"
    (project_root / "rtl").mkdir(parents=True)
    (project_root / "verification").mkdir()
    (project_root / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    (project_root / "verification" / "Makefile").write_text(
        "regression:\n\t@echo placeholder\n", encoding="utf-8"
    )
    server = _create_server(tmp_path)
    runtime = server._platform_runtime
    request = api_platform.RunCreateRequest.model_validate(
        {
            "project_id": "unused",
            "family": "simulation",
            "methodology": "uvm",
            "authoring_mode": "guided",
            "toolchain": "local",
            "design": {
                "top": "tb_top",
                "filelists": [],
                "sources": ["rtl/dut.sv"],
                "include_dirs": ["rtl"],
                "defines": [],
                "parameters": {},
            },
            "simulation": {
                "simulator": "vcs",
                "uvm_version": "1.2",
                "suites": ["UT", "IT"],
                "tests": ["smoke_test", "error_test"],
                "seeds": [7, 9],
                "coverage": ["assert", "line"],
                "waveform": "fsdb",
                "plusargs": [],
            },
        }
    )
    existing = {
        "simulation": {
            "recipe": {
                "kind": "make",
                "makefile": "verification/Makefile",
                "target": "regression",
                "variables": {"MODE": "ci"},
                "test_variable": "TEST",
                "seed_variable": "SEED",
                "output_variable": "RUN_DIR",
                "coverage_variable": "COVERAGE",
                "waveform_variable": "WAVEFORM",
                "artifacts": [],
                "coverage_databases": ["coverage/simv.vdb"],
                "waveform_artifacts": {
                    "fsdb": ["waves.fsdb"],
                    "vpd": ["waves.vpd"],
                },
                "result_logs": ["logs/result.log"],
                "success_markers": ["IMPORTED RUN PASSED"],
            }
        }
    }
    config = runtime.build_project_config(request, existing)

    jobs = runtime._build_run_requests(
        "matrix-run", project_root, config, request, runtime._profiles["local"]
    )

    matrix_jobs = jobs[:-1]
    assert len(jobs) == 9
    assert len({job.output_dir for job in jobs}) == 9
    assert [(job.suite, job.test_name, job.seed) for job in matrix_jobs] == [
        (suite, test, seed)
        for suite in ("UT", "IT")
        for test in ("smoke_test", "error_test")
        for seed in (7, 9)
    ]
    for job in matrix_jobs:
        assert job.command.tool == "make"
        assert "RUN_DIR={SESSION_DIR}" in job.command.argv
        assert f"TEST={job.test_name}" in job.command.argv
        assert f"SEED={job.seed}" in job.command.argv
        assert "COVERAGE=line+assert" in job.command.argv
        assert "WAVEFORM=fsdb" in job.command.argv
        assert job.artifact_paths == [
            Path("coverage/simv.vdb"),
            Path("waves.fsdb"),
            Path("logs/result.log"),
        ]
        assert job.result_paths == [Path("logs/result.log")]
        assert job.success_markers == ["IMPORTED RUN PASSED"]
        assert Path("rtl/dut.sv") in job.input_paths
        assert Path("verification/Makefile") in job.input_paths
    urg = jobs[-1]
    assert urg.command.tool == "urg"
    assert urg.input_paths == [
        Path(f".ucagent/platform-runs/matrix-run/recipe-{index:04d}/coverage/simv.vdb")
        for index in range(1, 9)
    ]

    disabled_body = request.model_copy(
        update={
            "simulation": request.simulation.model_copy(
                update={"coverage": [], "waveform": "none"}
            )
        }
    )
    disabled_config = runtime.build_project_config(disabled_body, existing)
    disabled_jobs = runtime._build_run_requests(
        "disabled-run",
        project_root,
        disabled_config,
        disabled_body,
        runtime._profiles["local"],
    )
    assert len(disabled_jobs) == 8
    for job in disabled_jobs:
        assert "COVERAGE=none" in job.command.argv
        assert "WAVEFORM=none" in job.command.argv
        assert Path("coverage/simv.vdb") not in job.artifact_paths
        assert Path("waves.fsdb") not in job.artifact_paths


def test_imported_make_recipe_rejects_undeclared_ui_capabilities(tmp_path) -> None:
    """Fail before dispatch when imported code cannot honor coverage or waveform selections."""

    runtime = _create_server(tmp_path)._platform_runtime
    body = _run_body("unused")
    body["methodology"] = "uvm"
    body["simulation"]["simulator"] = "vcs"
    body["simulation"]["unitytest_tests"] = []
    body["simulation"]["tests"] = ["smoke_test"]
    body["simulation"]["coverage"] = ["line"]
    body["simulation"]["waveform"] = "none"
    request = api_platform.RunCreateRequest.model_validate(body)
    recipe = {
        "simulation": {
            "recipe": {
                "kind": "make",
                "target": "regression",
                "test_variable": "TEST",
                "seed_variable": "SEED",
                "output_variable": "RUN_DIR",
            }
        }
    }
    with pytest.raises(ValueError, match="does not declare coverage"):
        runtime.build_project_config(request, recipe)

    body["simulation"]["coverage"] = []
    body["simulation"]["waveform"] = "fsdb"
    request = api_platform.RunCreateRequest.model_validate(body)
    with pytest.raises(ValueError, match="does not declare 'fsdb'"):
        runtime.build_project_config(request, recipe)


def test_simulation_request_enforces_methodology_simulator_waveform_matrix() -> None:
    """Reject combinations that would otherwise be silently ignored by an adapter."""

    body = _run_body("project")
    body["simulation"]["simulator"] = "vcs"
    body["simulation"]["waveform"] = "fst"
    with pytest.raises(ValueError, match="waveform"):
        api_platform.RunCreateRequest.model_validate(body)

    body["simulation"]["waveform"] = "fsdb"
    parsed = api_platform.RunCreateRequest.model_validate(body)
    assert parsed.simulation is not None
    assert parsed.simulation.simulator == "vcs"

    body["methodology"] = "uvm"
    body["simulation"]["unitytest_tests"] = []
    body["simulation"]["tests"] = ["smoke_test"]
    body["simulation"]["simulator"] = "verilator"
    with pytest.raises(ValueError, match="require simulation.simulator='vcs'"):
        api_platform.RunCreateRequest.model_validate(body)


def test_unitytest_request_requires_paths_and_builds_test_seed_matrix(tmp_path) -> None:
    """Append one real pytest job per explicit project path and seed after Picker."""

    project_root = tmp_path / "unity-matrix"
    (project_root / "tests").mkdir(parents=True)
    (project_root / "adder.sv").write_text("module adder; endmodule\n", encoding="utf-8")
    for name in ("test_smoke.py", "test_corner.py"):
        (project_root / "tests" / name).write_text(
            f"def {name[:-3]}():\n    assert True\n",
            encoding="utf-8",
        )
    runtime = _create_server(tmp_path)._platform_runtime
    body = _run_body("unused")
    body["simulation"]["unitytest_tests"] = [
        "tests/test_smoke.py",
        "tests/test_corner.py",
    ]
    body["simulation"]["seeds"] = [3, 5]
    request = api_platform.RunCreateRequest.model_validate(body)
    config = runtime.build_project_config(request)

    jobs = runtime._build_run_requests(
        "unity-run", project_root, config, request, runtime._profiles["local"]
    )

    assert len(jobs) == 5
    assert jobs[0].metadata["adapter"] == "picker"
    assert [(job.test_name, job.seed) for job in jobs[1:]] == [
        (test_path, seed)
        for test_path in ("tests/test_smoke.py", "tests/test_corner.py")
        for seed in (3, 5)
    ]
    for job in jobs[1:]:
        assert job.parser == "pytest"
        assert job.command.tool == "python"
        assert Path(".ucagent/platform-runs/unity-run/picker/adder") in job.input_paths
        assert job.command.env["PYTHONPATH"] == (
            "{WORKSPACE}/.ucagent/platform-runs/unity-run/picker"
        )

    body["simulation"]["unitytest_tests"] = []
    with pytest.raises(ValueError, match="explicit simulation.unitytest_tests"):
        api_platform.RunCreateRequest.model_validate(body)
    body["simulation"]["unitytest_tests"] = ["../outside_test.py"]
    with pytest.raises(ValueError, match="project paths"):
        api_platform.RunCreateRequest.model_validate(body)


def test_native_vcs_coverage_seeds_each_run_from_compile_design_vdb(tmp_path) -> None:
    """Link compile, private simulation VDB, and URG inputs through typed paths."""

    project_root = tmp_path / "native-coverage"
    project_root.mkdir()
    (project_root / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    runtime = _create_server(tmp_path)._platform_runtime
    request = api_platform.RunCreateRequest.model_validate(
        {
            "project_id": "unused",
            "family": "simulation",
            "methodology": "systemverilog",
            "authoring_mode": "guided",
            "toolchain": "local",
            "design": {
                "top": "dut",
                "filelists": [],
                "sources": ["dut.sv"],
                "include_dirs": [],
                "defines": [],
                "parameters": {},
            },
            "simulation": {
                "simulator": "vcs",
                "uvm_version": "1.2",
                "unitytest_tests": [],
                "suites": [],
                "tests": [],
                "seeds": [11],
                "coverage": ["line", "assert"],
                "waveform": "none",
                "plusargs": [],
            },
        }
    )
    config = runtime.build_project_config(request)

    compile_job, simulation_job, urg_job = runtime._build_run_requests(
        "coverage-run", project_root, config, request, runtime._profiles["local"]
    )

    compile_vdb = Path(".ucagent/platform-runs/coverage-run/compile/simv.vdb")
    assert Path("simv.vdb") in compile_job.artifact_paths
    assert compile_job.command.argv[compile_job.command.argv.index("-cm_dir") + 1] == (
        "{SESSION_DIR}/simv.vdb"
    )
    assert simulation_job.session_inputs[0].source == compile_vdb
    assert simulation_job.session_inputs[0].destination == Path("simv.vdb")
    assert "-cm_dir" in simulation_job.command.argv
    assert "{SESSION_DIR}/simv.vdb" in simulation_job.command.argv
    assert "{WORKSPACE}/.ucagent/platform-runs/coverage-run/sim-0001/simv.vdb" in (
        urg_job.command.argv
    )


def test_generated_uvm_timescale_is_a_signed_vcs_compile_input(tmp_path) -> None:
    """Apply the validated scaffold timescale so VCS O-2018 accepts a directive-less DUT."""

    project_root = tmp_path / "generated-uvm"
    project_root.mkdir()
    (project_root / "uart_tx.sv").write_text(
        (
            "module uart_tx(input logic clk, input logic rst_n, input logic start, "
            "output logic done); assign done = start; endmodule\n"
        ),
        encoding="utf-8",
    )
    api_platform.generate_uvm_scaffold(
        project_root,
        "uvm",
        api_platform.UvmScaffoldSpec.model_validate(
            {
                "name": "uart",
                "dut_top": "uart_tx",
                "design_sources": ["uart_tx.sv"],
                "signals": [
                    {"name": "start", "direction": "input"},
                    {"name": "done", "direction": "output"},
                ],
                "timescale": "10ns/1ns",
            }
        ),
    )
    runtime = _create_server(tmp_path)._platform_runtime
    request = api_platform.RunCreateRequest.model_validate(
        {
            "project_id": "unused",
            "family": "simulation",
            "methodology": "uvm",
            "authoring_mode": "guided",
            "toolchain": "local",
            "design": {
                "top": "tb_top",
                "filelists": ["uvm/files.f"],
                "sources": [],
                "include_dirs": [],
                "defines": [],
                "parameters": {},
            },
            "simulation": {
                "simulator": "vcs",
                "uvm_version": "1.2",
                "unitytest_tests": [],
                "suites": ["UT"],
                "tests": ["uart_test"],
                "seeds": [11],
                "coverage": [],
                "waveform": "none",
                "plusargs": [],
            },
        }
    )
    config = runtime.build_project_config(request)

    compile_job = runtime._build_run_requests(
        "generated-uvm-run", project_root, config, request, runtime._profiles["local"]
    )[0]

    assert "-timescale=10ns/1ns" in compile_job.command.argv
    assert Path("uvm/.ucagent_uvm_manifest.json") in compile_job.input_paths
    assert compile_job.metadata["timescale"] == "10ns/1ns"


def test_run_stage_snapshot_resolves_enabled_and_disabled_branches(tmp_path):
    """Capture selected Formal engine while preserving the unselected and replay branches."""

    project_root = tmp_path / "formal-stage-project"
    project_root.mkdir()
    (project_root / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    (project_root / "properties.sv").write_text(
        "assert property (@(posedge clk) 1'b1);\n", encoding="utf-8"
    )
    server = _create_server(tmp_path)
    with TestClient(server._app) as client:
        project = _create_project(client, project_root)
        response = client.post(
            "/api/v1/runs",
            json={
                "project_id": project["id"],
                "family": "formal",
                "methodology": "systemverilog",
                "authoring_mode": "guided",
                "toolchain": "local",
                "design": {
                    "top": "dut",
                    "filelists": [],
                    "sources": ["dut.sv"],
                    "include_dirs": [],
                    "defines": [],
                    "parameters": {},
                },
                "formal": {
                    "engine": "vc_formal",
                    "property_sets": ["properties.sv"],
                    "clock": {"signal": "clk", "period": "10ns"},
                    "reset": {"signal": "rst_n", "active": "low"},
                    "cex_replay": {"enabled": True, "methodology": "uvm"},
                },
            },
        )
        assert response.status_code == 200, response.text
        stages = client.get(
            f"/api/v1/runs/{response.json()['id']}/stages"
        ).json()["items"]
        by_name = {stage["name"]: stage for stage in stages}

        assert by_name["vc_formal"]["enabled"] is True
        assert by_name["formal_mc"]["enabled"] is False
        assert "vc_formal" in by_name["formal_mc"]["disabled_reason"]
        assert by_name["counterexample_dynamic_replay"]["enabled"] is False
        assert "falsified" in by_name["counterexample_dynamic_replay"]["disabled_reason"]


def test_run_rejects_contradictory_options_and_mismatched_workflow(tmp_path):
    """Reject ambiguous family payloads and workflow identifiers before dispatch."""

    project_root = tmp_path / "workflow-validation"
    project_root.mkdir()
    (project_root / "adder.sv").write_text("module adder; endmodule\n", encoding="utf-8")
    server = _create_server(tmp_path)
    with TestClient(server._app) as client:
        project = _create_project(client, project_root)
        contradictory = _run_body(project["id"])
        contradictory["formal"] = {
            "engine": "vc_formal",
            "property_sets": [],
            "clock": {},
            "reset": {},
            "cex_replay": {"enabled": False, "methodology": "uvm"},
        }
        assert client.post("/api/v1/runs", json=contradictory).status_code == 422

        mismatched = _run_body(project["id"])
        mismatched["workflow_id"] = "formal-guided"
        response = client.post("/api/v1/runs", json=mismatched)
        assert response.status_code == 400
        assert "does not match" in response.json()["detail"]
        assert client.get("/api/v1/runs").json()["total"] == 0


def test_retry_stage_creates_a_new_auditable_run(tmp_path, monkeypatch):
    """Retry a terminal stage by creating a fresh run instead of mutating old evidence."""

    project_root = tmp_path / "retry-project"
    project_root.mkdir()
    (project_root / "adder.sv").write_text("module adder; endmodule\n", encoding="utf-8")
    server = _create_server(tmp_path)
    real_get_adapter = api_platform.get_adapter

    def get_adapter(name: str):
        """Use a deterministic local Picker job for both original and retry runs."""

        return _FakePicker() if name == "picker" else real_get_adapter(name)

    monkeypatch.setattr(api_platform, "get_adapter", get_adapter)
    with TestClient(server._app) as client:
        project = _create_project(client, project_root)
        original = client.post("/api/v1/runs", json=_run_body(project["id"])).json()
        terminal = _wait_for_terminal(client, original["id"])
        stage = next(item for item in terminal["stages"] if item["enabled"])
        old_status = stage["execution_status"]

        response = client.post(f"/api/v1/stages/{stage['id']}/retry", json={})

        assert response.status_code == 200, response.text
        retry_run = response.json()["retry_run"]
        assert retry_run["id"] != original["id"]
        assert response.json()["execution_status"] == old_status
        retry_terminal = _wait_for_terminal(client, retry_run["id"])
        assert retry_terminal["execution_status"] == "completed", retry_terminal
        old_stage = client.get(f"/api/v1/runs/{original['id']}/stages").json()["items"]
        assert (
            next(item for item in old_stage if item["id"] == stage["id"])["execution_status"]
            == old_status
        )


def test_merge_results_preserves_duplicate_diagnostic_details(tmp_path):
    """Index identical diagnostics from separate jobs without a primary-key collision."""

    runtime = _create_server(tmp_path)._platform_runtime
    diagnostic = {
        "error_code": "license_unavailable",
        "error": "License unavailable.",
        "next_action": "Wait for a license seat and retry.",
    }

    merged = runtime._merge_results(
        "run-id",
        [{"diagnostics": [diagnostic]}, {"diagnostics": [diagnostic]}],
    )

    assert len({item["issue_id"] for item in merged["issues"]}) == 2
    assert all(item["next_action"] == diagnostic["next_action"] for item in merged["issues"])


def test_merge_results_maps_urg_scope_to_declared_functional_requirement(tmp_path):
    """Project exact URG hierarchy prefixes onto FG, FC, and CK coverage targets."""

    runtime = _create_server(tmp_path)._platform_runtime
    project = runtime.store.create_project(
        name="Coverage mapping",
        source_root=str(tmp_path),
        config={
            "simulation": {
                "coverage_mapping": [
                    {
                        "requirement_id": "CK-UART-RESET",
                        "scopes": ["tb_top.dut.uart"],
                        "metrics": ["line"],
                        "target_percent": 95,
                    }
                ]
            }
        },
    )
    run = runtime.store.create_run(
        project_id=project["project_id"],
        workflow="uvm-vcs",
        adapter="vcs",
        request={},
    )

    merged = runtime._merge_results(
        run["run_id"],
        [{"coverage": [{"metric": "line", "percent": 88.5, "scope": "tb_top.dut.uart.tx"}]}],
    )

    assert merged["coverage"] == [
        {
            "metric": "line",
            "percent": 88.5,
            "scope": "tb_top.dut.uart.tx",
            "mapping": "CK-UART-RESET",
            "requirement_id": "CK-UART-RESET",
            "target": 95,
        }
    ]


def test_driver_exception_terminalizes_job_attempt_and_stage(tmp_path, monkeypatch):
    """Leave no queued database records when the execution kernel raises unexpectedly."""

    project_root = tmp_path / "driver-error-project"
    project_root.mkdir()
    (project_root / "adder.sv").write_text("module adder; endmodule\n", encoding="utf-8")
    server = _create_server(tmp_path)
    real_get_adapter = api_platform.get_adapter

    def get_adapter(name: str):
        """Build a valid request before injecting a runner infrastructure failure."""

        return _FakePicker() if name == "picker" else real_get_adapter(name)

    def raise_runner_error(*args, **kwargs):
        """Simulate a process-launch failure below the workflow driver."""

        raise RuntimeError("runner exploded")

    monkeypatch.setattr(api_platform, "get_adapter", get_adapter)
    monkeypatch.setattr(server._platform_runtime._runner, "run", raise_runner_error)
    with TestClient(server._app) as client:
        project = _create_project(client, project_root)
        created = client.post("/api/v1/runs", json=_run_body(project["id"])).json()
        run = _wait_for_terminal(client, created["id"])

        assert run["execution_status"] == "error"
        assert run["verification_status"] == "inconclusive"
        jobs = server._platform_runtime.store.list_jobs(run["id"])
        assert jobs[0]["execution_status"] == "error"
        assert jobs[0]["verification_status"] == "inconclusive"
        assert jobs[0]["attempts"][0]["execution_status"] == "error"
        mapped_stage = next(
            item for item in run["stages"] if item["execution_status"] == "error"
        )
        assert mapped_stage["enabled"] is True
