"""Focused tests for real, structured commercial-license smoke probes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

from ucagent.eda import (
    ExecutionStatus,
    LicenseStatus,
    RunResult,
    ToolchainProfile,
    VerificationStatus,
    build_license_probe_request,
    classify_license_probe,
)
from ucagent.server.api_platform import PlatformRuntime


@pytest.mark.parametrize(
    ("text", "execution", "expected"),
    [
        ("compile completed", ExecutionStatus.COMPLETED, LicenseStatus.AVAILABLE),
        (
            "This software may be used only as authorized in a license agreement.",
            ExecutionStatus.COMPLETED,
            LicenseStatus.AVAILABLE,
        ),
        (
            "Licensed number of users already reached. Waiting for a license.",
            ExecutionStatus.ERROR,
            LicenseStatus.BUSY,
        ),
        (
            "FLEXnet Licensing error: -15, Cannot connect to license server",
            ExecutionStatus.ERROR,
            LicenseStatus.UNAVAILABLE,
        ),
        ("process exited unexpectedly", ExecutionStatus.ERROR, LicenseStatus.UNKNOWN),
        ("no output", ExecutionStatus.TIMEOUT, LicenseStatus.UNKNOWN),
    ],
)
def test_license_classifier_exposes_all_public_states(
    text: str,
    execution: ExecutionStatus,
    expected: LicenseStatus,
) -> None:
    """Separate checked-out seats, contention, outages, and ambiguous failures."""

    assert classify_license_probe(text, execution_status=execution) == expected


def test_license_classifier_honors_structured_runner_diagnostics() -> None:
    """Use explicit diagnostic codes even when a wrapper suppresses its raw message."""

    assert classify_license_probe(
        "",
        execution_status=ExecutionStatus.ERROR,
        diagnostics=[{"error_code": "license_busy"}],
    ) == LicenseStatus.BUSY
    assert classify_license_probe(
        "",
        execution_status=ExecutionStatus.ERROR,
        diagnostics=[{"error_code": "license_unavailable"}],
    ) == LicenseStatus.UNAVAILABLE


def test_builtin_license_smokes_are_isolated_argv_only_requests(tmp_path: Path) -> None:
    """Materialize fixed VCS and FPV sources only in the platform probe namespace."""

    workspace = tmp_path.resolve()
    vcs = build_license_probe_request(
        "vcs",
        workspace=workspace,
        input_dir=Path(".ucagent/platform/toolchain-probes/p/inputs/vcs"),
        output_dir=Path(".ucagent/platform/toolchain-probes/p/license/vcs"),
        run_id="probe.vcs",
        timeout_seconds=45,
    )
    formal = build_license_probe_request(
        "vc_formal",
        workspace=workspace,
        input_dir=Path(".ucagent/platform/toolchain-probes/p/inputs/vcf"),
        output_dir=Path(".ucagent/platform/toolchain-probes/p/license/vcf"),
        run_id="probe.vcf",
        timeout_seconds=45,
    )

    assert vcs is not None and formal is not None
    assert vcs.command.argv[0] == "vcs"
    assert vcs.command.tool == "vcs"
    assert vcs.command.timeout_seconds == 45
    assert vcs.metadata["probe_kind"] == "license_checkout"
    assert vcs.input_paths == [
        Path(".ucagent/platform/toolchain-probes/p/inputs/vcs/vcs_license_probe.sv")
    ]
    assert formal.command.argv[0] == "vcf"
    assert formal.command.tool == "vcf"
    assert formal.command.timeout_seconds == 45
    assert formal.metadata["probe_kind"] == "license_checkout"
    assert {path.name for path in formal.input_paths} == {
        "vcf_license_probe.sv",
        "vcf_license_probe.f",
        "vcf_license_probe.tcl",
    }
    assert (workspace / formal.input_paths[0]).is_file()
    assert not (workspace / "vcs_license_probe.sv").exists()
    assert all(";" not in argument for argument in vcs.command.argv)
    with pytest.raises(ValueError, match="platform/toolchain-probes"):
        build_license_probe_request(
            "vcs",
            workspace=workspace,
            input_dir=Path("project/probe"),
            output_dir=Path("output"),
            run_id="bad",
        )


class _ProbeConfig:
    """Select a missing profile file so a test can inject one typed profile."""

    def __init__(self, root: Path) -> None:
        """Retain the temporary platform root."""

        self.root = root

    def get_value(self, key: str, default=None):
        """Return only the isolated toolchain configuration path."""

        if key == "platform.toolchains_file":
            return str(self.root / "missing-toolchains.yaml")
        return default


class _ProbeServer:
    """Provide the minimal host interface required by PlatformRuntime."""

    def __init__(self, root: Path) -> None:
        """Expose an isolated workspace and HTTP identity."""

        self.workspace = str(root)
        self.cfg = _ProbeConfig(root)
        self._launch_roots = []
        self.host = "127.0.0.1"
        self.port = 8800


def test_platform_probe_runs_version_and_real_license_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist per-tool and aggregate license states without leaking configured values."""

    runtime = PlatformRuntime(_ProbeServer(tmp_path))
    profile = ToolchainProfile(
        id="commercial",
        tools={"vcs": sys.executable, "vcf": sys.executable},
        environment={"SNPSLMD_LICENSE_FILE": "27000@secret-license-host"},
        license_environment_names=["SNPSLMD_LICENSE_FILE"],
        minimum_free_bytes=0,
    )
    runtime._profiles = {profile.id: profile}
    log_index = 0

    def fake_run(request, selected_profile):
        """Return signed-run-shaped results for version, busy, and available probes."""

        nonlocal log_index
        assert selected_profile is profile
        log_index += 1
        log_dir = tmp_path / "fake-results" / str(log_index)
        log_dir.mkdir(parents=True)
        kind = request.metadata["probe_kind"]
        if kind == "version":
            output = (
                f"{request.command.tool} O-2018.09\n"
                "SNPSLMD_LICENSE_FILE=27000@secret-license-host\n"
            )
            execution = ExecutionStatus.COMPLETED
            verification = VerificationStatus.PASSED
        elif request.command.tool == "vcs":
            output = "Licensed number of users already reached; waiting for a license.\n"
            execution = ExecutionStatus.ERROR
            verification = VerificationStatus.UNKNOWN
        else:
            output = "formal license checkout and proof completed\n"
            execution = ExecutionStatus.COMPLETED
            verification = VerificationStatus.PASSED
        stdout = log_dir / "stdout.log"
        stdout.write_text(output, encoding="utf-8")
        now = datetime.now(timezone.utc)
        return RunResult(
            run_id=request.run_id,
            execution_status=execution,
            verification_status=verification,
            return_code=0 if execution == ExecutionStatus.COMPLETED else 1,
            started_at=now,
            completed_at=now,
            stdout_log=stdout,
        )

    monkeypatch.setattr(runtime._runner, "run", fake_run)

    result = runtime.probe_toolchain("commercial")

    assert result["status"] == "degraded"
    assert result["license_status"] == "busy"
    by_name = {item["name"]: item for item in result["capabilities"]}
    assert by_name["vcs"]["binary_available"] is True
    assert by_name["vcs"]["version_probe_status"] == "completed"
    assert by_name["vcs"]["license_status"] == "busy"
    assert by_name["vcs"]["available"] is False
    assert by_name["vcf"]["license_status"] == "available"
    assert by_name["vcf"]["available"] is True
    assert "secret-license-host" not in json.dumps(result)
