"""Focused tests for deterministic UVM 1.2 scaffold generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ucagent.platform import (
    UVM_MANIFEST,
    UvmScaffoldSpec,
    UvmSignal,
    generate_uvm_scaffold,
    validate_uvm_scaffold,
)


def _workspace(tmp_path: Path) -> Path:
    """Create a small user-owned RTL workspace for scaffold tests."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "adder.sv").write_text(
        "module adder(input logic clk, input logic rst_n, "
        "input logic [7:0] a, output logic [7:0] y); assign y = a; endmodule\n",
        encoding="utf-8",
    )
    return tmp_path


def _spec(reference_model: dict | None = None) -> UvmScaffoldSpec:
    """Return explicit DUT metadata without inventing expected behavior."""
    return UvmScaffoldSpec.model_validate(
        {
            "name": "adder",
            "dut_top": "adder",
            "design_sources": ["rtl/adder.sv"],
            "signals": [
                {"name": "a", "direction": "input", "width": 8},
                {"name": "y", "direction": "output", "width": 8},
            ],
            "reference_model": reference_model,
        }
    )


def test_generator_writes_complete_uvm_12_structure(tmp_path: Path) -> None:
    """Generate every required UVM component with deterministic dependency order."""
    workspace = _workspace(tmp_path)
    result = generate_uvm_scaffold(workspace, "verification/uvm", _spec())
    output = workspace / "verification" / "uvm"

    assert result.validation.valid is True
    assert len(result.files) == 15
    expected = {
        "adder_if.sv",
        "adder_item.sv",
        "adder_sequence.sv",
        "adder_sequencer.sv",
        "adder_driver.sv",
        "adder_monitor.sv",
        "adder_agent.sv",
        "adder_scoreboard.sv",
        "adder_coverage.sv",
        "adder_env.sv",
        "adder_test.sv",
        "adder_pkg.sv",
        "tb_top.sv",
        "files.f",
        UVM_MANIFEST,
    }
    assert {path.name for path in output.iterdir()} == expected
    package = (output / "adder_pkg.sv").read_text(encoding="utf-8")
    assert package.index("adder_item.sv") < package.index("adder_driver.sv")
    assert package.index("adder_driver.sv") < package.index("adder_env.sv")
    assert "UVM 1.2" not in package
    scoreboard = (output / "adder_scoreboard.sv").read_text(encoding="utf-8")
    assert "predict" not in scoreboard.casefold()
    assert "golden" not in scoreboard.casefold()
    assert "observed_count" in scoreboard
    tb_top = (output / "tb_top.sv").read_text(encoding="utf-8")
    assert "`ifdef UCAGENT_ENABLE_FSDB" in tb_top
    assert '$value$plusargs("fsdbfile=%s", fsdb_path)' in tb_top
    assert "$fsdbDumpfile(fsdb_path);" in tb_top
    assert "$fsdbDumpvars(0, tb_top);" in tb_top
    assert tb_top.index("`ifdef UCAGENT_ENABLE_FSDB") < tb_top.index("$fsdbDumpfile")
    assert tb_top.index("$fsdbDumpvars") < tb_top.index("`endif")
    manifest = json.loads((output / UVM_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["spec"]["uvm_version"] == "1.2"
    assert manifest["golden_model_generated"] is False
    assert manifest["scoreboard_mode"] == "observational"
    assert manifest["reference_evidence"] == []


def test_validator_detects_placeholders_and_dependency_damage(tmp_path: Path) -> None:
    """Reject unresolved implementation markers and a damaged package order."""
    workspace = _workspace(tmp_path)
    generate_uvm_scaffold(workspace, "verification/uvm", _spec())
    output = workspace / "verification" / "uvm"
    package_path = output / "adder_pkg.sv"
    package = package_path.read_text(encoding="utf-8")
    package = package.replace('  `include "adder_env.sv"\n', "", 1).replace(
        '  `include "adder_item.sv"',
        '  `include "adder_env.sv"\n  // TODO: repair order\n  `include "adder_item.sv"',
    )
    package_path.write_text(package, encoding="utf-8")

    validation = validate_uvm_scaffold(workspace, "verification/uvm")
    codes = {issue.code for issue in validation.errors}
    assert validation.valid is False
    assert "UVM_PLACEHOLDER_FOUND" in codes
    assert "UVM_PACKAGE_DEPENDENCY_ORDER" in codes
    assert any(issue.code == "UVM_GENERATED_FILE_EDITED" for issue in validation.warnings)


def test_reference_model_requires_user_evidence_and_detects_changes(tmp_path: Path) -> None:
    """Bind a declared user model by hash and invalidate stale provenance evidence."""
    workspace = _workspace(tmp_path)
    model_dir = workspace / "model"
    model_dir.mkdir()
    model_path = model_dir / "reference.sv"
    model_path.write_text("class adder_reference; endclass\n", encoding="utf-8")
    spec = _spec(
        {
            "kind": "sv",
            "provenance": "user_provided",
            "sources": ["model/reference.sv"],
        }
    )
    generate_uvm_scaffold(workspace, "verification/uvm", spec)
    filelist = (workspace / "verification" / "uvm" / "files.f").read_text(encoding="utf-8")
    assert "model/reference.sv" in filelist

    model_path.write_text("class changed_reference; endclass\n", encoding="utf-8")
    validation = validate_uvm_scaffold(workspace, "verification/uvm")
    assert validation.valid is False
    assert {issue.code for issue in validation.errors} == {"UVM_REFERENCE_EVIDENCE_CHANGED"}


def test_dpi_reference_inputs_are_declared_in_filelist(tmp_path: Path) -> None:
    """Compile user-provided DPI sources, includes, and libraries without generating behavior."""
    workspace = _workspace(tmp_path)
    model = workspace / "model"
    include = model / "include"
    include.mkdir(parents=True)
    (model / "reference.cc").write_text("int reference(int value) { return value; }\n", encoding="utf-8")
    (model / "libreference.a").write_bytes(b"user supplied archive")
    spec = _spec(
        {
            "kind": "dpi_c",
            "provenance": "user_provided",
            "sources": ["model/reference.cc"],
            "include_dirs": ["model/include"],
            "libraries": ["model/libreference.a"],
        }
    )

    generate_uvm_scaffold(workspace, "verification/uvm", spec)
    filelist = (workspace / "verification" / "uvm" / "files.f").read_text(encoding="utf-8")
    assert "+incdir+../../model/include" in filelist
    assert "../../model/reference.cc" in filelist
    assert "../../model/libreference.a" in filelist


def test_validator_handles_malformed_manifest_evidence(tmp_path: Path) -> None:
    """Return a bounded invalid result rather than crashing on malformed hash evidence."""
    workspace = _workspace(tmp_path)
    generate_uvm_scaffold(workspace, "verification/uvm", _spec())
    manifest_path = workspace / "verification" / "uvm" / UVM_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generated_files"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validation = validate_uvm_scaffold(workspace, "verification/uvm")
    assert validation.valid is False
    assert "UVM_MANIFEST_INVALID" in {issue.code for issue in validation.errors}


def test_validator_rejects_undeclared_prediction_logic(tmp_path: Path) -> None:
    """Do not accept prediction logic when no user-provided model is declared."""
    workspace = _workspace(tmp_path)
    generate_uvm_scaffold(workspace, "verification/uvm", _spec())
    scoreboard = workspace / "verification" / "uvm" / "adder_scoreboard.sv"
    scoreboard.write_text(
        scoreboard.read_text(encoding="utf-8") + "\n// golden prediction inserted without evidence\n",
        encoding="utf-8",
    )

    validation = validate_uvm_scaffold(workspace, "verification/uvm")
    assert validation.valid is False
    assert "UVM_UNDECLARED_REFERENCE_MODEL" in {issue.code for issue in validation.errors}


def test_validator_rejects_missing_design_source(tmp_path: Path) -> None:
    """Treat a missing DUT input as a structural scaffold failure."""
    workspace = _workspace(tmp_path)
    generate_uvm_scaffold(workspace, "verification/uvm", _spec())
    (workspace / "rtl" / "adder.sv").unlink()

    validation = validate_uvm_scaffold(workspace, "verification/uvm")
    assert validation.valid is False
    assert "UVM_DESIGN_SOURCE_MISSING" in {issue.code for issue in validation.errors}


def test_generator_preserves_unmanaged_files_when_overwriting(tmp_path: Path) -> None:
    """Refresh managed sources without deleting user-owned files in the output directory."""
    workspace = _workspace(tmp_path)
    generate_uvm_scaffold(workspace, "verification/uvm", _spec())
    note = workspace / "verification" / "uvm" / "user_notes.md"
    note.write_text("keep me\n", encoding="utf-8")

    result = generate_uvm_scaffold(workspace, "verification/uvm", _spec(), overwrite=True)

    assert result.validation.valid is True
    assert note.read_text(encoding="utf-8") == "keep me\n"


def test_generator_rejects_invalid_ports_and_output_escape(tmp_path: Path) -> None:
    """Reject ambiguous DUT metadata and attempts to publish outside the workspace."""
    workspace = _workspace(tmp_path)
    with pytest.raises(ValidationError, match="at least one DUT output"):
        UvmScaffoldSpec(
            name="adder",
            dut_top="adder",
            design_sources=("rtl/adder.sv",),
            signals=(
                UvmSignal(name="a", direction="input", width=8),
                UvmSignal(name="b", direction="input", width=8),
            ),
        )
    with pytest.raises(ValidationError, match="project paths"):
        generate_uvm_scaffold(workspace, "../outside", _spec())


def test_generator_never_accepts_generated_reference_provenance(tmp_path: Path) -> None:
    """Prevent scaffold generation from presenting an invented model as golden evidence."""
    _workspace(tmp_path)
    with pytest.raises(ValidationError, match="user_provided"):
        _spec(
            {
                "kind": "sv",
                "provenance": "generated",
                "sources": ["model/generated.sv"],
            }
        )
