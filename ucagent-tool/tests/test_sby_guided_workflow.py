"""Exercise the original formal stage sequence with native-SBY authoring and evidence."""

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
import yaml

from ucagent.checkers.formal_sby import SbyGuidedChecker
from ucagent.eda.formal_workflow import select_formal_engine
from ucagent.eda.models import ToolchainProfile
from ucagent.eda.sby_guided import GuidedSbySession, render_environment
from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records, save_records
from ucagent.lang.zh.skills.formal.lib.models import FormalRecords
from ucagent.util.config import load_yaml_with_env_vars


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def counter(tmp_path):
    """Create a real clocked counter and an explicit reset/port/property contract."""
    dut = tmp_path / "Counter"
    dut.mkdir()
    (dut / "Counter.sv").write_text("module Counter(input wire clk, rst_n, en, output reg [3:0] y);\nalways @(posedge clk) if (!rst_n) y <= 0; else if (en) y <= y + 4'd1;\nendmodule\n", encoding="utf-8")
    records = FormalRecords.model_validate({
        "dut": "Counter",
        "planning": {"project_overview": "Enabled four bit counter", "verification_scope": {"included": ["reset", "count"]}, "strategy": ["prove and cover"], "deliverables": ["proof evidence"], "risks": ["bounded coverage"]},
        "basic_info": {"module_type": "counter", "core_functions": ["count on enable"], "correctness_requirements": ["one increment per enabled cycle"], "ports": {"inputs": [{"name": n, "width": 1} for n in ("clk", "rst_n", "en")], "outputs": [{"name": "y", "width": 4}]}, "clock_reset": {"clock_signal": "clk", "clock_count": 1, "clock_edge": "posedge", "reset_signal": "rst_n"}},
        "spec": {"function_groups": [
            {"id": "FG-API", "functions": [{"id": "FC-API", "check_points": [{"id": "CK-API", "style": "Assume", "description": "Enable is unrestricted", "sva_body": "en == 0 || en == 1"}]}]},
            {"id": "FG-COUNT", "functions": [{"id": "FC-COUNT", "check_points": [{"id": "CK-COUNT", "style": "Seq", "description": "Increment wraps at four bits", "sva_body": "y == (($past(y) + 4'd1) & 4'hf)", "sby_guard": "uc_past_valid && rst_n && $past(rst_n) && $past(en)", "sby_trigger": "en"}, {"id": "CK-RESET", "style": "Seq", "description": "Reset on preceding edge", "sva_body": "y == 0", "sby_guard": "uc_past_valid && !$past(rst_n)"}]}]},
            {"id": "FG-COVERAGE", "functions": [{"id": "FC-REACH", "check_points": [{"id": "CK-REACH", "style": "Cover", "description": "Counter reaches three", "sva_body": "rst_n && y == 3"}]}]},
        ]},
        "extra_config": {"sby": {"sources": ["Counter/Counter.sv"], "mode": "prove", "depth": 12, "timeout_seconds": 30, "reset_policy": "initial", "reset_active": 0, "reset_cycles": 1, "review": {"assumptions": {"M_CK_API": "Enable values impose no behavioral restriction.", "M_ENV_RESET": "The specification starts with one asserted reset cycle."}, "limitations": "COI, full vacuity and unbounded liveness have not been established."}}},
        "summary": {"core_function": "Enabled counter", "overall_result": "passed", "acceptance_conclusion": "Safety assertions and declared reachability only."},
    })
    paths = FormalPaths(workspace=str(tmp_path), dut="Counter", out="formal_out")
    save_records(paths.records_yaml, records)
    return paths, records


