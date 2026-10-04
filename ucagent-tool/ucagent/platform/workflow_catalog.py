"""Build a complete visual workflow catalog without filtering disabled stages."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from .project import AuthoringMode, Methodology, WorkflowFamily


_ENV_EXPRESSION = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*):\s*([^)]*?)\)")
_STAGE_FLAG_LINE = re.compile(
    r"^(?P<indent>[ ]*)(?P<key>ignore|skip):[ ]*(?P<value>.*?)(?:[ ]+#.*)?$"
)
_RAW_WORKFLOWS = (
    (
        "unitytest-guided",
        "UnityTest Guided",
        WorkflowFamily.SIMULATION,
        Methodology.UNITYTEST,
        AuthoringMode.GUIDED,
        "default.yaml",
        ("picker", "toffee", "simulator"),
    ),
    (
        "formal-guided",
        "FormalMC Guided",
        WorkflowFamily.FORMAL,
        Methodology.SYSTEMVERILOG,
        AuthoringMode.GUIDED,
        "formal.yaml",
        ("formal_engine", "sva"),
    ),
    (
        "unitytest-vibe",
        "UnityTest Vibe",
        WorkflowFamily.SIMULATION,
        Methodology.UNITYTEST,
        AuthoringMode.VIBE,
        "vibe.yaml",
        ("picker", "toffee", "simulator"),
    ),
    (
        "unitytest-incremental",
        "UnityTest Incremental",
        WorkflowFamily.SIMULATION,
        Methodology.UNITYTEST,
        AuthoringMode.INCREMENTAL,
        "inc.yaml",
        ("picker", "toffee", "simulator", "version_control"),
    ),
)


class CatalogModel(BaseModel):
    """Strict immutable base model for API-facing workflow catalog data."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class CheckerDescriptor(CatalogModel):
    """Expose a stable checker identity without leaking internal arguments."""

    name: str
    class_name: str | None = None


