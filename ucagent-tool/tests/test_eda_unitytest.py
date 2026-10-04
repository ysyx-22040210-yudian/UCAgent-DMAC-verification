"""Focused tests for real Picker-backed UnityTest pytest execution."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from ucagent.eda import (
    CommandSpec,
    ExecutionStatus,
    JobRunner,
    RunRequest,
    ToolchainProfile,
    VerificationStatus,
    get_adapter,
    parse_pytest_log,
)


def _junit(*, failure: bool = False, error: bool = False, skipped: bool = False) -> str:
    """Return a compact pytest-compatible JUnit report for parser tests."""

    child = (
        '<failure message="assertion failed" />'
        if failure
        else '<error message="fixture failed" />'
        if error
        else '<skipped message="not applicable" />'
        if skipped
        else ""
    )
    return f'<testsuites><testsuite><testcase name="case">{child}</testcase></testsuite></testsuites>'


@pytest.mark.parametrize(
    ("return_code", "report", "execution", "verification", "diagnostic"),
    [
        (0, _junit(), ExecutionStatus.COMPLETED, VerificationStatus.PASSED, None),
        (1, _junit(failure=True), ExecutionStatus.COMPLETED, VerificationStatus.FAILED, None),
        (
            1,
            _junit(error=True),
            ExecutionStatus.ERROR,
            VerificationStatus.UNKNOWN,
            "pytest_infrastructure_error",
        ),
        (
            0,
            _junit(skipped=True),
            ExecutionStatus.COMPLETED,
            VerificationStatus.INCONCLUSIVE,
            "pytest_no_tests_collected",
        ),
    ],
)
def test_pytest_parser_separates_process_state_from_verification(
    return_code: int,
    report: str,
    execution: ExecutionStatus,
    verification: VerificationStatus,
    diagnostic: str | None,
) -> None:
    """Treat assertions as DUT failures while retaining infrastructure errors."""

    parsed = parse_pytest_log(report, return_code=return_code, test_name="tests/test_dut.py", seed=7)

    assert parsed.execution_status == execution
    assert parsed.verification_status == verification
    assert parsed.tests[0].seed == 7
    assert (parsed.diagnostics[0]["error_code"] if parsed.diagnostics else None) == diagnostic


def test_pytest_parser_handles_no_collection_and_malformed_reports() -> None:
    """Keep empty selections inconclusive and malformed evidence as an execution error."""

    empty = parse_pytest_log("no tests ran", return_code=5, test_name="tests/empty.py")
    malformed = parse_pytest_log(
        "<testsuites><testcase></testsuites>",
        return_code=1,
        test_name="tests/broken.py",
    )

    assert empty.execution_status == ExecutionStatus.COMPLETED
    assert empty.verification_status == VerificationStatus.INCONCLUSIVE
    assert empty.diagnostics[0]["error_code"] == "pytest_no_tests_collected"
    assert malformed.execution_status == ExecutionStatus.ERROR
    assert malformed.diagnostics[0]["error_code"] == "pytest_report_malformed"


def test_pytest_adapter_uses_only_structured_argv_and_bounded_environment(tmp_path: Path) -> None:
    """Bind one project test and seed to Picker output without a shell command."""

    request = get_adapter("pytest").build_test_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/unity-1"),
        test_path=Path("tests/test_adder.py"),
        picker_output_dir=Path("runs/picker"),
        dut_package=Path("runs/picker/Adder"),
        seed=19,
        waveform="fst",
        dut_name="Adder",
    )

    assert request.command.tool == "python"
    assert request.command.argv[:3] == ["python", "-m", "pytest"]
    assert request.command.argv[-1] == "{WORKSPACE}/tests/test_adder.py"
    assert request.command.env == {
        "PYTHONHASHSEED": "19",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "{WORKSPACE}/runs/picker",
        "UCAGENT_TEST_SEED": "19",
    }
    assert request.input_paths == [Path("tests/test_adder.py"), Path("runs/picker/Adder")]
    assert request.artifact_paths == [Path("pytest-report.xml"), Path("Adder.fst")]
    assert request.parser == "pytest"


def test_job_runner_executes_real_pytest_and_hashes_tests_and_binding(tmp_path: Path) -> None:
    """Execute a real pytest item with Picker output on PYTHONPATH and sign both inputs."""

    workspace = tmp_path.resolve()
    package = workspace / "generated" / "Adder"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("ANSWER = 42\n", encoding="utf-8")
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_adder.py").write_text(
        "import os\n"
        "from Adder import ANSWER\n\n"
        "def test_binding_and_seed():\n"
        "    assert ANSWER == 42\n"
        "    assert os.environ['UCAGENT_TEST_SEED'] == '23'\n",
        encoding="utf-8",
    )
    request = get_adapter("pytest").build_test_request(
        workspace=workspace,
        output_dir=Path("runs/unity-pass"),
        test_path=Path("tests/test_adder.py"),
        picker_output_dir=Path("generated"),
        dut_package=Path("generated/Adder"),
        seed=23,
        run_id="unity-pass",
    )
    profile = ToolchainProfile(
        id="local",
        tools={"python": sys.executable},
        minimum_free_bytes=0,
    )

    result = JobRunner(b"u" * 32).run(request, profile)

    assert result.execution_status == ExecutionStatus.COMPLETED
    assert result.verification_status == VerificationStatus.PASSED
    assert result.tests[0].test_name == "tests/test_adder.py"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["input_hashes"]) == {"generated/Adder", "tests/test_adder.py"}
    assert not (package / "__pycache__").exists()
    assert not (tests_dir / "__pycache__").exists()


def test_job_runner_records_assertion_failure_and_empty_selection(tmp_path: Path) -> None:
    """Publish failed and inconclusive pytest conclusions as completed executions."""

    workspace = tmp_path.resolve()
    package = workspace / "generated" / "Adder"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("\n", encoding="utf-8")
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fail.py").write_text(
        "def test_failure():\n    assert False, 'DUT mismatch'\n",
        encoding="utf-8",
    )
    (tests_dir / "test_empty.py").write_text("VALUE = 1\n", encoding="utf-8")
    profile = ToolchainProfile(
        id="local",
        tools={"python": sys.executable},
        minimum_free_bytes=0,
    )
    adapter = get_adapter("pytest")

    failed = JobRunner(b"f" * 32).run(
        adapter.build_test_request(
            workspace=workspace,
            output_dir=Path("runs/fail"),
            test_path=Path("tests/test_fail.py"),
            picker_output_dir=Path("generated"),
            dut_package=Path("generated/Adder"),
            seed=1,
            run_id="fail",
        ),
        profile,
    )
    empty = JobRunner(b"e" * 32).run(
        adapter.build_test_request(
            workspace=workspace,
            output_dir=Path("runs/empty"),
            test_path=Path("tests/test_empty.py"),
            picker_output_dir=Path("generated"),
            dut_package=Path("generated/Adder"),
            seed=1,
            run_id="empty",
        ),
        profile,
    )

    assert (failed.execution_status, failed.verification_status) == (
        ExecutionStatus.COMPLETED,
        VerificationStatus.FAILED,
    )
    assert (empty.execution_status, empty.verification_status) == (
        ExecutionStatus.COMPLETED,
        VerificationStatus.INCONCLUSIVE,
    )


def test_runner_rejects_unknown_environment_placeholders(tmp_path: Path) -> None:
    """Expand only runner-owned path placeholders in per-command environment values."""

    source = tmp_path / "input.txt"
    source.write_text("stable\n", encoding="utf-8")
    request = RunRequest(
        run_id="bad-placeholder",
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/bad-placeholder"),
        command=CommandSpec(
            argv=["python", "-c", "print('unused')"],
            tool="python",
            env={"PYTHONPATH": "{UNTRUSTED}/module"},
        ),
        input_paths=[Path("input.txt")],
    )
    profile = ToolchainProfile(
        id="local",
        tools={"python": sys.executable},
        minimum_free_bytes=0,
    )

    result = JobRunner(b"p" * 32).run(request, profile)

    assert result.execution_status == ExecutionStatus.ERROR
    assert result.diagnostics[0]["error_code"] == "process_start_error"
    assert "unsupported runner placeholders" in result.diagnostics[0]["error"]
