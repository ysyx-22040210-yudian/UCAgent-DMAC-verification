"""Read-only run planning and concise operational summaries for the workbench."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Literal, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from ucagent.eda.input_closure import resolve_vcs_filelist_closure
from ucagent.eda.adapters import get_adapter
from ucagent.platform.project import SbyOptions
from ucagent.eda.security import redact_data, resolve_within

if TYPE_CHECKING:
    from ucagent.server.api_platform import PlatformRuntime, RunCreateRequest


class ReadinessCheck(BaseModel):
    """Report one observable prerequisite and the action needed to repair it."""

    model_config = ConfigDict(extra="forbid")
    key: str
    status: Literal["passed", "warning", "blocked"]
    message: str
    action: str | None = None
    details: list[str] = Field(default_factory=list)


class RunPreview(BaseModel):
    """Describe a dry-run plan without creating runs, files, or tool processes."""

    model_config = ConfigDict(extra="forbid")
    ready: bool = False
    checks: list[ReadinessCheck] = Field(default_factory=list)
    job_count: int = 0
    test_count: int = 0
    matrix: list[dict[str, Any]] = Field(default_factory=list)
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    recipe: str = "native"


def run_defaults(project: dict[str, Any]) -> dict[str, Any]:
    """Project saved configuration onto editable run fields without inventing tests."""

    config = project.get("config") or {}
    workflow = config.get("workflow") or {}
    simulation = config.get("simulation") or {}
    formal = config.get("formal") or {}
    suites = simulation.get("suites") or []
    family = workflow.get("family", "simulation")
    methodology = workflow.get("methodology", "systemverilog")
    body = {
        "project_id": project["project_id"],
        "family": family,
        "methodology": methodology,
        "authoring_mode": workflow.get("authoring_mode", "guided"),
        "toolchain": config.get("toolchain", ""),
        "design": config.get("design") or {
            "top": "", "sources": [], "filelists": [], "include_dirs": [],
            "defines": [], "parameters": {},
        },
    }
    if family == "formal":
        clock = formal.get("clock") or {}
        reset = formal.get("reset") or {}
        body["formal"] = {
            "engine": formal.get("engine", "formalmc"),
            "sby": (formal.get("sby") or SbyOptions().model_dump()) if formal.get("engine") == "sby" else None,
            "property_sets": formal.get("property_sets") or [],
            "clock": {} if formal.get("engine", "formalmc") in {"sby", "formalmc"} else {"signal": clock.get("signal"), "period": f"{clock['period_ns']}ns" if clock.get("period_ns") is not None else None},
            "reset": {} if formal.get("engine", "formalmc") in {"sby", "formalmc"} else {"signal": reset.get("signal"), "active": "high" if reset.get("active_level") == 1 else "low"},
            "cex_replay": formal.get("cex_replay") or {"enabled": False, "methodology": "uvm"},
        }
    else:
        # The editor selects one suite at a time; distinct suite memberships must
        # never be flattened into an unintended cross-product of all tests.
        selected = suites[0] if suites else {}
        body["simulation"] = {
            "simulator": simulation.get("simulator", "verilator" if methodology == "unitytest" else "vcs"),
            "uvm_version": simulation.get("uvm_version", "1.2"),
            "suites": [selected["level"]] if selected else [],
            "tests": selected.get("tests") or [],
            "unitytest_tests": simulation.get("unitytest_tests") or [],
            "seeds": selected.get("seeds") or simulation.get("seeds") or [1],
            "coverage": simulation.get("coverage") or [],
            "waveform": simulation.get("waveform", "none"),
            "plusargs": [],
        }
    return body


def preview_run(runtime: PlatformRuntime, request: RunCreateRequest) -> RunPreview:
    """Inspect exact selected inputs and adapter plans without starting EDA work."""

    result = RunPreview()
    project = runtime.store.get_project(request.project_id)
    if project is None:
        raise KeyError(request.project_id)
    profile = runtime._profiles.get(request.toolchain)
    if profile is None:
        result.checks.append(ReadinessCheck(key="toolchain", status="blocked", message="The selected toolchain is not configured.", action="toolchains"))
        return result
    try:
        config = runtime.build_project_config(request, project.get("config") or {})
        workspace = runtime.resolve_project_root(project["source_root"])
    except (ValueError, OSError) as exc:
        result.checks.append(ReadinessCheck(key="configuration", status="blocked", message=str(exc)[:1500], action="edit"))
        return result
    result.recipe = config.simulation.recipe.kind
    result.checks.append(ReadinessCheck(key="configuration", status="passed", message="Structured project configuration is valid."))

    required = (
        list(get_adapter("sby").required_tools) if request.family == "formal" and config.formal.engine == "sby"
        else ["vcf" if config.formal.engine == "vc_formal" else "formalmc"]
        if request.family == "formal"
        else ["picker", config.simulation.simulator, "python"]
        if request.methodology == "unitytest"
        else ["make", "vcs"] if result.recipe == "make" else ["vcs"]
    )
    if request.family == "simulation" and config.simulation.coverage and request.methodology != "unitytest":
        required.append("urg")
    public = next((item for item in runtime.toolchains_public() if item["id"] == profile.id), {})
    capabilities = {item["name"]: item for item in public.get("capabilities") or []}
    for tool in dict.fromkeys(required):
        capability = capabilities.get(tool, {})
        executable = profile.tools.get(tool)
        binary = bool(executable and (Path(executable).is_file() or shutil.which(executable)))
        license_state = capability.get("license_status", "unknown")
        blocked = not binary or license_state == "unavailable"
        result.checks.append(ReadinessCheck(
            key=f"tool:{tool}",
            status="blocked" if blocked else "warning" if tool in {"vcs", "vcf"} and license_state != "available" else "passed",
            message=("Executable is not configured or readable." if not binary else "The latest license checkout was unavailable." if blocked else "License capacity is busy or has not been probed." if tool in {"vcs", "vcf"} and license_state != "available" else "Selected tool is available."),
            action="toolchains" if blocked or license_state != "available" else None,
        ))

    free = shutil.disk_usage(workspace).free
    minimum = max(profile.minimum_free_bytes, int(float(runtime.settings.get("minimum_free_disk_gb", 10)) * 1024**3))
    result.checks.append(ReadinessCheck(key="disk", status="passed" if free >= minimum else "blocked", message=f"{free / 1024**3:.1f} GiB available; {minimum / 1024**3:.0f} GiB required.", action=None if free >= minimum else "settings"))
    declared = [*config.design.sources, *config.design.filelists, *config.design.include_dirs]
    if request.family == "formal":
        declared.extend(config.formal.property_sets)
    elif request.methodology == "unitytest":
        declared.extend(config.simulation.unitytest_tests)
    elif result.recipe == "make":
        declared.append(config.simulation.recipe.makefile)
    elif result.recipe == "executable":
        declared.append(config.simulation.recipe.executable)
    missing = []
    for path in dict.fromkeys(declared):
        try:
            resolve_within(workspace, path, must_exist=True)
        except (ValueError, OSError):
            missing.append(path)
    result.checks.append(ReadinessCheck(key="inputs", status="blocked" if missing or not declared else "passed", message="Declared input files are readable." if declared and not missing else "Required input files are missing or outside the project.", details=missing[:20], action="edit" if missing or not declared else None))

    try:
        if request.family == "simulation":
            jobs = runtime._build_run_requests("preview", workspace, config, request, profile)
            result.job_count = len(jobs)
            result.matrix = [{"test": job.test_name or config.design.top, "suite": job.suite, "seed": job.seed} for job in jobs if job.parser in {"uvm", "pytest"}]
            result.test_count = len(result.matrix)
            result.jobs = [{"tool": job.command.tool or result.recipe, "phase": job.metadata.get("phase") or job.parser or "execution", "command": redact_data(job.command.argv)} for job in jobs[:40]]
            if request.methodology == "uvm" and not request.simulation.tests:
                raise ValueError("Select at least one explicit UVM test class before starting a run.")
        else:
            if config.formal.engine == "sby":
                options = config.formal.sby or SbyOptions()
                get_adapter("sby").prepare(
                    workspace=workspace, top=config.design.top,
                    sources=[Path(item) for item in (*config.design.sources, *config.formal.property_sets)],
                    filelists=map(Path, config.design.filelists), include_dirs=map(Path, config.design.include_dirs),
                    defines=config.design.defines, parameters=config.design.parameters, **options.model_dump(),
                )
                result.jobs = [{"tool": "sby", "phase": options.mode, "command": ["sby", "-d", "<private-session>/proof", "<generated>/run.sby"]}]
                result.checks.append(ReadinessCheck(key="sby_harness", status="warning", message="SBY reads clock/reset assumptions from the HDL harness. It does not synthesize constraints from signal names. Only Yosys-supported HDL/assertions are accepted."))
            elif config.formal.engine == "formalmc":
                adapter = get_adapter("formal_mc")
                script = adapter.select_script(config.formal.property_sets)
                job = adapter.build_formal_request(workspace=workspace, output_dir=Path(".ucagent/preview-formal"), tcl_path=script)
                result.jobs = [{"tool": "formalmc", "phase": "formal", "command": redact_data(job.command.argv)}]
                result.checks.append(ReadinessCheck(key="formalmc_environment", status="warning", message="FormalMC reads the clock, reset and assumptions from the declared Tcl entry. Tool presence is not proof acceptance; inspect avis.log after a real run."))
            elif not config.formal.clock.signal or not config.formal.reset.signal:
                raise ValueError("Formal proof requires explicit clock and reset signals.")
            result.job_count = 1
        result.checks.append(ReadinessCheck(key="plan", status="passed", message=f"{result.job_count} execution jobs planned."))
    except (ValueError, OSError) as exc:
        result.checks.append(ReadinessCheck(key="plan", status="blocked", message=str(exc)[:1500], action="edit"))

    if declared and not missing and result.recipe == "native":
        try:
            closure = resolve_vcs_filelist_closure(workspace, filelists=map(Path, config.design.filelists), sources=map(Path, config.design.sources), include_dirs=map(Path, config.design.include_dirs))
            if not closure.complete:
                result.checks.append(ReadinessCheck(key="input_closure", status="warning", message="Some transitive dependencies could not be resolved statically; compile will validate them.", details=[str(item.get("error")) for item in closure.diagnostics[:8]], action="edit"))
        except (ValueError, OSError) as exc:
            result.checks.append(ReadinessCheck(key="input_closure", status="blocked", message=str(exc)[:1500], action="edit"))
    if request.methodology == "uvm" and config.simulation.reference_model is None:
        result.checks.append(ReadinessCheck(key="reference_model", status="warning", message="No user-provided reference model is declared. Smoke success alone does not establish functional correctness."))
    if request.family == "simulation" and config.simulation.coverage and not config.simulation.coverage_mapping:
        result.checks.append(ReadinessCheck(key="coverage_mapping", status="warning", message="Coverage is not mapped to FG/FC/CK requirements. Percentages alone do not establish requirement closure."))
    result.ready = all(check.status != "blocked" for check in result.checks)
    return result


def run_summary(run: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize real jobs and normalized results; never infer missing stage progress."""

    result = run.get("result") or {}
    tests = result.get("tests") or []
    properties = result.get("properties") or []
    completed = sum(item["execution_status"] in {"completed", "error", "timeout", "cancelled"} for item in jobs)
    diagnostics = result.get("diagnostics") or []
    if not diagnostics:
        diagnostics = [diagnostic for job in jobs for diagnostic in (job.get("result") or {}).get("diagnostics") or []]
    selected = next((item for item in diagnostics if item.get("error_code")), {})
    active = next((item for item in jobs if item["execution_status"] == "running"), None)
    failed_tests = sum(str(item.get("verification_status") or item.get("status")) == "failed" for item in tests)
    return {
        "jobs_total": len(jobs), "jobs_finished": completed,
        "tests_total": len(tests), "tests_failed": failed_tests,
        "tests_passed": sum(str(item.get("verification_status") or item.get("status")) == "passed" for item in tests),
        "properties_total": len(properties),
        "properties_falsified": sum(item.get("status") == "falsified" for item in properties),
        "coverage_metrics": len(result.get("coverage") or []),
        "artifacts_total": len(result.get("artifacts") or []),
        "diagnostic_code": selected.get("error_code"),
        "diagnostic": selected.get("error") or (run.get("diagnostic") or {}).get("error"),
        "next_action": selected.get("next_action"),
        "active_tool": active.get("kind") if active else None,
    }
