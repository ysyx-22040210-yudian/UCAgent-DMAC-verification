"""Focused persistence tests for the visual verification platform."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from ucagent.server.platform_store import PlatformStore


def _create_run(store: PlatformStore, tmp_path):
    """Create a minimal project and run used by persistence tests."""

    project = store.create_project(
        name="adder",
        source_root=str(tmp_path),
        config={"schema_version": 1, "design": {"top": "tb_top"}},
    )
    return store.create_run(
        project_id=project["project_id"],
        workflow="simulation.uvm.guided",
        adapter="vcs",
        request={"tests": ["smoke"], "seeds": [1]},
    )


def test_store_persists_complete_run_graph(tmp_path):
    """SQLite records keep workflow, stage, job, result, and artifact state."""

    store = PlatformStore(str(tmp_path / "state"))
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    run = _create_run(store, tmp_path)
    run_id = run["run_id"]
    store.save_workflow(
        workflow_id="simulation.uvm.guided",
        family="simulation",
        methodology="uvm",
        authoring_mode="guided",
        definition={"id": "simulation.uvm.guided", "stages": []},
    )
    store.replace_run_stages(
        run_id,
        [
            {"id": "compile", "name": "Compile", "enabled": True},
            {
                "id": "formal",
                "name": "Formal",
                "enabled": False,
                "disabled_reason": "Simulation workflow selected",
            },
        ],
    )
    job_id = store.create_job(
        run_id=run_id,
        stage_id="compile",
        kind="vcs",
        command={"argv": ["vcs", "-full64"]},
    )
    attempt_id = store.create_attempt(
        job_id=job_id,
        number=1,
        execution_status="queued",
    )
    assert store.update_job_status(job_id, execution_status="running")
    assert store.update_attempt(attempt_id, execution_status="running")
    assert store.update_attempt(
        attempt_id,
        execution_status="completed",
        result={"return_code": 0},
        manifest_path="runs/example/manifest.json",
    )
    store.finish_job(
        job_id,
        execution_status="completed",
        verification_status="failed",
        result={"return_code": 0, "assertions": 1},
    )
    store.save_run_result(
        run_id,
        {
            "tests": [
                {
                    "test_name": "uvm_smoke",
                    "suite": "UT",
                    "seed": 1,
                    "execution_status": "completed",
                    "verification_status": "failed",
                    "duration_seconds": 1.25,
                }
            ],
            "coverage": [{"metric": "line", "percent": 87.5}],
            "properties": [
                {
                    "name": "p_ready",
                    "status": "proven",
                    "engine": "vc_formal",
                    "proof_depth": 12,
                    "runtime_seconds": 2.5,
                }
            ],
            "issues": [{"issue_id": "issue-1", "severity": "error", "title": "Mismatch"}],
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "kind": "waveform",
                    "name": "run.fsdb",
                    "path": "runs/example/run.fsdb",
                    "size_bytes": 42,
                    "sha256": "abc",
                }
            ],
        },
    )
    store.update_run_status(
        run_id,
        execution_status="completed",
        verification_status="failed",
    )

    stages = store.list_run_stages(run_id)
    assert [stage["enabled"] for stage in stages] == [True, False]
    assert [stage["execution_status"] for stage in stages] == ["queued", "cancelled"]
    assert [stage["verification_status"] for stage in stages] == ["unknown", "unknown"]
    assert store.update_stage_execution(run_id, "compile", "completed", "failed")
    assert store.update_stage_execution(run_id, "compile", "running", "passed")
    assert store.list_run_stages(run_id)[0]["verification_status"] == "failed"
    assert store.list_jobs(run_id)[0]["attempts"][0]["manifest_path"].endswith("manifest.json")
    test_result = store.list_result_rows(run_id, "tests")[0]
    assert test_result["status"] == "failed"
    assert test_result["duration_s"] == 1.25
    formal_result = store.list_result_rows(run_id, "properties")[0]
    assert formal_result["depth"] == 12
    assert formal_result["duration_s"] == 2.5
    assert store.list_result_rows(run_id, "issues")[0]["record_id"] == "issue-1"
    assert store.list_artifacts(run_id)[0]["artifact_id"] == "artifact-1"
    assert store.get_run(run_id)["execution_status"] == "completed"
    assert store.get_run(run_id)["verification_status"] == "failed"


def test_store_event_cursor_and_restart_recovery(tmp_path):
    """Event cursors survive reopening and active work gets an explicit restart result."""

    state_dir = tmp_path / "state"
    store = PlatformStore(str(state_dir))
    run = _create_run(store, tmp_path)
    store.replace_run_stages(
        run["run_id"],
        [
            {"id": "active", "name": "Active", "enabled": True, "execution_status": "running"},
            {"id": "future", "name": "Future", "enabled": True},
            {"id": "off", "name": "Off", "enabled": False},
        ],
    )
    job_id = store.create_job(
        run_id=run["run_id"],
        kind="vcs",
        command={"argv": ["vcs"]},
    )
    attempt_id = store.create_attempt(
        job_id=job_id,
        number=1,
        execution_status="running",
    )
    store.update_job_status(job_id, execution_status="running")
    first_sequence = store.append_event(run["run_id"], "job.log", {"line": "hello"})

    reopened = PlatformStore(str(state_dir))
    events = reopened.list_events(run["run_id"], after=first_sequence - 1)
    assert events[0]["sequence"] == first_sequence
    assert events[0]["payload"]["line"] == "hello"
    assert reopened.recover_interrupted_runs() == 1
    recovered = reopened.get_run(run["run_id"])
    assert recovered["execution_status"] == "error"
    assert recovered["verification_status"] == "inconclusive"
    assert recovered["diagnostic"]["error_code"] == "service_restarted"
    recovered_job = reopened.list_jobs(run["run_id"])[0]
    assert recovered_job["execution_status"] == "error"
    assert recovered_job["verification_status"] == "inconclusive"
    recovered_attempt = recovered_job["attempts"][0]
    assert recovered_attempt["attempt_id"] == attempt_id
    assert recovered_attempt["execution_status"] == "error"
    recovered_stages = {item["stage_id"]: item for item in reopened.list_run_stages(run["run_id"])}
    assert recovered_stages["active"]["execution_status"] == "error"
    assert recovered_stages["future"]["execution_status"] == "cancelled"
    assert recovered_stages["off"]["verification_status"] == "unknown"
    assert reopened.recover_interrupted_runs() == 0


def test_commit_job_result_rolls_back_job_graph_and_indexes_together(tmp_path):
    """A normalized-index failure must not leave a falsely completed Job or Attempt."""

    store = PlatformStore(str(tmp_path / "state"))
    run = _create_run(store, tmp_path)
    run_id = run["run_id"]
    store.replace_run_stages(
        run_id,
        [{"id": "compile", "name": "Compile", "enabled": True}],
    )
    job_id = store.create_job(
        run_id=run_id,
        stage_id="compile",
        kind="vcs",
        command={"argv": ["vcs"]},
    )
    attempt_id = store.create_attempt(
        job_id=job_id,
        number=1,
        execution_status="queued",
        manifest_path="runs/compile/manifest.json",
    )
    duplicate_artifacts = {
        "tests": [{"test_name": "compile", "verification_status": "passed"}],
        "artifacts": [
            {
                "artifact_id": "same-id",
                "kind": "log",
                "name": "first.log",
                "path": "runs/compile/first.log",
                "size_bytes": 1,
                "sha256": "a" * 64,
            },
            {
                "artifact_id": "same-id",
                "kind": "log",
                "name": "second.log",
                "path": "runs/compile/second.log",
                "size_bytes": 1,
                "sha256": "b" * 64,
            },
        ],
    }

    with pytest.raises(sqlite3.IntegrityError):
        store.commit_job_result(
            run_id=run_id,
            job_id=job_id,
            attempt_id=attempt_id,
            execution_status="completed",
            verification_status="passed",
            result={"return_code": 0},
            manifest_path="runs/compile/manifest.json",
            normalized_result=duplicate_artifacts,
        )

    job = store.list_jobs(run_id)[0]
    assert job["execution_status"] == "queued"
    assert job["attempts"][0]["execution_status"] == "queued"
    assert store.list_run_stages(run_id)[0]["execution_status"] == "queued"
    assert store.get_run(run_id)["result"] is None
    assert store.list_artifacts(run_id) == []
    assert not any(event["event_type"] == "job.persisted" for event in store.list_events(run_id))

    valid_result = {**duplicate_artifacts, "artifacts": duplicate_artifacts["artifacts"][:1]}
    store.commit_job_result(
        run_id=run_id,
        job_id=job_id,
        attempt_id=attempt_id,
        execution_status="completed",
        verification_status="passed",
        result={"return_code": 0},
        manifest_path="runs/compile/manifest.json",
        normalized_result=valid_result,
    )
    committed = store.list_jobs(run_id)[0]
    assert committed["execution_status"] == "completed"
    assert committed["attempts"][0]["execution_status"] == "completed"
    assert store.list_run_stages(run_id)[0]["execution_status"] == "completed"
    assert store.list_artifacts(run_id)[0]["artifact_id"] == "same-id"
    assert sum(
        event["event_type"] == "job.persisted" for event in store.list_events(run_id)
    ) == 1


def test_counterexample_replay_relation_survives_store_restart(tmp_path) -> None:
    """Persist the exact CEX artifact, child run, request, and derived evidence."""

    store = PlatformStore(str(tmp_path / "state"))
    project = store.create_project(name="formal", source_root=str(tmp_path), config={})
    source = store.create_run(
        project_id=project["project_id"],
        workflow="formal-guided",
        adapter="vc_formal",
        request={"family": "formal"},
    )
    target = store.create_run(
        project_id=project["project_id"],
        workflow="uvm-vcs",
        adapter="vcs",
        request={"family": "simulation"},
    )
    cex_path = tmp_path / "p_bad.vcd"
    cex_path.write_bytes(b"signed counterexample")
    store.save_run_result(
        source["run_id"],
        {
            "artifacts": [
                {
                    "artifact_id": "cex-artifact",
                    "kind": "counterexample",
                    "name": cex_path.name,
                    "path": str(cex_path),
                    "size_bytes": cex_path.stat().st_size,
                    "sha256": hashlib.sha256(cex_path.read_bytes()).hexdigest(),
                }
            ]
        },
    )
    replay = store.create_counterexample_replay(
        source_run_id=source["run_id"],
        property_name="p_bad",
        counterexample_artifact_id="cex-artifact",
        target_run_id=target["run_id"],
        methodology="uvm",
        request={"uvm_test": "cex_test", "seed": 7},
    )
    assert store.update_counterexample_replay(
        replay["replay_id"],
        status="reproduced",
        evidence={"target_manifest_artifact_id": "manifest-id"},
    )

    reopened = PlatformStore(str(tmp_path / "state"))
    restored = reopened.list_counterexample_replays(source["run_id"])

    assert len(restored) == 1
    assert restored[0]["property_name"] == "p_bad"
    assert restored[0]["target_run_id"] == target["run_id"]
    assert restored[0]["request"]["seed"] == 7
    assert restored[0]["status"] == "reproduced"
    assert restored[0]["evidence"]["target_manifest_artifact_id"] == "manifest-id"
    assert reopened.replay_source_runs_for_target(target["run_id"]) == [source["run_id"]]
