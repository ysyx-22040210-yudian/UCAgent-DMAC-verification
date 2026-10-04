"""End-to-end tests for argv execution, events, cancellation, and signed evidence."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import threading
import time

import pytest

from ucagent.eda import (
    CommandSpec,
    ExecutionStatus,
    JobRunner,
    ManifestVerificationError,
    RunRequest,
    SessionInput,
    ToolchainProfile,
    VerificationStatus,
    WorkflowDriver,
    verify_manifest,
)


def _profile(**overrides: object) -> ToolchainProfile:
    """Create a fake profile whose only executable is the current Python runtime."""

    values: dict[str, object] = {
        "id": "fake",
        "tools": {"python": sys.executable},
        "minimum_free_bytes": 0,
    }
    values.update(overrides)
    return ToolchainProfile(**values)


def _request(workspace: Path, run_id: str, code: str, **overrides: object) -> RunRequest:
    """Create a bounded fake-tool request suitable for runner integration tests."""

    values: dict[str, object] = {
        "run_id": run_id,
        "workspace": workspace.resolve(),
        "output_dir": Path("runs") / run_id,
        "command": CommandSpec(argv=["python", "-u", "-c", code], tool="python", timeout_seconds=5),
        "input_paths": [Path("rtl.sv")],
    }
    values.update(overrides)
    return RunRequest(**values)


def test_runner_streams_redacted_ndjson_and_verifies_manifest(tmp_path: Path) -> None:
    """Run a fake UVM tool, collect an artifact, and validate its signed evidence."""

    (tmp_path / "rtl.sv").write_text("module rtl; endmodule\n", encoding="utf-8")
    code = (
        "import os,sys,pathlib;"
        "print(os.environ['API_TOKEN']);"
        "print('UVM Report Summary\\nUVM_ERROR : 0\\nUVM_FATAL : 0');"
        "pathlib.Path(sys.argv[1]).write_text('{\"ok\":true}')"
    )
    request = _request(
        tmp_path,
        "pass",
        code,
        command=CommandSpec(
            argv=["python", "-u", "-c", code, "{SESSION_DIR}/result.json"],
            tool="python",
            env={"API_TOKEN": "top-secret-value"},
            timeout_seconds=5,
        ),
        parser="uvm",
        test_name="smoke",
        artifact_paths=[Path("result.json")],
    )
    received: list[dict[str, object]] = []
    result = JobRunner(b"test-signing-key").run(request, _profile(), on_event=received.append)
    assert result.execution_status == ExecutionStatus.COMPLETED
    assert result.verification_status == VerificationStatus.PASSED
    assert result.session_dir == tmp_path / "runs" / "pass"
    assert result.manifest_path is not None
    manifest = verify_manifest(result.manifest_path, b"test-signing-key", workspace=tmp_path)
    assert manifest["input_fingerprint"]
    assert {entry["path"] for entry in manifest["artifacts"]} >= {
        "events.ndjson",
        "stdout.log",
        "stderr.log",
        "result.json",
    }
    all_text = (result.stdout_log.read_text(encoding="utf-8") + result.manifest_path.read_text(encoding="utf-8"))
    assert "top-secret-value" not in all_text
    assert "<redacted>" in result.stdout_log.read_text(encoding="utf-8")
    persisted = [json.loads(line) for line in result.events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["sequence"] for event in persisted] == list(range(1, len(persisted) + 1))
    assert received[0]["type"] == "queued"
    assert received[-1]["type"] == "finished"
    assert not list((tmp_path / "runs").glob("*.tmp"))


def test_missing_input_returns_signed_execution_error(tmp_path: Path) -> None:
    """Preserve a structured failed attempt when a declared input does not exist."""

    request = _request(tmp_path, "missing-input", "print('must not run')")
    result = JobRunner(b"key").run(request, _profile())
    assert result.execution_status == ExecutionStatus.ERROR
    assert result.return_code is None
    assert result.diagnostics[0]["error_code"] == "process_start_error"
    assert result.manifest_path is not None
    verify_manifest(result.manifest_path, b"key", verify_files=True)


def test_missing_tool_alias_returns_signed_execution_error(tmp_path: Path) -> None:
    """Turn an incomplete administrator profile into recoverable run evidence."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    request = _request(tmp_path, "missing-tool", "print('must not run')")
    result = JobRunner(b"key").run(
        request,
        ToolchainProfile(id="incomplete", tools={"other": "other"}, minimum_free_bytes=0),
    )
    assert result.execution_status == ExecutionStatus.ERROR
    assert result.return_code is None
    assert result.diagnostics[0]["error_code"] == "process_start_error"
    assert "tool alias 'python' is not configured" in result.diagnostics[0]["error"]
    verify_manifest(result.manifest_path, b"key", workspace=tmp_path)


