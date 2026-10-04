"""Restart-recovery tests for atomically persisted platform Jobs."""

from __future__ import annotations

from pathlib import Path
import sys

from ucagent.eda import CommandSpec, RunRequest
from ucagent.server.api_platform import PlatformRuntime


class _Config:
    """Supply the minimal resolved configuration required by PlatformRuntime."""

    def __init__(self, root: Path) -> None:
        """Keep platform state and any optional toolchain file below the test root."""

        self.root = root

    def get_value(self, key: str, default=None):
        """Return a missing toolchain path so the local Python profile is selected."""

        if key == "platform.toolchains_file":
            return str(self.root / "missing-toolchains.yaml")
        if key == "launch.file_browser_roots":
            return [{"name": "tests", "path": str(self.root)}]
        return default


class _Server:
    """Provide the small master-server surface consumed by PlatformRuntime."""

    def __init__(self, root: Path) -> None:
        """Expose deterministic workspace, bind, and configuration values."""

        self.workspace = str(root)
        self.host = "127.0.0.1"
        self.port = 8800
        self.cfg = _Config(root)
        self._launch_roots = [{"name": "tests", "path": str(root)}]


def _create_runtime(root: Path) -> PlatformRuntime:
    """Create an offline runtime whose only required executable is Python."""

    runtime = PlatformRuntime(_Server(root))
    profile = runtime._profiles["local"]
    runtime._profiles["local"] = profile.model_copy(
        update={
            "tools": {**profile.tools, "python": sys.executable},
            "minimum_free_bytes": 0,
        }
    )
    return runtime


def _create_active_run(runtime: PlatformRuntime, project_root: Path) -> tuple[str, str, str]:
    """Persist one completed compile and one interrupted seed Job."""

    store = runtime.store
    project = store.create_project(
        name="Restart recovery",
        source_root=str(project_root),
        config={"schema_version": 1, "design": {"top": "rtl"}},
    )
    run = store.create_run(
        project_id=project["project_id"],
        workflow="simulation.uvm.guided",
        adapter="vcs",
        request={"tests": ["smoke"], "seeds": [1, 2]},
    )
    run_id = run["run_id"]
    store.replace_run_stages(
        run_id,
        [
            {"id": "simulation", "name": "Simulation", "enabled": True},
            {
                "id": "preflight",
                "name": "preflight",
                "parent_id": "simulation",
                "enabled": True,
            },
            {
                "id": "compile",
                "name": "Compile",
                "parent_id": "simulation",
                "enabled": True,
            },
            {
                "id": "regression",
                "name": "Regression",
                "parent_id": "simulation",
                "enabled": True,
            },
            {
                "id": "signoff",
                "name": "signoff",
                "parent_id": "simulation",
                "enabled": True,
            },
        ],
    )
    store.update_run_status(run_id, execution_status="running")

    compile_request = RunRequest(
        run_id=f"{run_id}.compile",
        workspace=project_root.resolve(),
        output_dir=Path(".ucagent") / "platform-runs" / run_id / "compile",
        command=CommandSpec(
            argv=[
                "python",
                "-c",
                "print('UVM Report Summary\\nUVM_ERROR : 0\\nUVM_FATAL : 0')",
            ],
            tool="python",
            timeout_seconds=10,
        ),
        input_paths=[Path("rtl.sv")],
        parser="uvm",
        test_name="compile_smoke",
        metadata={"phase": "compile"},
    )
    compile_job = store.create_job(
        run_id=run_id,
        stage_id="compile",
        kind="python",
        command={
            **compile_request.command.model_dump(mode="json"),
            "job_run_id": compile_request.run_id,
            "output_dir": str(compile_request.output_dir),
        },
    )
    compile_attempt = store.create_attempt(
        job_id=compile_job,
        number=1,
        execution_status="running",
        manifest_path=str(
            (project_root / compile_request.output_dir / "manifest.json").resolve()
        ),
    )
    store.update_job_status(compile_job, execution_status="running")
    compile_result = runtime._runner.run(
        compile_request,
        runtime._profiles["local"],
    )
    compile_data = compile_result.model_dump(mode="json")
    store.commit_job_result(
        run_id=run_id,
        job_id=compile_job,
        attempt_id=compile_attempt,
        execution_status=compile_result.execution_status.value,
        verification_status=compile_result.verification_status.value,
        result=compile_data,
        manifest_path=str(compile_result.manifest_path),
        normalized_result=runtime._merge_results(run_id, [compile_data]),
    )

    seed_output = Path(".ucagent") / "platform-runs" / run_id / "seed-0002"
    seed_job = store.create_job(
        run_id=run_id,
        stage_id="regression",
        kind="python",
        command={
            "argv": ["python", "-c", "print('seed 2')"],
            "tool": "python",
            "job_run_id": f"{run_id}.seed.2",
            "output_dir": str(seed_output),
        },
    )
    store.create_attempt(
        job_id=seed_job,
        number=1,
        execution_status="running",
        manifest_path=str((project_root / seed_output / "manifest.json").resolve()),
    )
    store.update_job_status(seed_job, execution_status="running")
    store.update_stage_execution(run_id, "compile", "completed", "passed")
    store.update_stage_execution(run_id, "regression", "running")
    runtime._refresh_group_stages(run_id)
    return run_id, compile_job, seed_job


