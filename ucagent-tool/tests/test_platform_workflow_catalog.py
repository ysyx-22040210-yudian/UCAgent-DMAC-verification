"""Focused tests for the complete visual workflow catalog."""

from __future__ import annotations

from ucagent.platform import iter_workflow_stages, load_workflow_catalog


def test_catalog_contains_raw_and_commercial_workflows() -> None:
    """Expose legacy YAML flows and canonical VCS/UVM flows in one catalog."""
    catalog = load_workflow_catalog()
    by_id = {workflow.id: workflow for workflow in catalog.workflows}

    assert catalog.schema_version == 1
    assert set(by_id) == {
        "unitytest-guided",
        "formal-guided",
        "unitytest-vibe",
        "unitytest-incremental",
        "systemverilog-vcs",
        "uvm-vcs",
    }
    assert by_id["unitytest-incremental"].authoring_mode == "incremental"
    assert by_id["unitytest-vibe"].authoring_mode == "vibe"
    assert by_id["uvm-vcs"].methodology == "uvm"
    assert by_id["systemverilog-vcs"].methodology == "systemverilog"


def test_disabled_raw_branches_remain_visible_with_reasons() -> None:
    """Keep Formal, CEX, Mock, and reference-model branches in the response tree."""
    catalog = load_workflow_catalog()
    by_id = {workflow.id: workflow for workflow in catalog.workflows}
    formal = {stage.name: stage for stage in iter_workflow_stages(by_id["formal-guided"])}
    unity = {stage.name: stage for stage in iter_workflow_stages(by_id["unitytest-guided"])}

    assert formal["counterexample_python_testgen"].enabled is False
    assert "CEX_CHECK" in formal["counterexample_python_testgen"].condition
    assert formal["counterexample_python_testgen"].disabled_reason
    assert formal["static_bug_validation"].enabled is False
    assert unity["mock_design_and_implementation"].enabled is False
    assert "IGNORE_MOCK_COMPONENT" in unity["mock_design_and_implementation"].condition
    assert unity["reference_model_implementation"].enabled is False
    assert "NEED_REF_MODEL" in unity["reference_model_implementation"].condition
    assert unity["line_coverage_analysis_and_improvement"].enabled is False


def test_formal_catalog_exposes_engine_and_dynamic_replay_branches() -> None:
    """Show VC Formal, FormalMC, and replay even before an engine is selected."""

    catalog = load_workflow_catalog()
    formal_workflow = next(
        workflow for workflow in catalog.workflows if workflow.id == "formal-guided"
    )
    formal = {stage.name: stage for stage in iter_workflow_stages(formal_workflow)}

    assert {"vc_formal", "formal_mc", "counterexample_dynamic_replay"} <= set(formal)
    assert formal["vc_formal"].enabled is False
    assert formal["vc_formal"].disabled_reason
    assert formal["formal_mc"].enabled is True
    assert formal["formal_mc"].disabled_reason is None
    assert formal["formal_mc"].condition == "formal.engine == formalmc"
    assert formal["counterexample_dynamic_replay"].disabled_reason


def test_explicit_options_enable_conditional_raw_branches() -> None:
    """Evaluate conditions from explicit settings without consulting process environment."""
    catalog = load_workflow_catalog(
        {
            "CEX_CHECK": False,
            "IGNORE_STATIC_CHECK": False,
            "IGNORE_MOCK_COMPONENT": False,
            "NEED_REF_MODEL": True,
            "SKIP_ENV_HUMAN_CHECK": False,
        }
    )
    by_id = {workflow.id: workflow for workflow in catalog.workflows}
    formal = {stage.name: stage for stage in iter_workflow_stages(by_id["formal-guided"])}
    unity = {stage.name: stage for stage in iter_workflow_stages(by_id["unitytest-guided"])}

    assert formal["counterexample_python_testgen"].enabled is True
    assert formal["static_bug_validation"].enabled is True
    assert unity["mock_design_and_implementation"].enabled is True
    assert unity["reference_model_implementation"].enabled is True
    assert unity["human_check_env_specification"].enabled is True


def test_stage_ids_and_parent_links_are_stable_and_unique() -> None:
    """Provide deterministic identities suitable for UI state and approval APIs."""
    first = load_workflow_catalog()
    second = load_workflow_catalog()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    for workflow in first.workflows:
        stages = tuple(iter_workflow_stages(workflow))
        ids = {stage.id for stage in stages}
        assert len(ids) == len(stages)
        for stage in stages:
            assert stage.workflow == workflow.id
            if stage.parent_id is not None:
                assert stage.parent_id in ids


def test_catalog_serialization_exposes_disabled_metadata() -> None:
    """Keep all UI contract fields in the serialized stage descriptor."""
    payload = load_workflow_catalog().model_dump(mode="json")
    stage = payload["workflows"][1]["stages"][7]

    assert set(stage) == {
        "id",
        "workflow",
        "name",
        "description",
        "parent_id",
        "kind",
        "requires_human_approval",
        "enabled",
        "disabled_reason",
        "condition",
        "inputs",
        "outputs",
        "checker",
        "required_capabilities",
        "children",
    }