def test_missing_declared_output_is_an_execution_error_and_not_cached(tmp_path: Path) -> None:
    """Refuse to accept or cache a successful exit that omitted required evidence."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    request = _request(
        tmp_path,
        "missing-output",
        "print('completed without output')",
        artifact_paths=[Path("simv")],
        metadata={"cacheable": True},
    )
    result = JobRunner(b"key").run(request, _profile())
    assert result.execution_status == ExecutionStatus.ERROR
    assert result.diagnostics[-1]["error_code"] == "missing_declared_artifact"
    assert not list((tmp_path / ".ucagent" / "eda-cache").rglob("*.json"))


def test_manifest_detects_artifact_and_signature_tampering(tmp_path: Path) -> None:
    """Reject modified artifacts as well as direct edits to the signed JSON payload."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    code = "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('original')"
    request = _request(
        tmp_path,
        "tamper",
        code,
        command=CommandSpec(
            argv=["python", "-c", code, "{SESSION_DIR}/proof.db"],
            tool="python",
            timeout_seconds=5,
        ),
        artifact_paths=[Path("proof.db")],
    )
    result = JobRunner(b"key").run(request, _profile())
    (result.session_dir / "proof.db").write_text("modified", encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="artifact hash mismatch"):
        verify_manifest(result.manifest_path, b"key")
    data = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    data["return_code"] = 99
    result.manifest_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="signature mismatch"):
        verify_manifest(result.manifest_path, b"key", verify_files=False)


def test_directory_artifact_is_one_tree_hash_and_detects_nested_tampering(tmp_path: Path) -> None:
    """Represent a VDB directory once while authenticating every nested file."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    code = (
        "import pathlib,sys;"
        "root=pathlib.Path(sys.argv[1]);root.mkdir();"
        "(root/'a.dat').write_text('a');(root/'b.dat').write_text('bb')"
    )
    request = _request(
        tmp_path,
        "directory-artifact",
        code,
        command=CommandSpec(
            argv=["python", "-c", code, "{SESSION_DIR}/simv.vdb"],
            tool="python",
            timeout_seconds=5,
        ),
        artifact_paths=[Path("simv.vdb")],
    )
    result = JobRunner(b"key").run(request, _profile())
    directory_records = [item for item in result.artifacts if item.path == Path("simv.vdb")]
    assert len(directory_records) == 1
    assert directory_records[0].is_directory is True
    assert directory_records[0].kind == "coverage_database"
    assert directory_records[0].size_bytes == 3
    assert all(item.path not in {Path("simv.vdb/a.dat"), Path("simv.vdb/b.dat")} for item in result.artifacts)
    verify_manifest(result.manifest_path, b"key")
    (result.session_dir / "simv.vdb" / "a.dat").write_text("changed", encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="artifact hash mismatch"):
        verify_manifest(result.manifest_path, b"key")


def test_runner_seeds_private_session_input_without_modifying_signed_source(tmp_path: Path) -> None:
    """Copy a compile VDB into one run, mutate only the private copy, and sign both roles."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    compile_vdb = tmp_path / ".ucagent" / "platform-runs" / "compile" / "simv.vdb"
    compile_vdb.mkdir(parents=True)
    source_file = compile_vdb / "design.dat"
    source_file.write_text("compiled-design", encoding="utf-8")
    code = (
        "import pathlib,sys;"
        "vdb=pathlib.Path(sys.argv[1]);"
        "assert (vdb/'design.dat').read_text() == 'compiled-design';"
        "(vdb/'runtime.dat').write_text('seed-17');"
        "print('TEST PASSED')"
    )
    request = _request(
        tmp_path,
        "session-input",
        code,
        command=CommandSpec(
            argv=["python", "-c", code, "{SESSION_DIR}/simv.vdb"],
            tool="python",
            timeout_seconds=5,
        ),
        session_inputs=[
            SessionInput(
                source=Path(".ucagent/platform-runs/compile/simv.vdb"),
                destination=Path("simv.vdb"),
            )
        ],
        artifact_paths=[Path("simv.vdb")],
        parser="uvm",
    )

    result = JobRunner(b"session-key").run(request, _profile())

    assert result.execution_status == ExecutionStatus.COMPLETED
    assert result.verification_status == VerificationStatus.PASSED
    assert source_file.read_text(encoding="utf-8") == "compiled-design"
    assert not (compile_vdb / "runtime.dat").exists()
    assert (result.session_dir / "simv.vdb" / "runtime.dat").read_text(encoding="utf-8") == "seed-17"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert ".ucagent/platform-runs/compile/simv.vdb" in manifest["input_hashes"]
    assert manifest["session_inputs"] == [
        {
            "source": ".ucagent/platform-runs/compile/simv.vdb",
            "destination": "simv.vdb",
        }
    ]
    verify_manifest(result.manifest_path, b"session-key", workspace=tmp_path)


