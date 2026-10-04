"""Typed Campaign inputs, immutable proposals, coverage selection and PPA gates."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .project import DesignConfig, ProjectPath


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class CampaignModel(BaseModel):
    """Reject unrecognized fields, nonfinite numbers and post-validation mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CampaignInputs(CampaignModel):
    """Keep synthesizable RTL distinct from simulation and formal harnesses."""

    rtl: DesignConfig
    testbench: DesignConfig | None = None
    formal_harness: DesignConfig | None = None
    specifications: tuple[ProjectPath, ...] = ()
    reference_models: tuple[ProjectPath, ...] = ()
    constraints: tuple[ProjectPath, ...] = ()

    @model_validator(mode="after")
    def separate_tops(self) -> "CampaignInputs":
        """Reject accidentally reusing a testbench as the synthesis top."""
        if self.testbench and self.rtl.top == self.testbench.top:
            raise ValueError("RTL and testbench tops must be explicitly distinct")
        if not self.rtl.sources and not self.rtl.filelists:
            raise ValueError("RTL inputs must not be empty")
        return self


class CampaignBudget(CampaignModel):
    """Bound all dispatched jobs, wall time, candidate bytes and automatic revisions."""

    max_jobs: int = Field(default=40, ge=1, le=10000)
    wall_seconds: int = Field(default=7200, ge=30, le=604800)
    max_candidate_bytes: int = Field(default=256 * 1024**2, ge=1024, le=10 * 1024**3)
    iterations_per_stage: int = Field(default=3, ge=1, le=3)
    no_progress_limit: int = Field(default=3, ge=1, le=3)


class CampaignCreate(CampaignModel):
    """Capture the user's explicit tools, input partitions and pre-approved budget."""

    project_id: Identifier
    name: str = Field(min_length=1, max_length=128)
    inputs: CampaignInputs
    toolchain: Identifier
    formal_engine: Literal["vc_formal", "sby", "formalmc", "none"]
    lint_engine: Literal["spyglass", "verilator", "yosys", "none"]
    synthesis_engine: Literal["dc", "yosys", "none"]
    equivalence_engine: Literal["formality", "eqy", "none"]
    technology_profile: Identifier | None = None
    budget: CampaignBudget = Field(default_factory=CampaignBudget)
    budget_confirmed: Literal[True]

    @model_validator(mode="after")
    def require_engine_inputs(self) -> "CampaignCreate":
        """Prevent guessed tops, technology libraries or implicit engine fallback."""
        if self.formal_engine != "none" and self.inputs.formal_harness is None:
            raise ValueError("formal_harness is required for the selected formal engine")
        if self.synthesis_engine != "none" and (not self.technology_profile or not self.inputs.constraints):
            raise ValueError("synthesis requires an explicit technology_profile and ISP-specific constraints")
        return self


class FileReplacement(CampaignModel):
    """Represent an exact UTF-8 candidate replacement, not a model-authored shell patch."""

    path: ProjectPath
    before_sha256: Digest
    content: str = Field(max_length=1024**2)


