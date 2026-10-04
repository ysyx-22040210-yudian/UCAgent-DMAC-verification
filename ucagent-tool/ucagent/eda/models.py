"""Typed contracts shared by EDA workflow drivers, adapters, and APIs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
import os
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExecutionStatus(str, Enum):
    """Describe whether an external tool process ran to a terminal state."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class VerificationStatus(str, Enum):
    """Describe the verification conclusion independently of process execution."""

    UNKNOWN = "unknown"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class FormalPropertyStatus(str, Enum):
    """Canonicalize property outcomes emitted by supported formal engines."""

    PROVEN = "proven"
    FALSIFIED = "falsified"
    VACUOUS = "vacuous"
    COVERED = "covered"
    UNCOVERED = "uncovered"
    INCONCLUSIVE = "inconclusive"
    DISABLED = "disabled"


class StrictModel(BaseModel):
    """Reject undeclared API fields so execution contracts cannot be widened silently."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CommandSpec(StrictModel):
    """Represent one argv-only process invocation accepted by :class:`JobRunner`."""

    argv: list[str] = Field(min_length=1, description="Argument vector; argv[0] is never passed through a shell.")
    tool: str | None = Field(
        default=None,
        description="Tool alias from the administrator-owned ToolchainProfile; omit only for a workspace executable.",
    )
    cwd: Path = Field(default=Path("."), description="Workspace-relative directory or {SESSION_DIR} placeholder.")
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Per-command environment additions. Secret values are redacted from evidence and logs.",
        repr=False,
    )
    timeout_seconds: float = Field(default=3600.0, gt=0, le=604800)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, argv: list[str]) -> list[str]:
        """Reject empty or control-character-bearing argv elements."""

        for index, value in enumerate(argv):
            if not isinstance(value, str) or not value:
                raise ValueError(f"argv[{index}] must be a non-empty string")
            if any(char in value for char in ("\x00", "\r", "\n")):
                raise ValueError(f"argv[{index}] contains a forbidden control character")
        return argv

    @field_validator("tool")
    @classmethod
    def validate_tool_alias(cls, value: str | None) -> str | None:
        """Keep tool aliases stable and safe for dictionary lookup."""

        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("tool must contain only letters, numbers, dot, underscore, or dash")
        return value

    @field_validator("env")
    @classmethod
    def validate_environment(cls, env: dict[str, str]) -> dict[str, str]:
        """Validate portable environment names and reject NUL bytes."""

        for name, value in env.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"invalid environment variable name: {name!r}")
            if "\x00" in value:
                raise ValueError(f"environment variable {name!r} contains a NUL byte")
        return env


class SessionInput(StrictModel):
    """Copy one immutable workspace input into a job's private staging directory."""

    source: Path = Field(description="Workspace-relative source file or directory included in the fingerprint.")
    destination: Path = Field(description="Session-relative destination populated before process launch.")

    @field_validator("source", "destination")
    @classmethod
    def validate_relative_path(cls, value: Path) -> Path:
        """Reject roots, traversal, and absolute staged-input paths."""

        if value.is_absolute() or not value.parts or any(part in {"", ".", ".."} for part in value.parts):
            raise ValueError("session input paths must be non-empty normalized relative paths")
        return value