def test_runner_rejects_missing_and_mismatched_session_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail before process launch when a seed is absent or its private copy is stale."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    missing = _request(
        tmp_path,
        "missing-session-input",
        "raise SystemExit('must not execute')",
        session_inputs=[
            SessionInput(source=Path("compile/missing.vdb"), destination=Path("simv.vdb"))
        ],
    )

    missing_result = JobRunner(b"missing-key").run(missing, _profile())

    assert missing_result.execution_status == ExecutionStatus.ERROR
    assert missing_result.return_code is None
    assert missing_result.diagnostics[0]["error_code"] == "session_input_missing"

    source = tmp_path / "compile" / "simv.vdb"
    source.mkdir(parents=True)
    (source / "design.dat").write_text("current", encoding="utf-8")
    real_copytree = shutil.copytree

    def corrupt_copy(source_path, destination_path, *args, **kwargs):
        """Copy normally, then model a stale or corrupted staged directory."""

        result = real_copytree(source_path, destination_path, *args, **kwargs)
        (Path(destination_path) / "design.dat").write_text("stale", encoding="utf-8")
        return result

    monkeypatch.setattr("ucagent.eda.runner.shutil.copytree", corrupt_copy)
    mismatched = _request(
        tmp_path,
        "mismatched-session-input",
        "raise SystemExit('must not execute')",
        session_inputs=[
            SessionInput(source=Path("compile/simv.vdb"), destination=Path("simv.vdb"))
        ],
    )

    mismatched_result = JobRunner(b"mismatch-key").run(mismatched, _profile())

    assert mismatched_result.execution_status == ExecutionStatus.ERROR
    assert mismatched_result.return_code is None
    assert mismatched_result.diagnostics[0]["error_code"] == "session_input_copy_mismatch"


