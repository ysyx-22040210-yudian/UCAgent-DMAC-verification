"""Canonical, non-secret project configuration for the visual platform."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Literal, Mapping

import yaml
from yaml.events import AliasEvent
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


PROJECT_CONFIG_RELATIVE_PATH = Path(".ucagent") / "project.yaml"
PROJECT_CONFIG_MAX_BYTES = 1_048_576
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_TOOLCHAIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_DEFINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_./:+,@%=-]+)?$")
_MAKE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_RECIPE_VALUE = re.compile(r"^[A-Za-z0-9_./:+,@%=-]+$")
_UVM_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
_SECRET_KEYS = {
    "access_key",
    "api_key",
    "license",
    "license_value",
    "lm_license_file",
    "passwd",
    "password",
    "private_key",
    "secret",
    "ssh_password",
    "token",
}
_SECRET_KEY_SUFFIXES = ("_api_key", "_password", "_private_key", "_secret", "_token")


def _validate_project_path(value: str) -> str:
    """Normalize one project-relative path and reject traversal or ambiguity."""
    if not isinstance(value, str):
        raise TypeError("project paths must be strings")
    if not value or value.strip() != value:
        raise ValueError("project paths must be non-empty and contain no surrounding whitespace")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in value
    ):
        raise ValueError("project paths must not contain control characters")
    if "'" in value or '"' in value:
        raise ValueError("project paths must not contain quote characters")
    normalized = value.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(value)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("project paths must be relative to the project root")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise ValueError("project paths must not contain empty, current, or parent components")
    if any(part.startswith("-") for part in posix_path.parts):
        raise ValueError("project paths must not contain components beginning with '-' (option injection)")
    if any(character in normalized for character in ("*", "?", "[", "]")):
        raise ValueError("project paths must identify concrete files or directories, not globs")
    return posix_path.as_posix()


ProjectPath = Annotated[str, AfterValidator(_validate_project_path)]
ScalarValue = str | int | float | bool


def _reject_secret_keys(values: Mapping[str, Any]) -> Mapping[str, Any]:
    """Reject fields conventionally used to carry credentials or license values."""
    for key in values:
        normalized = key.casefold()
        if normalized in _SECRET_KEYS or normalized.endswith(_SECRET_KEY_SUFFIXES):
            raise ValueError(f"secret-bearing field {key!r} is not allowed in project.yaml")
    return values


def _validate_identifier(value: str, field_name: str) -> str:
    """Validate a SystemVerilog identifier used by generated commands or sources."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a SystemVerilog identifier")
    return value


class StrictModel(BaseModel):
    """Base model that rejects undeclared project configuration fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class WorkflowFamily(str, Enum):
    """Supported top-level verification workflow families."""

    SIMULATION = "simulation"
    FORMAL = "formal"


class Methodology(str, Enum):
    """Supported verification methodologies independent of the selected tool."""

    UNITYTEST = "unitytest"
    SYSTEMVERILOG = "systemverilog"
    UVM = "uvm"


class AuthoringMode(str, Enum):
    """Supported ways an agent may author verification collateral."""

    GUIDED = "guided"
    INCREMENTAL = "incremental"
    VIBE = "vibe"


class DesignConfig(StrictModel):
    """Describe the design inputs consumed by all verification workflows."""

    top: str
    filelists: tuple[ProjectPath, ...] = ()
    sources: tuple[ProjectPath, ...] = ()
    include_dirs: tuple[ProjectPath, ...] = ()
    defines: tuple[str, ...] = ()
    parameters: dict[str, ScalarValue] = Field(default_factory=dict)

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str) -> str:
        """Require a concrete SystemVerilog top-level identifier."""
        return _validate_identifier(value, "design.top")

    @field_validator("defines")
    @classmethod
    def validate_defines(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require defines that can be passed as a single subprocess argument."""
        for value in values:
            if not _DEFINE.fullmatch(value):
                raise ValueError(f"invalid design define: {value!r}")
        if len(set(values)) != len(values):
            raise ValueError("design.defines must not contain duplicates")
        return values

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, values: dict[str, ScalarValue]) -> dict[str, ScalarValue]:
        """Reject ambiguous parameter names and credential-shaped entries."""
        _reject_secret_keys(values)
        for key in values:
            _validate_identifier(key, "design parameter")
        return values


class WorkflowConfig(StrictModel):
    """Select a workflow family, methodology, and independent authoring mode."""

    family: WorkflowFamily
    methodology: Methodology
    authoring_mode: AuthoringMode = AuthoringMode.GUIDED