class RunRequest(StrictModel):
    """Describe an immutable, workspace-scoped EDA process request."""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    workspace: Path = Field(description="Absolute root containing all project inputs and run outputs.")
    output_dir: Path = Field(description="Relative directory atomically published below workspace.")
    command: CommandSpec
    resource_class: Literal["eda", "claude", "analysis"] = "eda"
    stdin_path: Path | None = Field(default=None, description="Session-relative immutable input file supplied on stdin, never a shell redirect.")
    memory_limit_bytes: int | None = Field(default=None, ge=16 * 1024**2)
    output_limit_bytes: int = Field(default=256 * 1024**2, ge=1024, le=4 * 1024**3)
    input_paths: list[Path] = Field(default_factory=list, description="Workspace-relative files included in the fingerprint.")
    prepared_input_hashes: dict[str, str] = Field(default_factory=dict, description="Expected SHA-256 of control inputs consumed while preparing this request.")
    session_inputs: list[SessionInput] = Field(
        default_factory=list,
        description="Immutable workspace inputs copied to private session-relative destinations before launch.",
    )
    artifact_paths: list[Path] = Field(
        default_factory=list,
        description="Session-relative files or directories collected after execution.",
    )
    result_paths: list[Path] = Field(
        default_factory=list,
        description="Session-relative reports appended to bounded stdout/stderr before deterministic parsing.",
    )
    parser: Literal["none", "pytest", "uvm", "urg", "formal", "sby", "claude"] = "none"
    test_name: str | None = None
    suite: Literal["UT", "IT", "ST"] | None = None
    seed: int | None = Field(default=None, ge=0)
    property_set: str | None = None
    success_markers: list[str] = Field(default_factory=list)
    verification_hint: VerificationStatus = VerificationStatus.UNKNOWN
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        """Allow identifiers that are safe as event and artifact labels."""

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            raise ValueError("run_id must be 1-128 filesystem-safe characters")
        return value

    @field_validator("workspace")
    @classmethod
    def validate_workspace(cls, value: Path) -> Path:
        """Require callers to make the workspace boundary explicit."""

        if not value.is_absolute():
            raise ValueError("workspace must be an absolute path")
        return value

    @field_validator("output_dir")
    @classmethod
    def validate_output_dir(cls, value: Path) -> Path:
        """Prevent output publication outside the workspace."""

        if value.is_absolute() or not value.parts or any(part in {"", ".", ".."} for part in value.parts):
            raise ValueError("output_dir must be a non-empty normalized workspace-relative path")
        return value

    @field_validator("input_paths", "artifact_paths", "result_paths")
    @classmethod
    def validate_relative_paths(cls, values: list[Path]) -> list[Path]:
        """Reject absolute and parent-traversing evidence paths."""

        for value in values:
            if value.is_absolute() or any(part == ".." for part in value.parts):
                raise ValueError("input_paths, artifact_paths, and result_paths must stay relative to their declared roots")
        return values

    @field_validator("success_markers")
    @classmethod
    def validate_markers(cls, values: list[str]) -> list[str]:
        """Bound success markers used by deterministic log parsers."""

        if len(values) > 32:
            raise ValueError("at most 32 success markers are allowed")
        for value in values:
            if not value or len(value) > 256 or any(char in value for char in ("\x00", "\r", "\n")):
                raise ValueError("success markers must be non-empty single-line strings of at most 256 characters")
        return values

    @field_validator("prepared_input_hashes")
    @classmethod
    def validate_prepared_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        """Bind prepared controls to literal workspace-relative paths and SHA-256 digests."""
        for name, digest in values.items():
            path = Path(name)
            if not name or path.is_absolute() or any(part in {"..", "."} for part in path.parts) or path.as_posix() != name:
                raise ValueError("prepared input names must be normalized workspace-relative paths")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("prepared inputs require lowercase SHA-256 digests")
        return values

    @model_validator(mode="after")
    def validate_session_input_destinations(self) -> "RunRequest":
        """Reject reserved, duplicate, and order-dependent staging destinations."""

        reserved = {"events.ndjson", "manifest.json", "stderr.log", "stdout.log"}
        destinations = [item.destination for item in self.session_inputs]
        if self.stdin_path is not None:
            if self.stdin_path not in destinations:
                raise ValueError("stdin_path must name an exact immutable session_inputs destination")
        for destination in destinations:
            if destination.parts[0] in reserved:
                raise ValueError(f"session input destination is runner-reserved: {destination.as_posix()}")
        for index, left in enumerate(destinations):
            for right in destinations[index + 1 :]:
                if left == right or left in right.parents or right in left.parents:
                    raise ValueError("session input destinations must be unique and non-overlapping")
        return self


