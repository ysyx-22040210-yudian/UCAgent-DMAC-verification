"""Regression tests for the visual platform's non-secret runtime snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from ucagent.util.config import load_runtime_config, save_platform_runtime_config


def _project_config() -> dict[str, object]:
    """Return the smallest canonical project mapping used by snapshot tests."""

    return {
        "schema_version": 1,
        "design": {
            "top": "tb_top",
            "filelists": [],
            "sources": ["rtl/dut.sv"],
            "include_dirs": [],
            "defines": [],
            "parameters": {},
        },
        "workflow": {
            "family": "simulation",
            "methodology": "systemverilog",
            "authoring_mode": "guided",
        },
        "toolchain": "synopsys_o2018",
        "simulation": {
            "uvm_version": "1.2",
            "reference_model": None,
        },
    }


def test_platform_snapshot_records_resolved_paths_without_license_values(tmp_path: Path) -> None:
    """Persist project/run/tool aliases while retaining only license variable names."""

    (tmp_path / "rtl").mkdir()
    snapshot_path = save_platform_runtime_config(
        str(tmp_path),
        dut="tb_top",
        output_dir=".ucagent/platform-runs/run-1",
        run_id="run-1",
        project_config=_project_config(),
        toolchain={
            "id": "synopsys_o2018",
            "tools": {"vcs": "/opt/synopsys/bin/vcs"},
            "versions": {"vcs": "O-2018.09-SP2"},
            "max_concurrency": 2,
            "minimum_free_bytes": 10 * 1024**3,
            "license_environment_names": ["SNPSLMD_LICENSE_FILE"],
            "fsdb_pli": {
                "table": str((tmp_path / "host" / "novas.tab").resolve()),
                "library": str((tmp_path / "host" / "pli.a").resolve()),
                "runtime_library_dirs": [
                    str((tmp_path / "host" / "lib").resolve())
                ],
            },
        },
    )

    assert snapshot_path == tmp_path / ".ucagent" / "runtime_config.json"
    snapshot = load_runtime_config(str(tmp_path))
    platform = snapshot["verification_platform"]
    assert platform["workspace"] == str(tmp_path.resolve())
    assert platform["output_dir"] == ".ucagent/platform-runs/run-1"
    assert platform["toolchain"]["license_environment_names"] == [
        "SNPSLMD_LICENSE_FILE"
    ]
    assert "environment" not in platform["toolchain"]
    assert platform["toolchain"]["fsdb_pli"]["table"].endswith("novas.tab")


@pytest.mark.parametrize(
    ("project", "toolchain"),
    [
        (
            {**_project_config(), "api_key": "must-not-persist"},
            {"id": "local", "tools": {"python": "python"}},
        ),
        (
            _project_config(),
            {
                "id": "local",
                "tools": {"python": "python"},
                "environment": {"TOKEN": "must-not-persist"},
            },
        ),
    ],
)
def test_platform_snapshot_rejects_secret_bearing_inputs(
    tmp_path: Path,
    project: dict[str, object],
    toolchain: dict[str, object],
) -> None:
    """Refuse snapshots that could persist project or toolchain credentials."""

    with pytest.raises(ValueError, match="forbidden"):
        save_platform_runtime_config(
            str(tmp_path),
            dut="tb_top",
            output_dir=".ucagent/platform-runs/run-1",
            run_id="run-1",
            project_config=project,
            toolchain=toolchain,
        )