class NativeRecipe(StrictModel):
    """Request adapter-native command construction from structured project data."""

    kind: Literal["native"] = "native"


class MakeRecipe(StrictModel):
    """Invoke one matrix-aware Make target without an intermediate shell."""

    kind: Literal["make"] = "make"
    makefile: ProjectPath = "Makefile"
    target: str
    variables: dict[str, str] = Field(default_factory=dict)
    test_variable: str
    seed_variable: str
    output_variable: str
    coverage_variable: str | None = None
    waveform_variable: str | None = None
    artifacts: tuple[ProjectPath, ...] = ()
    coverage_databases: tuple[ProjectPath, ...] = ()
    waveform_artifacts: dict[Literal["fsdb", "vpd"], tuple[ProjectPath, ...]] = Field(
        default_factory=dict
    )
    result_logs: tuple[ProjectPath, ...] = ()
    success_markers: tuple[str, ...] = ()

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        """Reject Make target syntax that could expand or select multiple targets."""
        if not _MAKE_NAME.fullmatch(value):
            raise ValueError("make target must contain only letters, digits, dot, underscore, or dash")
        return value

    @field_validator("variables")
    @classmethod
    def validate_variables(cls, values: dict[str, str]) -> dict[str, str]:
        """Accept only bounded scalar Make assignments without expansion syntax."""
        _reject_secret_keys(values)
        for key, value in values.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"invalid Make variable name: {key!r}")
            if not value or len(value) > 512 or not _RECIPE_VALUE.fullmatch(value):
                raise ValueError(f"unsafe Make variable value for {key!r}")
        return values

    @field_validator(
        "test_variable",
        "seed_variable",
        "output_variable",
        "coverage_variable",
        "waveform_variable",
    )
    @classmethod
    def validate_matrix_variable(cls, value: str | None) -> str | None:
        """Require an explicit inert Make variable name for each runner-owned value."""
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("matrix Make variables must be identifiers")
        _reject_secret_keys({value: None})
        return value

    @field_validator("artifacts", "coverage_databases", "result_logs")
    @classmethod
    def validate_output_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Keep generated outputs unique and separate from runner-owned evidence files."""
        if len(set(values)) != len(values):
            raise ValueError("recipe output paths must not contain duplicates")
        reserved = {"events.ndjson", "manifest.json", "stderr.log", "stdout.log"}
        for value in values:
            if PurePosixPath(value).parts[0] in reserved:
                raise ValueError(f"recipe output path is reserved by JobRunner: {value!r}")
        return values

    @field_validator("waveform_artifacts")
    @classmethod
    def validate_waveform_artifacts(
        cls,
        values: dict[str, tuple[str, ...]],
    ) -> dict[str, tuple[str, ...]]:
        """Require concrete, nonempty artifact sets for each declared waveform format."""

        reserved = {"events.ndjson", "manifest.json", "stderr.log", "stdout.log"}
        for waveform, paths in values.items():
            if not paths:
                raise ValueError(
                    f"recipe waveform_artifacts[{waveform!r}] must contain at least one path"
                )
            if len(set(paths)) != len(paths):
                raise ValueError(
                    f"recipe waveform_artifacts[{waveform!r}] must not contain duplicates"
                )
            for path in paths:
                if PurePosixPath(path).parts[0] in reserved:
                    raise ValueError(f"recipe output path is reserved by JobRunner: {path!r}")
        return values

    @field_validator("success_markers")
    @classmethod
    def validate_success_markers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Bound exact project-owned markers used to conclude an imported run passed."""
        if len(values) > 32 or len(set(values)) != len(values):
            raise ValueError("recipe success_markers must be unique and contain at most 32 entries")
        for value in values:
            if not value or len(value) > 256 or any(character in value for character in ("\x00", "\r", "\n")):
                raise ValueError("recipe success markers must be non-empty single-line strings")
        return values

    @model_validator(mode="after")
    def validate_matrix_contract(self) -> "MakeRecipe":
        """Reject ambiguous ownership between static and per-job Make assignments."""
        runner_variables = (
            self.test_variable,
            self.seed_variable,
            self.output_variable,
            self.coverage_variable,
            self.waveform_variable,
        )
        dynamic_names = {name for name in runner_variables if name is not None}
        if len(dynamic_names) != len([name for name in runner_variables if name is not None]):
            raise ValueError("all runner-owned Make variables must be distinct")
        overlap = sorted(dynamic_names.intersection(self.variables))
        if overlap:
            raise ValueError(
                "runner-owned Make variables must not also appear in variables: "
                + ", ".join(overlap)
            )
        if bool(self.coverage_variable) != bool(self.coverage_databases):
            raise ValueError(
                "coverage_variable and coverage_databases must be declared together"
            )
        if bool(self.waveform_variable) != bool(self.waveform_artifacts):
            raise ValueError(
                "waveform_variable and waveform_artifacts must be declared together"
            )

        output_declarations: list[tuple[str, PurePosixPath]] = []
        output_groups = {
            "artifacts": self.artifacts,
            "coverage_databases": self.coverage_databases,
            "result_logs": self.result_logs,
            **{
                f"waveform_artifacts.{waveform}": paths
                for waveform, paths in self.waveform_artifacts.items()
            },
        }
        for owner, paths in output_groups.items():
            for path in paths:
                candidate = PurePosixPath(path)
                conflict = next(
                    (
                        (previous_owner, previous_path)
                        for previous_owner, previous_path in output_declarations
                        if candidate == previous_path
                        or candidate in previous_path.parents
                        or previous_path in candidate.parents
                    ),
                    None,
                )
                if conflict is not None:
                    previous_owner, previous_path = conflict
                    raise ValueError(
                        f"recipe output paths {previous_path.as_posix()!r} ({previous_owner}) "
                        f"and {path!r} ({owner}) overlap"
                    )
                output_declarations.append((owner, candidate))
        return self


