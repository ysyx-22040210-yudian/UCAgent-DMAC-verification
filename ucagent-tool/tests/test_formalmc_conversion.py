"""Real SBY migration, immutable source evidence and native result-integrity tests."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from test_sby_guided_workflow import counter, real_session
from ucagent.eda.formalmc_conversion import convert_sby_to_formalmc, render_target
from ucagent.eda.formalmc_conversion import verify_converted_project
from ucagent.eda.parsers import parse_formal_log
from ucagent.eda.sby_guided import render_environment
from ucagent.lang.zh.skills.formal.lib.formal_tools import save_records


def tree_hashes(root):
    """Snapshot every original authoring and proof byte, not just the RTL."""
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("policy,mutant,mode", [
    ("initial", False, "prove"), ("unconstrained", False, "prove"),
    ("initial", True, "prove"), ("initial", False, "bmc"),
])
def test_real_conversion_and_relocated_runner(real_session, tmp_path, policy, mutant, mode):
    """Use real solver evidence, relocate output and reject old results or altered inputs."""
    session, records = real_session
    records.extra_config["sby"].update(reset_policy=policy, mode=mode)
    if policy != "initial":
        records.extra_config["sby"].pop("reset_cycles", None)
    if mutant:
        rtl = Path(session.paths.rtl_dir) / "Counter.sv"
        rtl.write_text(rtl.read_text().replace("y + 4'd1", "y + 4'd2"))
    source_result = session.collect(render_environment(session.paths, records), execute=True)
    save_records(session.paths.records_yaml, records)
    root = Path(session.workspace)
    before = tree_hashes(root)
    files, report = convert_sby_to_formalmc(root, "Counter", session.key)
    assert tree_hashes(root) == before
    assert convert_sby_to_formalmc(root, "Counter", session.key)[0] == files
    assert report["verification_status"] == report["formalmc_acceptance"] == "not_run"
    assert report["input_sha256"] == source_result["input_sha256"]
    assert [p["label"] for p in report["properties"]] == [p["label"] for p in source_result["properties"]]
    if mutant:
        assert source_result["verification_status"] == "failed"
    if mode == "bmc":
        assert source_result["verification_status"] == "inconclusive"
    moved = tmp_path / "other root with spaces" / "bundle"
    moved.mkdir(parents=True)
    for name, content in files.items():
        target = moved / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    manifest = verify_converted_project(moved)
    assert "run_formalmc.py" not in files
    assert not any(name.endswith(".zip") or "key" in name or name.endswith(".log") for name in files)
    checker = moved / "formal/Counter_checker.sv"
    checker.write_text(checker.read_text() + "\n// altered")
    with pytest.raises(ValueError, match="changed"):
        verify_converted_project(moved.resolve())
    records.spec.function_groups[1].functions[0].check_points[0].sby_guard = "1'b1"
    save_records(session.paths.records_yaml, records)
    with pytest.raises(ValueError, match="differ"):
        convert_sby_to_formalmc(root, "Counter", session.key)


@pytest.mark.parametrize("log,rc,wanted", [
    ("A_CK_X Pass\nC_CK_Y Cover_Pass\nG_A_CK_X Pass", 0, "passed"),
    ("A_CK_X Pass\nC_CK_Y Cover_Pass", 0, "inconclusive"),
    ("A_CK_X FALSE\nC_CK_Y Cover_Pass\nG_A_CK_X Pass", 0, "failed"),
    ("A_CK_X TRIVIALLY_TRUE\nC_CK_Y Cover_Pass\nG_A_CK_X Pass", 0, "inconclusive"),
    ("A_CK_X Pass\nC_CK_Y Cover_Pass\nG_A_CK_X Pass", 1, "unknown"),
    ("A_CK_X Pass\nC_CK_Y Cover_Pass\nG_A_CK_X Pass\nlicense checkout failed", 0, "unknown"),
    ("top.one.A_CK_X Pass\ntop.two.A_CK_X Pass\nC_CK_Y Pass\nG_A_CK_X Pass", 0, "inconclusive"),
    ("A_CK_X UNDEC\nC_CK_Y Cover_Fail\nG_A_CK_X Pass", 0, "inconclusive"),
    ("A_CK_X Pass\nC_CK_Y Cover_Pass\nG_A_CK_X Pass\nA_RTL_INTERNAL FALSE", 0, "failed"),
])
def test_native_parser_requires_complete_results(log, rc, wanted):
    """Partial, ambiguous and infrastructure-failed output cannot reuse an earlier green result."""
    expected = [{"label": "A_CK_X", "kind": "assert"}, {"label": "C_CK_Y", "kind": "cover"},
                {"label": "G_A_CK_X", "kind": "guard_witness"}]
    assert parse_formal_log(log, return_code=rc, engine="formal_mc", expected_properties=expected).verification_status == wanted


def test_unrun_and_forged_evidence_rejected(counter):
    """Metadata or a hand-authored coverage report cannot authorize an conversion."""
    paths, records = counter
    save_records(paths.records_yaml, records)
    with pytest.raises((ValueError, OSError)):
        convert_sby_to_formalmc(Path(paths.workspace), "Counter", b"not-an-accepted-signature")


@pytest.mark.parametrize("edge", ["posedge", "negedge"])
def test_history_and_reset_contract_is_explicit(counter, edge):
    """Reset properties remain active and guards apply on the same sampling edge."""
    paths, records = counter
    records.basic_info["clock_reset"]["clock_edge"] = edge
    generated = render_environment(paths, records)
    checker, wrapper, mapping = render_target(records, generated)
    assert "disable iff" not in checker
    assert "uc_past_valid && !$past(rst_n)" in checker
    assert "@(" + edge + " clk)" in checker
    assert "M_ENV_RESET: assume property" in wrapper
    assert len(mapping) == len(generated["properties"])


def test_explicit_combinational_conversion(counter):
    """A combinational invariant must not acquire a sampled clock."""
    paths, records = counter
    points = records.spec.function_groups[1].functions[0].check_points
    points[0].style = "Comb"
    points[0].sva_body, points[0].sby_guard = "y <= 4'hf", "1'b1"
    generated = render_environment(paths, records)
    checker, _, mapping = render_target(records, generated)
    assert "if (1'b1) A_CK_COUNT: assert (y <= 4'hf);" in checker
    assert next(p for p in mapping if p["label"] == "A_CK_COUNT")["sampling"] == "combinational"


@pytest.mark.parametrize("construct", [
    "always @(posedge clk) if(rst_n) assert(y <= 4'hf);",
    "(* anyseq *) reg formal_choice;",
])
def test_custom_verification_and_tool_extensions_blocked(real_session, construct):
    """Compiled source extensions require explicit modeling, not a silent raw-source copy."""
    session, records = real_session
    rtl = Path(session.paths.rtl_dir) / "Counter.sv"
    rtl.write_text(rtl.read_text().replace("endmodule", construct + "\nendmodule"))
    session.collect(render_environment(session.paths, records), execute=True)
    save_records(session.paths.records_yaml, records)
    with pytest.raises(ValueError, match="inputs/Counter/Counter.sv:"):
        convert_sby_to_formalmc(Path(session.workspace), "Counter", session.key)


def test_nonportable_ck_reports_identifier(counter):
    """Unknown system functions are attributed to the exact CK before packaging."""
    paths, records = counter
    records.spec.function_groups[1].functions[0].check_points[0].sva_body = "$initstate"
    with pytest.raises(ValueError, match="CK-COUNT.sva_body"):
        render_target(records, render_environment(paths, records))


@pytest.mark.parametrize("target", ["Counter/Counter.sv", "formal_out/.formal_records.yaml"])
def test_source_modified_during_conversion_is_rejected(real_session, monkeypatch, target):
    """An edit between initial input validation and publication must block the project."""
    import ucagent.eda.formalmc_conversion as converter
    session, records = real_session
    session.collect(render_environment(session.paths, records), execute=True)
    save_records(session.paths.records_yaml, records)
    root = Path(session.workspace)
    original = converter.render_target

    def concurrent_edit(*args, **kwargs):
        """Apply a real external file edit at a deterministic publication barrier."""
        rendered = original(*args, **kwargs)
        path = root / target
        path.write_bytes(path.read_bytes() + b"\n")
        return rendered

    monkeypatch.setattr(converter, "render_target", concurrent_edit)
    with pytest.raises(ValueError, match="Source changed while converting"):
        converter.convert_sby_to_formalmc(root, "Counter", session.key)


def test_native_property_mapping_retains_counterexample_and_runtime():
    """CK normalization keeps real report evidence paths and proof statistics."""
    parsed = parse_formal_log("top.u_checker.A_CK_X FALSE runtime=1.5 depth=8 cex=trace.vcd\nG_A_CK_X Cover_Pass",
        engine="formal_mc", expected_properties=[{"label":"A_CK_X","kind":"assert"}, {"label":"G_A_CK_X","kind":"guard_witness"}])
    assert parsed.verification_status == "failed"
    result = next(p for p in parsed.properties if p.name == "A_CK_X")
    assert result.counterexample_path == Path("trace.vcd") and result.runtime_seconds == 1.5 and result.proof_depth == 8