def test_session_input_mapping_is_part_of_the_signed_fingerprint(tmp_path: Path) -> None:
    """Prevent cache or evidence reuse when only the private destination contract changes."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    source = tmp_path / "compile" / "simv.vdb"
    source.mkdir(parents=True)
    (source / "design.dat").write_text("design", encoding="utf-8")
    runner = JobRunner(b"fingerprint-key")
    first = runner.run(
        _request(
            tmp_path,
            "mapping-a",
            "print('done')",
            session_inputs=[
                SessionInput(source=Path("compile/simv.vdb"), destination=Path("simv.vdb"))
            ],
        ),
        _profile(),
    )
    second = runner.run(
        _request(
            tmp_path,
            "mapping-b",
            "print('done')",
            session_inputs=[
                SessionInput(
                    source=Path("compile/simv.vdb"),
                    destination=Path("coverage/simv.vdb"),
                )
            ],
        ),
        _profile(),
    )
    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))

    assert first_manifest["input_hashes"] == second_manifest["input_hashes"]
    assert first_manifest["input_fingerprint"] != second_manifest["input_fingerprint"]


def test_result_report_is_redacted_parsed_and_signed(tmp_path: Path) -> None:
    """Parse a tool-owned report file when stdout is empty and remove embedded secrets."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    code = (
        "import os,pathlib,sys;"
        "pathlib.Path(sys.argv[1]).write_text("
        "'token='+os.environ['API_TOKEN']+'\\nInfo-P016: property A_SAFE is TRUE\\n')"
    )
    request = _request(
        tmp_path,
        "formal-report",
        code,
        command=CommandSpec(
            argv=["python", "-c", code, "{SESSION_DIR}/console.log"],
            tool="python",
            env={"API_TOKEN": "formal-secret"},
            timeout_seconds=5,
        ),
        parser="formal",
        result_paths=[Path("console.log")],
        artifact_paths=[Path("console.log")],
        metadata={"engine": "vc_formal"},
    )
    result = JobRunner(b"key").run(request, _profile())
    assert result.verification_status == VerificationStatus.PASSED
    assert result.properties[0].name == "A_SAFE"
    assert result.properties[0].engine == "vc_formal"
    report = (result.session_dir / "console.log").read_text(encoding="utf-8")
    assert "formal-secret" not in report
    assert "<redacted>" in report
    manifest = verify_manifest(result.manifest_path, b"key", workspace=tmp_path)
    assert manifest["properties"][0]["name"] == "A_SAFE"


def test_input_fingerprint_ignores_unique_session_directory(tmp_path: Path) -> None:
    """Allow exact-input cache reuse across otherwise identical run identifiers."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    code = "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('same')"
    manifests: list[dict[str, object]] = []
    for run_id in ("fingerprint-a", "fingerprint-b"):
        request = _request(
            tmp_path,
            run_id,
            code,
            command=CommandSpec(
                argv=["python", "-c", code, "{SESSION_DIR}/output.txt"],
                tool="python",
                timeout_seconds=5,
            ),
            artifact_paths=[Path("output.txt")],
        )
        result = JobRunner(b"key").run(request, _profile())
        manifests.append(verify_manifest(result.manifest_path, b"key", workspace=tmp_path))
    assert manifests[0]["input_fingerprint"] == manifests[1]["input_fingerprint"]


def test_broad_directory_input_excludes_runner_owned_state(tmp_path: Path) -> None:
    """Keep a root include directory stable while still detecting design changes."""

    source = tmp_path / "rtl.sv"
    source.write_text("rtl", encoding="utf-8")
    code = "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('compiled')"
    runner = JobRunner(b"root-input-key")
    manifests = []
    for run_id in ("root-input-source", "root-input-consumer"):
        request = _request(
            tmp_path,
            run_id,
            code,
            command=CommandSpec(
                argv=["python", "-c", code, "{SESSION_DIR}/compiled.bin"],
                tool="python",
                timeout_seconds=5,
            ),
            input_paths=[Path(".")],
            artifact_paths=[Path("compiled.bin")],
            metadata={"cacheable": True, "phase": "compile"},
        )
        result = runner.run(request, _profile())
        manifests.append(verify_manifest(result.manifest_path, b"root-input-key", workspace=tmp_path))
    assert manifests[0]["cache_hit"] is False
    assert manifests[1]["cache_hit"] is True
    assert manifests[0]["input_fingerprint"] == manifests[1]["input_fingerprint"]
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="input hash mismatch"):
        verify_manifest(
            tmp_path / "runs" / "root-input-consumer" / "manifest.json",
            b"root-input-key",
            workspace=tmp_path,
        )


def test_cacheable_exact_input_restores_artifacts_without_running_tool(tmp_path: Path) -> None:
    """Reuse only a verified fingerprint and sign a distinct cache-hit manifest."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    code = (
        "import pathlib,sys;counter=pathlib.Path(sys.argv[1]);"
        "count=int(counter.read_text()) if counter.exists() else 0;"
        "counter.write_text(str(count+1));pathlib.Path(sys.argv[2]).write_text('compiled')"
    )
    runner = JobRunner(b"cache-key")
    manifests = []
    for run_id in ("cache-source", "cache-consumer"):
        request = _request(
            tmp_path,
            run_id,
            code,
            command=CommandSpec(
                argv=[
                    "python",
                    "-c",
                    code,
                    "{WORKSPACE}/execution-count.txt",
                    "{SESSION_DIR}/compiled.bin",
                ],
                tool="python",
                timeout_seconds=5,
            ),
            artifact_paths=[Path("compiled.bin")],
            metadata={"cacheable": True, "phase": "compile"},
        )
        result = runner.run(request, _profile())
        assert (result.session_dir / "compiled.bin").read_text(encoding="utf-8") == "compiled"
        manifests.append(verify_manifest(result.manifest_path, b"cache-key", workspace=tmp_path))
    assert (tmp_path / "execution-count.txt").read_text(encoding="utf-8") == "1"
    assert manifests[0]["cache_hit"] is False
    assert manifests[1]["cache_hit"] is True
    assert manifests[1]["source_manifest"].endswith("cache-source/manifest.json")