class ExecutableRecipe(StrictModel):
    """Invoke one project-owned executable directly with an argument vector."""

    kind: Literal["executable"] = "executable"
    executable: ProjectPath
    arguments: tuple[str, ...] = ()

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Reject control characters and shell operators from declared arguments."""
        for value in values:
            if (
                not value
                or len(value) > 512
                or re.search(r"[\x00\r\n;&|`<>]|\$\(", value)
                or ".." in value.replace("\\", "/").split("/")
                or PurePosixPath(value.replace("\\", "/")).is_absolute()
                or PureWindowsPath(value).drive
                or re.search(r"(?i)(?:password|secret|token|api[_-]?key|license)(?:=|$)", value)
            ):
                raise ValueError(f"unsafe executable argument: {value!r}")
        return values


Recipe = Annotated[NativeRecipe | MakeRecipe | ExecutableRecipe, Field(discriminator="kind")]


class SvReferenceModel(StrictModel):
    """Declare an existing, user-authored SystemVerilog reference model."""

    kind: Literal["sv"] = "sv"
    provenance: Literal["user_provided"] = "user_provided"
    sources: tuple[ProjectPath, ...] = Field(min_length=1)
    top: str | None = None

    @field_validator("top")
    @classmethod
    def validate_optional_top(cls, value: str | None) -> str | None:
        """Validate the optional reference-model top-level name."""
        return _validate_identifier(value, "reference_model.top") if value is not None else None


class DpiCReferenceModel(StrictModel):
    """Declare existing user-authored C or C++ sources exposed through DPI-C."""

    kind: Literal["dpi_c"] = "dpi_c"
    provenance: Literal["user_provided"] = "user_provided"
    sources: tuple[ProjectPath, ...] = Field(min_length=1)
    include_dirs: tuple[ProjectPath, ...] = ()
    libraries: tuple[ProjectPath, ...] = ()


class ExternalReferenceModel(StrictModel):
    """Declare a project-owned external reference-model executable."""

    kind: Literal["external"] = "external"
    provenance: Literal["user_provided"] = "user_provided"
    executable: ProjectPath
    arguments: tuple[str, ...] = ()

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Apply the same no-shell argument contract as executable recipes."""
        return ExecutableRecipe.validate_arguments(values)


ReferenceModel = Annotated[
    SvReferenceModel | DpiCReferenceModel | ExternalReferenceModel,
    Field(discriminator="kind"),
]