@pytest.mark.parametrize("skills", [False, True])
@pytest.mark.parametrize("cex", [False, True])
@pytest.mark.parametrize("static", [False, True])
def test_engine_selection_preserves_original_stage_tree(monkeypatch, skills, cex, static):
    """Engine selection must preserve all eleven stages, nested CK stages and branches."""
    monkeypatch.setenv("CEX_CHECK", str(cex).lower())
    monkeypatch.setenv("IGNORE_STATIC_CHECK", str(static).lower())
    config = load_yaml_with_env_vars(str(ROOT / "ucagent/lang/zh/config/formal.yaml"))
    original = deepcopy(config)
    config["runtime_options"]["formal_engine"] = "sby"
    config["skill"]["use_skill"] = skills
    selected = select_formal_engine(config)
    assert [s["name"] for s in selected["stage"]] == [s["name"] for s in original["stage"]]
    assert len(selected["stage"]) == 11
    assert selected["stage"][7]["ignore"] == cex
    assert selected["stage"][9]["ignore"] == static
    assert len(selected["stage"][2]["stage"]) == 3
    assert selected["skill"]["use_skill"] == skills
    assert all(not s["force_use_skill"] for s in selected["stage"])
    assert "property/endproperty" in selected["mission"]["prompt"]["system"]
    assert select_formal_engine(original) is original


def test_render_explicit_reset_and_property_mapping(counter):
    """Render expression-based properties without implied reset disable or hierarchy reads."""
    paths, records = counter
    generated = render_environment(paths, records)
    checker = Path(paths.checker).read_text(encoding="utf-8")
    wrapper = Path(paths.wrapper).read_text(encoding="utf-8")
    assert "A_CK_COUNT: assert" in checker and "G_A_CK_COUNT: cover" in checker
    assert "M_ENV_RESET: assume" in wrapper
    assert "input wire en" in wrapper
    assert "property (" not in checker and "disable iff" not in checker
    assert any(p["fg"] == "FG-COUNT" and p["label"] == "A_CK_COUNT" for p in generated["properties"])


@pytest.mark.parametrize("change", ["full_sva", "collision", "whitebox", "missing_polarity", "multiclock", "port_width", "injection", "unknown_option"])
def test_invalid_authoring_contract_fails_before_execution(counter, change):
    """Reject unsupported or ambiguous input instead of silently changing semantics."""
    paths, records = counter
    cp = records.spec.function_groups[1].functions[0].check_points[0]
    if change == "full_sva":
        cp.sva_body = "en |=> y == $past(y) + 1"
    elif change == "collision":
        records.spec.function_groups[1].functions[0].check_points[1].id = cp.id
    elif change == "whitebox":
        records.spec.whitebox_signals = ["logic state"]
    elif change == "missing_polarity":
        records.extra_config["sby"].pop("reset_active")
    elif change == "multiclock":
        records.basic_info["clock_reset"]["clock_count"] = 2
    elif change == "port_width":
        records.basic_info["ports"]["outputs"][0]["width"] = "WIDTH"
    elif change == "injection":
        cp.sva_body = "1); assume(0"
    else:
        records.extra_config["sby"]["shell"] = "true"
    with pytest.raises(ValueError):
        render_environment(paths, records)


def test_generation_needs_no_skill_directory_or_toolchain(counter):
    """The normal Check action renders with no copied Skills and no EDA installation."""
    paths, _ = counter
    checker = SbyGuidedChecker("Counter", phase="property", cfg={"_temp_cfg": {"DUT": "Counter", "OUT": "formal_out"}})
    checker.set_workspace(paths.workspace)
    checker.on_init()
    ok, details = checker.do_check()
    assert ok, details
    assert not (Path(paths.workspace) / ".ucagent/skills").exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_full_config_and_snapshot_resolve_sby_without_skills(tmp_path, monkeypatch, enabled):
    """The public config loader must specialize real stages and persist explicit selection."""
    from importlib import import_module
    from ucagent.util.config import get_config, save_runtime_config, load_runtime_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cfg = get_config("formal.yaml", [{"runtime_options.formal_engine": "sby"}, {"skill.use_skill": enabled}, {"hooks.continue": "Explicit stage continuation"}], workspace=str(tmp_path))
    cfg.update_template({"DUT": "Counter", "OUT": "formal_out", "WORKSPACE": str(tmp_path), "Version": "test"})
    cfg.update_template(cfg.template_overwrite.as_dict())
    cfg.un_freeze()
    cfg._temp_cfg = {"DUT": "Counter", "OUT": "formal_out"}
    cfg.freeze()
    save_runtime_config(str(tmp_path), cfg)
    assert load_runtime_config(str(tmp_path))["runtime_options"]["formal_engine"] == "sby"
    assert cfg.guide_doc.source == "Formal_SBY_Doc"
    assert cfg.skill.use_skill == enabled
    assert cfg.hooks.get_value("continue") == "Explicit stage continuation"
    assert not (tmp_path / ".ucagent/skills").exists()
    for stage in cfg.stage:
        for node in [stage, *stage.get_value("stage", [])]:
            for definition in node.get_value("checker", []):
                module, name = definition.clss.rsplit(".", 1)
                checker = getattr(import_module(module), name)(**definition.args.as_dict(), cfg=cfg)
                checker.set_workspace(str(tmp_path))
                checker.on_init()
                assert checker.paths.out == "formal_out"
    from ucagent.util.functions import render_template_dir

    render_template_dir(str(tmp_path), str(ROOT / "ucagent/lang/zh/template/formal_sby"), {"DUT": "Counter"})
    assert yaml.safe_load((tmp_path / "formal_sby/.formal_records.yaml").read_text(encoding="utf-8"))["dut"] == "Counter"