def test_cache_rejects_tampered_source_and_executes_fresh_tool(tmp_path: Path) -> None:
    """Fall back to execution when a cached artifact no longer matches its signed hash."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    code = (
        "import pathlib,sys;counter=pathlib.Path(sys.argv[1]);"
        "count=int(counter.read_text()) if counter.exists() else 0;"
        "counter.write_text(str(count+1));pathlib.Path(sys.argv[2]).write_text('compiled')"
    )
    runner = JobRunner(b"cache-key")

    def request_for(run_id: str) -> RunRequest:
        """Build two requests whose logical command and inputs have the same fingerprint."""

        return _request(
            tmp_path,
            run_id,
            code,
            command=CommandSpec(
                argv=[
                    "python",
                    "-c",
                    code,
                    "{WORKSPACE}/execution-count.txt",
                    "{SESSION_DIR}/compiled.bin",
                ],
                tool="python",
                timeout_seconds=5,
            ),
            artifact_paths=[Path("compiled.bin")],
            metadata={"cacheable": True, "phase": "compile"},
        )

    source = runner.run(request_for("tampered-cache-source"), _profile())
    (source.session_dir / "compiled.bin").write_text("tampered", encoding="utf-8")
    fresh = runner.run(request_for("tampered-cache-fresh"), _profile())
    manifest = verify_manifest(fresh.manifest_path, b"cache-key", workspace=tmp_path)
    assert manifest["cache_hit"] is False
    assert (tmp_path / "execution-count.txt").read_text(encoding="utf-8") == "2"


def test_runner_timeout_terminates_process_and_preserves_terminal_evidence(tmp_path: Path) -> None:
    """Time out a fake tool, terminate it, and publish the partial logs atomically."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    request = _request(
        tmp_path,
        "timeout",
        "import time;print('started',flush=True);time.sleep(30)",
        command=CommandSpec(
            argv=["python", "-u", "-c", "import time;print('started',flush=True);time.sleep(30)"],
            tool="python",
            timeout_seconds=0.2,
        ),
    )
    result = JobRunner(b"key").run(request, _profile())
    assert result.execution_status == ExecutionStatus.TIMEOUT
    assert result.verification_status == VerificationStatus.UNKNOWN
    assert result.session_dir is not None
    assert result.diagnostics[0]["error_code"] == "timeout"
    verify_manifest(result.manifest_path, b"key", workspace=tmp_path)