def test_restart_keeps_valid_completed_job_and_marks_only_unfinished_work_retryable(
    tmp_path: Path,
) -> None:
    """Retain a signed compile while terminalizing an interrupted seed after restart."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "rtl.sv").write_text("module rtl; endmodule\n", encoding="utf-8")
    runtime = _create_runtime(tmp_path)
    run_id, compile_job_id, seed_job_id = _create_active_run(runtime, project_root)
    last_live_cursor = runtime.store.append_event(
        run_id,
        "stdout",
        {"job_id": seed_job_id, "message": "seed 2 started"},
    )

    reopened = _create_runtime(tmp_path)
    recovered_run = reopened.store.get_run(run_id)
    assert recovered_run["execution_status"] == "error"
    assert recovered_run["verification_status"] == "inconclusive"
    assert recovered_run["diagnostic"]["error_code"] == "service_restarted"
    assert recovered_run["diagnostic"]["retryable"] is True

    jobs = {job["job_id"]: job for job in reopened.store.list_jobs(run_id)}
    compile_job = jobs[compile_job_id]
    assert compile_job["execution_status"] == "completed"
    assert compile_job["verification_status"] == "passed"
    assert compile_job["attempts"][0]["execution_status"] == "completed"
    assert Path(compile_job["attempts"][0]["manifest_path"]).is_file()
    seed_job = jobs[seed_job_id]
    assert seed_job["execution_status"] == "error"
    assert seed_job["verification_status"] == "inconclusive"
    assert seed_job["result"]["retryable"] is True
    assert seed_job["result"]["diagnostics"][0]["error_code"] == "recovery_manifest_invalid"
    assert seed_job["attempts"][0]["execution_status"] == "error"

    stages = {
        stage["stage_id"]: stage for stage in reopened.store.list_run_stages(run_id)
    }
    assert stages["compile"]["execution_status"] == "completed"
    assert stages["compile"]["verification_status"] == "passed"
    assert stages["regression"]["execution_status"] == "error"
    assert stages["preflight"]["execution_status"] == "completed"
    assert stages["preflight"]["verification_status"] == "passed"
    assert stages["signoff"]["execution_status"] == "error"
    assert stages["signoff"]["verification_status"] == "inconclusive"
    assert stages["simulation"]["execution_status"] == "error"
    assert {artifact["name"] for artifact in reopened.store.list_artifacts(run_id)} >= {
        "manifest.json",
        "stdout.log",
    }

    recovery_events = reopened.store.list_events(run_id, after=last_live_cursor)
    assert recovery_events
    assert [event["sequence"] for event in recovery_events] == sorted(
        event["sequence"] for event in recovery_events
    )
    assert {event["event_type"] for event in recovery_events} >= {
        "job.evidence_invalid",
        "run.recovered",
    }
    assert reopened.store.list_events(run_id, after=last_live_cursor - 1)[0]["payload"][
        "message"
    ] == "seed 2 started"

    event_count = len(reopened.store.list_events(run_id))
    reopened_again = _create_runtime(tmp_path)
    assert len(reopened_again.store.list_events(run_id)) == event_count
    assert {
        job["job_id"]: job["execution_status"]
        for job in reopened_again.store.list_jobs(run_id)
    } == {compile_job_id: "completed", seed_job_id: "error"}


def test_restart_rejects_completed_job_when_signed_inputs_changed(tmp_path: Path) -> None:
    """Invalidate a previously completed Job if its signed RTL input is stale."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    source = project_root / "rtl.sv"
    source.write_text("module rtl; endmodule\n", encoding="utf-8")
    runtime = _create_runtime(tmp_path)
    run_id, compile_job_id, _ = _create_active_run(runtime, project_root)
    source.write_text("module rtl; wire changed; endmodule\n", encoding="utf-8")

    reopened = _create_runtime(tmp_path)
    jobs = {job["job_id"]: job for job in reopened.store.list_jobs(run_id)}
    compile_job = jobs[compile_job_id]
    assert compile_job["execution_status"] == "error"
    assert compile_job["verification_status"] == "inconclusive"
    assert compile_job["result"]["retryable"] is True
    diagnostic = compile_job["result"]["diagnostics"][0]
    assert diagnostic["error_code"] == "recovery_manifest_invalid"
    assert "input hash mismatch" in diagnostic["observed"]
    assert reopened.store.list_artifacts(run_id) == []
