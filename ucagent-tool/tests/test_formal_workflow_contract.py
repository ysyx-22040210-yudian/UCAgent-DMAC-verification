"""Focused regressions for the legacy Formal workflow trust boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import ucagent
from ucagent.checkers.formal import CounterexampleTestgenChecker, PlanningStructureChecker
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import (
    parse_avis_log,
    update_records_run_results,
    validate_log_has_results,
)
from ucagent.lang.zh.skills.formal.lib.models import FormalRecords


ROOT = Path(__file__).resolve().parents[1]
FORMAL_CONFIG = ROOT / "ucagent" / "lang" / "zh" / "config" / "formal.yaml"
FORMAL_DOCS = ROOT / "ucagent" / "lang" / "zh" / "doc" / "Formal_Doc"


def _resolved_cfg(dut: str = "Demo", output: str = "formal_out") -> dict:
    """Build the minimum already-resolved checker configuration."""

    return {"_temp_cfg": {"DUT": dut, "OUT": output}}


def _write_runtime_config(workspace: Path, dut: str, output: str) -> None:
    """Write a valid runtime snapshot for a standalone formal Skill consumer."""

    import_root = Path(ucagent.__file__).resolve().parent.parent
    metadata = workspace / ".ucagent"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / "runtime_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": dut,
                "OUT": output,
                "test_output_dir": f"{output}/tests",
                "ucagent_python_path": str(import_root),
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_counterexample_workspace(workspace: Path, assertion: str) -> None:
    """Create a minimal formal record and one executable replay test."""

    output = workspace / "formal_out"
    tests = output / "tests"
    rtl = workspace / "Demo"
    tests.mkdir(parents=True)
    rtl.mkdir()
    (rtl / "Demo.sv").write_text("module Demo; endmodule\n", encoding="utf-8")
    (output / ".formal_records.yaml").write_text(
        """dut: Demo
analysis:
  tt_entries: []
  fa_entries:
    - id: FA-001
      prop_name: A_CK_BUG
      analysis: observed output violates the design equation
      resolution: RTL_BUG
""",
        encoding="utf-8",
    )
    (tests / "conftest.py").write_text(
        "class _Signal:\n"
        "    value = 0\n\n"
        "class _Dut:\n"
        "    a = _Signal()\n"
        "    y = _Signal()\n"
        "    def Step(self, cycles):\n"
        "        return cycles\n"
        "    def Finish(self):\n"
        "        return None\n\n"
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def dut():\n"
        "    return _Dut()\n",
        encoding="utf-8",
    )
    (tests / "test_Demo_counterexample.py").write_text(
        "def test_cex_bug(dut):\n"
        "    dut.a.value = 1\n"
        "    dut.Step(1)\n"
        "    observed = dut.y.value\n"
        "    expected = 1\n"
        "    try:\n"
        f"        {assertion}\n"
        "    finally:\n"
        "        dut.Finish()\n",
        encoding="utf-8",
    )


def test_formal_paths_use_resolved_config_after_checker_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Environment and process directory cannot redirect a Formal Checker."""

    monkeypatch.setenv("DUT", "WrongDut")
    monkeypatch.setenv("OUT", "wrong-output")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    checker = PlanningStructureChecker("Demo", cfg=_resolved_cfg())
    assert checker.paths is None
    checker.set_workspace(str(tmp_path))
    assert checker.paths is None
    checker.on_init()

    assert checker.paths.dut == "Demo"
    assert checker.paths.out == "formal_out"
    assert checker.paths.base == str(tmp_path / "formal_out")