def test_timeout_terminates_descendant_processes(tmp_path: Path) -> None:
    """Kill a spawned child so it cannot mutate workspace state after timeout returns."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    child_code = "import pathlib,sys,time;time.sleep(1);pathlib.Path(sys.argv[1]).write_text('survived')"
    parent_code = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{child_code!r},sys.argv[1]]);"
        "print('child-started',flush=True);time.sleep(30)"
    )
    request = _request(
        tmp_path,
        "process-tree",
        parent_code,
        command=CommandSpec(
            argv=["python", "-u", "-c", parent_code, "{WORKSPACE}/child-survived.txt"],
            tool="python",
            timeout_seconds=0.4,
        ),
    )
    result = JobRunner(b"key").run(request, _profile())
    assert result.execution_status == ExecutionStatus.TIMEOUT
    time.sleep(1.0)
    assert not (tmp_path / "child-survived.txt").exists()


def test_runner_honors_cancel_signal_and_disk_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancel a running process tree and reject jobs below the configured disk threshold."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    cancel = threading.Event()
    cancel.set()
    cancelled = JobRunner(b"key").run(
        _request(tmp_path, "cancel", "import time;time.sleep(30)"),
        _profile(),
        cancel_event=cancel,
    )
    assert cancelled.execution_status == ExecutionStatus.CANCELLED

    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage._replace(free=1))
    gated = JobRunner(b"key").run(
        _request(tmp_path, "disk", "print('never')"),
        _profile(minimum_free_bytes=2),
    )
    assert gated.execution_status == ExecutionStatus.ERROR
    assert gated.session_dir is None
    assert gated.diagnostics[0]["error_code"] == "insufficient_disk_space"


def test_runner_rejects_setup_scripts_without_sourcing_them(tmp_path: Path) -> None:
    """Require explicit administrator-materialized environment instead of hidden shell execution."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    result = JobRunner(b"key").run(
        _request(tmp_path, "setup", "print('never')"),
        _profile(setup_scripts=[Path("/eda/setup.sh")]),
    )
    assert result.execution_status == ExecutionStatus.ERROR
    assert result.diagnostics[0]["error_code"] == "setup_script_not_materialized"
    assert not (tmp_path / "runs" / "setup").exists()


def test_runner_requires_an_existing_absolute_eda_temporary_directory(tmp_path: Path) -> None:
    """Fail before launch when the administrator configured an unusable scratch path."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    profile = _profile(environment={"TMPDIR": str(tmp_path / "missing-scratch")})
    result = JobRunner(b"key").run(
        _request(tmp_path, "bad-tmpdir", "print('never')"),
        profile,
    )

    assert result.execution_status == ExecutionStatus.ERROR
    assert result.diagnostics[0]["error_code"] == "temporary_directory_unavailable"
    assert not (tmp_path / "runs" / "bad-tmpdir").exists()


def test_profile_concurrency_serializes_license_consumers(tmp_path: Path) -> None:
    """Keep two jobs sharing a one-seat profile from running concurrently."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    runner = JobRunner(b"key")
    profile = _profile(max_concurrency=1)
    first_running = threading.Event()
    results: dict[str, object] = {}

    def first_callback(event: dict[str, object]) -> None:
        """Signal once the first fake license consumer owns the slot."""

        if event["type"] == "running":
            first_running.set()

    def run_first() -> None:
        """Run a long-enough first job to expose semaphore overlap."""

        results["first"] = runner.run(
            _request(tmp_path, "license-first", "import time;time.sleep(0.6)"),
            profile,
            on_event=first_callback,
        )

    worker = threading.Thread(target=run_first)
    worker.start()
    assert first_running.wait(timeout=2)
    started = time.monotonic()
    second = runner.run(_request(tmp_path, "license-second", "print('second')"), profile)
    elapsed = time.monotonic() - started
    worker.join(timeout=2)
    assert second.execution_status == ExecutionStatus.COMPLETED
    assert elapsed >= 0.3
    assert results["first"].execution_status == ExecutionStatus.COMPLETED


def test_runner_rejects_inputs_changed_during_execution(tmp_path: Path) -> None:
    """Mark evidence invalid when a source changes after its initial fingerprint."""

    source = tmp_path / "rtl.sv"
    source.write_text("before", encoding="utf-8")
    running = threading.Event()
    holder: dict[str, object] = {}

    def on_event(event: dict[str, object]) -> None:
        """Signal once initial input hashes have been captured and the process starts."""

        if event["type"] == "running":
            running.set()

    def execute() -> None:
        """Run a fake simulator long enough for a controlled source mutation."""

        holder["result"] = JobRunner(b"key").run(
            _request(tmp_path, "input-drift", "import time;time.sleep(0.4)"),
            _profile(),
            on_event=on_event,
        )

    worker = threading.Thread(target=execute)
    worker.start()
    assert running.wait(timeout=2)
    source.write_text("after", encoding="utf-8")
    worker.join(timeout=2)
    result = holder["result"]
    assert result.execution_status == ExecutionStatus.ERROR
    assert result.verification_status == VerificationStatus.UNKNOWN
    assert result.diagnostics[-1]["error_code"] == "inputs_changed_during_run"
    with pytest.raises(ManifestVerificationError, match="input hash mismatch"):
        verify_manifest(result.manifest_path, b"key", workspace=tmp_path)


