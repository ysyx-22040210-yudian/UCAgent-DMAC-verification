"""Exercise structured open-formal planning and fail-closed SBY evidence handling."""

from pathlib import Path
import sys

import pytest

from ucagent.eda.adapters import get_adapter
from ucagent.eda.sby_results import parse_sby_results
from ucagent.eda import CommandSpec, JobRunner, RunRequest, ToolchainProfile, verify_manifest
from ucagent.platform.project import FormalConfig, SbyOptions


def report(tmp_path, status="PASS", code=0, kind="assert", child="", trace=None):
    """Create minimal current SBY status/JUnit fixtures in a fresh private session."""
    proof = tmp_path / "proof"
    proof.mkdir()
    (proof / "status").write_text(f"{status} {code} 0.5\n")
    attr = f' tracefile="{trace}"' if trace else ""
    (proof / "run.xml").write_text(f'<testsuites><testsuite><properties><property name="status" value="{status}"/></properties><testcase name="p" id="dut.p" type="{kind}"{attr}>{child}</testcase></testsuite></testsuites>')
    return proof


@pytest.mark.parametrize("mode,status,code,kind,child,expected", [
    ("prove", "PASS", 0, "assert", "", "passed"),
    ("bmc", "PASS", 0, "assert", "", "inconclusive"),
    ("prove", "FAIL", 2, "assert", "<failure/>", "failed"),
    ("prove", "UNKNOWN", 4, "assert", "<skipped/>", "inconclusive"),
    ("cover", "PASS", 0, "cover", "", "passed"),
    ("cover", "FAIL", 2, "cover", "<failure/>", "inconclusive"),
])
def test_sby_conclusions(tmp_path, mode, status, code, kind, child, expected):
    """Keep bounded checks, cover misses and failed assertions semantically distinct."""
    report(tmp_path, status, code, kind, child)
    result = parse_sby_results(tmp_path, mode=mode, depth=10, return_code=code)
    assert result.execution_status == "completed"
    assert result.verification_status == expected
    if mode == "bmc":
        assert result.properties[0].status == "inconclusive"
        assert result.diagnostics[0]["error_code"] == "bounded_check_passed"


@pytest.mark.parametrize("failure", ["missing", "malformed", "mismatch", "empty", "traversal", "contradiction", "dtd"])
def test_sby_invalid_evidence_never_passes(tmp_path, failure):
    """Reject stale, missing, contradictory or escaping evidence instead of trusting logs."""
    if failure != "missing":
        proof = report(tmp_path, trace="../../outside.vcd" if failure == "traversal" else None, child="<failure/>" if failure == "contradiction" else "")
        if failure == "malformed":
            (proof / "run.xml").write_text("not XML")
        elif failure == "mismatch":
            (proof / "status").write_text("FAIL 2 0.5")
        elif failure == "empty":
            (proof / "run.xml").write_text('<testsuites><testsuite><properties><property name="status" value="PASS"/></properties></testsuite></testsuites>')
        elif failure == "dtd":
            (proof / "run.xml").write_text('<!DOCTYPE x><testsuites/>')
    result = parse_sby_results(tmp_path, mode="prove", depth=10, return_code=0)
    assert result.execution_status == "error"
    assert result.verification_status == "unknown"
    assert result.properties == []


def test_sby_declared_trace_is_evidence_not_dynamic_replay(tmp_path):
    """Associate only the trace named by SBY with its falsified property."""
    proof = report(tmp_path, "FAIL", 2, child="<failure/>", trace="engine_0/trace.vcd")
    (proof / "engine_0").mkdir()
    (proof / "engine_0/trace.vcd").write_text("$enddefinitions $end\n")
    result = parse_sby_results(tmp_path, mode="prove", depth=10, return_code=2)
    assert result.properties[0].counterexample_path == Path("proof/engine_0/trace.vcd")
    assert "dynamically_reproduced" not in result.properties[0].details