class StageDescriptor(CatalogModel):
    """Describe one visible workflow node, including inactive conditional nodes."""

    id: str
    workflow: str
    name: str
    description: str
    parent_id: str | None
    kind: Literal["stage", "group", "gate"]
    requires_human_approval: bool = False
    enabled: bool
    disabled_reason: str | None = None
    condition: str | None = None
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    checker: tuple[CheckerDescriptor, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    children: tuple["StageDescriptor", ...] = ()


class WorkflowDescriptor(CatalogModel):
    """Describe one workflow and its complete ordered stage tree."""

    id: str
    name: str
    family: WorkflowFamily
    methodology: Methodology
    authoring_mode: AuthoringMode
    description: str
    source: str
    required_capabilities: tuple[str, ...]
    stages: tuple[StageDescriptor, ...]


class WorkflowCatalog(CatalogModel):
    """Versioned response model returned by the workflow catalog endpoint."""

    schema_version: Literal[1] = 1
    workflows: tuple[WorkflowDescriptor, ...]


StageDescriptor.model_rebuild()


def _yaml_scalar(value: Any) -> str:
    """Serialize one trusted option as a YAML scalar for source preprocessing."""
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        raise TypeError("workflow catalog options must be YAML scalar values")
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    return repr(value)


def _parse_default_scalar(value: str) -> Any:
    """Parse an environment-expression default as a safe YAML scalar."""
    parsed = yaml.safe_load(value)
    if isinstance(parsed, (dict, list)):
        raise ValueError("workflow option defaults must be scalar values")
    return parsed


def _prepare_raw_yaml(
    source: str,
    options: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Parse raw YAML while preserving stage ignore and skip expressions."""
    conditions: dict[str, str] = {}
    prepared_lines: list[str] = []
    for line in source.splitlines():
        flag_match = _STAGE_FLAG_LINE.match(line)
        if flag_match:
            value = flag_match.group("value").strip()
            sentinel = f"__UCAGENT_STAGE_CONDITION_{len(conditions)}__"
            conditions[sentinel] = value
            prepared_lines.append(
                f"{flag_match.group('indent')}{flag_match.group('key')}: {json.dumps(sentinel)}"
            )
        else:
            prepared_lines.append(line)
    prepared = "\n".join(prepared_lines)

    def substitute(match: re.Match[str]) -> str:
        """Resolve a non-stage expression from explicit options or its source default."""
        name = match.group(1)
        default = _parse_default_scalar(match.group(2))
        return _yaml_scalar(options.get(name, default))

    prepared = _ENV_EXPRESSION.sub(substitute, prepared)
    payload = yaml.safe_load(prepared)
    if not isinstance(payload, dict):
        raise ValueError("workflow YAML must contain one mapping")
    return payload, conditions


def _evaluate_stage_flag(
    value: Any,
    conditions: Mapping[str, str],
    options: Mapping[str, Any],
) -> tuple[bool, str]:
    """Evaluate one restricted stage flag and return its original expression."""
    expression = conditions.get(value, value) if isinstance(value, str) else value
    if isinstance(expression, bool):
        return expression, str(expression).lower()
    if expression is None:
        return False, "false"
    if not isinstance(expression, str):
        raise ValueError(f"unsupported workflow stage condition: {expression!r}")
    stripped = expression.strip()
    negate = stripped.startswith("not ")
    body = stripped[4:].strip() if negate else stripped
    match = _ENV_EXPRESSION.fullmatch(body)
    if match:
        selected = options.get(match.group(1), _parse_default_scalar(match.group(2)))
    else:
        selected = _parse_default_scalar(body)
    if not isinstance(selected, bool):
        raise ValueError(f"stage condition must resolve to a boolean: {expression!r}")
    return (not selected if negate else selected), stripped


def _string_tuple(value: Any) -> tuple[str, ...]:
    """Project a YAML scalar or sequence into a stable tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _checker_descriptors(value: Any) -> tuple[CheckerDescriptor, ...]:
    """Project raw checker declarations into bounded public identities."""
    if not isinstance(value, list):
        return ()
    descriptors: list[CheckerDescriptor] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        class_name = item.get("clss")
        descriptors.append(
            CheckerDescriptor(
                name=item["name"],
                class_name=class_name if isinstance(class_name, str) else None,
            )
        )
    return tuple(descriptors)


def _stage_capabilities(
    workflow_id: str,
    stage_name: str,
    checkers: tuple[CheckerDescriptor, ...],
) -> tuple[str, ...]:
    """Infer coarse adapter capabilities used by a visual preflight."""
    searchable = " ".join(
        [stage_name, *(checker.name for checker in checkers), *(checker.class_name or "" for checker in checkers)]
    ).casefold()
    capabilities: set[str] = set()
    if workflow_id.startswith("formal"):
        capabilities.update(("formal_engine", "sva"))
    else:
        capabilities.update(("picker", "toffee", "simulator"))
    if "coverage" in searchable:
        capabilities.add("coverage")
    if "waveform" in searchable or "bug" in searchable:
        capabilities.add("waveform")
    if "counterexample" in searchable or "cex" in searchable:
        capabilities.update(("cex_replay", "simulator"))
    if "human" in searchable or "approve" in searchable:
        capabilities.add("human_approval")
    if "commit" in searchable or "workspace" in searchable and "incremental" in workflow_id:
        capabilities.add("version_control")
    return tuple(sorted(capabilities))


def _build_stage_tree(
    raw_stages: Any,
    *,
    workflow_id: str,
    conditions: Mapping[str, str],
    options: Mapping[str, Any],
    parent_id: str | None = None,
    parent_enabled: bool = True,
    parent_disabled_reason: str | None = None,
    path: tuple[str, ...] = (),
) -> tuple[StageDescriptor, ...]:
    """Recursively build a complete stage tree without dropping disabled nodes."""
    if not isinstance(raw_stages, list):
        return ()
    descriptors: list[StageDescriptor] = []
    sibling_names: set[str] = set()
    for raw_stage in raw_stages:
        if not isinstance(raw_stage, dict) or not isinstance(raw_stage.get("name"), str):
            continue
        name = raw_stage["name"]
        if name in sibling_names:
            raise ValueError(f"duplicate stage name under {parent_id or workflow_id}: {name}")
        sibling_names.add(name)
        stage_path = (*path, name)
        stage_id = f"{workflow_id}:{'/'.join(stage_path)}"
        ignored = False
        skipped = False
        ignore_expression: str | None = None
        skip_expression: str | None = None
        condition_parts: list[str] = []
        if "ignore" in raw_stage:
            ignored, ignore_expression = _evaluate_stage_flag(raw_stage["ignore"], conditions, options)
            condition_parts.append(f"ignore when {ignore_expression}")
        if "skip" in raw_stage:
            skipped, skip_expression = _evaluate_stage_flag(raw_stage["skip"], conditions, options)
            condition_parts.append(f"skip when {skip_expression}")
        enabled = parent_enabled and not ignored and not skipped
        if not parent_enabled:
            disabled_reason = parent_disabled_reason or "parent stage is disabled"
        elif ignored:
            disabled_reason = f"ignore condition evaluated true: {ignore_expression}"
        elif skipped:
            disabled_reason = f"skip condition evaluated true: {skip_expression}"
        else:
            disabled_reason = None
        checkers = _checker_descriptors(raw_stage.get("checker"))
        raw_children = raw_stage.get("stage")
        human_gate = raw_stage.get("need_human_check") is True
        if isinstance(raw_children, list) and raw_children:
            kind: Literal["stage", "group", "gate"] = "group"
        elif human_gate:
            kind = "gate"
        else:
            kind = "stage"
        children = _build_stage_tree(
            raw_children,
            workflow_id=workflow_id,
            conditions=conditions,
            options=options,
            parent_id=stage_id,
            parent_enabled=enabled,
            parent_disabled_reason=disabled_reason,
            path=stage_path,
        )
        description = raw_stage.get("desc")
        descriptors.append(
            StageDescriptor(
                id=stage_id,
                workflow=workflow_id,
                name=name,
                description=description if isinstance(description, str) else name,
                parent_id=parent_id,
                kind=kind,
                requires_human_approval=human_gate,
                enabled=enabled,
                disabled_reason=disabled_reason,
                condition="; ".join(condition_parts) or None,
                inputs=_string_tuple(raw_stage.get("reference_files")),
                outputs=_string_tuple(raw_stage.get("output_files")),
                checker=checkers,
                required_capabilities=_stage_capabilities(workflow_id, name, checkers),
                children=children,
            )
        )
    return tuple(descriptors)


def _manual_stage(
    workflow_id: str,
    name: str,
    description: str,
    capabilities: tuple[str, ...],
    *,
    parent_id: str | None = None,
    kind: Literal["stage", "group", "gate"] = "stage",
    enabled: bool = True,
    disabled_reason: str | None = None,
    condition: str | None = None,
    inputs: tuple[str, ...] = (),
    outputs: tuple[str, ...] = (),
    children: tuple[StageDescriptor, ...] = (),
) -> StageDescriptor:
    """Construct one canonical non-YAML workflow stage."""
    stage_id = f"{workflow_id}:{name}" if parent_id is None else f"{parent_id}/{name}"
    return StageDescriptor(
        id=stage_id,
        workflow=workflow_id,
        name=name,
        description=description,
        parent_id=parent_id,
        kind=kind,
        enabled=enabled,
        disabled_reason=disabled_reason,
        condition=condition,
        inputs=inputs,
        outputs=outputs,
        checker=(),
        required_capabilities=capabilities,
        children=children,
    )


def _canonical_systemverilog_workflow() -> WorkflowDescriptor:
    """Return the native SystemVerilog/VCS workflow shown in the catalog."""
    workflow_id = "systemverilog-vcs"
    stages = (
        _manual_stage(
            workflow_id,
            "preflight",
            "Validate project paths, VCS availability, license capacity, and disk space.",
            ("vcs", "license", "disk"),
            inputs=(".ucagent/project.yaml",),
        ),
        _manual_stage(
            workflow_id,
            "compile_elaborate",
            "Compile and elaborate the native SystemVerilog testbench in an isolated directory.",
            ("vcs",),
            inputs=("design.sources", "design.filelists"),
            outputs=("simv", "compile.log"),
        ),
        _manual_stage(
            workflow_id,
            "run_matrix",
            "Run the declared test and seed matrix while preserving verification failures.",
            ("vcs",),
            inputs=("simv", "simulation.suites", "simulation.seeds"),
            outputs=("test-results.json", "run.log"),
        ),
        _manual_stage(
            workflow_id,
            "coverage_merge",
            "Merge enabled code and assertion coverage with URG.",
            ("urg", "coverage"),
            enabled=False,
            disabled_reason="simulation.coverage is empty",
            condition="simulation.coverage is non-empty",
            inputs=("coverage databases",),
            outputs=("coverage-report",),
        ),
        _manual_stage(
            workflow_id,
            "waveform_artifacts",
            "Publish the configured waveform as a run-scoped artifact.",
            ("waveform",),
            enabled=False,
            disabled_reason="simulation.waveform is none",
            condition="simulation.waveform != none",
            outputs=("waveform artifact",),
        ),
        _manual_stage(
            workflow_id,
            "signoff",
            "Verify normalized results and the signed run manifest.",
            ("evidence_manifest",),
            kind="gate",
            inputs=("test-results.json", "manifest.json"),
        ),
    )
    return WorkflowDescriptor(
        id=workflow_id,
        name="Native SystemVerilog with VCS",
        family=WorkflowFamily.SIMULATION,
        methodology=Methodology.SYSTEMVERILOG,
        authoring_mode=AuthoringMode.GUIDED,
        description="Structured native SystemVerilog compilation and regression with VCS.",
        source="canonical",
        required_capabilities=("vcs",),
        stages=stages,
    )


def _canonical_uvm_workflow() -> WorkflowDescriptor:
    """Return the UVM 1.2/VCS workflow shown in the catalog."""
    workflow_id = "uvm-vcs"
    regression_id = f"{workflow_id}:regression"
    regression_children = tuple(
        StageDescriptor(
            id=f"{regression_id}/{level.lower()}",
            workflow=workflow_id,
            name=level.lower(),
            description=f"Run the declared {level} test and seed matrix.",
            parent_id=regression_id,
            kind="stage",
            enabled=True,
            condition=f"a {level} suite is declared",
            inputs=(f"simulation.suites[level={level}]", "simv"),
            outputs=(f"{level.lower()}-test-results.json",),
            required_capabilities=("uvm", "vcs"),
        )
        for level in ("UT", "IT", "ST")
    )
    stages = (
        _manual_stage(
            workflow_id,
            "preflight",
            "Validate UVM 1.2, VCS, license capacity, project paths, and disk space.",
            ("uvm", "vcs", "license", "disk"),
            inputs=(".ucagent/project.yaml",),
        ),
        _manual_stage(
            workflow_id,
            "environment_scaffold",
            "Generate and structurally validate a UVM 1.2 environment when one is requested.",
            ("uvm",),
            condition="project requests a generated environment",
            outputs=("UVM source tree", "files.f"),
        ),
        _manual_stage(
            workflow_id,
            "environment_import",
            "Inspect an existing UVM environment without rewriting it.",
            ("uvm",),
            enabled=False,
            disabled_reason="no imported UVM environment is selected",
            condition="project selects an imported environment",
            inputs=("existing UVM source tree",),
        ),
        _manual_stage(
            workflow_id,
            "compile_elaborate",
            "Compile the UVM environment and design in an isolated VCS directory.",
            ("uvm", "vcs"),
            inputs=("UVM source tree", "design.sources", "design.filelists"),
            outputs=("simv", "compile.log"),
        ),
        StageDescriptor(
            id=regression_id,
            workflow=workflow_id,
            name="regression",
            description="Execute UT, IT, and ST suites as independent test and seed jobs.",
            parent_id=None,
            kind="group",
            enabled=True,
            required_capabilities=("uvm", "vcs"),
            children=regression_children,
        ),
        _manual_stage(
            workflow_id,
            "result_observer",
            "Normalize UVM reports, process status, and explicit project success evidence.",
            ("uvm",),
            inputs=("run.log",),
            outputs=("test-results.json",),
        ),
        _manual_stage(
            workflow_id,
            "coverage_merge",
            "Merge enabled VCS coverage and publish normalized metrics with URG.",
            ("urg", "coverage"),
            enabled=False,
            disabled_reason="simulation.coverage is empty",
            condition="simulation.coverage is non-empty",
            inputs=("coverage databases",),
            outputs=("coverage-report", "coverage.json"),
        ),
        _manual_stage(
            workflow_id,
            "waveform_artifacts",
            "Publish FSDB or VPD without converting or parsing FSDB in the browser.",
            ("waveform", "verdi_artifact"),
            enabled=False,
            disabled_reason="simulation.waveform is none",
            condition="simulation.waveform != none",
            outputs=("waveform artifact",),
        ),
        _manual_stage(
            workflow_id,
            "signoff",
            "Verify normalized UVM results, coverage mapping, and signed evidence.",
            ("evidence_manifest",),
            kind="gate",
            inputs=("test-results.json", "manifest.json"),
        ),
    )
    return WorkflowDescriptor(
        id=workflow_id,
        name="UVM 1.2 with VCS",
        family=WorkflowFamily.SIMULATION,
        methodology=Methodology.UVM,
        authoring_mode=AuthoringMode.GUIDED,
        description="Generated or imported UVM 1.2 environments with UT, IT, and ST regression.",
        source="canonical",
        required_capabilities=("uvm", "vcs", "urg"),
        stages=stages,
    )


def _formal_adapter_stages(workflow_id: str, engine: str = "formalmc") -> tuple[StageDescriptor, ...]:
    """Show the original FormalMC default and every explicitly selectable alternative."""

    dispatch_id = f"{workflow_id}:toolchain_dispatch"
    selected_engine = "formal_mc" if engine == "formalmc" else engine
    engine_children = tuple(
        StageDescriptor(
            id=f"{dispatch_id}/{engine}",
            workflow=workflow_id,
            name=engine,
            description=description,
            parent_id=dispatch_id,
            kind="stage",
            enabled=engine == selected_engine,
            disabled_reason=None if engine == selected_engine else "This alternative requires explicit engine selection; no automatic fallback is used.",
            condition=f"formal.engine == {'formalmc' if engine == 'formal_mc' else engine}",
            inputs=("design.filelists", "formal.property_sets"),
            outputs=("formal report", "proof database", "counterexample"),
            required_capabilities=(capability, "sva"),
        )
        for engine, description, capability in (
            (
                "vc_formal",
                "Run the fixed VC Formal FPV batch lifecycle and normalize report_fv output.",
                "vc_formal",
            ),
            (
                "formal_mc",
                "Run the declared FormalMC Tcl recipe and normalize all property outcomes.",
                "formal_mc",
            ),
            (
                "sby",
                "Run bundled SBY/SMTBMC/Z3 in prove, bounded-check or cover mode; retain typed property results and VCD traces.",
                "sby",
            ),
        )
    )
    return (
        StageDescriptor(
            id=dispatch_id,
            workflow=workflow_id,
            name="toolchain_dispatch",
            description="Use the original FormalMC Tcl workflow by default; alternate engines are never selected automatically.",
            parent_id=None,
            kind="group",
            enabled=True,
            required_capabilities=("formal_engine",),
            children=engine_children,
        ),
        _manual_stage(
            workflow_id,
            "counterexample_dynamic_replay",
            "Translate an actual falsified-property trace and rerun it through UVM or UnityTest.",
            ("cex_replay", "simulator"),
            enabled=False,
            disabled_reason="Dynamic replay requires a falsified property and an explicit replay target.",
            condition="formal.cex_replay.enabled and a property is falsified",
            inputs=("signed counterexample", "declared replay target"),
            outputs=("dynamic replay manifest", "test result", "waveform"),
        ),
    )


def load_workflow_catalog(
    options: Mapping[str, Any] | None = None,
    config_dir: str | Path | None = None,
) -> WorkflowCatalog:
    """Load all raw built-in stages plus canonical SystemVerilog and UVM flows."""
    selected_options = dict(options or {})
    source_dir = (
        Path(config_dir).expanduser().resolve()
        if config_dir is not None
        else Path(__file__).resolve().parents[1] / "lang" / "zh" / "config"
    )
    workflows: list[WorkflowDescriptor] = []
    for (
        workflow_id,
        name,
        family,
        methodology,
        authoring_mode,
        filename,
        required_capabilities,
    ) in _RAW_WORKFLOWS:
        path = source_dir / filename
        payload, conditions = _prepare_raw_yaml(path.read_text(encoding="utf-8"), selected_options)
        formal_engine = selected_options.get("FORMAL_ENGINE", "formalmc")
        if workflow_id == "formal-guided" and formal_engine == "sby":
            from ucagent.eda.formal_workflow import select_formal_engine

            payload = select_formal_engine(payload)
            name = "SBY Guided"
        stages = _build_stage_tree(
            payload.get("stage"),
            workflow_id=workflow_id,
            conditions=conditions,
            options=selected_options,
        )
        if workflow_id == "formal-guided":
            stages = (*stages, *_formal_adapter_stages(workflow_id, formal_engine))
        mission = payload.get("mission")
        mission_name = mission.get("name") if isinstance(mission, dict) else None
        workflows.append(
            WorkflowDescriptor(
                id=workflow_id,
                name=name,
                family=family,
                methodology=methodology,
                authoring_mode=authoring_mode,
                description=mission_name if isinstance(mission_name, str) else name,
                source=f"builtin:{filename}",
                required_capabilities=required_capabilities,
                stages=stages,
            )
        )
    workflows.extend((_canonical_systemverilog_workflow(), _canonical_uvm_workflow()))
    return WorkflowCatalog(workflows=tuple(workflows))


def iter_workflow_stages(workflow: WorkflowDescriptor) -> Iterator[StageDescriptor]:
    """Yield every stage in display order from a workflow's nested tree."""
    pending = list(reversed(workflow.stages))
    while pending:
        stage = pending.pop()
        yield stage
        pending.extend(reversed(stage.children))