class RegressionSuite(StrictModel):
    """Describe one UT, IT, or ST regression suite and its named tests."""

    name: str
    level: Literal["UT", "IT", "ST"]
    tests: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = ()

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Require a stable suite identifier."""
        if not _TOOLCHAIN_ID.fullmatch(value):
            raise ValueError("suite name must be an identifier")
        return value

    @field_validator("tests")
    @classmethod
    def validate_tests(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique UVM-compatible test class names."""
        if len(set(values)) != len(values):
            raise ValueError("suite tests must not contain duplicates")
        for value in values:
            _validate_identifier(value, "suite test")
        return values

    @field_validator("seeds")
    @classmethod
    def validate_seeds(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        """Require positive, unique random seeds."""
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("suite seeds must be positive and unique")
        return values


class CoverageRequirementMapping(StrictModel):
    """Map deterministic URG scopes and metrics to one FG, FC, or CK requirement."""

    requirement_id: str
    scopes: tuple[str, ...] = Field(min_length=1)
    metrics: tuple[Literal["line", "cond", "tgl", "fsm", "branch", "assert"], ...] = Field(
        min_length=1
    )
    target_percent: float = Field(default=100.0, ge=0, le=100)

    @field_validator("requirement_id")
    @classmethod
    def validate_requirement_id(cls, value: str) -> str:
        """Require the canonical functional requirement tag namespace."""

        if not re.fullmatch(r"(?:FG|FC|CK)-[A-Za-z0-9][A-Za-z0-9_.-]{0,126}", value):
            raise ValueError("coverage requirement_id must begin with FG-, FC-, or CK-")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Accept bounded exact hierarchy prefixes without pattern execution."""

        if len(set(values)) != len(values):
            raise ValueError("coverage mapping scopes must not contain duplicates")
        for value in values:
            if (
                not value
                or len(value) > 256
                or value.strip() != value
                or any(char in value for char in ("\x00", "\r", "\n", "*", "?", "[", "]"))
            ):
                raise ValueError("coverage mapping scopes must be bounded exact hierarchy prefixes")
        return values

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Reject duplicate metric selectors within one requirement mapping."""

        if len(set(values)) != len(values):
            raise ValueError("coverage mapping metrics must not contain duplicates")
        return values


class SimulationConfig(StrictModel):
    """Configure simulation, regression, coverage, waveform, and reference-model inputs."""

    uvm_version: str = "1.2"
    simulator: Literal["verilator", "vcs"] = "verilator"
    recipe: Recipe = Field(default_factory=NativeRecipe)
    unitytest_tests: tuple[ProjectPath, ...] = ()
    suites: tuple[RegressionSuite, ...] = ()
    seeds: tuple[int, ...] = ()
    coverage: tuple[Literal["line", "cond", "tgl", "fsm", "branch", "assert"], ...] = ()
    coverage_mapping: tuple[CoverageRequirementMapping, ...] = ()
    waveform: Literal["none", "vcd", "fst", "vpd", "fsdb"] = "none"
    reference_model: ReferenceModel | None = None

    @field_validator("seeds")
    @classmethod
    def validate_seeds(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        """Require positive, unique global regression seeds."""
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("simulation.seeds must be positive and unique")
        return values

    @field_validator("uvm_version")
    @classmethod
    def validate_uvm_version(cls, value: str) -> str:
        """Accept a bounded inert version identifier for imported verification recipes."""
        if not _UVM_VERSION.fullmatch(value):
            raise ValueError("simulation.uvm_version must be a safe version identifier")
        return value

    @field_validator("coverage")
    @classmethod
    def validate_coverage(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Reject duplicate coverage metrics that would distort command construction."""
        if len(set(values)) != len(values):
            raise ValueError("simulation.coverage must not contain duplicates")
        return values

    @field_validator("unitytest_tests")
    @classmethod
    def validate_unitytest_tests(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique concrete project paths for UnityTest pytest selection."""

        if len(set(values)) != len(values):
            raise ValueError("simulation.unitytest_tests must not contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_suite_names(self) -> "SimulationConfig":
        """Require suite and requirement identifiers to be unique within a project."""
        names = [suite.name for suite in self.suites]
        if len(set(names)) != len(names):
            raise ValueError("simulation suite names must be unique")
        requirement_ids = [mapping.requirement_id for mapping in self.coverage_mapping]
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("simulation coverage requirement identifiers must be unique")
        return self


class FormalClock(StrictModel):
    """Describe the optional formal clock constraint."""

    signal: str | None = None
    edge: Literal["rising", "falling"] = "rising"
    period_ns: float | None = Field(default=None, gt=0)

    @field_validator("signal")
    @classmethod
    def validate_signal(cls, value: str | None) -> str | None:
        """Validate a configured formal clock signal identifier."""
        return _validate_identifier(value, "formal.clock.signal") if value is not None else None


class FormalReset(StrictModel):
    """Describe the optional formal reset constraint."""

    signal: str | None = None
    active_level: Literal[0, 1] = 0
    cycles: int = Field(default=2, ge=1)

    @field_validator("signal")
    @classmethod
    def validate_signal(cls, value: str | None) -> str | None:
        """Validate a configured formal reset signal identifier."""
        return _validate_identifier(value, "formal.reset.signal") if value is not None else None


class CounterexampleReplay(StrictModel):
    """Configure real dynamic replay for formal counterexamples."""

    enabled: bool = True
    methodology: Literal["uvm", "unitytest"] = "uvm"


class SbyOptions(StrictModel):
    """Bound open formal execution without accepting SBY/Yosys command strings."""

    mode: Literal["prove", "bmc", "cover"] = "prove"
    depth: int = Field(default=40, ge=1, le=100000, strict=True)
    timeout_seconds: int = Field(default=120, ge=1, le=86400, strict=True)
    multiclock: bool = Field(default=False, strict=True)


class FormalConfig(StrictModel):
    """Configure the selected formal engine, properties, and replay policy."""

    engine: Literal["formalmc", "vc_formal", "sby"] = "formalmc"
    sby: SbyOptions | None = None
    property_sets: tuple[ProjectPath, ...] = ()
    clock: FormalClock = Field(default_factory=FormalClock)
    reset: FormalReset = Field(default_factory=FormalReset)
    cex_replay: CounterexampleReplay = Field(default_factory=CounterexampleReplay)

    @model_validator(mode="after")
    def validate_engine_options(self) -> "FormalConfig":
        """Reject timing constraints or engine options that would otherwise be ignored."""
        if self.engine == "formalmc" and (self.clock.signal is not None or self.reset.signal is not None or self.clock.period_ns is not None):
            raise ValueError("FormalMC clock/reset constraints belong in the Tcl script (def_clk/def_rst); leave formal.clock and formal.reset empty")
        if self.engine != "sby" and self.sby is not None:
            raise ValueError("formal.sby is valid only for engine='sby'")
        if self.engine == "sby" and (self.clock.signal is not None or self.reset.signal is not None or self.clock.period_ns is not None):
            raise ValueError("SBY clock/reset assumptions belong in the HDL harness; leave formal.clock and formal.reset empty")
        return self


class ProjectConfig(StrictModel):
    """Canonical schema for ``<workspace>/.ucagent/project.yaml``."""

    schema_version: Literal[1] = 1
    design: DesignConfig
    workflow: WorkflowConfig
    toolchain: str
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    formal: FormalConfig = Field(default_factory=FormalConfig)

    @field_validator("toolchain")
    @classmethod
    def validate_toolchain(cls, value: str) -> str:
        """Require a stable host-owned toolchain profile identifier."""
        if not _TOOLCHAIN_ID.fullmatch(value):
            raise ValueError("toolchain must be a profile identifier, not a path or command")
        return value

    @model_validator(mode="after")
    def validate_native_uvm_version(self) -> "ProjectConfig":
        """Keep generated UVM and simulator-specific settings on their canonical contracts."""
        if (
            self.workflow.family == WorkflowFamily.SIMULATION
            and self.workflow.methodology == Methodology.UVM
            and isinstance(self.simulation.recipe, NativeRecipe)
            and self.simulation.uvm_version != "1.2"
        ):
            raise ValueError("native UVM workflows require simulation.uvm_version 1.2")
        if self.workflow.family == WorkflowFamily.SIMULATION:
            methodology = self.workflow.methodology
            simulator = self.simulation.simulator
            if methodology != Methodology.UNITYTEST and simulator != "vcs":
                raise ValueError(
                    "native SystemVerilog and UVM workflows require simulation.simulator='vcs'"
                )
            allowed_waveforms = (
                {"none", "fst", "vcd"}
                if methodology == Methodology.UNITYTEST and simulator == "verilator"
                else {"none", "fsdb"}
                if methodology == Methodology.UNITYTEST
                else {"none", "fsdb", "vpd"}
            )
            if self.simulation.waveform not in allowed_waveforms:
                choices = ", ".join(sorted(allowed_waveforms))
                raise ValueError(
                    f"{methodology}/{simulator} waveform must be one of: {choices}"
                )
            recipe = self.simulation.recipe
            if isinstance(recipe, MakeRecipe):
                if self.simulation.coverage and not recipe.coverage_variable:
                    raise ValueError(
                        "imported Make recipe does not declare coverage_variable and "
                        "coverage_databases"
                    )
                waveform = self.simulation.waveform
                if waveform != "none" and (
                    not recipe.waveform_variable
                    or waveform not in recipe.waveform_artifacts
                ):
                    raise ValueError(
                        f"imported Make recipe does not declare {waveform!r} waveform artifacts"
                    )
        return self


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that also rejects duplicate mapping keys."""

    def compose_node(self, parent: yaml.nodes.Node | None, index: int | None) -> yaml.nodes.Node:
        """Reject aliases so a small project file cannot expand into an alias graph."""
        if self.check_event(AliasEvent):
            raise ValueError("YAML aliases are not allowed in project.yaml")
        return super().compose_node(parent, index)


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> dict:
    """Construct a mapping while rejecting ambiguous duplicate YAML keys."""
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def project_config_path(workspace: str | Path) -> Path:
    """Return the canonical project configuration path for a workspace."""
    return Path(workspace).expanduser().resolve() / PROJECT_CONFIG_RELATIVE_PATH


def _iter_declared_paths(config: ProjectConfig) -> tuple[str, ...]:
    """Project all schema fields whose values carry project-relative paths."""
    paths = list(config.design.filelists)
    paths.extend(config.design.sources)
    paths.extend(config.design.include_dirs)
    paths.extend(config.formal.property_sets)
    recipe = config.simulation.recipe
    if isinstance(recipe, MakeRecipe):
        paths.append(recipe.makefile)
    elif isinstance(recipe, ExecutableRecipe):
        paths.append(recipe.executable)
    reference_model = config.simulation.reference_model
    if isinstance(reference_model, SvReferenceModel):
        paths.extend(reference_model.sources)
    elif isinstance(reference_model, DpiCReferenceModel):
        paths.extend(reference_model.sources)
        paths.extend(reference_model.include_dirs)
        paths.extend(reference_model.libraries)
    elif isinstance(reference_model, ExternalReferenceModel):
        paths.append(reference_model.executable)
    return tuple(paths)


def validate_project_boundaries(config: ProjectConfig, workspace: str | Path) -> None:
    """Reject configured paths that resolve outside the workspace through links."""
    root = Path(workspace).expanduser().resolve()
    for declared_path in _iter_declared_paths(config):
        candidate = (root / declared_path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError(
                f"configured path escapes the project root after link resolution: {declared_path}"
            ) from error


def load_project_config(workspace: str | Path) -> ProjectConfig:
    """Safely load and validate the canonical workspace project configuration."""
    root = Path(workspace).expanduser().resolve()
    path = root / PROJECT_CONFIG_RELATIVE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"project configuration not found: {path}")
    if path.is_symlink():
        raise ValueError("project.yaml must not be a symbolic link")
    size = path.stat().st_size
    if size > PROJECT_CONFIG_MAX_BYTES:
        raise ValueError(f"project.yaml exceeds {PROJECT_CONFIG_MAX_BYTES} bytes")
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"invalid project.yaml: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("project.yaml must contain one YAML mapping")
    config = ProjectConfig.model_validate(payload)
    validate_project_boundaries(config, root)
    return config


def save_project_config(
    workspace: str | Path,
    config: ProjectConfig | Mapping[str, Any],
) -> Path:
    """Validate and atomically save ``project.yaml`` without serializing secrets."""
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    parsed = config if isinstance(config, ProjectConfig) else ProjectConfig.model_validate(config)
    validate_project_boundaries(parsed, root)
    control_dir = root / PROJECT_CONFIG_RELATIVE_PATH.parent
    resolved_control_dir = control_dir.resolve(strict=False)
    try:
        resolved_control_dir.relative_to(root)
    except ValueError as error:
        raise ValueError(".ucagent resolves outside the project root") from error
    if control_dir.exists() and control_dir.is_symlink():
        raise ValueError(".ucagent must not be a symbolic link")
    control_dir.mkdir(parents=True, exist_ok=True)
    path = control_dir / PROJECT_CONFIG_RELATIVE_PATH.name
    if path.exists() and path.is_symlink():
        raise ValueError("project.yaml must not be a symbolic link")
    serialized = yaml.safe_dump(
        parsed.model_dump(mode="json"),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=control_dir,
            prefix=".project-",
            suffix=".yaml.tmp",
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return path


def parse_recipe(payload: Mapping[str, Any]) -> NativeRecipe | MakeRecipe | ExecutableRecipe:
    """Validate one discriminated recipe for API callers that edit it independently."""
    return TypeAdapter(Recipe).validate_python(payload)


def parse_reference_model(
    payload: Mapping[str, Any],
) -> SvReferenceModel | DpiCReferenceModel | ExternalReferenceModel:
    """Validate one user-provided reference-model declaration."""
    return TypeAdapter(ReferenceModel).validate_python(payload)