def test_formal_paths_load_runtime_snapshot_without_environment_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Standalone Skill paths come exclusively from runtime_config.json."""

    _write_runtime_config(tmp_path, "SnapshotDut", "runs/formal-1")
    monkeypatch.setenv("DUT", "WrongDut")
    monkeypatch.setenv("OUT", "wrong-output")

    paths = FormalPaths.from_runtime_config(tmp_path)

    assert paths.dut == "SnapshotDut"
    assert paths.out == os.path.join("runs", "formal-1")
    assert paths.test_file == str(
        tmp_path / "runs" / "formal-1" / "tests" / "test_SnapshotDut_counterexample.py"
    )


@pytest.mark.parametrize(
    ("dut", "output"),
    [
        ("-option", "formal_out"),
        ("Demo\nInjected", "formal_out"),
        ('Demo"Injected', "formal_out"),
        ("Demo", "../outside"),
        ("Demo", "formal/-option"),
        ("Demo", "formal\noutput"),
    ],
)
def test_formal_paths_reject_injection_and_workspace_escape(
    tmp_path: Path, dut: str, output: str
) -> None:
    """DUT and output values cannot become shell, Tcl, or option injections."""

    with pytest.raises(ValueError):
        FormalPaths.from_resolved_config(tmp_path, _resolved_cfg(dut, output))


def test_formalmc_undecided_status_is_parsed_and_persisted(tmp_path: Path) -> None:
    """An Undec result remains explicit instead of disappearing as a pass."""

    log_path = tmp_path / "avis.log"
    log_path.write_text(
        "  1 top.A_CK_OK : Pass\n"
        "  2 top.A_CK_WAIT : Undec\n"
        "  3 top.C_CK_REACH : Fail\n"
        "Info-P016: property top.A_CK_DEPTH is UNKNOWN\n",
        encoding="utf-8",
    )

    assert validate_log_has_results(log_path.read_text(encoding="utf-8")) is True
    parsed = parse_avis_log(str(log_path))
    assert parsed == {
        "pass": ["A_CK_OK"],
        "trivially_true": [],
        "false": [],
        "cover_pass": [],
        "cover_fail": ["C_CK_REACH"],
        "undecided": ["A_CK_WAIT", "A_CK_DEPTH"],
    }
    records = FormalRecords(dut="Demo")
    update_records_run_results(records, parsed, str(log_path))
    assert records.run_results.undecided_properties == ["A_CK_WAIT", "A_CK_DEPTH"]
    assert records.run_results.stats["undecided_count"] == 2
    assert records.run_results.iteration_history[-1].undecided_count == 2


def test_formal_config_uses_real_docs_and_has_no_made_up_tools() -> None:
    """Formal prompts reference the selected docs and remain usable without Skills."""

    raw = load_yaml_with_env_vars(str(FORMAL_CONFIG))
    assert raw["guide_doc"] == {
        "path": "{GUIDE_DOC}",
        "source": "Formal_Doc",
        "enable": True,
    }
    rendered = json.dumps(raw, ensure_ascii=False)
    assert "GenerateChecker" not in rendered
    assert "GenerateFormalScript" not in rendered
    assert "技能禁用时" in rendered
    assert "Checker 已自动生成" not in rendered

    expected_docs = {
        "functions_and_checks.md",
        "sva_property.md",
        "checker_module.md",
        "env_analysis.md",
        "counterexample.md",
        "bug_report.md",
        "coi_coverage.md",
        "formal_summary.md",
    }
    assert all(name in rendered for name in expected_docs)
    assert all((FORMAL_DOCS / name).is_file() for name in expected_docs)

    referenced = set()
    for value in raw["mission"]["prompt"].values():
        if isinstance(value, str):
            referenced.update(
                match.split("Guide_Doc/", 1)[1]
                for match in value.split()
                if "Guide_Doc/" in match and match.endswith(".md")
            )
    for stage in raw["stage"]:
        for reference in stage.get("reference_files", []):
            if isinstance(reference, str) and reference.startswith("Guide_Doc/"):
                referenced.add(reference.removeprefix("Guide_Doc/"))
    assert referenced
    assert all((FORMAL_DOCS / name.strip("。`" )).is_file() for name in referenced)


@pytest.mark.parametrize(
    ("assertion", "expected_success", "expected_reproduction"),
    [
        ("assert observed == expected", True, "reproduced"),
        ("assert observed != expected", False, None),
    ],
)
def test_counterexample_checker_executes_tests_and_verifies_signed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assertion: str,
    expected_success: bool,
    expected_reproduction: str | None,
) -> None:
    """Static function presence cannot replace a real, signed replay result."""

    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    _write_counterexample_workspace(tmp_path, assertion)
    checker = CounterexampleTestgenChecker("Demo", cfg=_resolved_cfg())
    checker.set_workspace(str(tmp_path)).on_init()

    success, result = checker.do_check(timeout=30)

    assert success is expected_success
    evidence_path = Path(checker.paths.counterexample_evidence)
    assert evidence_path.is_file()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert len(evidence["integrity_hmac"]) == 64
    assert evidence["selected_functions"] == ["test_cex_bug"]
    assert evidence["test_results"] == [
        {
            "function": "test_cex_bug",
            "outcome": "failed" if expected_success else "passed",
        }
    ]
    if expected_success:
        assert result["reproduction_status"] == expected_reproduction
        assert result["execution_status"] == "completed"
        assert result["verification_status"] == "failed"
        evidence["test_results"][0]["outcome"] = "passed"
        verified, reason = checker._verify_evidence(
            evidence,
            ["A_CK_BUG"],
            ["test_cex_bug"],
        )
        assert verified is False
        assert "signature mismatch" in reason.lower()
    else:
        assert result["error_code"] == "COUNTEREXAMPLE_REPLAY_EVIDENCE_INVALID"


def test_counterexample_checker_rejects_unconditional_failure_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unconditional assertion cannot manufacture counterexample evidence."""

    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    _write_counterexample_workspace(tmp_path, "assert False")
    checker = CounterexampleTestgenChecker("Demo", cfg=_resolved_cfg())
    checker.set_workspace(str(tmp_path)).on_init()

    success, result = checker.do_check(timeout=30)

    assert success is False
    assert result["error_code"] == "COUNTEREXAMPLE_TEST_CONTRACT_INVALID"
    assert not Path(checker.paths.counterexample_evidence).exists()