def test_sby_native_inputs_and_private_staging(tmp_path):
    """Flatten literal file lists, hash includes and generate no arbitrary command hooks."""
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/inc").mkdir()
    (tmp_path / "rtl/top.sv").write_text("module top; endmodule\n")
    (tmp_path / "rtl/files.f").write_text("+incdir+inc\n+define+WIDTH=8\ntop.sv\n")
    adapter = get_adapter("sby")
    plan = adapter.prepare(workspace=tmp_path, top="top", filelists=[Path("rtl/files.f")])
    content, inputs = plan.content, plan.inputs
    assert "smtbmc z3" in content
    assert "-DWIDTH=8" in content
    assert '-Iinputs/rtl/inc' in content and '-I"' not in content
    assert '"inputs/rtl/top.sv"' in content
    assert Path("rtl/files.f") in inputs
    (tmp_path / "run.sby").write_text(content, newline="\n")
    job = adapter.build_formal_request(workspace=tmp_path, output_dir=Path("results/one"), config_path=Path("run.sby"), plan=plan, mode="prove", depth=40, timeout_seconds=120, run_id="test")
    assert job.parser == "sby"
    assert "-f" not in job.command.argv
    assert job.command.cwd == Path("{SESSION_DIR}")
    assert job.metadata["cacheable"] is False
    assert set(job.prepared_input_hashes) == {"run.sby", "rtl/files.f"}


@pytest.mark.parametrize("token", ["-load lib.so", "-y ../outside", "../../outside.sv", "$(touch bad)", "-f loop.f"])
def test_sby_rejects_unsafe_filelists(tmp_path, token):
    """Reject simulator plugins, escaping paths, command substitutions and recursion."""
    (tmp_path / "loop.f").write_text(token)
    with pytest.raises((ValueError, FileNotFoundError)):
        get_adapter("sby").prepare(workspace=tmp_path, top="top", filelists=[Path("loop.f")])


@pytest.mark.parametrize("status,code,expected", [("ERROR", 16, "error"), ("TIMEOUT", 8, "timeout")])
def test_sby_tool_failure_is_not_a_dut_failure(tmp_path, status, code, expected):
    """Keep syntax/solver failures and internal deadlines independent of verification."""
    report(tmp_path, status, code, child="<error/>")
    result = parse_sby_results(tmp_path, mode="prove", depth=10, return_code=code)
    assert result.execution_status == expected
    assert result.verification_status == "unknown"


def test_sby_probes_use_supported_entry_points():
    """SMTBMC must be probed with help, not an unsupported version switch."""
    adapter = get_adapter("sby")
    profile = ToolchainProfile(id="fixture", tools={tool: sys.executable for tool in adapter.required_tools})
    assert [command.argv for command in adapter.probe_commands(profile)] == [
        ["sby", "--version"], ["yosys", "-V"], ["yosys-smtbmc", "-h"], ["z3", "--version"],
    ]


@pytest.mark.parametrize("options", [{"engine": "vc_formal", "sby": {}}, {"engine": "sby", "clock": {"signal": "clk"}}, {"engine": "sby", "reset": {"signal": "rst"}}])
def test_sby_rejects_silently_ignored_options(options):
    """Never pretend to impose VC Formal timing constraints on an SBY harness."""
    with pytest.raises(ValueError):
        FormalConfig.model_validate(options)
    with pytest.raises(ValueError):
        SbyOptions(multiclock="false")


def test_sby_trace_and_xml_are_individual_signed_downloads(tmp_path):
    """Publish evidence as addressable files in addition to the proof directory hash."""
    code = "from pathlib import Path; import sys; p=Path('proof'); p.mkdir(); (p/'status').write_text('FAIL 2 0'); (p/'trace.vcd').write_text('$enddefinitions $end'); (p/'run.xml').write_text('<testsuites><testsuite><properties><property name=\"status\" value=\"FAIL\"/></properties><testcase name=\"p\" type=\"ASSERT\" tracefile=\"trace.vcd\"><failure/></testcase></testsuite></testsuites>'); sys.exit(2)"
    request = RunRequest(workspace=tmp_path, output_dir=Path("runs/one"), command=CommandSpec(tool="python", argv=["python", "-c", code], cwd=Path("{SESSION_DIR}")), parser="sby", metadata={"mode": "prove", "depth": 10}, artifact_paths=[Path(".")])
    result = JobRunner(b"test-only-signing-key").run(request, ToolchainProfile(id="fixture", tools={"python": sys.executable}, minimum_free_bytes=0))
    assert result.execution_status == "completed" and result.verification_status == "failed"
    manifest = verify_manifest(result.manifest_path, b"test-only-signing-key", workspace=tmp_path)
    assert {Path(artifact["path"]).as_posix() for artifact in manifest["artifacts"]} >= {"proof/trace.vcd", "proof/run.xml", "proof/status"}


