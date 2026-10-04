"""Evidence and restart contracts for real formal counterexample replay."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from ucagent.eda import CommandSpec, RunRequest, ToolchainProfile
from ucagent.server.api_platform import (
    CounterexampleReplayStartRequest,
    PlatformRuntime,
)


class _Config:
    """Provide one missing profile file so tests can install a local profile."""

    def __init__(self, root: Path) -> None:
        """Remember the isolated test root."""

        self.root = root

    def get_value(self, key: str, default=None):
        """Resolve only configuration values required by PlatformRuntime."""

        if key == "platform.toolchains_file":
            return str(self.root / "missing-toolchains.yaml")
        return default


def _runtime(root: Path) -> PlatformRuntime:
    """Create one offline runtime using the current Python interpreter."""

    server = SimpleNamespace(
        workspace=str(root),
        host="127.0.0.1",
        port=8800,
        cfg=_Config(root),
        _launch_roots=[{"path": str(root)}],
    )
    runtime = PlatformRuntime(server)
    runtime._profiles["local"] = ToolchainProfile(
        id="local",
        tools={"python": sys.executable},
        minimum_free_bytes=0,
    )
    return runtime


def _signed_formal_source(runtime: PlatformRuntime, project_root: Path) -> tuple[str, str]:
    """Run a harmless producer and persist one genuinely signed falsified property."""

    design = project_root / "design.sv"
    design.write_text("module design; endmodule\n", encoding="utf-8")
    project = runtime.store.create_project(
        name="Formal replay",
        source_root=str(project_root),
        config={"simulation": {"uvm_version": "1.2"}},
    )
    source_request = {
        "project_id": project["project_id"],
        "family": "formal",
        "methodology": "systemverilog",
        "authoring_mode": "guided",
        "toolchain": "local",
        "design": {
            "top": "design",
            "filelists": [],
            "sources": ["design.sv"],
            "include_dirs": [],
            "defines": [],
            "parameters": {},
        },
        "formal": {
            "engine": "vc_formal",
            "property_sets": [],
            "clock": {"signal": "clk", "period": "10ns"},
            "reset": {"signal": "rst_n", "active": "low"},
            "cex_replay": {"enabled": True, "methodology": "uvm"},
        },
    }
    source = runtime.store.create_run(
        project_id=project["project_id"],
        workflow="formal-guided",
        adapter="vc_formal",
        request=source_request,
    )
    runtime.store.replace_run_stages(
        source["run_id"],
        [
            {
                "id": "formal-guided:counterexample_dynamic_replay",
                "name": "counterexample_dynamic_replay",
                "enabled": False,
                "disabled_reason": "Waiting for signed falsification evidence.",
            }
        ],
    )
    result = runtime._runner.run(
        RunRequest(
            run_id=f"{source['run_id']}.formal",
            workspace=project_root.resolve(),
            output_dir=Path("runs") / "formal",
            command=CommandSpec(
                argv=[
                    "python",
                    "-c",
                    (
                        "import pathlib; p=pathlib.Path('proof'); p.mkdir(); "
                        "(p/'p_bad.vcd').write_bytes(b'cex-steps'); "
                        "print('p_bad falsified runtime=0.1 depth=4 cex=proof/p_bad.vcd')"
                    ),
                ],
                tool="python",
                cwd=Path("{SESSION_DIR}"),
                timeout_seconds=10,
            ),
            input_paths=[Path("design.sv")],
            artifact_paths=[Path("proof")],
            parser="formal",
            property_set="p_bad",
        ),
        runtime._profiles["local"],
    )
    merged = runtime._merge_results(source["run_id"], [result.model_dump(mode="json")])
    runtime.store.save_run_result(source["run_id"], merged)
    runtime.store.update_run_status(
        source["run_id"],
        execution_status="completed",
        verification_status="failed",
    )
    property_row = runtime.store.list_result_rows(source["run_id"], "properties")[0]
    return source["run_id"], str(property_row["counterexample_artifact_id"])


def test_replay_requires_signed_cex_and_real_failed_child_run(tmp_path: Path, monkeypatch) -> None:
    """Mark reproduced only after a signed dynamic process produces a failed test."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = _runtime(tmp_path / "state")
    source_run_id, cex_artifact_id = _signed_formal_source(runtime, project_root)
    replay_test = project_root / "replay_test.py"
    replay_test.write_text(
        "def test_replays_p_bad():\n    assert 1 == 0, 'observed formal trace mismatch'\n",
        encoding="utf-8",
    )

    def create_completed_dynamic_run(request):
        """Execute pytest through JobRunner and persist its signed failing result."""

        child = runtime.store.create_run(
            project_id=request.project_id,
            workflow="uvm-vcs",
            adapter="vcs",
            request=request.model_dump(mode="json"),
        )
        result = runtime._runner.run(
            RunRequest(
                run_id=f"{child['run_id']}.replay",
                workspace=project_root.resolve(),
                output_dir=Path("runs") / child["run_id"],
                command=CommandSpec(
                    argv=[
                        "python",
                        "-m",
                        "pytest",
                        "{WORKSPACE}/replay_test.py",
                        "-q",
                        "--junitxml={SESSION_DIR}/pytest-results.xml",
                    ],
                    tool="python",
                    cwd=Path("{SESSION_DIR}"),
                    timeout_seconds=30,
                ),
                input_paths=[Path("replay_test.py")],
                artifact_paths=[Path("pytest-results.xml")],
                result_paths=[Path("pytest-results.xml")],
                parser="pytest",
                test_name="p_bad_uvm_replay",
                suite="UT",
                seed=7,
            ),
            runtime._profiles["local"],
        )
        assert result.execution_status.value == "completed"
        assert result.verification_status.value == "failed"
        merged = runtime._merge_results(child["run_id"], [result.model_dump(mode="json")])
        runtime.store.save_run_result(child["run_id"], merged)
        runtime.store.update_run_status(
            child["run_id"],
            execution_status="completed",
            verification_status="failed",
        )
        return runtime.run_public(runtime.store.get_run(child["run_id"]))

    monkeypatch.setattr(runtime, "create_run", create_completed_dynamic_run)
    started = runtime.start_counterexample_replay(
        source_run_id,
        CounterexampleReplayStartRequest(
            property_name="p_bad",
            methodology="uvm",
            uvm_test="p_bad_uvm_replay",
            suite="UT",
            seed=7,
        ),
    )
    reconciled = runtime.reconcile_counterexample_replays(source_run_id)

    assert started["counterexample_artifact_id"] == cex_artifact_id
    assert reconciled["reproduced"] == 1
    replay = reconciled["items"][0]
    assert replay["status"] == "reproduced"
    assert replay["evidence"]["target_manifest_artifact_id"]
    assert replay["evidence"]["target_manifest_sha256"]
    stage = runtime.store.list_run_stages(source_run_id)[0]
    assert stage["enabled"] is True
    assert stage["execution_status"] == "completed"
    assert stage["verification_status"] == "failed"

    reopened = _runtime(tmp_path / "state")
    restored = reopened.reconcile_counterexample_replays(source_run_id)
    assert restored["items"][0]["status"] == "reproduced"
    assert restored["items"][0]["target_run_id"] == started["target_run_id"]

    replay_test.write_text(
        "def test_replays_p_bad():\n    assert True\n",
        encoding="utf-8",
    )
    invalidated = reopened.reconcile_counterexample_replays(source_run_id)
    assert invalidated["items"][0]["status"] == "evidence_invalid"
    invalid_stage = reopened.store.list_run_stages(source_run_id)[0]
    assert invalid_stage["execution_status"] == "error"
    assert invalid_stage["verification_status"] == "inconclusive"


def test_replay_rejects_policy_mismatch_before_starting_child(tmp_path: Path) -> None:
    """Refuse a method not authorized by the immutable formal-run replay policy."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = _runtime(tmp_path / "state")
    source_run_id, _ = _signed_formal_source(runtime, project_root)

    with pytest.raises(ValueError, match="immutable formal source-run policy"):
        runtime.start_counterexample_replay(
            source_run_id,
            CounterexampleReplayStartRequest(
                property_name="p_bad",
                methodology="unitytest",
                unitytest_test="replay_test.py",
                simulator="verilator",
            ),
        )

    assert runtime.store.list_counterexample_replays(source_run_id) == []