class ProposalCreate(CampaignModel):
    """Bind a candidate to a complete approved input version and stated intent."""

    campaign_id: Identifier
    base_fingerprint: Digest
    purpose: Literal["design", "bug_fix", "semantic_optimization", "verification_change"]
    rationale: str = Field(min_length=1, max_length=8000)
    requirements: tuple[str, ...] = Field(min_length=1, max_length=256)
    changes: tuple[FileReplacement, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def unique_paths(self) -> "ProposalCreate":
        """Reject order-dependent overlapping changes and execution configuration."""
        paths = [item.path for item in self.changes]
        if len(set(paths)) != len(paths):
            raise ValueError("proposal paths must be unique")
        for path in paths:
            if any(part.startswith(".") for part in path.split("/")):
                raise ValueError("proposals cannot modify hidden execution configuration")
        return self


class CoverageBin(CampaignModel):
    """Identify a coverage object within exact design and coverage-model versions."""

    id: Identifier
    design_hash: Digest
    model_hash: Digest
    name: str = Field(min_length=1, max_length=2048)
    kind: Literal["code", "assertion", "functional"]
    goal: int = Field(default=1, ge=1)
    requirements: tuple[str, ...] = ()


class CoverageObservation(CampaignModel):
    """Record per-test hits with explicit missing-data and signed-artifact identity."""

    bin_id: Identifier
    run_id: Identifier
    test: str = Field(min_length=1, max_length=256)
    seed: int = Field(ge=0)
    count: int | None = Field(default=None, ge=0)
    design_hash: Digest
    model_hash: Digest
    artifact_id: Identifier


class RegressionTest(CampaignModel):
    """Describe measured test cost and protected/exploration selection constraints."""

    id: str = Field(min_length=1, max_length=512)
    cost_seconds: float = Field(gt=0)
    mandatory: bool = False
    bug_regression: bool = False
    exploration: bool = False
    hit_bins: frozenset[Identifier] = frozenset()


def select_regression(tests: list[RegressionTest], required_bins: set[str]) -> dict:
    """Use deterministic cost-weighted set cover without dropping protected tests.

    Inputs must already be reconciled to one design/model version and backed by
    signed observations. This heuristic is not a trained ML model or a claim of
    equivalent defect detection on previously unseen inputs.
    """
    if len({test.id for test in tests}) != len(tests):
        raise ValueError("test identities must be unique")
    selected = []
    covered = set()
    remaining = {test.id: test for test in tests}
    for test in sorted(tests, key=lambda item: item.id):
        if test.mandatory or test.bug_regression or test.exploration:
            selected.append({"id": test.id, "reason": "protected", "new_bins": sorted(test.hit_bins - covered)})
            covered.update(test.hit_bins)
            remaining.pop(test.id)
    while required_bins - covered:
        ranked = sorted(remaining.values(), key=lambda item: (
            -len(item.hit_bins & (required_bins - covered)) / item.cost_seconds, item.id))
        if not ranked or not ranked[0].hit_bins & (required_bins - covered):
            break
        test = ranked[0]
        selected.append({"id": test.id, "reason": "new_bins_per_second",
                         "new_bins": sorted(test.hit_bins & (required_bins - covered))})
        covered.update(test.hit_bins)
        remaining.pop(test.id)
    chosen = {item["id"] for item in selected}
    return {"selected": selected, "uncovered": sorted(required_bins - covered),
            "predicted_seconds": sum(test.cost_seconds for test in tests if test.id in chosen),
            "algorithm": "cost_weighted_set_cover", "defect_detection_validated": False}


class PpaResult(CampaignModel):
    """Keep synthesis-level measurements, tool identity and power prerequisites explicit."""

    candidate: Identifier
    tool: Literal["dc", "yosys"]
    library_hash: Digest
    constraints_hash: Digest
    scenario: str = Field(min_length=1, max_length=256)
    corner: Literal["SS", "FF", "TT"]
    area: float | None = Field(default=None, ge=0)
    setup_slack_ns: float | None = None
    hold_slack_ns: float | None = None
    power_mw: float | None = Field(default=None, ge=0)
    activity_hash: Digest | None = None
    frequency_mhz: float | None = Field(default=None, gt=0)
    annotation_percent: float | None = Field(default=None, ge=0, le=100)
    equivalence: Literal["unknown", "passed", "failed", "inconclusive"] = "unknown"
    regression: Literal["unknown", "passed", "failed", "inconclusive"] = "unknown"
    artifact_id: Identifier


class PpaTargets(CampaignModel):
    """Represent explicitly approved, scenario-bound target conditions after baseline."""

    baseline_artifact_id: Identifier
    library_hash: Digest
    constraints_hash: Digest
    scenario: str = Field(min_length=1, max_length=256)
    corner: Literal["SS", "FF", "TT"]
    max_area: float | None = Field(default=None, gt=0)
    min_setup_slack_ns: float | None = None
    min_hold_slack_ns: float | None = None
    max_power_mw: float | None = Field(default=None, gt=0)
    min_annotation_percent: float = Field(default=95, ge=0, le=100)


def evaluate_ppa(result: PpaResult, targets: PpaTargets | None) -> dict:
    """Never confuse candidate generation, absent targets or incomplete power with success."""
    if targets is None:
        return {"status": "awaiting_target_approval", "gaps": []}
    if any(getattr(result, key) != getattr(targets, key)
           for key in ("library_hash", "constraints_hash", "scenario", "corner")):
        return {"status": "incomparable", "gaps": ["measurement_context_mismatch"]}
    missing, gaps, evaluated = [], [], 0
    for metric, threshold, direction in (
        ("area", targets.max_area, "max"), ("setup_slack_ns", targets.min_setup_slack_ns, "min"),
        ("hold_slack_ns", targets.min_hold_slack_ns, "min"), ("power_mw", targets.max_power_mw, "max")):
        if threshold is None:
            continue
        evaluated += 1
        value = getattr(result, metric)
        if metric == "power_mw" and (not result.activity_hash or not result.frequency_mhz
                                    or result.annotation_percent is None
                                    or result.annotation_percent < targets.min_annotation_percent):
            value = None
        if value is None:
            missing.append(metric)
        elif (direction == "max" and value > threshold) or (direction == "min" and value < threshold):
            gaps.append({"metric": metric, "observed": value, "target": threshold})
    if result.equivalence != "passed" or result.regression != "passed":
        missing.append("functional_acceptance")
    return {"status": "not_met" if gaps else "not_evaluated" if missing or not evaluated else "met",
            "gaps": gaps, "missing": missing, "level": "synthesis_only"}
