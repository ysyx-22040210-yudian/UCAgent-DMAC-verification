"""Regress the restored FormalMC defaults without claiming a real EDA acceptance run."""

from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

from ucagent.eda.adapters.formal_mc import FormalMcAdapter
from ucagent.eda import CommandSpec, JobRunner, ToolchainProfile, verify_manifest
from ucagent.platform.project import FormalConfig
from ucagent.server.api_platform import FormalRunOptions
from ucagent.server.platform_workbench import run_defaults
from ucagent.util.config import load_yaml_with_env_vars


def test_default_formal_engine_is_original_formalmc():
    """Omitted engine selection must never activate VCF or installed SBY automatically."""
    assert FormalConfig().engine == "formalmc"
    assert FormalRunOptions().engine == "formalmc"
    project = {"project_id": "p", "config": {"workflow": {"family": "formal"}}}
    defaults = run_defaults(project)
    assert defaults["formal"]["engine"] == "formalmc"
    assert defaults["formal"]["clock"] == defaults["formal"]["reset"] == {}


@pytest.mark.parametrize("engine", ["vc_formal", "sby", "formalmc"])
def test_explicit_historical_engine_is_not_reinterpreted(engine):
    """Reading saved project selections cannot rewrite old runs as FormalMC evidence."""
    project = {"project_id": "p", "config": {"workflow": {"family": "formal"}, "formal": {"engine": engine}}}
    assert run_defaults(project)["formal"]["engine"] == engine
    assert project["config"]["formal"]["engine"] == engine


@pytest.mark.parametrize("fields", [{"clock": {"signal": "clk"}}, {"clock": {"period_ns": 10}}, {"reset": {"signal": "rst_n"}}])
def test_formalmc_rejects_ignored_vcf_timing(fields):
    """A Tcl engine cannot pretend to apply timing fields outside its script."""
    with pytest.raises(ValidationError, match="def_clk/def_rst"):
        FormalConfig(**fields)


@pytest.mark.parametrize("entries", [[], ["properties.sv"], ["first.tcl", "second.tcl"]])
def test_formalmc_requires_unambiguous_tcl_entry(entries):
    """Never accept a missing script or silently execute only the first of two entries."""
    with pytest.raises(ValueError, match="exactly one entry"):
        FormalMcAdapter.select_script(entries)


def test_formalmc_command_and_transitive_inputs(tmp_path):
    """Use the original argv, retain helper inputs and avoid unsafe proof cache reuse."""
    (tmp_path / "run.tcl").write_text("source helper.tcl\nprove\n", encoding="utf-8")
    (tmp_path / "helper.tcl").write_text("def_clk clk\n", encoding="utf-8")
    (tmp_path / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    request = FormalMcAdapter().build_formal_request(
        workspace=tmp_path, output_dir=Path("runs/formal"), tcl_path=Path("run.tcl"), design_inputs=[Path("dut.sv")],
    )
    assert request.command.tool == "formalmc"
    assert request.command.argv == ["FormalMC", "-f", "{WORKSPACE}/run.tcl", "-override", "-work_dir", "{SESSION_DIR}"]
    assert set(request.input_paths) == {Path("run.tcl"), Path("helper.tcl"), Path("dut.sv")}
    assert request.result_paths == [Path("avis.log")]
    assert request.metadata["cacheable"] is False
    assert request.parser == "formal"


@pytest.mark.parametrize("script", ["missing.tcl", "../outside.tcl"])
def test_formalmc_missing_or_escaping_entry_is_blocked(tmp_path, script):
    """Reject missing and outside-workspace scripts before process dispatch."""
    with pytest.raises(ValueError):
        FormalMcAdapter().build_formal_request(workspace=tmp_path, output_dir=Path("runs/formal"), tcl_path=Path(script))


def test_formalmc_missing_helper_is_blocked(tmp_path):
    """Readable entry text does not make a missing sourced helper executable."""
    (tmp_path / "run.tcl").write_text("source missing.tcl\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing.tcl"):
        FormalMcAdapter().build_formal_request(workspace=tmp_path, output_dir=Path("runs/formal"), tcl_path=Path("run.tcl"))


@pytest.mark.parametrize("outcome,expected", [("Pass", "passed"), ("FALSE", "failed"), ("Undec", "inconclusive")])
def test_formalmc_fixture_reports_keep_verification_status_separate(tmp_path, outcome, expected):
    """Exercise real child execution with synthetic logs, not a real FormalMC proof."""
    (tmp_path / "run.tcl").write_text("prove\n", encoding="utf-8")
    request = FormalMcAdapter().build_formal_request(workspace=tmp_path, output_dir=Path("runs/formal"), tcl_path=Path("run.tcl"))
    code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('Info-P016: property A_CK_RESULT is ' + sys.argv[2] + '\\n')"
    request = request.model_copy(update={"command": CommandSpec(tool="fixture_python", argv=["python", "-c", code, "{SESSION_DIR}/avis.log", outcome], timeout_seconds=10), "metadata": {**request.metadata, "synthetic_fixture": True}})
    profile = ToolchainProfile(id="fixture", tools={"fixture_python": sys.executable}, minimum_free_bytes=0)
    result = JobRunner(b"test-only-signing-key").run(request, profile)
    assert result.execution_status == "completed"
    assert result.verification_status == expected
    evidence = verify_manifest(result.manifest_path, b"test-only-signing-key", workspace=tmp_path)
    assert evidence["metadata"]["synthetic_fixture"] is True
    assert evidence["metadata"]["cacheable"] is False


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_original_formalmc_stage_order_and_conditional_branches(enabled, monkeypatch):
    """Keep the eleven original authoring stages and both optional branch settings."""
    monkeypatch.setenv("CEX_CHECK", enabled)
    monkeypatch.setenv("IGNORE_STATIC_CHECK", enabled)
    config = load_yaml_with_env_vars(str(Path(__file__).resolve().parents[1] / "ucagent/lang/zh/config/formal.yaml"))
    assert [stage["name"] for stage in config["stage"]] == [
        "requirement_analysis_and_planning", "dut_function_understanding", "functional_specification_analysis",
        "property_generation", "script_generation", "environment_debugging_iteration",
        "coverage_analysis_and_optimization", "counterexample_python_testgen", "formal_execution",
        "static_bug_validation", "verification_review_and_summary",
    ]
    assert "FormalMC" in config["mission"]["prompt"]["system"]
    assert config["template_overwrite"]["LOG_FILE"] == "avis.log"
    by_name = {stage["name"]: stage for stage in config["stage"]}
    assert by_name["counterexample_python_testgen"]["ignore"] is (enabled == "true")
    assert by_name["static_bug_validation"]["ignore"] is (enabled == "true")