def test_sby_filelist_edit_invalidates_prepared_request(tmp_path):
    """Changing defines or file-list order after preparation must not execute a stale plan."""
    (tmp_path / "rtl.sv").write_text("module top; endmodule")
    (tmp_path / "files.f").write_text("rtl.sv")
    adapter = get_adapter("sby")
    plan = adapter.prepare(workspace=tmp_path, top="top", filelists=[Path("files.f")])
    (tmp_path / "run.sby").write_text(plan.content, newline="\n")
    request = adapter.build_formal_request(workspace=tmp_path, output_dir=Path("runs/stale"), config_path=Path("run.sby"), plan=plan, mode="prove", depth=40, timeout_seconds=120, run_id="stale")
    (tmp_path / "files.f").write_text("+define+CHANGED\nrtl.sv")
    result = JobRunner(b"test-key").run(request, ToolchainProfile(id="fixture", tools={"sby": sys.executable}, minimum_free_bytes=0))
    assert result.execution_status == "error" and result.return_code is None
    assert result.diagnostics[0]["error_code"] == "prepared_inputs_changed"


def test_sby_rejects_unsupported_quoted_include_directory(tmp_path):
    """Reject Yosys include-option quoting limitations during preflight, not mid-run."""
    (tmp_path / "rtl.sv").write_text("module top; endmodule")
    (tmp_path / "include space").mkdir()
    with pytest.raises(ValueError, match="include directory names"):
        get_adapter("sby").prepare(workspace=tmp_path, top="top", sources=[Path("rtl.sv")], include_dirs=[Path("include space")])


def test_sby_failed_induction_is_not_a_reachable_counterexample(tmp_path):
    """Real SBY UNKNOWN reports may mark one induction property failure in JUnit."""
    proof = report(tmp_path, "UNKNOWN", 4, child="<failure/>", trace="engine_0/trace_induct.vcd")
    (proof / "engine_0").mkdir()
    (proof / "engine_0/trace_induct.vcd").write_text("$enddefinitions $end\n")
    result = parse_sby_results(tmp_path, mode="prove", depth=20, return_code=4)
    assert result.execution_status == "completed"
    assert result.verification_status == "inconclusive"
    assert result.properties[0].status == "inconclusive"
    assert result.properties[0].counterexample_path is None
    assert result.properties[0].details["unproven_failure_trace"] is True
    assert result.properties[0].details["trace_path"] == "proof/engine_0/trace_induct.vcd"


@pytest.mark.parametrize("duplicate_id", [False, True])
def test_sby_generate_properties_keep_distinct_witness_ids(tmp_path, duplicate_id):
    """Same source location is valid only when individual property IDs are distinct."""
    proof = report(tmp_path)
    second = "slot0" if duplicate_id else "slot1"
    (proof / "run.xml").write_text('<testsuites><testsuite><properties>'
        '<property name="status" value="PASS"/></properties>'
        '<testcase name="same location" id="slot0" type="ASSERT"/>'
        '<testcase name="same location" id="' + second + '" type="ASSERT"/>'
        '</testsuite></testsuites>')
    result = parse_sby_results(tmp_path, mode="prove", depth=4, return_code=0)
    if duplicate_id:
        assert result.execution_status == "error" and result.properties == []
    else:
        assert result.verification_status == "passed"
        assert {p.name for p in result.properties} == {"same location [slot0]", "same location [slot1]"}
        assert len(result.properties) == 2