def test_catalog_explicit_sby_selection_keeps_disabled_branches():
    """TK/API previews specialize one tree without changing the default FormalMC catalog."""
    from ucagent.platform.workflow_catalog import load_workflow_catalog

    defaults = next(w for w in load_workflow_catalog().workflows if w.id == "formal-guided")
    sby = next(w for w in load_workflow_catalog({"FORMAL_ENGINE": "sby"}).workflows if w.id == "formal-guided")
    assert [s.name for s in defaults.stages] == [s.name for s in sby.stages]
    assert defaults.name == "FormalMC Guided" and sby.name == "SBY Guided"
    branches = next(s for s in sby.stages if s.name == "toolchain_dispatch").children
    assert [s.name for s in branches if s.enabled] == ["sby"]
    assert "COI" in sby.stages[6].description


def test_complete_guide_example_is_renderable(tmp_path):
    """The normative guide includes an entire valid authoring record, not disconnected fragments."""
    guide = (ROOT / "ucagent/lang/zh/doc/Formal_SBY_Doc/sby_workflow.md").read_text(encoding="utf-8")
    records = FormalRecords.model_validate(yaml.safe_load(guide.split("```yaml\n", 1)[1].split("```", 1)[0]))
    paths = FormalPaths(workspace=str(tmp_path), dut="Counter", out="formal_out")
    generated = render_environment(paths, records)
    assert generated["options"].reset_active == 0


def test_escaping_generated_path_is_rejected(counter, tmp_path):
    """Generated artifacts cannot follow a tests-directory link outside the workspace."""
    paths, records = counter
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    try:
        Path(paths.tests).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError):
        render_environment(paths, records)


@pytest.fixture
def real_session(counter):
    """Use explicitly enabled installed OSS tools; fixtures never simulate their results."""
    tool_root = os.environ.get("UCAGENT_TEST_SBY_BIN")
    if not tool_root:
        pytest.skip("Set UCAGENT_TEST_SBY_BIN to run real SBY acceptance")
    paths, records = counter
    profile = ToolchainProfile(id="sby-real-test", tools={name: str(Path(tool_root) / name) for name in ("sby", "yosys", "yosys-smtbmc", "z3")}, environment={"PATH": tool_root + os.pathsep + os.environ.get("PATH", "")}, minimum_free_bytes=10 * 1024**3)
    return GuidedSbySession(paths, profile, b"isolated-test-key-not-for-production"), records


