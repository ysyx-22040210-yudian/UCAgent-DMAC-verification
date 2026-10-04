"""Focused regression tests for normalized platform issues and signed evidence links."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ucagent.server.api_platform import PlatformRuntime
from ucagent.server.platform_store import PlatformStore


def _artifact(
    artifact_id: str,
    path: Path,
    *,
    session_dir: Path,
    kind: str,
    is_directory: bool = False,
) -> dict[str, object]:
    """Build the subset of a signed manifest artifact used by result merging."""

    if is_directory:
        size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        digest = "0" * 64
    else:
        data = path.read_bytes()
        size = len(data)
        digest = hashlib.sha256(data).hexdigest()
    return {
        "id": artifact_id,
        "run_id": "job",
        "path": path.relative_to(session_dir).as_posix(),
        "kind": kind,
        "is_directory": is_directory,
        "size_bytes": size,
        "sha256": digest,
        "media_type": "application/octet-stream",
        "hash_excludes": [],
    }


def _runtime() -> PlatformRuntime:
    """Create a merge-only runtime without initializing unrelated server state."""

    return object.__new__(PlatformRuntime)


def test_failed_test_creates_one_stable_issue_with_signed_job_evidence(tmp_path):
    """Map a completed verification failure to a stable test-and-seed finding."""

    session = tmp_path / "test-session"
    session.mkdir()
    stdout = session / "stdout.log"
    stdout.write_text("UVM_ERROR : 1\n", encoding="utf-8")
    stderr = session / "stderr.log"
    stderr.touch()
    waveform = session / "waves.fsdb"
    waveform.write_bytes(b"fsdb evidence")
    failed = {
        "test_name": "uart_error_test",
        "suite": "UT",
        "seed": 29,
        "execution_status": "completed",
        "verification_status": "failed",
        "error_count": 1,
        "fatal_count": 0,
        "assertion_failures": 2,
        "message": "scoreboard mismatch",
        "log_path": "stdout.log",
    }
    result = {
        "run_id": "run-a.simulate.UT.uart_error_test.29",
        "session_dir": str(session),
        "tests": [failed, dict(failed)],
        "artifacts": [
            _artifact("stdout-id", stdout, session_dir=session, kind="log"),
            _artifact("stderr-id", stderr, session_dir=session, kind="log"),
            _artifact("wave-id", waveform, session_dir=session, kind="waveform"),
        ],
    }

    first = _runtime()._merge_results("parent-run", [result])
    second = _runtime()._merge_results("parent-run", [result])

    assert len(first["tests"]) == 2
    assert len(first["issues"]) == 1
    issue = first["issues"][0]
    assert issue["issue_id"] == second["issues"][0]["issue_id"]
    assert issue["category"] == "test_failure"
    assert issue["test_case"] == "uart_error_test"
    assert issue["suite"] == "UT"
    assert issue["seed"] == 29
    assert issue["execution_status"] == "completed"
    assert issue["verification_status"] == "failed"
    assert issue["evidence_artifact_ids"] == ["stdout-id", "wave-id"]
    assert issue["next_action"]


def test_falsified_property_links_only_an_existing_signed_counterexample(tmp_path):
    """Expose real CEX evidence but never manufacture a CEX identifier for a missing path."""

    session = tmp_path / "formal-session"
    proof = session / "proof"
    proof.mkdir(parents=True)
    counterexample = proof / "p_bad.vcd"
    counterexample.write_bytes(b"real counterexample")
    formal_log = session / "stdout.log"
    formal_log.write_text("p_bad | falsified\n", encoding="utf-8")
    result = {
        "run_id": "run-formal.formal",
        "session_dir": str(session),
        "properties": [
            {
                "name": "p_bad",
                "status": "falsified",
                "engine": "vc_formal",
                "proof_depth": 17,
                "counterexample_path": "proof/p_bad.vcd",
            },
            {
                "name": "p_missing_cex",
                "status": "falsified",
                "engine": "vc_formal",
                "counterexample_path": "proof/not-created.vcd",
            },
            {"name": "p_good", "status": "proven", "engine": "vc_formal"},
        ],
        "artifacts": [
            _artifact("formal-log-id", formal_log, session_dir=session, kind="log"),
            _artifact(
                "proof-directory-id",
                proof,
                session_dir=session,
                kind="proof_directory",
                is_directory=True,
            ),
        ],
    }

    merged = _runtime()._merge_results("parent-formal-run", [result])

    assert len(merged["issues"]) == 2
    by_property = {item["property_name"]: item for item in merged["issues"]}
    actual = by_property["p_bad"]
    assert actual["counterexample_available"] is True
    assert actual["counterexample_path"] == str(counterexample.resolve())
    assert actual["counterexample_artifact_id"] != "proof-directory-id"
    exact_cex = next(
        item
        for item in merged["artifacts"]
        if item.get("artifact_id") == actual["counterexample_artifact_id"]
    )
    assert exact_cex["path"] == str(counterexample.resolve())
    assert exact_cex["sha256"] == hashlib.sha256(counterexample.read_bytes()).hexdigest()
    assert exact_cex["metadata"]["covered_by_artifact_id"] == "proof-directory-id"
    assert actual["evidence_artifact_ids"] == [exact_cex["artifact_id"], "formal-log-id"]
    missing = by_property["p_missing_cex"]
    assert missing["counterexample_available"] is False
    assert missing["counterexample_path"] == "proof/not-created.vcd"
    assert "counterexample_artifact_id" not in missing
    assert missing["evidence_artifact_ids"] == ["formal-log-id"]
    property_rows = {item["name"]: item for item in merged["properties"]}
    assert property_rows["p_bad"]["counterexample_artifact_id"] == exact_cex["artifact_id"]
    assert "counterexample_artifact_id" not in property_rows["p_missing_cex"]


def test_passed_results_create_no_issue_and_duplicate_diagnostics_persist_safely(tmp_path):
    """Keep no-bug runs empty and give identical findings from distinct jobs unique IDs."""

    diagnostic = {
        "error_code": "license_unavailable",
        "error": "License unavailable.",
        "next_action": "Wait for a license seat and retry.",
    }
    no_bug = _runtime()._merge_results(
        "run-no-bug",
        [
            {
                "run_id": "run-no-bug.pass",
                "tests": [
                    {
                        "test_name": "smoke",
                        "execution_status": "completed",
                        "verification_status": "passed",
                    }
                ],
                "properties": [{"name": "p_good", "status": "proven"}],
            }
        ],
    )
    assert no_bug["issues"] == []

    merged = _runtime()._merge_results(
        "run-diagnostics",
        [
            {"run_id": "job-one", "diagnostics": [diagnostic, dict(diagnostic)]},
            {"run_id": "job-two", "diagnostics": [diagnostic]},
        ],
    )
    assert len(merged["issues"]) == 2
    assert len({item["issue_id"] for item in merged["issues"]}) == 2

    store = PlatformStore(str(tmp_path / "state"))
    store.create_project(name="Project", source_root=str(tmp_path), config={}, project_id="project")
    store.create_run(
        project_id="project",
        workflow="simulation-guided",
        adapter="vcs",
        request={},
        run_id="run-diagnostics",
    )
    store.save_run_result("run-diagnostics", merged)
    store.save_run_result("run-diagnostics", merged)
    rows = store.list_result_rows("run-diagnostics", "issues")
    assert len(rows) == 2
    assert {item["next_action"] for item in rows} == {diagnostic["next_action"]}