class Artifact(StrictModel):
    """Describe a content-addressed artifact stored outside the database."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str
    path: Path = Field(description="Path relative to the published run directory.")
    kind: str = "file"
    is_directory: bool = False
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = "application/octet-stream"
    hash_excludes: list[Path] = Field(
        default_factory=list,
        description="Signed relative exclusions used only to avoid a run-directory manifest self-reference.",
    )


class TestResult(StrictModel):
    """Capture one native, UnityTest, or UVM test conclusion."""

    test_name: str
    suite: Literal["UT", "IT", "ST"] | None = None
    seed: int | None = Field(default=None, ge=0)
    execution_status: ExecutionStatus
    verification_status: VerificationStatus
    duration_seconds: float | None = Field(default=None, ge=0)
    error_count: int = Field(default=0, ge=0)
    fatal_count: int = Field(default=0, ge=0)
    assertion_failures: int = Field(default=0, ge=0)
    message: str = ""
    log_path: Path | None = None


class CoverageMetric(StrictModel):
    """Store a normalized URG code or assertion coverage measurement."""

    metric: Literal["line", "cond", "tgl", "fsm", "branch", "assert"]
    percent: float = Field(ge=0, le=100)
    scope: str = "overall"
    covered: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    suite: Literal["UT", "IT", "ST"] | None = None
    test_name: str | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> "CoverageMetric":
        """Ensure covered and total counts form a plausible pair."""

        if (self.covered is None) != (self.total is None):
            raise ValueError("covered and total must be supplied together")
        if self.covered is not None and self.total is not None and self.covered > self.total:
            raise ValueError("covered cannot exceed total")
        return self


class FormalProperty(StrictModel):
    """Represent one normalized assertion or cover-property result."""

    name: str
    status: FormalPropertyStatus
    runtime_seconds: float | None = Field(default=None, ge=0)
    proof_depth: int | None = Field(default=None, ge=0)
    engine: str | None = None
    coi: str | None = None
    vacuous: bool | None = None
    counterexample_path: Path | None = None
    evidence_path: Path | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class FsdbPliProfile(StrictModel):
    """Declare the administrator-owned Verdi PLI files required by VCS FSDB builds."""

    table: Path = Field(description="Absolute path to the Verdi VCS novas.tab file.")
    library: Path = Field(description="Absolute path to the Verdi VCS pli.a library.")
    runtime_library_dirs: tuple[Path, ...] = Field(
        min_length=1,
        description="Absolute directories containing the matching FSDB dumper shared libraries.",
    )

    @field_validator("table", "library", "runtime_library_dirs")
    @classmethod
    def validate_host_path(cls, value: Path | tuple[Path, ...]) -> Path | tuple[Path, ...]:
        """Require explicit absolute host paths without control characters."""

        paths = value if isinstance(value, tuple) else (value,)
        if len(set(paths)) != len(paths):
            raise ValueError("FSDB PLI paths must not contain duplicates")
        for path in paths:
            rendered = str(path)
            if not path.is_absolute() or any(char in rendered for char in ("\x00", "\r", "\n")):
                raise ValueError("FSDB PLI paths must be absolute single-line host paths")
        return value


class ToolchainProfile(StrictModel):
    """Hold administrator-controlled executable and concurrency settings."""

    id: str
    display_name: str | None = None
    tools: dict[str, str] = Field(description="Map stable aliases such as vcs or vcf to executable paths or names.")
    environment: dict[str, str] = Field(default_factory=dict, repr=False)
    claude_model: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$",
        description="Optional explicit Claude gateway model for this host profile; otherwise use private user settings.",
    )
    setup_scripts: list[Path] = Field(
        default_factory=list,
        description="Administrator-owned setup scripts recorded for probe diagnostics; JobRunner never sources them.",
    )
    license_environment_names: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1, ge=1, le=1024)
    agent_max_concurrency: int = Field(default=1, ge=1, le=16)
    analysis_max_concurrency: int = Field(default=1, ge=1, le=16)
    minimum_root_free_bytes: int = Field(default=1024**3, ge=0)
    minimum_free_bytes: int = Field(default=10 * 1024**3, ge=0)
    versions: dict[str, str] = Field(default_factory=dict)
    execution_user: str | None = None
    npi_bridge: Path | None = Field(default=None, description="Absolute administrator-owned bridge.so built against this host's installed NPI SDK.")
    npi_bridge_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fsdb_pli: FsdbPliProfile | None = Field(
        default=None,
        description="Explicit Verdi PLI table and library used for native VCS FSDB compilation.",
    )

    @field_validator("id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        """Require a stable profile identifier suitable for storage keys."""

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            raise ValueError("toolchain id must be 1-128 filesystem-safe characters")
        return value

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject malformed aliases and executable values before process launch."""

        if not value:
            raise ValueError("at least one tool executable must be configured")
        for alias, executable in value.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
                raise ValueError(f"invalid tool alias: {alias!r}")
            if not executable or any(char in executable for char in ("\x00", "\r", "\n")):
                raise ValueError(f"invalid executable for tool {alias!r}")
        return value

    @field_validator("environment")
    @classmethod
    def validate_profile_environment(cls, env: dict[str, str]) -> dict[str, str]:
        """Validate administrator-provided environment names and values."""

        return CommandSpec.validate_environment(env)

    def require_tool(self, alias: str) -> str:
        """Return a configured executable or fail with an actionable alias error."""

        try:
            return self.tools[alias]
        except KeyError as exc:
            available = ", ".join(sorted(self.tools)) or "none"
            raise ValueError(f"tool alias {alias!r} is not configured; available aliases: {available}") from exc

    def require_fsdb_pli(self) -> tuple[Path, Path]:
        """Return existing explicit FSDB PLI inputs or fail before an EDA job starts."""

        if self.fsdb_pli is None:
            raise ValueError(
                "native VCS FSDB output requires toolchain fsdb_pli.table and fsdb_pli.library"
            )
        missing = [path for path in (self.fsdb_pli.table, self.fsdb_pli.library) if not path.is_file()]
        missing.extend(path for path in self.fsdb_pli.runtime_library_dirs if not path.is_dir())
        if missing:
            rendered = ", ".join(str(path) for path in missing)
            raise ValueError(f"configured FSDB PLI file does not exist: {rendered}")
        return self.fsdb_pli.table, self.fsdb_pli.library

    def fsdb_runtime_library_path(self) -> str:
        """Return the explicit FSDB runtime search path followed by the profile baseline."""

        self.require_fsdb_pli()
        assert self.fsdb_pli is not None
        values = [str(path) for path in self.fsdb_pli.runtime_library_dirs]
        baseline = self.environment.get("LD_LIBRARY_PATH")
        if baseline:
            values.append(baseline)
        return os.pathsep.join(values)

    def public_view(self) -> dict[str, Any]:
        """Return UI-safe profile metadata with every environment value redacted."""

        return {
            "id": self.id,
            "display_name": self.display_name,
            "claude_model": self.claude_model,
            "tools": dict(self.tools),
            "environment": {name: "<redacted>" for name in self.environment},
            "setup_scripts": [str(path) for path in self.setup_scripts],
            "license_environment_names": list(self.license_environment_names),
            "max_concurrency": self.max_concurrency,
            "agent_max_concurrency": self.agent_max_concurrency,
            "analysis_max_concurrency": self.analysis_max_concurrency,
            "minimum_root_free_bytes": self.minimum_root_free_bytes,
            "minimum_free_bytes": self.minimum_free_bytes,
            "versions": dict(self.versions),
            "execution_user": self.execution_user,
            "npi_bridge": str(self.npi_bridge) if self.npi_bridge else None,
            "npi_bridge_sha256": self.npi_bridge_sha256,
            "fsdb_pli": (
                {
                    "table": str(self.fsdb_pli.table),
                    "library": str(self.fsdb_pli.library),
                    "runtime_library_dirs": [
                        str(path) for path in self.fsdb_pli.runtime_library_dirs
                    ],
                }
                if self.fsdb_pli is not None
                else None
            ),
        }


class RunResult(StrictModel):
    """Return terminal execution state, normalized findings, and signed evidence paths."""

    run_id: str
    execution_status: ExecutionStatus
    verification_status: VerificationStatus
    return_code: int | None = None
    started_at: datetime
    completed_at: datetime
    session_dir: Path | None = None
    command: list[str] = Field(default_factory=list, description="Redacted argv used for evidence and display.")
    stdout_log: Path | None = None
    stderr_log: Path | None = None
    events_path: Path | None = None
    manifest_path: Path | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    tests: list[TestResult] = Field(default_factory=list)
    coverage: list[CoverageMetric] = Field(default_factory=list)
    properties: list[FormalProperty] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
