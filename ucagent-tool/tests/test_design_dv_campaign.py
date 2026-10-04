"""Campaign isolation, optimistic approvals, restart and honest closure contracts."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ucagent.eda.claude import build_claude_request, parse_claude_output, validate_cli_capabilities
from ucagent.eda.models import CommandSpec, RunRequest, SessionInput, ToolchainProfile
from ucagent.eda.runner import JobRunner
from ucagent.platform.campaign import (CampaignCreate, PpaResult, PpaTargets, ProposalCreate,
                                      RegressionTest, evaluate_ppa, select_regression)
from ucagent.server.campaign_service import CampaignConflict, CampaignService
from ucagent.server.platform_store import PlatformStore


@pytest.fixture
def campaign(tmp_path):
    """Create a real SQLite Campaign around a tiny independent RTL project."""
    source = tmp_path / "project"
    source.mkdir()
    (source / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    (source / "spec.md").write_text("No external ports.\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    store = PlatformStore(str(state))
    project = store.create_project(name="dut", source_root=str(source), config={})
    runtime = SimpleNamespace(store=store, state_dir=state,
        _profiles={"local": ToolchainProfile(id="local", tools={"python": sys.executable})})
    service = CampaignService(runtime)
    request = CampaignCreate(project_id=project["project_id"], name="DUT campaign", toolchain="local",
        inputs={"rtl": {"top": "dut", "sources": ["dut.sv"]}, "specifications": ["spec.md"]},
        formal_engine="none", lint_engine="none", synthesis_engine="none",
        equivalence_engine="none", budget_confirmed=True)
    return service, service.create(request), source


def proposal(campaign, name="dut.sv", content="module dut; wire a; endmodule\n"):
    """Construct an exact-hash replacement of one frozen input."""
    return ProposalCreate(campaign_id=campaign["id"], base_fingerprint=campaign["fingerprint"],
        purpose="semantic_optimization", rationale="Exercise isolated candidate review",
        requirements=["FG-interface"], changes=[{"path": name,
        "before_sha256": campaign["input_hashes"][name], "content": content}])


def test_campaign_complete_catalog_and_no_fake_success(campaign):
    """Disabled branches stay visible and a newly frozen input is not a pass."""
    service, data, _ = campaign
    assert len(data["stages"]) == 11
    assert data["verification_status"] == "unknown"
    assert data["ppa_status"] == "awaiting_target_approval"
    assert all(row["disabled_reason"] for row in data["stages"] if not row["enabled"])
    with pytest.raises(CampaignConflict, match="Approve"):
        service.transition(data["id"], "resume", 0)
    service.stage_action(data["id"], "specification", "approve", "Reviewed the source and specification")
    running = service.transition(data["id"], "resume", 0)
    assert running["state"] == "running"
    with pytest.raises(CampaignConflict, match="revision"):
        service.transition(data["id"], "pause", 0)


def test_proposal_keeps_source_and_rechecks_approval(campaign):
    """Approval is for testing, never automatic integration or verification pass."""
    service, data, source = campaign
    original = (source / "dut.sv").read_bytes()
    result = service.propose(proposal(data))
    assert (source / "dut.sv").read_bytes() == original
    assert "wire a" in result["diff"]
    approved = service.review_proposal(result["id"], "approve", data["fingerprint"], "Test this candidate")
    assert approved["state"] == "approved_for_testing"
    assert approved["integrated"] is False
    assert approved["verification_status"] == "unknown"


@pytest.mark.parametrize("target", ["source", "baseline", "candidate"])
def test_stale_or_tampered_input_blocks_review(campaign, target):
    """Every approval binds source, baseline and candidate identities."""
    service, data, source = campaign
    result = service.propose(proposal(data))
    roots = {"source": source, "baseline": service.root / data["id"] / "baseline",
             "candidate": service.root / data["id"] / "candidates" / result["id"]}
    (roots[target] / "dut.sv").write_text("module altered; endmodule\n", encoding="utf-8")
    with pytest.raises(CampaignConflict):
        service.review_proposal(result["id"], "approve", data["fingerprint"], "Review")


def test_protected_spec_and_iteration_budget(campaign):
    """Spec edits are explicit protected proposals and automatic attempts are bounded."""
    service, data, _ = campaign
    result = service.propose(proposal(data, "spec.md", "Proposed new specification\n"))
    assert result["protected"] is True
    service.propose(proposal(data))
    service.propose(proposal(data))
    with pytest.raises(CampaignConflict, match="budget"):
        service.propose(proposal(data))


def test_campaign_restart_preserves_gates(campaign):
    """Restart pauses coordination without losing stages, proposals or the event cursor."""
    service, data, _ = campaign
    service.stage_action(data["id"], "specification", "approve", "Reviewed")
    service.transition(data["id"], "resume", 0)
    service.propose(proposal(data))
    recovered = CampaignService(service.runtime).get(data["id"])
    service.store.recover_interrupted_runs()
    assert recovered["state"] == "paused"
    assert recovered["stages"][0]["approval_status"] == "approved"
    assert len(recovered["proposals"]) == 1
    assert service.store.get_run(data["id"])["execution_status"] == "queued"


def test_claude_no_unscoped_shell_or_last_session():
    """Noninteractive requests have exact session IDs, immutable stdin and restricted tools."""
    request = build_claude_request(workspace=Path.cwd(), output_dir=Path("out"),
        prompt_path=Path("prompt"), mcp_path=Path("mcp"), settings_path=Path("policy"),
        session_id="01234567-89ab-cdef-0123-456789abcdef", resume=True)
    assert "--resume" in request.command.argv
    assert not {"-c", "--bare", "--dangerously-skip-permissions"} & set(request.command.argv)
    assert request.resource_class == "claude" and request.stdin_path == Path("prompt.txt")
    assert "--tools=" in request.command.argv
    assert validate_cli_capabilities("--print")


@pytest.mark.parametrize("mutation,expected", [({}, "completed"),
    ({"session_id": "other"}, "error"), ({"is_error": True}, "error"),
    ({"permission_denials": [{}]}, "error"), ({"is_error": "false"}, "error")])
def test_claude_structured_result_is_never_a_verification_pass(mutation, expected):
    """CLI claims do not complete engineering gates, even when its call succeeds."""
    event = {"type": "result", "session_id": "id", "is_error": False, "subtype": "success", "result": "all tests passed"}
    event.update(mutation)
    parsed = parse_claude_output(json.dumps(event), return_code=0, session_id="id")
    assert parsed.execution_status == expected
    assert parsed.verification_status == "unknown"
    assert parse_claude_output("fabricated pass", return_code=0, session_id="id").execution_status == "error"


def test_runner_immutable_stdin_and_output_gate(tmp_path):
    """Use real child processes to validate stdin delivery and bounded output termination."""
    (tmp_path / "prompt.txt").write_text("approved input", encoding="utf-8")
    profile = ToolchainProfile(id="tests", tools={"python": sys.executable}, minimum_free_bytes=0,
                               minimum_root_free_bytes=0)
    runner = JobRunner(b"test-key")
    request = RunRequest(workspace=tmp_path, output_dir=Path("out"), resource_class="claude",
        command=CommandSpec(argv=["python", "-c", "import sys; print(sys.stdin.read())"], tool="python"),
        session_inputs=[SessionInput(source=Path("prompt.txt"), destination=Path("in.txt"))], stdin_path=Path("in.txt"))
    result = runner.run(request, profile)
    assert "approved input" in result.stdout_log.read_text()
    flood = request.model_copy(update={"output_dir": Path("flood"), "stdin_path": None,
        "command": CommandSpec(argv=["python", "-c", "print('x'*20000)"], tool="python"), "output_limit_bytes": 1024})
    result = runner.run(flood, profile)
    assert result.execution_status == "error"
    assert result.diagnostics[0]["error_code"] == "output_limit_exceeded"
    assert runner._profile_semaphore(profile, "claude") is not runner._profile_semaphore(profile, "eda")


def test_regression_selection_protects_exploration_and_reports_gaps():
    """Cheap historical tests cannot evict mandatory, bug or exploration coverage."""
    tests = [RegressionTest(id="cheap", cost_seconds=1, hit_bins={"a", "b"}),
             RegressionTest(id="slow", cost_seconds=10, hit_bins={"a"}),
             RegressionTest(id="bug", cost_seconds=2, bug_regression=True),
             RegressionTest(id="explore", cost_seconds=4, exploration=True)]
    result = select_regression(tests, {"a", "b", "unseen"})
    assert {item["id"] for item in result["selected"]} == {"cheap", "bug", "explore"}
    assert result["uncovered"] == ["unseen"]
    assert result["defect_detection_validated"] is False


def test_ppa_missing_activity_or_targets_never_pass():
    """PPA results require frozen context, measured values and functional acceptance."""
    result = PpaResult(candidate="candidate", tool="dc", library_hash="a"*64,
        constraints_hash="b"*64, scenario="isp", corner="TT", area=10, power_mw=1,
        equivalence="passed", regression="passed", artifact_id="measurement")
    targets = PpaTargets(baseline_artifact_id="baseline", library_hash="a"*64,
        constraints_hash="b"*64, scenario="isp", corner="TT", max_area=15, max_power_mw=2)
    assert evaluate_ppa(result, None)["status"] == "awaiting_target_approval"
    assert evaluate_ppa(result, targets)["status"] == "not_evaluated"
    measured = result.model_copy(update={"activity_hash": "c"*64, "frequency_mhz": 100, "annotation_percent": 96})
    assert evaluate_ppa(measured, targets)["status"] == "met"
    assert evaluate_ppa(measured.model_copy(update={"area": 20}), targets)["status"] == "not_met"
    assert evaluate_ppa(measured.model_copy(update={"corner": "SS"}), targets)["status"] == "incomparable"
    with pytest.raises(ValidationError):
        RegressionTest(id="bad", cost_seconds=float("nan"))