@pytest.mark.parametrize("mode", ["prove", "bmc"])
def test_real_sby_proof_cover_resume_and_tamper(real_session, mode):
    """Execute actual proof/cover, distinguish BMC, and reject stale or modified evidence."""
    session, records = real_session
    records.extra_config["sby"]["mode"] = mode
    generated = render_environment(session.paths, records)
    report = session.collect(generated, execute=True)
    assert report["verification_status"] == ("passed" if mode == "prove" else "inconclusive")
    assert report["coverage"]["coi"] == "unsupported"
    assert report["coverage"]["covered"] == report["coverage"]["total"]
    index_before = session.index.read_bytes()
    resumed = GuidedSbySession(session.paths, session.profile, session.key)
    assert resumed.collect(generated, execute=False) == report
    assert session.index.read_bytes() == index_before
    source = Path(session.paths.rtl_dir) / "Counter.sv"
    original = source.read_text(encoding="utf-8")
    source.write_text(original + "// changed input\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        resumed.collect(generated, execute=False)
    source.write_text(original, encoding="utf-8")
    manifest_path = Path(session.paths.workspace) / json.loads(index_before)["manifests"][mode]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["verification_status"] = "forged"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        resumed.collect(generated, execute=False)


def test_real_sby_failure_and_counterexample(real_session):
    """A real faulty RTL remains a verification failure with a signed VCD trace."""
    session, records = real_session
    source = Path(session.paths.rtl_dir) / "Counter.sv"
    source.write_text(source.read_text(encoding="utf-8").replace("y + 4'd1", "y + 4'd2"), encoding="utf-8")
    report = session.collect(render_environment(session.paths, records), execute=True)
    assert report["verification_status"] == "failed"
    failed = [p for p in report["properties"] if p["status"] == "falsified"]
    assert failed and all(p["counterexample"] for p in failed)


def test_real_cover_miss_is_inconclusive(real_session):
    """Insufficient bounded reachability is not a proof of unreachability or a DUT bug."""
    session, records = real_session
    records.extra_config["sby"]["depth"] = 3
    records.spec.function_groups[-1].functions[0].check_points[0].sva_body = "rst_n && y == 15"
    report = session.collect(render_environment(session.paths, records), execute=True)
    assert report["verification_status"] == "inconclusive"
    cover = next(p for p in report["properties"] if p["label"] == "C_CK_REACH")
    assert cover["status"] in {"uncovered", "inconclusive"} and not cover["counterexample"]


def test_real_interface_width_mismatch_is_rejected(real_session):
    """Successful elaboration with resized ports cannot be accepted as a valid harness."""
    session, records = real_session
    records.basic_info["ports"]["outputs"][0]["width"] = 3
    with pytest.raises(ValueError, match="interface"):
        session.collect(render_environment(session.paths, records), execute=True)


def test_host_profile_and_key_are_private_and_stable(counter, tmp_path, monkeypatch):
    """Use a selected host profile without placing its environment or signing key in records."""
    paths, _ = counter
    host = tmp_path / "host"
    directory = host / ".ucagent"
    directory.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: host))
    (directory / "toolchains.yaml").write_text(yaml.safe_dump({"profiles": {"sby": {"tools": {name: name for name in ("sby", "yosys", "yosys-smtbmc", "z3")}}}}), encoding="utf-8")
    first = GuidedSbySession.from_host(paths, "sby")
    second = GuidedSbySession.from_host(paths, "sby")
    assert first.key == second.key and len(first.key) == 32
    assert not (Path(paths.base) / "formal-manifest.key").exists()
    if os.name != "nt":
        assert (directory / "formal-manifest.key").stat().st_mode & 0o077 == 0


def test_guided_cancellation_uses_runner_signal(counter):
    """The existing stage kill operation must signal JobRunner rather than a shell process."""
    paths, _ = counter
    checker = SbyGuidedChecker("Counter", phase="script")
    checker._executing = True
    assert checker.is_processing()
    checker.kill()
    assert checker._cancel.is_set()


def test_real_guided_stage_review_and_signoff(real_session):
    """Run the original Check actions through evidence-backed review and final summary."""
    session, records = real_session
    for phase in ("script", "environment", "coverage", "summary"):
        checker = SbyGuidedChecker("Counter", phase=phase, cfg={"_temp_cfg": {"DUT": "Counter", "OUT": "formal_out"}})
        checker.set_workspace(session.paths.workspace)
        checker.on_init()
        checker._session = session
        ok, result = checker.do_check()
        assert ok, result
        assert result["verification_status"] == "passed"
        if phase == "script":
            records = load_records(session.paths.records_yaml)
            report = json.loads((Path(session.paths.tests) / "sby_coverage.json").read_text(encoding="utf-8"))
            records.extra_config["sby"]["review"]["input_sha256"] = report["input_sha256"]
            save_records(session.paths.records_yaml, records)
    summary = Path(session.paths.summary).read_text(encoding="utf-8")
    assert "passed" in summary and "COI" in summary