def test_workflow_driver_continues_verification_failures_and_aggregates_worst_status(tmp_path: Path) -> None:
    """Continue a regression after a DUT failure while preserving its failed conclusion."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    failed = _request(
        tmp_path,
        "failed-test",
        "print('UVM Report Summary\\nUVM_ERROR : 1\\nUVM_FATAL : 0')",
        parser="uvm",
        test_name="bad",
    )
    passed = _request(
        tmp_path,
        "passed-test",
        "print('UVM Report Summary\\nUVM_ERROR : 0\\nUVM_FATAL : 0')",
        parser="uvm",
        test_name="good",
    )
    events: list[dict[str, object]] = []
    result = WorkflowDriver(JobRunner(b"key")).run([failed, passed], _profile(), on_event=events.append)
    assert len(result.jobs) == 2
    assert result.execution_status == ExecutionStatus.COMPLETED
    assert result.verification_status == VerificationStatus.FAILED
    assert {event["job_index"] for event in events} == {0, 1}
    with pytest.raises(ValueError, match="at least one"):
        WorkflowDriver(JobRunner(b"key")).run([], _profile())


def test_workflow_driver_publishes_each_job_before_starting_its_successor(tmp_path: Path) -> None:
    """Invoke the persistence callback before a later workflow Job can run."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    order: list[str] = []
    first = _request(
        tmp_path,
        "atomic-first",
        "print('UVM Report Summary\\nUVM_ERROR : 0\\nUVM_FATAL : 0')",
        parser="uvm",
        test_name="first",
    )
    second = _request(
        tmp_path,
        "atomic-second",
        "print('UVM Report Summary\\nUVM_ERROR : 0\\nUVM_FATAL : 0')",
        parser="uvm",
        test_name="second",
    )

    def on_event(event: dict[str, object]) -> None:
        """Record only process-start events to compare with publication order."""

        if event["type"] == "running":
            order.append(f"run-{event['job_index']}")

    def on_job_result(index: int, request: RunRequest, result: object) -> None:
        """Model the durable store callback and require already-published evidence."""

        assert request.run_id == ("atomic-first" if index == 0 else "atomic-second")
        assert result.manifest_path.is_file()
        order.append(f"persist-{index}")

    result = WorkflowDriver(JobRunner(b"key")).run(
        [first, second],
        _profile(),
        on_event=on_event,
        on_job_result=on_job_result,
    )

    assert result.execution_status == ExecutionStatus.COMPLETED
    assert order == ["run-0", "persist-0", "run-1", "persist-1"]


def test_workflow_driver_marks_partial_pass_as_inconclusive(tmp_path: Path) -> None:
    """Do not preserve an earlier pass when a later required job times out."""

    (tmp_path / "rtl.sv").write_text("rtl", encoding="utf-8")
    passed = _request(
        tmp_path,
        "partial-pass",
        "print('UVM Report Summary\\nUVM_ERROR : 0\\nUVM_FATAL : 0')",
        parser="uvm",
        test_name="good",
    )
    timed_out = _request(
        tmp_path,
        "partial-timeout",
        "import time;time.sleep(5)",
        command=CommandSpec(
            argv=["python", "-c", "import time;time.sleep(5)"],
            tool="python",
            timeout_seconds=0.1,
        ),
    )

    result = WorkflowDriver(JobRunner(b"key")).run([passed, timed_out], _profile())

    assert result.execution_status == ExecutionStatus.TIMEOUT
    assert result.verification_status == VerificationStatus.INCONCLUSIVE
