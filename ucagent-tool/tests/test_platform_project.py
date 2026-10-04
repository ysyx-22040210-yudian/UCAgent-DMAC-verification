"""Focused tests for the canonical visual-platform project configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ucagent.platform import (
    ExecutableRecipe,
    MakeRecipe,
    ProjectConfig,
    load_project_config,
    parse_recipe,
    parse_reference_model,
    save_project_config,
)


def _project_payload() -> dict:
    """Return a minimal canonical project payload used by focused tests."""
    return {
        "schema_version": 1,
        "design": {
            "top": "tb_top",
            "filelists": ["rtl/files.f"],
            "sources": ["rtl/dut.sv"],
            "include_dirs": ["rtl/include"],
            "defines": ["SYNOPSYS", "WIDTH=8"],
            "parameters": {"WIDTH": 8},
        },
        "workflow": {
            "family": "simulation",
            "methodology": "uvm",
            "authoring_mode": "guided",
        },
        "toolchain": "synopsys_o2018",
        "simulation": {
            "uvm_version": "1.2",
            "simulator": "vcs",
            "recipe": {"kind": "native"},
            "suites": [{"name": "smoke", "level": "UT", "tests": ["smoke_test"]}],
            "seeds": [1, 2],
            "coverage": ["line", "assert"],
            "coverage_mapping": [
                {
                    "requirement_id": "FG-UART",
                    "scopes": ["tb_top.dut"],
                    "metrics": ["line", "assert"],
                    "target_percent": 95,
                }
            ],
            "waveform": "fsdb",
        },
        "formal": {
            "engine": "vc_formal",
            "property_sets": ["formal/properties.sva"],
            "clock": {},
            "reset": {},
            "cex_replay": {"enabled": True, "methodology": "uvm"},
        },
    }


def _make_recipe_payload(**updates: object) -> dict:
    """Return the complete current imported-Make recipe contract."""

    payload: dict[str, object] = {
        "kind": "make",
        "makefile": "verification/Makefile",
        "target": "regression",
        "variables": {"MODE": "nightly"},
        "test_variable": "TEST",
        "seed_variable": "SEED",
        "output_variable": "RUN_DIR",
        "coverage_variable": "COVERAGE",
        "waveform_variable": "WAVEFORM",
        "artifacts": ["logs/compiler.log"],
        "coverage_databases": ["coverage/simv.vdb"],
        "waveform_artifacts": {
            "fsdb": ["waves.fsdb"],
            "vpd": ["waves.vpd"],
        },
        "result_logs": ["logs/simulation.log"],
        "success_markers": ["PROJECT TEST PASSED"],
    }
    payload.update(updates)
    return payload


def test_project_config_round_trip_is_canonical_and_non_secret(tmp_path: Path) -> None:
    """Save and load the strict schema without widening its public contract."""
    config = ProjectConfig.model_validate(_project_payload())
    path = save_project_config(tmp_path, config)

    assert path == tmp_path / ".ucagent" / "project.yaml"
    loaded = load_project_config(tmp_path)
    assert loaded == config
    text = path.read_text(encoding="utf-8")
    assert "schema_version: 1" in text
    assert "authoring_mode: guided" in text
    assert "simulator: vcs" in text
    assert "requirement_id: FG-UART" in text
    assert "linuxserver" not in text


def test_coverage_mapping_rejects_noncanonical_tags_and_patterns() -> None:
    """Keep requirement mapping deterministic and bound to FG, FC, or CK tags."""

    payload = _project_payload()
    payload["simulation"]["coverage_mapping"][0]["requirement_id"] = "REQ-UART"
    with pytest.raises(ValidationError, match="FG-, FC-, or CK-"):
        ProjectConfig.model_validate(payload)

    payload = _project_payload()
    payload["simulation"]["coverage_mapping"][0]["scopes"] = ["tb_top.*"]
    with pytest.raises(ValidationError, match="exact hierarchy prefixes"):
        ProjectConfig.model_validate(payload)


def test_simulation_simulator_is_explicit_and_defaults_to_verilator() -> None:
    """Accept only supported Picker backends and default new projects to Verilator."""

    payload = _project_payload()
    payload["workflow"]["methodology"] = "unitytest"
    payload["simulation"]["unitytest_tests"] = ["unity_test/tests/test_smoke.py"]
    payload["simulation"]["waveform"] = "fst"
    del payload["simulation"]["simulator"]
    assert ProjectConfig.model_validate(payload).simulation.simulator == "verilator"

    payload["simulation"]["simulator"] = "vcs"
    payload["simulation"]["waveform"] = "fsdb"
    assert ProjectConfig.model_validate(payload).simulation.simulator == "vcs"

    payload["simulation"]["simulator"] = "iverilog"
    with pytest.raises(ValidationError, match="simulator"):
        ProjectConfig.model_validate(payload)


def test_unitytest_paths_are_canonical_and_unique() -> None:
    """Store only concrete project-relative pytest inputs in project.yaml."""

    payload = _project_payload()
    payload["workflow"]["methodology"] = "unitytest"
    payload["simulation"]["simulator"] = "verilator"
    payload["simulation"]["waveform"] = "none"
    payload["simulation"]["unitytest_tests"] = [
        "unity_test/tests/test_smoke.py",
        "unity_test/tests/test_corner.py",
    ]

    config = ProjectConfig.model_validate(payload)

    assert config.simulation.unitytest_tests == (
        "unity_test/tests/test_smoke.py",
        "unity_test/tests/test_corner.py",
    )
    payload["simulation"]["unitytest_tests"] = ["tests/test_smoke.py"] * 2
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        ProjectConfig.model_validate(payload)
    payload["simulation"]["unitytest_tests"] = ["../outside.py"]
    with pytest.raises(ValidationError, match="project paths"):
        ProjectConfig.model_validate(payload)


def test_project_rejects_simulator_and_waveform_mismatches() -> None:
    """Prevent a project file from selecting combinations ignored by its adapters."""

    payload = _project_payload()
    payload["simulation"]["simulator"] = "verilator"
    with pytest.raises(ValidationError, match="require simulation.simulator='vcs'"):
        ProjectConfig.model_validate(payload)

    payload["workflow"]["methodology"] = "unitytest"
    payload["simulation"]["simulator"] = "vcs"
    payload["simulation"]["waveform"] = "vcd"
    with pytest.raises(ValidationError, match="waveform"):
        ProjectConfig.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sources", ["../outside.sv"]),
        ("filelists", ["C:\\outside.f"]),
        ("include_dirs", ["/absolute/include"]),
        ("sources", ["rtl/*.sv"]),
        ("sources", ["-f"]),
        ("sources", ["rtl/-override.sv"]),
        ("sources", ["rtl/bad\nsource.sv"]),
        ("sources", ["rtl/bad\u0085source.sv"]),
        ("sources", ['rtl/"quoted".sv']),
        ("sources", ["rtl/'quoted'.sv"]),
    ],
)
def test_project_config_rejects_non_concrete_or_escaping_paths(field: str, value: list[str]) -> None:
    """Reject path traversal, absolute paths, and ambiguous source globs."""
    payload = _project_payload()
    payload["design"][field] = value

    with pytest.raises(ValidationError, match="project paths"):
        ProjectConfig.model_validate(payload)


def test_project_config_rejects_raw_shell_and_extra_fields() -> None:
    """Only typed recipes are accepted; arbitrary shell strings are never part of the schema."""
    payload = _project_payload()
    payload["simulation"]["recipe"] = {"kind": "native", "command": "vcs; rm -rf output"}

    with pytest.raises(ValidationError, match="command"):
        ProjectConfig.model_validate(payload)

    with pytest.raises(ValidationError, match="unsafe executable argument"):
        parse_recipe(
            {
                "kind": "executable",
                "executable": "scripts/run_vcs.py",
                "arguments": ["--test=smoke;echo injected"],
            }
        )


def test_typed_imported_recipes_expose_only_declared_values() -> None:
    """Validate Make and executable recipes as argument-vector declarations."""
    make = parse_recipe(
        _make_recipe_payload()
    )
    executable = parse_recipe(
        {
            "kind": "executable",
            "executable": "scripts/run.py",
            "arguments": ["--suite", "UT"],
        }
    )

    assert isinstance(make, MakeRecipe)
    assert make.target == "regression"
    assert make.test_variable == "TEST"
    assert make.coverage_variable == "COVERAGE"
    assert make.coverage_databases == ("coverage/simv.vdb",)
    assert make.waveform_variable == "WAVEFORM"
    assert make.waveform_artifacts["fsdb"] == ("waves.fsdb",)
    assert make.result_logs == ("logs/simulation.log",)
    assert isinstance(executable, ExecutableRecipe)
    assert executable.arguments == ("--suite", "UT")


@pytest.mark.parametrize(
    "recipe",
    [
        _make_recipe_payload(),
        {"kind": "executable", "executable": "scripts/run.py"},
    ],
)
def test_imported_recipe_accepts_safe_existing_uvm_version(recipe: dict) -> None:
    """Allow an imported environment to retain its explicitly declared UVM version."""
    payload = _project_payload()
    payload["simulation"]["uvm_version"] = "1.1d"
    payload["simulation"]["recipe"] = recipe

    config = ProjectConfig.model_validate(payload)
    assert config.simulation.uvm_version == "1.1d"


def test_native_uvm_remains_fixed_to_version_12() -> None:
    """Reject unsupported native UVM generation even when the version token is syntactically safe."""
    payload = _project_payload()
    payload["simulation"]["uvm_version"] = "1.1"

    with pytest.raises(ValidationError, match="native UVM workflows require"):
        ProjectConfig.model_validate(payload)


@pytest.mark.parametrize("version", ["1.2;exec", "1.2 value", "$(VERSION)", "", "v" * 33])
def test_project_config_rejects_unsafe_uvm_versions(version: str) -> None:
    """Reject UVM version text that could alter adapter command construction."""
    payload = _project_payload()
    payload["simulation"]["uvm_version"] = version
    payload["simulation"]["recipe"] = _make_recipe_payload()

    with pytest.raises(ValidationError, match="safe version identifier"):
        ProjectConfig.model_validate(payload)


def test_reference_model_contract_allows_only_user_provided_variants() -> None:
    """Reject generated provenance and undeclared reference-model algorithms."""
    reference = parse_reference_model(
        {
            "kind": "dpi_c",
            "provenance": "user_provided",
            "sources": ["model/reference.cc"],
        }
    )
    assert reference.kind == "dpi_c"

    with pytest.raises(ValidationError):
        parse_reference_model({"kind": "generated", "sources": ["model/generated.sv"]})
    with pytest.raises(ValidationError, match="user_provided"):
        parse_reference_model(
            {
                "kind": "sv",
                "provenance": "generated",
                "sources": ["model/generated.sv"],
            }
        )


def test_secret_shaped_project_fields_are_rejected() -> None:
    """Keep credentials and license values out of project configuration snapshots."""
    payload = _project_payload()
    payload["design"]["parameters"] = {"API_TOKEN": "sensitive"}
    with pytest.raises(ValidationError, match="secret-bearing"):
        ProjectConfig.model_validate(payload)

    payload = _project_payload()
    payload["simulation"]["recipe"] = _make_recipe_payload(
        target="run", variables={"PASSWORD": "sensitive"}
    )
    with pytest.raises(ValidationError, match="secret-bearing"):
        ProjectConfig.model_validate(payload)


def test_make_recipe_requires_unambiguous_matrix_and_output_contract() -> None:
    """Reject old scalar recipes and collisions with runner-owned matrix assignments."""

    with pytest.raises(ValidationError, match="test_variable"):
        parse_recipe({"kind": "make", "target": "regression"})

    with pytest.raises(ValidationError, match="must be distinct"):
        parse_recipe(_make_recipe_payload(seed_variable="TEST"))

    with pytest.raises(ValidationError, match="must not also appear"):
        parse_recipe(_make_recipe_payload(variables={"TEST": "manual"}))

    with pytest.raises(ValidationError, match="must be distinct"):
        parse_recipe(_make_recipe_payload(coverage_variable="SEED"))

    with pytest.raises(ValidationError, match="must not also appear"):
        parse_recipe(
            _make_recipe_payload(
                variables={"WAVEFORM": "fsdb"},
                waveform_variable="WAVEFORM",
            )
        )

    with pytest.raises(ValidationError, match="must be declared together"):
        parse_recipe(_make_recipe_payload(coverage_variable=None))

    with pytest.raises(ValidationError, match="must be declared together"):
        parse_recipe(_make_recipe_payload(waveform_artifacts={}))

    with pytest.raises(ValidationError, match="reserved by JobRunner"):
        parse_recipe(_make_recipe_payload(result_logs=["stdout.log"]))

    with pytest.raises(ValidationError, match="project paths"):
        parse_recipe(_make_recipe_payload(artifacts=["../escaped.fsdb"]))

    with pytest.raises(ValidationError, match="overlap"):
        parse_recipe(
            _make_recipe_payload(
                artifacts=["waves.fsdb"],
            )
        )

    with pytest.raises(ValidationError, match="overlap"):
        parse_recipe(
            _make_recipe_payload(
                artifacts=["coverage"],
            )
        )


def test_imported_recipe_capabilities_fail_closed_when_selected() -> None:
    """Reject requested coverage or waveforms absent from an imported recipe contract."""

    payload = _project_payload()
    payload["simulation"]["recipe"] = _make_recipe_payload(
        coverage_variable=None,
        coverage_databases=[],
    )
    with pytest.raises(ValidationError, match="does not declare coverage"):
        ProjectConfig.model_validate(payload)

    payload = _project_payload()
    payload["simulation"]["coverage"] = []
    payload["simulation"]["waveform"] = "vpd"
    payload["simulation"]["recipe"] = _make_recipe_payload(
        waveform_artifacts={"fsdb": ["waves.fsdb"]},
    )
    with pytest.raises(ValidationError, match="does not declare 'vpd'"):
        ProjectConfig.model_validate(payload)


def test_project_loader_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    """Reject duplicate YAML keys instead of silently selecting one value."""
    control = tmp_path / ".ucagent"
    control.mkdir()
    (control / "project.yaml").write_text(
        "schema_version: 1\nschema_version: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate YAML key"):
        load_project_config(tmp_path)


def test_project_loader_rejects_yaml_aliases(tmp_path: Path) -> None:
    """Reject YAML aliases before they can expand into an ambiguous configuration graph."""
    control = tmp_path / ".ucagent"
    control.mkdir()
    (control / "project.yaml").write_text(
        "schema_version: 1\ndesign: &design\n  top: tb_top\ncopy: *design\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="aliases are not allowed"):
        load_project_config(tmp_path)


def test_project_loader_rejects_symlink_escape(tmp_path: Path) -> None:
    """Reject an in-project path whose existing symbolic link resolves outside."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "rtl"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable for this test account")
    payload = _project_payload()
    payload["design"]["sources"] = ["rtl/dut.sv"]

    with pytest.raises(ValueError, match="escapes the project root"):
        save_project_config(tmp_path, payload)
