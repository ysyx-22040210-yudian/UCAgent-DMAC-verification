"""Versioned FastAPI surface for the visual commercial-verification platform.

The module deliberately accepts only structured project and run inputs.  EDA
commands are produced by administrator-selected adapters and are executed only
by :class:`ucagent.eda.JobRunner`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from typing import Any, Callable, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml

from ucagent.eda import (
    CommandSpec,
    ExecutionStatus,
    JobRunner,
    LicenseStatus,
    RunRequest,
    RunResult,
    ToolchainProfile,
    VerificationStatus,
    WorkflowDriver,
    build_license_probe_request,
    classify_license_probe,
    get_adapter,
)
from ucagent.eda.security import PathSecurityError, is_secret_name, redact_data, resolve_within
from ucagent.eda.manifest import ManifestVerificationError, sha256_file, verify_manifest
from ucagent.platform import (
    ProjectConfig,
    ProjectPath,
    UVM_MANIFEST,
    UvmScaffoldSpec,
    generate_uvm_scaffold,
    load_project_config,
    save_project_config,
    validate_uvm_scaffold,
)
from ucagent.server.api_mcp import project_mcp_tools
from ucagent.platform.project import SbyOptions
from ucagent.server.platform_store import PlatformStore
from ucagent.server.platform_workbench import RunPreview, preview_run, run_defaults, run_summary
from ucagent.util.config import save_platform_runtime_config


_TERMINAL_EXECUTION_STATES = {"completed", "error", "timeout", "cancelled"}
_SAFE_PLUSARG = re.compile(r"^\+[A-Za-z_][A-Za-z0-9_.-]*(?:=[A-Za-z0-9_./:+,@%=-]+)?$")
_SAFE_PROJECT_NAME = re.compile(r"^[^\x00\r\n]{1,128}$")
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class ApiModel(BaseModel):
    """Reject undeclared API fields at the trust boundary."""

    model_config = ConfigDict(extra="forbid")


class ProjectCreateRequest(ApiModel):
    """Import an existing server directory as a platform project."""

    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=4096)
    config: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Reject control characters from a user-visible project name."""

        if value.strip() != value or not _SAFE_PROJECT_NAME.fullmatch(value):
            raise ValueError("project name must be trimmed and contain no control characters")
        return value


class SimulationRunOptions(ApiModel):
    """Describe a structured simulation or UVM regression matrix."""

    simulator: Literal["verilator", "vcs"] = "verilator"
    uvm_version: str = Field(default="1.2", min_length=1, max_length=32)
    unitytest_tests: list[ProjectPath] = Field(default_factory=list, max_length=10000)
    suites: list[Literal["UT", "IT", "ST"]] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list, max_length=10000)
    seeds: list[int] = Field(default_factory=list, max_length=10000)
    coverage: list[Literal["line", "cond", "tgl", "fsm", "branch", "assert"]] = Field(
        default_factory=list
    )
    waveform: Literal["none", "vcd", "fst", "vpd", "fsdb"] = "none"
    plusargs: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("uvm_version")
    @classmethod
    def validate_uvm_version(cls, value: str) -> str:
        """Allow imported project versions while rejecting option syntax."""

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError("uvm_version must be a bounded version identifier")
        return value

    @field_validator("tests")
    @classmethod
    def validate_tests(cls, values: list[str]) -> list[str]:
        """Require unique SystemVerilog-compatible test class names."""

        if len(set(values)) != len(values):
            raise ValueError("simulation tests must not contain duplicates")
        for value in values:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value):
                raise ValueError(f"invalid simulation test name: {value!r}")
        return values

    @field_validator("unitytest_tests")
    @classmethod
    def validate_unitytest_tests(cls, values: list[str]) -> list[str]:
        """Require unique nonempty path strings before project-schema normalization."""

        if len(set(values)) != len(values):
            raise ValueError("unitytest_tests must not contain duplicates")
        if any(not value or value.strip() != value for value in values):
            raise ValueError("unitytest_tests must contain trimmed nonempty project paths")
        return values

    @field_validator("seeds")
    @classmethod
    def validate_seeds(cls, values: list[int]) -> list[int]:
        """Require positive unique seeds for a deterministic matrix."""

        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("simulation seeds must be positive and unique")
        return values

    @field_validator("coverage", "suites")
    @classmethod
    def validate_unique_lists(cls, values: list[str]) -> list[str]:
        """Reject duplicate suite and coverage selectors."""

        if len(set(values)) != len(values):
            raise ValueError("selectors must not contain duplicates")
        return values

    @field_validator("plusargs")
    @classmethod
    def validate_plusargs(cls, values: list[str]) -> list[str]:
        """Accept only inert VCS plusargs, never shell syntax."""

        for value in values:
            if not _SAFE_PLUSARG.fullmatch(value):
                raise ValueError(f"invalid simulator plusarg: {value!r}")
        return values


class FormalClockRequest(ApiModel):
    """Describe a clock signal for an FPV run."""

    signal: str | None = None
    period: str | None = None


class FormalResetRequest(ApiModel):
    """Describe a reset signal for an FPV run."""

    signal: str | None = None
    active: Literal["high", "low"] = "low"


class CounterexampleReplayRequest(ApiModel):
    """Select whether falsified properties require real dynamic replay."""

    enabled: bool = True
    methodology: Literal["uvm", "unitytest"] = "uvm"


class CounterexampleReplayStartRequest(ApiModel):
    """Bind one signed formal counterexample to an explicit dynamic test."""

    property_name: str = Field(min_length=1, max_length=1024)
    methodology: Literal["uvm", "unitytest"]
    uvm_test: str | None = Field(default=None, max_length=256)
    unitytest_test: ProjectPath | None = None
    suite: Literal["UT", "IT", "ST"] = "UT"
    seed: int = Field(default=1, ge=1)
    simulator: Literal["vcs", "verilator"] = "vcs"
    waveform: Literal["none", "vcd", "fst", "vpd", "fsdb"] = "none"
    plusargs: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("property_name")
    @classmethod
    def validate_property_name(cls, value: str) -> str:
        """Reject control characters while preserving hierarchical property names."""

        if value.strip() != value or any(character in value for character in ("\x00", "\r", "\n")):
            raise ValueError("property_name must be a trimmed single-line identifier")
        return value

    @field_validator("plusargs")
    @classmethod
    def validate_plusargs(cls, values: list[str]) -> list[str]:
        """Apply the same inert-plusarg contract as ordinary simulation runs."""

        return SimulationRunOptions.validate_plusargs(values)

    @model_validator(mode="after")
    def validate_target(self) -> "CounterexampleReplayStartRequest":
        """Require exactly one real target and a simulator-compatible waveform."""

        if self.methodology == "uvm":
            if not self.uvm_test or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", self.uvm_test):
                raise ValueError("UVM replay requires a valid uvm_test class name")
            if self.unitytest_test is not None:
                raise ValueError("unitytest_test is valid only for UnityTest replay")
            if self.simulator != "vcs":
                raise ValueError("UVM replay requires simulator='vcs'")
            if self.waveform not in {"none", "fsdb", "vpd"}:
                raise ValueError("UVM replay waveform must be none, fsdb, or vpd")
        else:
            if self.unitytest_test is None:
                raise ValueError("UnityTest replay requires unitytest_test")
            if self.uvm_test is not None:
                raise ValueError("uvm_test is valid only for UVM replay")
            allowed = {"none", "vcd", "fst"} if self.simulator == "verilator" else {"none", "fsdb"}
            if self.waveform not in allowed:
                raise ValueError(
                    f"UnityTest/{self.simulator} replay waveform must be one of: "
                    + ", ".join(sorted(allowed))
                )
        return self


class FormalRunOptions(ApiModel):
    """Describe structured commercial or bundled open formal execution."""

    engine: Literal["formalmc", "vc_formal", "sby"] = "formalmc"
    sby: SbyOptions | None = None
    property_sets: list[str] = Field(default_factory=list)
    clock: FormalClockRequest = Field(default_factory=FormalClockRequest)
    reset: FormalResetRequest = Field(default_factory=FormalResetRequest)
    cex_replay: CounterexampleReplayRequest = Field(default_factory=CounterexampleReplayRequest)


class RunCreateRequest(ApiModel):
    """Create one workflow run from typed configuration, never command text."""

    project_id: str
    workflow_id: str | None = None
    family: Literal["simulation", "formal"]
    methodology: Literal["unitytest", "systemverilog", "uvm"]
    authoring_mode: Literal["guided", "incremental", "vibe"] = "guided"
    toolchain: str
    design: dict[str, Any]
    simulation: SimulationRunOptions | None = None
    formal: FormalRunOptions | None = None

    @model_validator(mode="after")
    def validate_family_options(self) -> "RunCreateRequest":
        """Require the matching family options and reject contradictory input."""

        if self.family == "simulation" and self.simulation is None:
            raise ValueError("simulation options are required for a simulation workflow")
        if self.family == "simulation" and self.formal is not None:
            raise ValueError("formal options are not valid for a simulation workflow")
        if self.family == "formal" and self.formal is None:
            raise ValueError("formal options are required for a formal workflow")
        if self.family == "formal" and self.simulation is not None:
            raise ValueError("simulation options are not valid for a formal workflow")
        if self.simulation is not None:
            simulator = self.simulation.simulator
            waveform = self.simulation.waveform
            if self.methodology == "unitytest":
                if not self.simulation.unitytest_tests:
                    raise ValueError(
                        "UnityTest runs require at least one explicit simulation.unitytest_tests path"
                    )
                if self.simulation.tests:
                    raise ValueError(
                        "simulation.tests contains UVM class names; UnityTest runs use unitytest_tests paths"
                    )
            elif self.simulation.unitytest_tests:
                raise ValueError("simulation.unitytest_tests is valid only for UnityTest runs")
            if self.methodology != "unitytest" and simulator != "vcs":
                raise ValueError("native SystemVerilog and UVM workflows require simulation.simulator='vcs'")
            allowed_waveforms = (
                {"none", "fst", "vcd"}
                if self.methodology == "unitytest" and simulator == "verilator"
                else {"none", "fsdb"}
                if self.methodology == "unitytest"
                else {"none", "fsdb", "vpd"}
            )
            if waveform not in allowed_waveforms:
                choices = ", ".join(sorted(allowed_waveforms))
                raise ValueError(
                    f"{self.methodology}/{simulator} waveform must be one of: {choices}"
                )
        return self


class StageActionRequest(ApiModel):
    """Carry an optional human note for a stage decision."""

    note: str = Field(default="", max_length=4096)


class PlatformSettingsUpdate(ApiModel):
    """Allow only non-secret, bounded runtime settings to be changed."""

    minimum_free_disk_gb: float | None = Field(default=None, ge=1, le=10240)
    max_concurrency: int | None = Field(default=None, ge=1, le=1024)
    retention_days: int | None = Field(default=None, ge=1, le=36500)


class UvmScaffoldRequest(ApiModel):
    """Request generation of a project-local UVM 1.2 environment."""

    output_dir: str = Field(min_length=1, max_length=1024)
    spec: UvmScaffoldSpec


def _iso_timestamp(value: Any) -> Any:
    """Convert stored Unix timestamps to ISO-8601 for browser consumers."""

    if not isinstance(value, (int, float)):
        return value
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _safe_json(value: Any) -> Any:
    """Convert Pydantic models and path-like values into JSON-safe data."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    return value


def _mcp_config_mapping(server: Any) -> dict[str, Any]:
    """Return the MCP configuration as a plain mapping without secret values."""

    try:
        raw = server.cfg.get_value("mcp_server", {}) or {}
    except AttributeError:
        raw = {}
    if isinstance(raw, dict):
        return raw
    converter = getattr(raw, "as_dict", None)
    if callable(converter):
        converted = converter()
        return converted if isinstance(converted, dict) else {}
    return {}


def _mcp_protocol_url(raw_url: Any) -> str | None:
    """Normalize a configured HTTP MCP base URL to its protocol endpoint."""

    if not isinstance(raw_url, str) or not raw_url.strip():
        return None
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    path = parsed.path.rstrip("/")
    if not path.endswith("/mcp"):
        path += "/mcp"
    return parsed._replace(path=path, query="", fragment="").geturl()


def _active_agent_mcp(server: Any) -> tuple[Any | None, Any | None]:
    """Locate the in-process VerifyPDB agent and its MCP server, if attached."""

    pdb_instance = getattr(server, "pdb", None)
    agent = getattr(pdb_instance, "agent", None) if pdb_instance is not None else None
    mcp_server = getattr(pdb_instance, "_mcp_server", None) if pdb_instance is not None else None
    if agent is None:
        agent = getattr(server, "agent", None)
    if mcp_server is None:
        mcp_server = getattr(server, "mcp_server", None)
    return agent, mcp_server


def _public_mcp_info(server: Any) -> dict[str, Any]:
    """Describe the embedded platform, embedded agent, or external MCP endpoint."""

    config = _mcp_config_mapping(server)
    platform_mcp = getattr(server, "platform_mcp_server", None)
    if platform_mcp is not None:
        protocol_url = _mcp_protocol_url(platform_mcp.url())
        tools = list(getattr(platform_mcp, "tools", []))
        return {
            "enabled": True,
            "status": "healthy",
            "service_mode": "embedded_platform",
            "hosted_here": True,
            "protocol_url": protocol_url,
            "transport": "streamable-http",
            "tools": tools,
            "tool_count": len(tools),
            "schema_source": "platform_runtime",
            "client_config": (
                {"mcpServers": {"ucagent": {"url": protocol_url}}}
                if protocol_url is not None
                else None
            ),
            "message": "This platform process hosts the MCP protocol service at /mcp.",
        }
    agent, mcp_server = _active_agent_mcp(server)
    running_value = getattr(mcp_server, "is_running", False) if mcp_server is not None else False
    running = bool(running_value() if callable(running_value) else running_value)
    no_file_ops = bool(getattr(mcp_server, "no_file_ops", False))
    tools = project_mcp_tools(agent, no_file_ops=no_file_ops) if agent is not None else []

    protocol_url = None
    if running:
        url_getter = getattr(mcp_server, "url", None)
        if callable(url_getter):
            protocol_url = _mcp_protocol_url(url_getter())

    external_url = _mcp_protocol_url(
        config.get("protocol_url") or config.get("url") or config.get("endpoint")
    )
    externally_configured = bool(
        external_url
        or config.get("externally_configured")
        or config.get("external")
        or (agent is None and (config.get("enable") or config.get("enabled")))
    )
    if externally_configured and protocol_url is None:
        protocol_url = external_url

    if running:
        status = "healthy"
        mode = "embedded_agent"
        message = "The active agent is hosting the MCP protocol service."
    elif externally_configured:
        status = "externally_configured"
        mode = "external"
        message = "MCP is configured outside this platform process; this HTTP service does not mount /mcp."
    else:
        status = "unavailable"
        mode = "none"
        message = "No MCP protocol service is hosted by this platform process."

    client_config = None
    if protocol_url is not None:
        client_config = {"mcpServers": {"ucagent": {"url": protocol_url}}}
    return {
        "enabled": running or externally_configured,
        "status": status,
        "service_mode": mode,
        "hosted_here": running,
        "protocol_url": protocol_url,
        "transport": "streamable-http" if protocol_url is not None else None,
        "tools": tools,
        "tool_count": len(tools),
        "schema_source": "active_agent" if agent is not None else None,
        "client_config": client_config,
        "message": message,
    }


def _period_to_ns(value: str | None) -> float | None:
    """Parse a bounded time literal into nanoseconds for project.yaml."""

    if value is None or not value.strip():
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(fs|ps|ns|us|ms|s)?\s*", value, re.IGNORECASE)
    if not match:
        raise ValueError("formal clock period must be a number with fs, ps, ns, us, ms, or s")
    amount = float(match.group(1))
    scale = {
        "fs": 1e-6,
        "ps": 1e-3,
        "ns": 1.0,
        "us": 1e3,
        "ms": 1e6,
        "s": 1e9,
    }[(match.group(2) or "ns").lower()]
    result = amount * scale
    if result <= 0:
        raise ValueError("formal clock period must be positive")
    return result


class PlatformRuntime:
    """Coordinate platform persistence, adapters, jobs, and safe host configuration."""

    def __init__(self, server: Any) -> None:
        """Initialize state under the master workspace and recover interrupted jobs."""

        self.server = server
        self.workspace = Path(server.workspace).resolve()
        self.state_dir = self.workspace / ".ucagent" / "platform"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = PlatformStore(str(self.state_dir))
        self.run_root = self.state_dir / "runs"
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.upload_root = self.state_dir / "uploads"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.state_dir / "settings.json"
        self.settings = self._load_settings()
        self.toolchain_path = self._toolchain_path()
        self._profiles: dict[str, ToolchainProfile] = {}
        self._profile_errors: dict[str, str] = {}
        self.reload_toolchains()
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._runtime_lock = threading.RLock()
        manifest_key = self._load_manifest_key()
        self._manifest_key = manifest_key
        self._runner = JobRunner(hmac_key=manifest_key)
        from ucagent.server.campaign_service import CampaignService
        self.campaigns = CampaignService(self)
        from ucagent.server.formal_sessions import FormalSessions
        self.formal_sessions = FormalSessions(self)
        self._recover_interrupted_runs(manifest_key)
        for source_run_id in self.store.source_runs_with_counterexample_replays():
            self.reconcile_counterexample_replays(source_run_id)

    def _load_manifest_key(self) -> bytes:
        """Load or create a private local manifest signing key with restrictive mode."""

        key_path = self.state_dir / "manifest.key"
        if key_path.exists():
            data = key_path.read_bytes()
            if len(data) >= 32:
                return data
            raise RuntimeError(f"Manifest signing key is invalid: {key_path}")
        data = secrets.token_bytes(32)
        temp_path = key_path.with_suffix(".tmp")
        temp_path.write_bytes(data)
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, key_path)
        return data

    def _recover_interrupted_runs(self, manifest_key: bytes) -> None:
        """Validate published Job evidence before terminalizing interrupted work."""

        active_runs = [
            run
            for run in self.store.list_runs()
            if run["execution_status"] in {"queued", "running"} and run["adapter"] != "campaign"
        ]
        for run in active_runs:
            project = self.store.get_project(run["project_id"])
            workspace = Path(project["source_root"]).resolve() if project else None
            valid_results: list[dict[str, Any]] = []
            for job in self.store.list_jobs(run["run_id"]):
                attempts = list(job.get("attempts") or [])
                attempt = attempts[-1] if attempts else None
                manifest_value = attempt.get("manifest_path") if attempt else None
                result_data: dict[str, Any] | None = None
                validation_error: str | None = None
                if workspace is None:
                    validation_error = "project workspace is unavailable"
                elif manifest_value:
                    manifest_path = Path(str(manifest_value))
                    if not manifest_path.is_absolute():
                        manifest_path = workspace / manifest_path
                    try:
                        manifest_path = manifest_path.resolve(strict=True)
                        manifest_path.relative_to(workspace)
                        manifest = verify_manifest(
                            manifest_path,
                            manifest_key,
                            workspace=workspace,
                            verify_files=True,
                        )
                        expected_job_run_id = str((job.get("command") or {}).get("job_run_id") or "")
                        if expected_job_run_id and manifest.get("run_id") != expected_job_run_id:
                            raise ManifestVerificationError("manifest Job run identifier mismatch")
                        execution_status = str(manifest.get("execution_status") or "")
                        if execution_status not in {"completed", "error", "timeout", "cancelled"}:
                            raise ManifestVerificationError("manifest has no terminal execution status")
                        session_dir = manifest_path.parent
                        result_data = {
                            "run_id": manifest.get("run_id"),
                            "execution_status": execution_status,
                            "verification_status": str(
                                manifest.get("verification_status") or "unknown"
                            ),
                            "return_code": manifest.get("return_code"),
                            "started_at": manifest.get("started_at"),
                            "completed_at": manifest.get("completed_at"),
                            "session_dir": str(session_dir),
                            "command": list(manifest.get("command") or []),
                            "stdout_log": str(session_dir / "stdout.log"),
                            "stderr_log": str(session_dir / "stderr.log"),
                            "events_path": str(session_dir / "events.ndjson"),
                            "manifest_path": str(manifest_path),
                            "artifacts": list(manifest.get("artifacts") or []),
                            "tests": list(manifest.get("tests") or []),
                            "coverage": list(manifest.get("coverage") or []),
                            "properties": list(manifest.get("properties") or []),
                            "diagnostics": list(manifest.get("diagnostics") or []),
                        }
                    except (ManifestVerificationError, FileNotFoundError, OSError, ValueError) as exc:
                        validation_error = str(exc)
                elif job["execution_status"] == "completed":
                    validation_error = "completed Job has no persisted manifest path"

                if result_data is not None:
                    valid_results.append(result_data)
                    if job["execution_status"] in {"queued", "running"} and attempt is not None:
                        normalized = self._merge_results(run["run_id"], valid_results)
                        self.store.commit_job_result(
                            run_id=run["run_id"],
                            job_id=job["job_id"],
                            attempt_id=attempt["attempt_id"],
                            execution_status=str(result_data["execution_status"]),
                            verification_status=str(result_data["verification_status"]),
                            result=result_data,
                            manifest_path=str(result_data["manifest_path"]),
                            normalized_result=normalized,
                        )
                elif validation_error and job["execution_status"] in {"queued", "running", "completed"}:
                    diagnostic = {
                        "error_code": "recovery_manifest_invalid",
                        "error": "Published Job evidence could not be validated after service restart.",
                        "observed": validation_error[:500],
                        "next_action": "Retry the run from its persisted configuration.",
                        "retryable": True,
                    }
                    self.store.invalidate_job_evidence(
                        run_id=run["run_id"],
                        job_id=job["job_id"],
                        diagnostic=diagnostic,
                    )

            merged = self._merge_results(run["run_id"], valid_results)
            self.store.save_run_result(run["run_id"], merged)
            jobs_after = self.store.list_jobs(run["run_id"])
            if jobs_after and all(job["execution_status"] == "completed" for job in jobs_after):
                conclusions = [str(job["verification_status"]) for job in jobs_after]
                verification = max(
                    conclusions,
                    key={"unknown": 0, "passed": 1, "inconclusive": 2, "failed": 3}.get,
                )
                self.store.update_run_status(
                    run["run_id"],
                    execution_status="completed",
                    verification_status=verification,
                )
                self.store.append_event(
                    run["run_id"],
                    "run.recovered",
                    {"completed_jobs": len(jobs_after), "execution_status": "completed"},
                )

        self.store.recover_interrupted_runs()
        for run in active_runs:
            self._refresh_job_stages(run["run_id"])
            self._refresh_group_stages(run["run_id"])
            self._reconcile_derived_stages(run["run_id"])

    def _load_settings(self) -> dict[str, Any]:
        """Load non-secret platform settings and apply safe defaults."""

        settings: dict[str, Any] = {}
        if self.settings_path.exists():
            try:
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    settings = raw
            except (OSError, ValueError):
                settings = {}
        settings.setdefault("minimum_free_disk_gb", 10.0)
        settings.setdefault("max_concurrency", 1)
        settings.setdefault("retention_days", None)
        return settings

    def save_settings(self, update: PlatformSettingsUpdate) -> dict[str, Any]:
        """Atomically persist administrator-safe settings."""

        values = update.model_dump(exclude_none=True)
        if "retention_days" in update.model_fields_set:
            values["retention_days"] = update.retention_days
        for key, value in values.items():
            self.settings[key] = value
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.settings, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.settings_path)
        self.reload_toolchains()
        return self.public_settings()

    def public_settings(self) -> dict[str, Any]:
        """Return non-secret paths and limits required by the Settings page."""

        return {
            **self.settings,
            "workspace_root": str(self.workspace),
            "artifact_root": str(self.run_root),
            "bind_host": self.server.host,
            "port": self.server.port,
            "toolchain_config_path": str(self.toolchain_path),
        }

    def _toolchain_path(self) -> Path:
        """Resolve the administrator-owned toolchain file from server configuration."""

        try:
            configured = self.server.cfg.get_value("platform.toolchains_file", "")
        except AttributeError:
            configured = ""
        if configured:
            return Path(str(configured)).expanduser().resolve()
        return (Path.home() / ".ucagent" / "toolchains.yaml").resolve()

    def reload_toolchains(self) -> None:
        """Load toolchain profiles while keeping all credential values in process memory."""

        profiles: dict[str, ToolchainProfile] = {}
        errors: dict[str, str] = {}
        raw_profiles = dict(getattr(self.server, "_builtin_toolchains", {}))
        if self.toolchain_path.is_file():
            try:
                raw = yaml.safe_load(self.toolchain_path.read_text(encoding="utf-8")) or {}
                configured_profiles = raw.get("profiles", raw.get("toolchains", {}))
                if not isinstance(configured_profiles, dict):
                    raise ValueError("toolchains.yaml profiles must be a mapping")
                for identifier, item in configured_profiles.items():
                    if identifier in raw_profiles:
                        errors[str(identifier)] = "A host profile cannot replace a bundled toolchain; choose a distinct profile id."
                    else:
                        raw_profiles[identifier] = item
            except Exception as exc:
                errors["toolchains.yaml"] = str(exc)
        for identifier, item in raw_profiles.items():
            try:
                if not isinstance(item, dict):
                    raise ValueError("profile must be a mapping")
                payload = {**item, "id": str(identifier)}
                environment = dict(payload.get("environment") or {})
                license_names = list(payload.get("license_environment_names") or [])
                forbidden = [name for name in environment if is_secret_name(name) or name in license_names]
                if forbidden:
                    raise ValueError(
                        "secret environment values must not be stored in toolchains.yaml; "
                        f"declare their names only: {', '.join(sorted(forbidden))}"
                    )
                payload["environment"] = environment
                payload["max_concurrency"] = min(
                    int(payload.get("max_concurrency", 1)),
                    int(self.settings.get("max_concurrency", 1)),
                )
                payload["minimum_free_bytes"] = max(
                    int(payload.get("minimum_free_bytes", 10 * 1024**3)),
                    int(float(self.settings.get("minimum_free_disk_gb", 10)) * 1024**3),
                )
                # Validate non-secret host data first: Pydantic diagnostics may
                # include invalid input values, so credentials enter only afterwards.
                profile = ToolchainProfile.model_validate(payload)
                for name in profile.license_environment_names:
                    if name in os.environ:
                        environment[name] = os.environ[name]
                profiles[str(identifier)] = profile.model_copy(update={"environment": environment})
            except Exception as exc:
                errors[str(identifier)] = str(exc)
        if not profiles:
            # Resolving the interpreter symlink escapes a venv on POSIX and
            # silently drops its installed verification dependencies.
            tools = {"python": os.path.abspath(os.sys.executable)}
            for alias in ("make", "picker", "vcs", "urg", "vcf", "verdi", "verilator", "sby", "yosys", "yosys-smtbmc", "z3"):
                executable = shutil.which(alias)
                if executable:
                    tools[alias] = executable
            formal_mc = shutil.which("FormalMC") or shutil.which("formalmc")
            if formal_mc:
                tools["formalmc"] = formal_mc
            profiles["local"] = ToolchainProfile(
                id="local",
                display_name="Local auto-detected tools",
                tools=tools,
                max_concurrency=int(self.settings.get("max_concurrency", 1)),
                minimum_free_bytes=int(float(self.settings.get("minimum_free_disk_gb", 10)) * 1024**3),
            )
        self._profiles = profiles
        self._profile_errors = errors

    def allowed_roots(self) -> list[Path]:
        """Return canonical server roots from which projects may be imported."""

        roots = [self.workspace]
        for item in getattr(self.server, "_launch_roots", []):
            try:
                root = Path(str(item.get("path", ""))).resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if root not in roots:
                roots.append(root)
        return roots

    def resolve_project_root(self, raw_path: str) -> Path:
        """Resolve an existing project path and enforce configured import boundaries."""

        candidate = Path(raw_path).expanduser().resolve(strict=True)
        if not candidate.is_dir():
            raise ValueError("project path must be an existing directory")
        for root in self.allowed_roots():
            try:
                candidate.relative_to(root)
                return candidate
            except ValueError:
                continue
        allowed = ", ".join(str(path) for path in self.allowed_roots())
        raise ValueError(f"project path is outside configured roots: {allowed}")

    def create_project(self, request: ProjectCreateRequest) -> dict[str, Any]:
        """Import, validate, and persist a project without copying large artifacts."""

        source_root = self.resolve_project_root(request.path)
        config: dict[str, Any]
        if request.config is not None:
            parsed = ProjectConfig.model_validate(request.config)
            save_project_config(source_root, parsed)
            config = parsed.model_dump(mode="json")
        else:
            try:
                config = load_project_config(source_root).model_dump(mode="json")
            except FileNotFoundError:
                config = {}
        project = self.store.create_project(
            name=request.name,
            source_root=str(source_root),
            config=config,
        )
        return self.project_public(project)

    def project_public(self, project: dict[str, Any]) -> dict[str, Any]:
        """Project a stored project into the stable browser contract."""

        config = project.get("config") or {}
        design = config.get("design") or {}
        workflow = config.get("workflow") or {}
        simulation = config.get("simulation") or {}
        timestamps = {
            key: _iso_timestamp(project.get(key))
            for key in ("created_at", "updated_at")
            if project.get(key) is not None
        }
        return {
            "id": project["project_id"],
            "name": project["name"],
            "path": project["source_root"],
            "design": design,
            "workflow_family": workflow.get("family"),
            "methodology": workflow.get("methodology"),
            "simulator": simulation.get("simulator"),
            "toolchain": config.get("toolchain"),
            "uvm_version": simulation.get("uvm_version"),
            "source_count": len(design.get("sources") or []) + len(design.get("filelists") or []),
            "authoring_mode": workflow.get("authoring_mode", "guided"),
            "simulation": simulation,
            "formal": config.get("formal") or {},
            "run_defaults": run_defaults(project),
            "migration": self.formal_sessions.migration_for_project(project["project_id"]),
            **timestamps,
        }

    def build_project_config(
        self,
        request: RunCreateRequest,
        existing: dict[str, Any] | None = None,
    ) -> ProjectConfig:
        """Translate a browser run request into canonical project.yaml data."""

        payload: dict[str, Any] = json.loads(json.dumps(existing or {}))
        payload.update(
            {
                "schema_version": 1,
                "design": request.design,
                "workflow": {
                    "family": request.family,
                    "methodology": request.methodology,
                    "authoring_mode": request.authoring_mode,
                },
                "toolchain": request.toolchain,
            }
        )
        if request.simulation is not None:
            simulation = request.simulation
            suites = simulation.suites or ["UT"]
            simulation_payload = dict(payload.get("simulation") or {})
            simulation_payload.update(
                {
                    "simulator": simulation.simulator,
                    "uvm_version": simulation.uvm_version,
                    "unitytest_tests": simulation.unitytest_tests,
                    "suites": (
                        []
                        if request.methodology == "unitytest"
                        else [
                            {
                                "name": level.lower(),
                                "level": level,
                                "tests": simulation.tests or ["smoke_test"],
                                "seeds": simulation.seeds,
                            }
                            for level in suites
                        ]
                    ),
                    "seeds": simulation.seeds,
                    "coverage": simulation.coverage,
                    "waveform": simulation.waveform,
                }
            )
            payload["simulation"] = simulation_payload
        if request.formal is not None:
            formal = request.formal
            payload["formal"] = {
                "engine": formal.engine,
                "sby": formal.sby.model_dump() if formal.sby else None,
                "property_sets": formal.property_sets,
                "clock": {
                    "signal": formal.clock.signal,
                    "period_ns": _period_to_ns(formal.clock.period),
                },
                "reset": {
                    "signal": formal.reset.signal,
                    "active_level": 1 if formal.reset.active == "high" else 0,
                },
                "cex_replay": formal.cex_replay.model_dump(),
            }
        return ProjectConfig.model_validate(payload)

    def workflow_catalog(self, formal_engine: str = "formalmc") -> list[dict[str, Any]]:
        """Return every workflow and disabled branch from the raw catalog."""

        try:
            from ucagent.platform.workflow_catalog import load_workflow_catalog

            catalog = load_workflow_catalog({"FORMAL_ENGINE": formal_engine})
            raw_workflows = catalog.model_dump(mode="json")["workflows"]
        except (ImportError, AttributeError):
            raw_workflows = []
        result = [self._workflow_public(item) for item in raw_workflows]
        for workflow in result:
            if formal_engine != "formalmc":
                continue  # A catalog preview must not rewrite persisted default definitions.
            self.store.save_workflow(
                workflow_id=workflow["id"],
                family=workflow["family"],
                methodology=workflow["methodology"],
                authoring_mode=workflow["authoring_mode"],
                definition=workflow,
            )
        return result

    def _workflow_public(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """Normalize checker descriptors for the browser workflow tree."""

        def normalize_stage(stage: dict[str, Any]) -> dict[str, Any]:
            """Recursively normalize one stage descriptor."""

            item = dict(stage)
            checkers = item.get("checker") or item.get("checkers") or []
            item["checker"] = [
                entry.get("name") or entry.get("class_name") if isinstance(entry, dict) else str(entry)
                for entry in checkers
            ]
            item["children"] = [normalize_stage(child) for child in item.get("children") or []]
            return item

        item = dict(workflow)
        item["stages"] = [normalize_stage(stage) for stage in item.get("stages") or []]
        return item

    def create_run(self, request: RunCreateRequest) -> dict[str, Any]:
        """Persist a structured run and dispatch it to a background workflow driver."""

        project = self.store.get_project(request.project_id)
        if project is None:
            raise KeyError(request.project_id)
        profile = self._profiles.get(request.toolchain)
        if profile is None:
            raise ValueError(f"unknown toolchain profile: {request.toolchain}")
        config = self.build_project_config(request, project.get("config") or {})
        default_workflow_ids = {
            ("simulation", "unitytest", "guided"): "unitytest-guided",
            ("simulation", "unitytest", "incremental"): "unitytest-incremental",
            ("simulation", "unitytest", "vibe"): "unitytest-vibe",
            ("simulation", "systemverilog", "guided"): "systemverilog-vcs",
            ("simulation", "uvm", "guided"): "uvm-vcs",
            ("formal", "systemverilog", "guided"): "formal-guided",
        }
        workflow_id = request.workflow_id
        if workflow_id is None and request.family == "formal":
            workflow_id = "formal-guided"
        if workflow_id is None:
            workflow_id = default_workflow_ids.get(
                (request.family, request.methodology, request.authoring_mode),
                f"{request.family}-{request.methodology}-{request.authoring_mode}",
            )
        selected_workflow = next(
            (item for item in self.workflow_catalog() if item["id"] == workflow_id), None
        )
        if selected_workflow is None:
            raise ValueError(f"unknown workflow_id: {workflow_id}")
        expected_selection = (
            request.family,
            request.methodology,
            request.authoring_mode,
        )
        observed_selection = (
            selected_workflow.get("family"),
            selected_workflow.get("methodology"),
            selected_workflow.get("authoring_mode"),
        )
        if observed_selection != expected_selection:
            raise ValueError(
                f"workflow_id {workflow_id!r} does not match family, methodology, and authoring_mode"
            )
        source_root = Path(project["source_root"]).resolve(strict=True)
        migration = self.formal_sessions.migration_for_project(request.project_id)
        if migration:
            from ucagent.eda.formalmc_conversion import verify_converted_project
            if str(source_root) != migration["workspace"] or config.formal.engine != "formalmc":
                raise ValueError("Migrated project identity/engine changed; create a new project for different inputs.")
            fixed = verify_converted_project(source_root, migration["manifest_sha256"])
            if config.design.model_dump(mode="json") != fixed["design"] or list(config.formal.property_sets) != ["formal.tcl"]:
                raise ValueError("Migrated design inputs changed; create a new migration for a different design.")
        save_project_config(source_root, config)
        self.store.update_project(
            request.project_id,
            name=project["name"],
            config=config.model_dump(mode="json"),
        )
        adapter_name = (
            request.formal.engine
            if request.family == "formal" and request.formal is not None
            else ("picker" if request.methodology == "unitytest" else "vcs")
        )
        persisted = self.store.create_run(
            project_id=request.project_id,
            workflow=workflow_id,
            adapter=adapter_name,
            request=request.model_dump(mode="json"),
        )
        save_platform_runtime_config(
            str(source_root),
            dut=config.design.top,
            output_dir=(Path(".ucagent") / "platform-runs" / persisted["run_id"]).as_posix(),
            run_id=persisted["run_id"],
            project_config=config.model_dump(mode="json"),
            toolchain={
                "id": profile.id,
                "tools": dict(profile.tools),
                "versions": dict(profile.versions),
                "max_concurrency": profile.max_concurrency,
                "minimum_free_bytes": profile.minimum_free_bytes,
                "license_environment_names": list(profile.license_environment_names),
                "fsdb_pli": (
                    {
                        "table": str(profile.fsdb_pli.table),
                        "library": str(profile.fsdb_pli.library),
                        "runtime_library_dirs": [
                            str(path) for path in profile.fsdb_pli.runtime_library_dirs
                        ],
                    }
                    if profile.fsdb_pli is not None
                    else None
                ),
            },
        )
        if selected_workflow is not None:
            flattened: list[dict[str, Any]] = []
            suite_levels = {suite.level.casefold() for suite in config.simulation.suites}
            has_generated_scaffold = any(
                (source_root / Path(filelist).parent / ".ucagent_uvm_manifest.json").is_file()
                for filelist in config.design.filelists
            )

            def configure_stage(stage: dict[str, Any]) -> dict[str, Any]:
                """Resolve catalog conditions against this immutable run configuration."""

                item = dict(stage)
                name = str(item.get("name") or "").casefold()
                children = [configure_stage(child) for child in item.get("children") or []]
                item["children"] = children
                enabled = bool(item.get("enabled", True))
                reason = item.get("disabled_reason")
                if name == "coverage_merge":
                    enabled = bool(config.simulation.coverage)
                    reason = None if enabled else "simulation.coverage is empty"
                elif name == "waveform_artifacts":
                    enabled = config.simulation.waveform != "none"
                    reason = None if enabled else "simulation.waveform is none"
                elif name in {"ut", "it", "st"} and workflow_id == "uvm-vcs":
                    enabled = name in suite_levels
                    reason = None if enabled else f"No {name.upper()} suite is declared."
                elif name == "environment_scaffold" and workflow_id == "uvm-vcs":
                    enabled = has_generated_scaffold
                    reason = None if enabled else "No generated UVM scaffold is selected."
                elif name == "environment_import" and workflow_id == "uvm-vcs":
                    enabled = not has_generated_scaffold
                    reason = None if enabled else "The run uses a generated UVM scaffold."
                elif name in {"vc_formal", "formal_mc", "sby"}:
                    selected_engine = "formal_mc" if config.formal.engine == "formalmc" else config.formal.engine
                    enabled = name == selected_engine
                    reason = None if enabled else f"formal.engine selects {selected_engine}."
                elif name == "counterexample_dynamic_replay":
                    enabled = False
                    reason = (
                        "Waiting for a falsified property and an explicit dynamic replay target."
                        if config.formal.cex_replay.enabled
                        else "formal.cex_replay.enabled is false"
                    )
                elif config.formal.engine == "sby" and request.family == "formal" and name not in {"formal_execution", "toolchain_dispatch"}:
                    enabled = False
                    reason = "This SBY run executes supplied RTL/harness assets. Agent authoring and review are not executed by the local proof service."
                item["enabled"] = enabled
                item["disabled_reason"] = reason if not enabled else None
                item["execution_status"] = "queued" if enabled else "cancelled"
                item["verification_status"] = "unknown"
                return item

            configured_stages = [
                configure_stage(stage) for stage in selected_workflow.get("stages") or []
            ]

            def collect_stages(stages: list[dict[str, Any]]) -> None:
                """Flatten a display tree while retaining each node's parent identity."""

                for stage in stages:
                    item = dict(stage)
                    children = list(item.pop("children", []) or [])
                    flattened.append(item)
                    collect_stages(children)

            collect_stages(configured_stages)
            self.store.replace_run_stages(persisted["run_id"], flattened)
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._execute_run,
            args=(persisted["run_id"], source_root, config, request, profile, cancel_event),
            daemon=True,
            name=f"ucagent-run-{persisted['run_id'][:12]}",
        )
        with self._runtime_lock:
            self._cancel_events[persisted["run_id"]] = cancel_event
            self._threads[persisted["run_id"]] = thread
        thread.start()
        return self.run_public(self.store.get_run(persisted["run_id"]) or persisted)

    def _execute_run(
        self,
        run_id: str,
        workspace: Path,
        config: ProjectConfig,
        request: RunCreateRequest,
        profile: ToolchainProfile,
        cancel_event: threading.Event,
    ) -> None:
        """Build adapter-owned requests, run them, and persist normalized evidence."""

        self.store.update_run_status(run_id, execution_status="running")
        try:
            job_requests = self._build_run_requests(run_id, workspace, config, request, profile)
            job_ids = []
            job_stage_ids = []
            attempt_ids = []
            for job_request in job_requests:
                stage_id = self._stage_for_request(run_id, job_request)
                job_stage_ids.append(stage_id)
                job_id = self.store.create_job(
                    run_id=run_id,
                    stage_id=stage_id,
                    kind=str(job_request.command.tool or "workspace_executable"),
                    command=redact_data(
                        {
                            **job_request.command.model_dump(mode="json"),
                            "job_run_id": job_request.run_id,
                            "output_dir": str(job_request.output_dir),
                        },
                        tuple(profile.environment.values()),
                    ),
                )
                job_ids.append(job_id)
                attempt_ids.append(
                    self.store.create_attempt(
                        job_id=job_id,
                        number=1,
                        execution_status="queued",
                        manifest_path=str(
                            (workspace / job_request.output_dir / "manifest.json").resolve()
                        ),
                    )
                )

            persisted_results: list[dict[str, Any]] = []

            def on_event(event: dict[str, Any]) -> None:
                """Persist one driver event with its stable Job identifier."""

                payload = _safe_json(event)
                index = int(payload.get("job_index", 0))
                event_type = str(payload.pop("type", payload.pop("event_type", "job.event")))
                if 0 <= index < len(job_ids):
                    payload["job_id"] = job_ids[index]
                    stage_id = job_stage_ids[index]
                    if stage_id:
                        payload["stage_id"] = stage_id
                        if event_type == "running":
                            self.store.update_stage_execution(run_id, stage_id, "running")
                    if event_type == "running":
                        self.store.update_job_status(
                            job_ids[index], execution_status="running"
                        )
                        self.store.update_attempt(
                            attempt_ids[index], execution_status="running"
                        )
                        self._refresh_group_stages(run_id)
                runner_payload = payload.pop("payload", {})
                if isinstance(runner_payload, dict):
                    payload.update(runner_payload)
                if event_type in {"stdout", "stderr"} and payload.get("text"):
                    payload["message"] = payload["text"]
                    payload["level"] = "error" if event_type == "stderr" else "info"
                elif event_type in {"error", "timing_out"}:
                    payload["level"] = "error"
                self.store.append_event(
                    run_id,
                    event_type,
                    redact_data(payload, tuple(profile.environment.values())),
                )

            def on_job_result(
                job_index: int,
                _: RunRequest,
                result: RunResult,
            ) -> None:
                """Atomically publish one Job result before the next Job can start."""

                if not 0 <= job_index < len(job_ids):
                    raise IndexError(f"workflow returned an unknown Job index: {job_index}")
                result_data = result.model_dump(mode="json")
                next_results = [*persisted_results, result_data]
                merged_result = self._merge_results(run_id, next_results)
                self.store.commit_job_result(
                    run_id=run_id,
                    job_id=job_ids[job_index],
                    attempt_id=attempt_ids[job_index],
                    execution_status=result.execution_status.value,
                    verification_status=result.verification_status.value,
                    result=result_data,
                    manifest_path=str(result.manifest_path) if result.manifest_path else None,
                    normalized_result=merged_result,
                )
                persisted_results.append(result_data)
                self._refresh_job_stages(run_id)
                self._refresh_group_stages(run_id)

            workflow_result = WorkflowDriver(self._runner).run(
                job_requests,
                profile,
                workflow_id=run_id,
                on_event=on_event,
                on_job_result=on_job_result,
                cancel_event=cancel_event,
            )
            results = list(persisted_results)
            for skipped_index in range(len(workflow_result.jobs), len(job_ids)):
                skipped_result = {
                    "diagnostics": [
                        {
                            "error_code": "dependency_not_completed",
                            "error": "The job was not started because an earlier job did not complete.",
                            "next_action": "Correct the earlier job failure and retry the workflow.",
                        }
                    ]
                }
                self.store.finish_job(
                    job_ids[skipped_index],
                    execution_status="cancelled",
                    verification_status="inconclusive",
                    result=skipped_result,
                )
                self.store.update_attempt(
                    attempt_ids[skipped_index],
                    execution_status="cancelled",
                    result=skipped_result,
                )
                skipped_stage_id = job_stage_ids[skipped_index]
                if skipped_stage_id:
                    stage = next(
                        (
                            item
                            for item in self.store.list_run_stages(run_id)
                            if (item.get("stage_id") or item.get("id")) == skipped_stage_id
                        ),
                        None,
                    )
                    if stage is not None and stage.get("execution_status") == "queued":
                        self.store.update_stage_execution(
                            run_id,
                            skipped_stage_id,
                            "cancelled",
                            "inconclusive",
                        )
            self._refresh_job_stages(run_id)
            self._refresh_group_stages(run_id)
            merged = self._merge_results(run_id, results)
            self.store.save_run_result(run_id, merged)
            self.store.update_run_status(
                run_id,
                execution_status=workflow_result.execution_status.value,
                verification_status=workflow_result.verification_status.value,
                diagnostic=(merged.get("diagnostics") or [None])[0],
            )
            self._reconcile_derived_stages(run_id)
        except Exception as exc:
            diagnostic = {
                "error_code": "workflow_driver_error",
                "error": str(exc),
                "next_action": "Inspect the persisted run request and toolchain configuration, then retry.",
            }
            for job in self.store.list_jobs(run_id):
                if job["execution_status"] in {"queued", "running"}:
                    self.store.finish_job(
                        job["job_id"],
                        execution_status="error",
                        verification_status="inconclusive",
                        result={"diagnostics": [diagnostic]},
                    )
                    for attempt in job.get("attempts") or []:
                        if attempt["execution_status"] in {"queued", "running"}:
                            self.store.update_attempt(
                                attempt["attempt_id"],
                                execution_status="error",
                                result={"diagnostics": [diagnostic]},
                            )
                    if job.get("stage_id"):
                        self.store.update_stage_execution(
                            run_id,
                            job["stage_id"],
                            "error",
                            "inconclusive",
                        )
            self._refresh_job_stages(run_id)
            self._refresh_group_stages(run_id)
            self.store.update_run_status(
                run_id,
                execution_status="error",
                verification_status="inconclusive",
                diagnostic=diagnostic,
            )
            self._reconcile_derived_stages(run_id)
            self.store.append_event(run_id, "run.error", diagnostic)
        finally:
            with self._runtime_lock:
                self._cancel_events.pop(run_id, None)
                self._threads.pop(run_id, None)
            for source_run_id in self.store.replay_source_runs_for_target(run_id):
                self.reconcile_counterexample_replays(source_run_id)

    def _refresh_job_stages(self, run_id: str) -> None:
        """Derive each leaf stage state from all Jobs assigned to that stage."""

        jobs_by_stage: dict[str, list[dict[str, Any]]] = {}
        for job in self.store.list_jobs(run_id):
            if job.get("stage_id"):
                jobs_by_stage.setdefault(str(job["stage_id"]), []).append(job)
        verification_priority = {
            "unknown": 0,
            "passed": 1,
            "inconclusive": 2,
            "failed": 3,
        }
        for stage_id, jobs in jobs_by_stage.items():
            execution_values = {str(job["execution_status"]) for job in jobs}
            if "running" in execution_values:
                execution = "running"
            elif "error" in execution_values:
                execution = "error"
            elif "timeout" in execution_values:
                execution = "timeout"
            elif "cancelled" in execution_values:
                execution = "cancelled"
            elif "queued" in execution_values:
                execution = "queued"
            else:
                execution = "completed"
            verification = max(
                (str(job["verification_status"]) for job in jobs),
                key=lambda value: verification_priority.get(value, -1),
            )
            self.store.update_stage_execution(
                run_id,
                stage_id,
                execution,
                verification,
            )

    def _refresh_group_stages(self, run_id: str) -> None:
        """Derive group execution and verification states from enabled children."""

        stages = self.store.list_run_stages(run_id)
        by_parent: dict[str, list[dict[str, Any]]] = {}
        for stage in stages:
            parent_id = stage.get("parent_id")
            if parent_id and stage.get("enabled", True):
                by_parent.setdefault(str(parent_id), []).append(stage)
        verification_priority = {
            "unknown": 0,
            "passed": 1,
            "inconclusive": 2,
            "failed": 3,
        }
        for stage in reversed(stages):
            stage_id = str(stage.get("stage_id") or stage.get("id"))
            children = by_parent.get(stage_id)
            if not children:
                continue
            execution_values = [str(child["execution_status"]) for child in children]
            if "running" in execution_values:
                execution = "running"
            elif "queued" in execution_values:
                execution = "queued"
            elif "error" in execution_values:
                execution = "error"
            elif "timeout" in execution_values:
                execution = "timeout"
            elif "cancelled" in execution_values:
                execution = "cancelled"
            else:
                execution = "completed"
            verification = max(
                (str(child["verification_status"]) for child in children),
                key=lambda value: verification_priority.get(value, -1),
            )
            self.store.update_stage_execution(
                run_id,
                stage_id,
                execution,
                verification,
            )
            stage["execution_status"] = execution
            stage["verification_status"] = verification

    def _reconcile_derived_stages(self, run_id: str) -> None:
        """Derive non-process stage states only from persisted Jobs and signed evidence."""

        run = self.store.get_run(run_id)
        if run is None:
            return
        stages = self.store.list_run_stages(run_id)
        jobs = self.store.list_jobs(run_id)
        by_name: dict[str, list[dict[str, Any]]] = {}
        for stage in stages:
            by_name.setdefault(str(stage.get("name") or "").casefold(), []).append(stage)

        def replace(name: str, execution: str, verification: str) -> None:
            """Replace each enabled derived stage sharing one canonical name."""

            for stage in by_name.get(name, []):
                if stage.get("enabled", True):
                    self.store.replace_stage_state(
                        run_id,
                        str(stage.get("stage_id") or stage.get("id")),
                        execution,
                        verification,
                    )
                    stage["execution_status"] = execution
                    stage["verification_status"] = verification

        run_execution = str(run.get("execution_status") or "queued")
        run_verification = str(run.get("verification_status") or "unknown")
        terminal = run_execution in _TERMINAL_EXECUTION_STATES
        if jobs:
            replace("preflight", "completed", "passed")
        elif terminal:
            replace("preflight", "error", "inconclusive")

        compile_stages = by_name.get("compile_elaborate", [])
        compile_stage = compile_stages[0] if compile_stages else None
        if compile_stage is not None and compile_stage.get("execution_status") != "queued":
            compile_execution = str(compile_stage.get("execution_status") or "queued")
            compile_verification = str(compile_stage.get("verification_status") or "unknown")
            for name in ("environment_scaffold", "environment_import"):
                if compile_execution == "completed":
                    replace(name, "completed", "passed")
                elif compile_execution in _TERMINAL_EXECUTION_STATES:
                    replace(name, compile_execution, compile_verification or "inconclusive")

        selected_formal = next(
            (
                stage
                for name in ("vc_formal", "formal_mc", "sby")
                for stage in by_name.get(name, [])
                if stage.get("enabled", True)
            ),
            None,
        )
        if selected_formal is not None:
            replace(
                "formal_execution",
                str(selected_formal.get("execution_status") or "queued"),
                str(selected_formal.get("verification_status") or "unknown"),
            )

        result = run.get("result") or {}
        tests = list(result.get("tests") or [])
        if tests and terminal:
            replace(
                "result_observer",
                "completed" if run_execution == "completed" else run_execution,
                run_verification,
            )
        elif terminal and by_name.get("result_observer"):
            replace("result_observer", "error", "inconclusive")

        waveform_artifacts = [
            artifact
            for artifact in result.get("artifacts") or []
            if str(artifact.get("kind") or "").casefold() == "waveform"
            or Path(str(artifact.get("path") or "")).suffix.casefold()
            in {".fsdb", ".vpd", ".vcd", ".fst"}
        ]
        if by_name.get("waveform_artifacts") and terminal:
            replace(
                "waveform_artifacts",
                "completed" if waveform_artifacts else "error",
                "passed" if waveform_artifacts else "inconclusive",
            )

        if by_name.get("signoff") and terminal:
            manifests_valid = bool(jobs)
            project = self.store.get_project(run["project_id"])
            project_root = (
                Path(project["source_root"]).resolve(strict=True) if project is not None else None
            )
            for job in jobs:
                attempts = list(job.get("attempts") or [])
                manifest_value = attempts[-1].get("manifest_path") if attempts else None
                if project_root is None or not manifest_value:
                    manifests_valid = False
                    break
                manifest_path = Path(str(manifest_value))
                if not manifest_path.is_absolute():
                    manifest_path = project_root / manifest_path
                try:
                    verify_manifest(
                        manifest_path.resolve(strict=True),
                        self._manifest_key,
                        workspace=project_root,
                        verify_files=True,
                    )
                except (ManifestVerificationError, FileNotFoundError, OSError, ValueError):
                    manifests_valid = False
                    break
            if run_execution == "completed" and manifests_valid:
                replace("signoff", "completed", run_verification)
            else:
                replace("signoff", "error", "inconclusive")
        self._refresh_group_stages(run_id)

    def _stage_for_request(self, run_id: str, request: RunRequest) -> str | None:
        """Map adapter phase metadata to the closest visible workflow stage."""

        phase = str(request.metadata.get("phase") or request.metadata.get("adapter") or "").casefold()
        stages = self.store.list_run_stages(run_id)
        preferred_tokens = {
            "compile": ("compile_elaborate", "compile"),
            "simulate": (str(request.suite or "").casefold(), "run_matrix", "regression"),
            "recipe": (str(request.suite or "").casefold(), "regression", "run_matrix", "compile_elaborate"),
            "imported_executable": (str(request.suite or "").casefold(), "regression", "run_matrix"),
            "urg": ("coverage_merge", "coverage"),
            "formal": (
                str(request.metadata.get("adapter") or request.metadata.get("engine") or "").replace("formalmc", "formal_mc"),
                "formal_execution",
                "proof",
            ),
            "picker": ("picker", "dut"),
            "unitytest": ("regression", "run_matrix", "test"),
        }
        key = "formal" if request.parser in {"formal", "sby"} else (
            "urg" if request.command.tool == "urg" else phase
        )
        tokens = preferred_tokens.get(key, (phase,))
        for token in tokens:
            if not token:
                continue
            for stage in stages:
                searchable = " ".join(
                    (
                        str(stage.get("stage_id") or stage.get("id") or ""),
                        str(stage.get("name") or ""),
                        " ".join(stage.get("required_capabilities") or []),
                    )
                ).casefold()
                if token in searchable and stage.get("enabled", True):
                    return str(stage.get("stage_id") or stage.get("id"))
        return None

    def _build_run_requests(
        self,
        run_id: str,
        workspace: Path,
        config: ProjectConfig,
        request: RunCreateRequest,
        profile: ToolchainProfile,
    ) -> list[RunRequest]:
        """Build an ordered compile/regression/coverage or formal request sequence."""

        base = Path(".ucagent") / "platform-runs" / run_id
        if request.family == "formal":
            return self._build_formal_requests(run_id, workspace, config, base)
        if request.methodology == "unitytest":
            picker = get_adapter("picker")
            pytest_adapter = get_adapter("pytest")
            if not config.design.sources:
                raise ValueError("UnityTest Picker export requires at least one design source")
            if not config.simulation.unitytest_tests:
                raise ValueError(
                    "UnityTest execution requires at least one explicit simulation.unitytest_tests path"
                )
            waveform = config.simulation.waveform
            simulator = config.simulation.simulator
            profile.require_tool("picker")
            profile.require_tool(simulator)
            profile.require_tool("python")
            if simulator == "vcs" and waveform == "fsdb":
                profile.require_tool("verdi")
            picker_output = base / "picker"
            jobs = [
                picker.build_export_request(
                    workspace=workspace,
                    output_dir=picker_output,
                    dut_name=config.design.top,
                    top=config.design.top,
                    source=Path(config.design.sources[0]),
                    filelists=[Path(item) for item in config.design.filelists],
                    simulator=simulator,
                    waveform=waveform,
                    coverage=bool(config.simulation.coverage),
                    verdi_mode="legacy",
                    run_id=f"{run_id}.picker",
                )
            ]
            seeds = config.simulation.seeds or (1,)
            dut_package = picker_output / config.design.top
            for index, (test_path, seed) in enumerate(
                (
                    (Path(test_path), seed)
                    for test_path in config.simulation.unitytest_tests
                    for seed in seeds
                ),
                start=1,
            ):
                jobs.append(
                    pytest_adapter.build_test_request(
                        workspace=workspace,
                        output_dir=base / f"unitytest-{index:04d}",
                        test_path=test_path,
                        picker_output_dir=picker_output,
                        dut_package=dut_package,
                        seed=seed,
                        waveform=waveform,
                        dut_name=config.design.top,
                        run_id=f"{run_id}.unitytest.{index}",
                    )
                )
            return jobs

        simulation = config.simulation
        recipe = simulation.recipe
        if recipe.kind == "make":
            adapter = get_adapter("vcs")
            coverage_values = list(simulation.coverage)
            waveform = simulation.waveform
            if coverage_values and (
                not recipe.coverage_variable or not recipe.coverage_databases
            ):
                raise ValueError(
                    "Imported Make recipe does not declare coverage_variable and "
                    "coverage_databases"
                )
            if waveform != "none" and (
                not recipe.waveform_variable
                or waveform not in recipe.waveform_artifacts
            ):
                raise ValueError(
                    f"Imported Make recipe does not declare {waveform!r} waveform artifacts"
                )
            selected_waveform_artifacts = (
                recipe.waveform_artifacts.get(waveform, ())
                if waveform != "none"
                else ()
            )
            matrix = [
                (test_name, suite.level, seed)
                for suite in simulation.suites
                for test_name in suite.tests
                for seed in (suite.seeds or simulation.seeds or (1,))
            ]
            if not matrix:
                raise ValueError(
                    "Imported Make recipes require at least one explicitly configured suite/test matrix item"
                )
            input_paths = list(
                dict.fromkeys(
                    [
                        Path(recipe.makefile),
                        *(Path(item) for item in config.design.sources),
                        *(Path(item) for item in config.design.filelists),
                        *(Path(item) for item in config.design.include_dirs),
                    ]
                )
            )
            allowed_variables = [
                *recipe.variables,
                recipe.test_variable,
                recipe.seed_variable,
                recipe.output_variable,
                *(
                    [recipe.coverage_variable]
                    if recipe.coverage_variable is not None
                    else []
                ),
                *(
                    [recipe.waveform_variable]
                    if recipe.waveform_variable is not None
                    else []
                ),
            ]
            jobs: list[RunRequest] = []
            coverage_database_paths: list[Path] = []
            for index, (test_name, suite, seed) in enumerate(matrix, start=1):
                output_dir = base / f"recipe-{index:04d}"
                selected_artifacts = [
                    *(Path(item) for item in recipe.artifacts),
                    *(
                        Path(item)
                        for item in recipe.coverage_databases
                        if coverage_values
                    ),
                    *(Path(item) for item in selected_waveform_artifacts),
                ]
                built = adapter.build_recipe_request(
                    workspace=workspace,
                    output_dir=output_dir,
                    makefile=Path(recipe.makefile),
                    target=recipe.target,
                    declared_targets=[recipe.target],
                    variables=recipe.variables,
                    allowed_variables=allowed_variables,
                    test_variable=recipe.test_variable,
                    test_name=test_name,
                    seed_variable=recipe.seed_variable,
                    seed=seed,
                    output_variable=recipe.output_variable,
                    coverage_variable=recipe.coverage_variable,
                    coverage=coverage_values,
                    waveform_variable=recipe.waveform_variable,
                    waveform=waveform,
                    artifact_paths=selected_artifacts,
                    result_paths=[Path(item) for item in recipe.result_logs],
                    success_markers=recipe.success_markers,
                    suite=suite,
                    run_id=f"{run_id}.recipe.{index}",
                )
                jobs.append(built.model_copy(update={"input_paths": input_paths}))
                if coverage_values:
                    coverage_database_paths.extend(
                        output_dir / Path(item) for item in recipe.coverage_databases
                    )
            if coverage_database_paths:
                jobs.append(
                    get_adapter("urg").build_merge_request(
                        workspace=workspace,
                        output_dir=base / "urg",
                        databases=coverage_database_paths,
                        run_id=f"{run_id}.urg",
                    )
                )
            return jobs
        if recipe.kind == "executable":
            return [
                RunRequest(
                    run_id=f"{run_id}.recipe",
                    workspace=workspace,
                    output_dir=base / "recipe",
                    command=CommandSpec(
                        argv=[f"{{WORKSPACE}}/{recipe.executable}", *recipe.arguments],
                        timeout_seconds=7200,
                    ),
                    input_paths=[Path(recipe.executable)],
                    parser="uvm",
                    test_name=Path(recipe.executable).name,
                    success_markers=["TEST PASSED", "UVM_TEST_PASSED", "HIT GOOD TRAP"],
                    metadata={"adapter": "vcs", "phase": "imported_executable"},
                )
            ]

        vcs = get_adapter("vcs")
        waveform = simulation.waveform
        if waveform not in {"none", "fsdb", "vpd"}:
            raise ValueError("Native VCS workflows support FSDB or VPD waveform output")
        compile_dir = base / "compile"
        generated_uvm_scaffold = False
        generated_uvm_timescale: str | None = None
        generated_uvm_manifests: list[Path] = []
        if request.methodology == "uvm":
            inspected_outputs: set[Path] = set()
            for filelist in config.design.filelists:
                output_dir = Path(filelist).parent
                if output_dir in inspected_outputs:
                    continue
                inspected_outputs.add(output_dir)
                manifest_path = workspace / output_dir / UVM_MANIFEST
                if not manifest_path.is_file():
                    continue
                validation = validate_uvm_scaffold(workspace, output_dir.as_posix())
                if not validation.valid:
                    first_issue = validation.errors[0]
                    raise ValueError(
                        "generated UVM scaffold validation failed before VCS compile: "
                        f"{first_issue.code} at {first_issue.path}: {first_issue.message}"
                    )
                manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                scaffold_spec = UvmScaffoldSpec.model_validate(manifest_payload.get("spec"))
                if (
                    generated_uvm_timescale is not None
                    and generated_uvm_timescale != scaffold_spec.timescale
                ):
                    raise ValueError("generated UVM filelists declare conflicting timescales")
                generated_uvm_timescale = scaffold_spec.timescale
                generated_uvm_manifests.append(manifest_path.relative_to(workspace))
                generated_uvm_scaffold = True
        compile_request = vcs.build_compile_request(
                workspace=workspace,
                output_dir=compile_dir,
                top=config.design.top,
                sources=[Path(item) for item in config.design.sources],
                filelists=[Path(item) for item in config.design.filelists],
                include_dirs=[Path(item) for item in config.design.include_dirs],
                defines=config.design.defines,
                parameters=config.design.parameters,
                methodology=request.methodology,
                uvm_version=simulation.uvm_version,
                timescale=generated_uvm_timescale,
                configuration_inputs=generated_uvm_manifests,
                coverage=simulation.coverage,
                waveform=waveform,
                fsdb_pli=profile.require_fsdb_pli() if waveform == "fsdb" else None,
                run_id=f"{run_id}.compile",
            )
        jobs = [
            compile_request.model_copy(
                update={
                    "metadata": {
                        **compile_request.metadata,
                        "cacheable": compile_request.metadata.get("cacheable") is True,
                    },
                }
            )
        ]
        plusargs = request.simulation.plusargs if request.simulation is not None else []
        matrix: list[tuple[str | None, str | None, int | None]] = []
        if request.methodology == "uvm":
            for suite in simulation.suites:
                seeds = suite.seeds or simulation.seeds or (1,)
                for test_name in suite.tests:
                    matrix.extend((test_name, suite.level, seed) for seed in seeds)
        else:
            matrix.extend((None, None, seed) for seed in (simulation.seeds or (1,)))
        vdb_paths = []
        for index, (test_name, suite, seed) in enumerate(matrix, start=1):
            output_dir = base / f"sim-{index:04d}"
            jobs.append(
                vcs.build_simulation_request(
                    workspace=workspace,
                    output_dir=output_dir,
                    executable=compile_dir / "simv",
                    runtime_inputs=[compile_dir / "simv.daidir"],
                    coverage_database=(
                        compile_dir / "simv.vdb" if simulation.coverage else None
                    ),
                    test_name=test_name,
                    suite=suite,
                    seed=seed,
                    coverage=simulation.coverage,
                    waveform=waveform,
                    fsdb_runtime_library_path=(
                        profile.fsdb_runtime_library_path()
                        if waveform == "fsdb"
                        else None
                    ),
                    expect_waveform_artifact=generated_uvm_scaffold and waveform != "none",
                    plusargs=plusargs,
                    success_markers=["TEST PASSED", "UVM_TEST_PASSED", "HIT GOOD TRAP"],
                    run_id=f"{run_id}.sim.{index}",
                )
            )
            if simulation.coverage:
                vdb_paths.append(output_dir / "simv.vdb")
        if vdb_paths:
            jobs.append(
                get_adapter("urg").build_merge_request(
                    workspace=workspace,
                    output_dir=base / "urg",
                    databases=vdb_paths,
                    run_id=f"{run_id}.urg",
                )
            )
        return jobs

    def _build_formal_requests(
        self,
        run_id: str,
        workspace: Path,
        config: ProjectConfig,
        base: Path,
    ) -> list[RunRequest]:
        """Materialize signed formal inputs and build an engine-specific request."""

        formal = config.formal
        if formal.engine == "sby":
            options = formal.sby or SbyOptions()
            adapter = get_adapter("sby")
            plan = adapter.prepare(
                workspace=workspace, top=config.design.top,
                sources=[Path(item) for item in (*config.design.sources, *formal.property_sets)],
                filelists=map(Path, config.design.filelists), include_dirs=map(Path, config.design.include_dirs),
                defines=config.design.defines, parameters=config.design.parameters,
                **options.model_dump(),
            )
            # Each run gets a new immutable control input; existing proof trees
            # are never deleted or reused by SBY's force/reuse switches.
            input_dir = workspace / ".ucagent" / "platform-inputs" / run_id
            input_dir.mkdir(parents=True, exist_ok=False)
            path = input_dir / "run.sby"
            path.write_text(plan.content, encoding="utf-8", newline="\n")
            return [adapter.build_formal_request(
                workspace=workspace, output_dir=base / "formal", config_path=path.relative_to(workspace),
                plan=plan, mode=options.mode, depth=options.depth,
                timeout_seconds=options.timeout_seconds, run_id=f"{run_id}.formal",
            )]
        if formal.engine == "vc_formal":
            if not config.design.filelists and not config.design.sources:
                raise ValueError("VC Formal requires design.filelists or design.sources")
            if not formal.clock.signal or not formal.reset.signal:
                raise ValueError("VC Formal requires explicit formal.clock.signal and formal.reset.signal")
            input_identity = hashlib.sha256(
                json.dumps(
                    {
                        "design": config.design.model_dump(mode="json"),
                        "formal": formal.model_dump(mode="json"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:32]
            input_dir = workspace / ".ucagent" / "platform-inputs" / input_identity
            input_dir.mkdir(parents=True, exist_ok=True)
            filelist_path = input_dir / "design.f"

            def quote_filelist_path(value: str) -> str:
                """Resolve and quote a signed project input for the isolated formal session."""

                normalized = resolve_within(
                    workspace,
                    Path(value),
                    must_exist=True,
                ).as_posix()
                return f'"{normalized}"' if any(character.isspace() for character in normalized) else normalized

            filelist_lines = []
            filelist_lines.extend(
                f'"+incdir+{quote_filelist_path(item).strip(chr(34))}"'
                if any(character.isspace() for character in item)
                else f"+incdir+{quote_filelist_path(item)}"
                for item in config.design.include_dirs
            )
            filelist_lines.extend(f"+define+{item}" for item in config.design.defines)
            filelist_lines.extend(
                f"-F {quote_filelist_path(item)}" for item in config.design.filelists
            )
            filelist_lines.extend(quote_filelist_path(item) for item in config.design.sources)
            filelist_lines.extend(quote_filelist_path(item) for item in formal.property_sets)
            filelist_content = "\n".join(filelist_lines) + "\n"
            if filelist_path.exists() and filelist_path.read_text(encoding="utf-8") != filelist_content:
                raise RuntimeError("Content-addressed formal file-list collision detected")
            if not filelist_path.exists():
                temporary_filelist = filelist_path.with_name(
                    f".{filelist_path.name}.{secrets.token_hex(8)}.tmp"
                )
                temporary_filelist.write_text(filelist_content, encoding="utf-8")
                os.replace(temporary_filelist, filelist_path)
            relative_filelist = filelist_path.relative_to(workspace)
            adapter = get_adapter("vc_formal")
            tcl = adapter.render_tcl(
                filelist=relative_filelist,
                top=config.design.top,
                clock={
                    "signal": formal.clock.signal,
                    **({"period": formal.clock.period_ns} if formal.clock.period_ns else {}),
                },
                reset={
                    "signal": formal.reset.signal,
                    "sense": "high" if formal.reset.active_level else "low",
                },
            )
            tcl_path = input_dir / "run.tcl"
            if tcl_path.exists() and tcl_path.read_text(encoding="utf-8") != tcl:
                raise RuntimeError("Content-addressed formal Tcl collision detected")
            if not tcl_path.exists():
                temporary_tcl = tcl_path.with_name(f".{tcl_path.name}.{secrets.token_hex(8)}.tmp")
                temporary_tcl.write_text(tcl, encoding="utf-8")
                os.replace(temporary_tcl, tcl_path)
            formal_request = adapter.build_formal_request(
                    workspace=workspace,
                    output_dir=base / "formal",
                    tcl_path=tcl_path.relative_to(workspace),
                    filelist=relative_filelist,
                    design_inputs=[
                        *(Path(item) for item in config.design.sources),
                        *(Path(item) for item in config.design.filelists),
                        *(Path(item) for item in config.design.include_dirs),
                        *(Path(item) for item in formal.property_sets),
                    ],
                    property_set=",".join(formal.property_sets) or None,
                    run_id=f"{run_id}.formal",
                )
            return [
                formal_request.model_copy(
                    update={
                        "metadata": {
                            **formal_request.metadata,
                            "cacheable": formal_request.metadata.get("cacheable") is True,
                        },
                    }
                )
            ]
        adapter = get_adapter("formal_mc")
        tcl_path = adapter.select_script(formal.property_sets)
        formal_request = adapter.build_formal_request(
            workspace=workspace,
            output_dir=base / "formal",
            tcl_path=tcl_path,
            design_inputs=[
                *(Path(item) for item in config.design.sources),
                *(Path(item) for item in config.design.filelists),
                *(Path(item) for item in config.design.include_dirs),
                *(Path(item) for item in formal.property_sets),
            ],
            property_set=",".join(formal.property_sets),
            run_id=f"{run_id}.formal",
        )
        return [formal_request]

    def _merge_results(self, run_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge normalized job results and derive traceable verification issues."""

        merged: dict[str, Any] = {
            "tests": [],
            "coverage": [],
            "properties": [],
            "artifacts": [],
            "issues": [],
            "diagnostics": [],
        }
        issues_by_id: dict[str, dict[str, Any]] = {}

        def status_value(value: Any) -> str:
            """Return a lower-case status from either an enum or serialized value."""

            return str(getattr(value, "value", value) or "unknown").casefold()

        def stable_issue_id(kind: str, source: str, identity: dict[str, Any]) -> str:
            """Derive a repeatable globally unique identifier for one run finding."""

            return hashlib.sha256(
                json.dumps(
                    {
                        "run_id": run_id,
                        "kind": kind,
                        "source": source,
                        "identity": identity,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()[:24]

        def add_issue(issue: dict[str, Any]) -> None:
            """Deduplicate a repeated diagnosis while retaining all evidence IDs."""

            issue_id = str(issue["issue_id"])
            prior = issues_by_id.get(issue_id)
            if prior is None:
                issues_by_id[issue_id] = issue
                return
            evidence = list(
                dict.fromkeys(
                    [
                        *(prior.get("evidence_artifact_ids") or []),
                        *(issue.get("evidence_artifact_ids") or []),
                    ]
                )
            )
            if evidence:
                prior["evidence_artifact_ids"] = evidence

        for result_index, result in enumerate(results):
            source = str(
                result.get("run_id")
                or result.get("manifest_path")
                or result.get("input_fingerprint")
                or f"result-{result_index}"
            )
            session_dir = Path(str(result.get("session_dir") or ""))
            artifact_records: list[tuple[dict[str, Any], Path | None]] = []
            for artifact in result.get("artifacts") or []:
                item = dict(artifact)
                if not item.get("artifact_id"):
                    item["artifact_id"] = item.get("id")
                item["metadata"] = {
                    **(item.get("metadata") or {}),
                    "is_directory": bool(item.get("is_directory", False)),
                    "hash_excludes": item.get("hash_excludes") or [],
                }
                relative = Path(str(item.get("path") or ""))
                resolved: Path | None = None
                if relative.parts and session_dir.parts:
                    resolved = (relative if relative.is_absolute() else session_dir / relative).resolve()
                    item["path"] = str(resolved)
                elif relative.is_absolute():
                    resolved = relative.resolve()
                merged["artifacts"].append(item)
                artifact_records.append((item, resolved))
            manifest_path = result.get("manifest_path")
            if manifest_path:
                manifest = Path(str(manifest_path))
                if manifest.is_file():
                    merged["artifacts"].append(
                        {
                            "artifact_id": hashlib.sha256(str(manifest).encode("utf-8")).hexdigest()[:32],
                            "kind": "manifest",
                            "name": "manifest.json",
                            "path": str(manifest.resolve()),
                            "media_type": "application/json",
                            "size_bytes": manifest.stat().st_size,
                            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                        }
                    )
            def artifact_for_path(raw_path: Any) -> tuple[str, str] | None:
                """Resolve an emitted path to an exact downloadable signed artifact."""

                if not raw_path:
                    return None
                candidate = Path(str(raw_path))
                if not candidate.is_absolute() and session_dir.parts:
                    candidate = session_dir / candidate
                try:
                    candidate = candidate.resolve(strict=True)
                except OSError:
                    return None
                for artifact_item, artifact_path in list(artifact_records):
                    artifact_id = artifact_item.get("artifact_id")
                    if not artifact_id or artifact_path is None or not artifact_path.exists():
                        continue
                    try:
                        matches = candidate == artifact_path or (
                            bool(artifact_item.get("is_directory"))
                            and candidate.is_relative_to(artifact_path)
                        )
                    except (OSError, ValueError):
                        matches = False
                    if matches:
                        if candidate == artifact_path and candidate.is_file():
                            return str(artifact_id), str(candidate)
                        if not candidate.is_file() or not artifact_item.get("is_directory"):
                            continue
                        relative_member = candidate.relative_to(artifact_path).as_posix()
                        member_id = hashlib.sha256(
                            f"{artifact_id}:{relative_member}".encode("utf-8")
                        ).hexdigest()[:32]
                        member = {
                            "artifact_id": member_id,
                            "kind": "counterexample",
                            "name": candidate.name,
                            "path": str(candidate),
                            "media_type": (
                                mimetypes.guess_type(candidate.name)[0]
                                or "application/octet-stream"
                            ),
                            "size_bytes": candidate.stat().st_size,
                            "sha256": sha256_file(candidate),
                            "metadata": {
                                "is_directory": False,
                                "covered_by_artifact_id": str(artifact_id),
                                "covered_by_directory_sha256": artifact_item.get("sha256"),
                                "relative_member": relative_member,
                            },
                        }
                        if not any(
                            existing.get("artifact_id") == member_id
                            for existing in merged["artifacts"]
                        ):
                            merged["artifacts"].append(member)
                            artifact_records.append((member, candidate))
                        return member_id, str(candidate)
                return None

            def signed_evidence_ids(*, formal: bool = False) -> list[str]:
                """Return nonempty signed logs/reports and simulation waveforms."""

                allowed = {"log", "report"} if formal else {"log", "report", "waveform"}
                values = []
                for artifact_item, artifact_path in artifact_records:
                    artifact_id = artifact_item.get("artifact_id")
                    if (
                        artifact_id
                        and artifact_path is not None
                        and artifact_path.exists()
                        and int(artifact_item.get("size_bytes") or 0) > 0
                        and str(artifact_item.get("kind") or "") in allowed
                    ):
                        values.append(str(artifact_id))
                return list(dict.fromkeys(values))

            merged["coverage"].extend(result.get("coverage") or [])
            for test in result.get("tests") or []:
                test_item = dict(test)
                merged["tests"].append(test_item)
                if status_value(test_item.get("verification_status") or test_item.get("status")) != "failed":
                    continue
                test_name = str(test_item.get("test_name") or test_item.get("name") or "unknown")
                suite = test_item.get("suite")
                seed = test_item.get("seed")
                evidence_ids = signed_evidence_ids()
                log_match = artifact_for_path(test_item.get("log_path"))
                if log_match:
                    evidence_ids = list(dict.fromkeys([log_match[0], *evidence_ids]))
                    test_item["log_path"] = log_match[1]
                add_issue(
                    {
                        "issue_id": stable_issue_id(
                            "test_failure",
                            source,
                            {"test_name": test_name, "suite": suite, "seed": seed},
                        ),
                        "severity": "high",
                        "title": f"Verification test failed: {test_name}",
                        "status": "open",
                        "category": "test_failure",
                        "run_id": run_id,
                        "test_case": test_name,
                        "test_name": test_name,
                        "suite": suite,
                        "seed": seed,
                        "execution_status": status_value(test_item.get("execution_status")),
                        "verification_status": "failed",
                        "message": str(test_item.get("message") or ""),
                        "error_count": int(test_item.get("error_count") or 0),
                        "fatal_count": int(test_item.get("fatal_count") or 0),
                        "assertion_failures": int(test_item.get("assertion_failures") or 0),
                        "evidence_artifact_ids": evidence_ids,
                        "next_action": (
                            "Review the signed logs and waveform evidence, classify the failure as DUT or "
                            "verification infrastructure, and correct the responsible implementation without "
                            "weakening the checker."
                        ),
                    }
                )

            for formal_property in result.get("properties") or []:
                property_item = dict(formal_property)
                cex_match = artifact_for_path(property_item.get("counterexample_path"))
                evidence_match = artifact_for_path(property_item.get("evidence_path"))
                if cex_match:
                    property_item["counterexample_path"] = cex_match[1]
                    property_item["counterexample_artifact_id"] = cex_match[0]
                if evidence_match:
                    property_item["evidence_path"] = evidence_match[1]
                    property_item["evidence_artifact_id"] = evidence_match[0]
                merged["properties"].append(property_item)
                if status_value(property_item.get("status")) != "falsified":
                    continue
                property_name = str(
                    property_item.get("name") or property_item.get("property_name") or "unknown"
                )
                evidence_ids = signed_evidence_ids(formal=True)
                if cex_match:
                    evidence_ids = list(dict.fromkeys([cex_match[0], *evidence_ids]))
                if evidence_match:
                    evidence_ids = list(dict.fromkeys([evidence_match[0], *evidence_ids]))
                issue = {
                    "issue_id": stable_issue_id(
                        "formal_falsification",
                        source,
                        {"property_name": property_name},
                    ),
                    "severity": "high",
                    "title": f"Formal property falsified: {property_name}",
                    "status": "open",
                    "category": "formal_falsification",
                    "run_id": run_id,
                    "property_name": property_name,
                    "property_status": "falsified",
                    "engine": property_item.get("engine"),
                    "proof_depth": property_item.get("proof_depth", property_item.get("depth")),
                    "counterexample_available": bool(cex_match),
                    "evidence_artifact_ids": evidence_ids,
                    "next_action": (
                        "Inspect the signed formal result and any actual counterexample artifact, correct the "
                        "RTL or assumptions, then rerun proof before requesting dynamic reproduction."
                    ),
                }
                if property_item.get("counterexample_path"):
                    issue["counterexample_path"] = property_item["counterexample_path"]
                if cex_match:
                    issue["counterexample_artifact_id"] = cex_match[0]
                if property_item.get("evidence_path"):
                    issue["formal_evidence_path"] = property_item["evidence_path"]
                if evidence_match:
                    issue["formal_evidence_artifact_id"] = evidence_match[0]
                add_issue(issue)

            diagnostics = list(result.get("diagnostics") or [])
            merged["diagnostics"].extend(diagnostics)
            diagnostic_evidence = signed_evidence_ids()
            for diagnostic in diagnostics:
                diagnostic_item = dict(diagnostic)
                add_issue(
                    {
                        **diagnostic_item,
                        "issue_id": stable_issue_id("diagnostic", source, diagnostic_item),
                        "severity": "error",
                        "title": str(
                            diagnostic_item.get("error")
                            or diagnostic_item.get("error_code")
                            or "Run diagnostic"
                        ),
                        "status": "open",
                        "category": diagnostic_item.get("error_code"),
                        "run_id": run_id,
                        "evidence_artifact_ids": diagnostic_evidence,
                    }
                )
        merged["issues"] = list(issues_by_id.values())
        store = getattr(self, "store", None)
        run = store.get_run(run_id) if store is not None else None
        project = store.get_project(run["project_id"]) if run is not None else None
        simulation = ((project or {}).get("config") or {}).get("simulation") or {}
        mappings = list(simulation.get("coverage_mapping") or [])
        mapped_coverage: list[dict[str, Any]] = []
        for raw_metric in merged["coverage"]:
            metric = dict(raw_metric)
            metric_name = str(metric.get("metric") or metric.get("name") or "").casefold()
            metric_scope = str(metric.get("scope") or "overall")
            matches = [
                mapping
                for mapping in mappings
                if metric_name in mapping.get("metrics", [])
                and any(
                    metric_scope == scope or metric_scope.startswith(f"{scope}.")
                    for scope in mapping.get("scopes", [])
                )
            ]
            if not matches:
                metric["mapping"] = "Unmapped: declare simulation.coverage_mapping"
                mapped_coverage.append(metric)
                continue
            for mapping in matches:
                mapped_coverage.append(
                    {
                        **metric,
                        "mapping": mapping["requirement_id"],
                        "requirement_id": mapping["requirement_id"],
                        "target": mapping.get("target_percent", 100.0),
                    }
                )
        merged["coverage"] = mapped_coverage
        return merged

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        """Request process-tree cancellation for an active run."""

        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["execution_status"] in _TERMINAL_EXECUTION_STATES:
            return self.run_public(run)
        with self._runtime_lock:
            event = self._cancel_events.get(run_id)
        if event is None:
            self.store.update_run_status(
                run_id,
                execution_status="error",
                verification_status="inconclusive",
                diagnostic={
                    "error_code": "runner_not_available",
                    "error": "The active runner is no longer attached to this process.",
                    "next_action": "Retry the run from its persisted request.",
                },
            )
        else:
            event.set()
            self.store.append_event(run_id, "run.cancel_requested", {})
        return self.run_public(self.store.get_run(run_id) or run)

    def start_counterexample_replay(
        self,
        source_run_id: str,
        request: CounterexampleReplayStartRequest,
    ) -> dict[str, Any]:
        """Start one real dynamic run linked to signed falsified-property evidence."""

        source_run = self.store.get_run(source_run_id)
        if source_run is None:
            raise KeyError(source_run_id)
        source_request = source_run.get("request") or {}
        if source_request.get("family") != "formal":
            raise ValueError("counterexample replay requires a formal source run")
        if source_run.get("execution_status") != "completed":
            raise ValueError("formal source run must have completed execution before replay")
        replay_policy = ((source_request.get("formal") or {}).get("cex_replay") or {})
        if replay_policy.get("enabled") is not True:
            raise ValueError("formal.cex_replay.enabled is false for the source run")
        if replay_policy.get("methodology") != request.methodology:
            raise ValueError(
                "replay methodology must match the immutable formal source-run policy"
            )
        properties = self.store.list_result_rows(source_run_id, "properties")
        property_result = next(
            (
                item
                for item in properties
                if str(item.get("property_name") or item.get("name")) == request.property_name
            ),
            None,
        )
        if property_result is None:
            raise ValueError(f"formal property not found: {request.property_name}")
        if str(property_result.get("status") or "").casefold() != "falsified":
            raise ValueError("only a falsified formal property can be dynamically replayed")
        counterexample_artifact_id = property_result.get("counterexample_artifact_id")
        if not isinstance(counterexample_artifact_id, str) or not counterexample_artifact_id:
            raise ValueError("falsified property has no exact signed counterexample artifact")
        self.verify_artifact_provenance(source_run_id, counterexample_artifact_id)

        if request.methodology == "unitytest":
            assert request.unitytest_test is not None
            project = self.store.get_project(source_run["project_id"])
            if project is None:
                raise KeyError(source_run["project_id"])
            resolve_within(
                Path(project["source_root"]),
                Path(request.unitytest_test),
                must_exist=True,
            )
        simulation = SimulationRunOptions(
            simulator=request.simulator,
            uvm_version=str(
                ((self.store.get_project(source_run["project_id"]) or {}).get("config") or {})
                .get("simulation", {})
                .get("uvm_version", "1.2")
            ),
            unitytest_tests=(
                [request.unitytest_test]
                if request.methodology == "unitytest" and request.unitytest_test is not None
                else []
            ),
            suites=[request.suite] if request.methodology == "uvm" else [],
            tests=[request.uvm_test] if request.methodology == "uvm" and request.uvm_test else [],
            seeds=[request.seed],
            coverage=[],
            waveform=request.waveform,
            plusargs=request.plusargs,
        )
        target_request = RunCreateRequest(
            project_id=source_run["project_id"],
            family="simulation",
            methodology=request.methodology,
            authoring_mode="guided",
            toolchain=str(source_request.get("toolchain") or ""),
            design=dict(source_request.get("design") or {}),
            simulation=simulation,
        )
        target_run = self.create_run(target_request)
        replay = self.store.create_counterexample_replay(
            source_run_id=source_run_id,
            property_name=request.property_name,
            counterexample_artifact_id=counterexample_artifact_id,
            target_run_id=target_run["id"],
            methodology=request.methodology,
            request=request.model_dump(mode="json"),
        )
        stage_id = self.store.activate_stage(source_run_id, "counterexample_dynamic_replay")
        self.store.append_event(
            source_run_id,
            "counterexample.replay_started",
            {
                "replay_id": replay["replay_id"],
                "property_name": request.property_name,
                "counterexample_artifact_id": counterexample_artifact_id,
                "target_run_id": target_run["id"],
                "stage_id": stage_id,
            },
        )
        self.store.add_audit_event(
            "counterexample.replay_started",
            "run",
            source_run_id,
            {
                "replay_id": replay["replay_id"],
                "property_name": request.property_name,
                "target_run_id": target_run["id"],
            },
        )
        return {**replay, "target_run": target_run}

    def reconcile_counterexample_replays(self, source_run_id: str) -> dict[str, Any]:
        """Revalidate replay links and derive the deferred replay-stage conclusion."""

        source_run = self.store.get_run(source_run_id)
        if source_run is None:
            raise KeyError(source_run_id)
        replays = self.store.list_counterexample_replays(source_run_id)
        if not replays:
            return {"items": [], "total": 0, "required_properties": [], "reproduced": 0}
        properties = self.store.list_result_rows(source_run_id, "properties")
        required_properties = {
            str(item.get("property_name") or item.get("name"))
            for item in properties
            if str(item.get("status") or "").casefold() == "falsified"
            and item.get("counterexample_artifact_id")
        }
        updated: list[dict[str, Any]] = []
        for replay in replays:
            target = self.store.get_run(replay["target_run_id"])
            evidence: dict[str, Any] = {
                "counterexample_artifact_id": replay["counterexample_artifact_id"],
                "target_run_id": replay["target_run_id"],
            }
            try:
                _, counterexample_path, counterexample_provenance = self.verify_artifact_provenance(
                    source_run_id,
                    replay["counterexample_artifact_id"]
                )
                evidence["counterexample_sha256"] = sha256_file(counterexample_path)
                evidence.update(
                    {
                        f"counterexample_{key}": value
                        for key, value in counterexample_provenance.items()
                    }
                )
            except (KeyError, ValueError):
                status = "evidence_invalid"
            else:
                target_execution = str((target or {}).get("execution_status") or "error")
                target_verification = str(
                    (target or {}).get("verification_status") or "inconclusive"
                )
                if target_execution in {"queued", "running"}:
                    status = target_execution
                elif target_execution != "completed":
                    status = "inconclusive"
                elif target_verification != "failed":
                    status = "not_reproduced"
                else:
                    failed_tests = [
                        item
                        for item in self.store.list_result_rows(
                            replay["target_run_id"], "tests"
                        )
                        if str(item.get("status") or item.get("verification_status") or "").casefold()
                        == "failed"
                    ]
                    manifests = [
                        item
                        for item in self.store.list_artifacts(replay["target_run_id"])
                        if item.get("kind") == "manifest"
                    ]
                    verified_manifest = None
                    for manifest in manifests:
                        try:
                            _, manifest_path = self.resolve_artifact(manifest["artifact_id"])
                            target_project = self.store.get_project(target["project_id"])
                            if target_project is None:
                                raise ValueError("target replay project is unavailable")
                            verify_manifest(
                                manifest_path,
                                self._manifest_key,
                                workspace=Path(target_project["source_root"]).resolve(strict=True),
                                verify_files=True,
                            )
                        except (KeyError, ValueError, ManifestVerificationError, OSError):
                            continue
                        verified_manifest = manifest
                        break
                    if failed_tests and verified_manifest is not None:
                        status = "reproduced"
                        evidence["failed_test_record_ids"] = [
                            item.get("record_id") for item in failed_tests
                        ]
                        evidence["target_manifest_artifact_id"] = verified_manifest[
                            "artifact_id"
                        ]
                        evidence["target_manifest_sha256"] = verified_manifest["sha256"]
                    else:
                        status = "evidence_invalid"
            if status != replay.get("status") or evidence != replay.get("evidence"):
                self.store.update_counterexample_replay(
                    replay["replay_id"], status=status, evidence=evidence
                )
                self.store.append_event(
                    source_run_id,
                    "counterexample.replay_status",
                    {
                        "replay_id": replay["replay_id"],
                        "property_name": replay["property_name"],
                        "target_run_id": replay["target_run_id"],
                        "status": status,
                    },
                )
            current = self.store.get_counterexample_replay(replay["replay_id"])
            if current is not None:
                updated.append(current)

        stages = self.store.list_run_stages(source_run_id)
        replay_stage = next(
            (item for item in stages if item.get("name") == "counterexample_dynamic_replay"),
            None,
        )
        if replay_stage is not None and replay_stage.get("enabled"):
            reproduced_properties = {
                item["property_name"] for item in updated if item["status"] == "reproduced"
            }
            attempted_properties = {item["property_name"] for item in updated}
            statuses = {item["status"] for item in updated}
            if required_properties and required_properties <= reproduced_properties:
                execution_status, verification_status = "completed", "failed"
            elif statuses & {"running"}:
                execution_status, verification_status = "running", "unknown"
            elif statuses & {"queued"} or required_properties - attempted_properties:
                execution_status, verification_status = "queued", "unknown"
            elif statuses & {"evidence_invalid", "inconclusive"}:
                execution_status, verification_status = "error", "inconclusive"
            else:
                execution_status, verification_status = "completed", "inconclusive"
            self.store.replace_stage_state(
                source_run_id,
                str(replay_stage.get("stage_id") or replay_stage.get("id")),
                execution_status,
                verification_status,
            )
        return {
            "items": updated,
            "total": len(updated),
            "required_properties": sorted(required_properties),
            "reproduced": sum(item["status"] == "reproduced" for item in updated),
        }

    def shutdown(self) -> None:
        """Cancel owned jobs and allow bounded time for process cleanup and signed publication."""

        self.formal_sessions.shutdown()
        with self._runtime_lock:
            events = list(self._cancel_events.values())
            threads = list(self._threads.values())
        for event in events:
            event.set()
        # Workers publish their terminal evidence after observing cancellation.
        # Never hold the registry lock while joining: workers release it on exit.
        deadline = time.monotonic() + 10
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def run_public(self, run: dict[str, Any]) -> dict[str, Any]:
        """Project one stored run into the stable browser representation."""

        request = run.get("request") or {}
        project = self.store.get_project(run["project_id"])
        diagnostic = run.get("diagnostic") or {}
        result = run.get("result") or {}
        manifest_hash = None
        for artifact in result.get("artifacts") or []:
            if str(artifact.get("path", "")).endswith("manifest.json"):
                manifest_hash = artifact.get("sha256")
                break
        summary = run_summary(run, self.store.list_jobs(run["run_id"]))
        return {
            "id": run["run_id"],
            "project_id": run["project_id"],
            "project_name": project.get("name") if project else None,
            "workflow_id": run["workflow"],
            "family": request.get("family"),
            "methodology": request.get("methodology"),
            "authoring_mode": request.get("authoring_mode"),
            "toolchain": request.get("toolchain"),
            "execution_status": run["execution_status"],
            "verification_status": run["verification_status"],
            "created_at": _iso_timestamp(run.get("created_at")),
            "started_at": _iso_timestamp(run.get("started_at")),
            "finished_at": _iso_timestamp(run.get("finished_at")),
            "stages": self.run_stages_public(run["run_id"]),
            "manifest_hash": manifest_hash,
            "error": diagnostic.get("error"),
            "summary": summary,
            "request": redact_data(request),
            "progress": (
                round(100 * summary["jobs_finished"] / summary["jobs_total"])
                if summary["jobs_total"] else None
            ),
            "current_stage": summary["active_tool"],
            "cex_replay": (request.get("formal") or {}).get("cex_replay"),
        }

    def run_stages_public(self, run_id: str) -> list[dict[str, Any]]:
        """Return run stages with globally addressable API identifiers."""

        if self.store.list_counterexample_replays(run_id):
            self.reconcile_counterexample_replays(run_id)
        result = []
        for stage in self.store.list_run_stages(run_id):
            item = dict(stage)
            raw_id = str(item.get("stage_id") or item.get("id"))
            item["stage_key"] = raw_id
            item["id"] = f"{run_id}:{raw_id}"
            if item.get("parent_id"):
                item["parent_id"] = f"{run_id}:{item['parent_id']}"
            item.pop("stage_id", None)
            result.append(item)
        return result

    def jobs_public(self, run_id: str) -> list[dict[str, Any]]:
        """Normalize persisted jobs for the Run Detail page."""

        result = []
        for job in self.store.list_jobs(run_id):
            data = job.get("result") or {}
            diagnostics = data.get("diagnostics") or []
            result.append(
                {
                    "id": job["job_id"],
                    "run_id": run_id,
                    "stage_id": f"{run_id}:{job['stage_id']}" if job.get("stage_id") else None,
                    "name": job["kind"],
                    "tool": job["kind"],
                    "execution_status": job["execution_status"],
                    "verification_status": job["verification_status"],
                    "attempt": len(job.get("attempts") or []),
                    "command": (job.get("command") or {}).get("argv", []),
                    "started_at": _iso_timestamp(job.get("started_at")),
                    "finished_at": _iso_timestamp(job.get("finished_at")),
                    "exit_code": data.get("return_code"),
                    "diagnostic_code": diagnostics[0].get("error_code") if diagnostics else None,
                    "diagnostic": diagnostics[0].get("error") if diagnostics else None,
                }
            )
        return result

    def toolchains_public(self) -> list[dict[str, Any]]:
        """Return toolchain capabilities without exposing environment values."""

        probes = self.store.list_toolchain_probes()
        result = []
        for identifier, profile in self._profiles.items():
            probe = probes.get(identifier, {})
            capabilities = (probe.get("details") or {}).get("capabilities") or [
                {
                    "name": alias,
                    "available": bool(Path(executable).is_file() or shutil.which(executable)),
                    "version": profile.versions.get(alias),
                }
                for alias, executable in sorted(profile.tools.items())
            ]
            capabilities = list(capabilities)
            if "vcs" in profile.tools and not any(
                item.get("name") == "fsdb_pli" for item in capabilities
            ):
                pli_paths = (
                    (
                        profile.fsdb_pli.table,
                        profile.fsdb_pli.library,
                        *profile.fsdb_pli.runtime_library_dirs,
                    )
                    if profile.fsdb_pli is not None
                    else ()
                )
                pli_available = bool(pli_paths) and all(
                    path.is_file() if index < 2 else path.is_dir()
                    for index, path in enumerate(pli_paths)
                )
                capabilities.append(
                    {
                        "name": "fsdb_pli",
                        "available": pli_available,
                        "reason": None
                        if pli_available
                        else "Explicit Verdi novas.tab, pli.a, and runtime library paths are not configured or readable.",
                    }
                )
            result.append(
                {
                    "id": identifier,
                    "name": profile.display_name or identifier,
                    "available": any(item["available"] for item in capabilities),
                    "status": probe.get("status", "unknown"),
                    "license_status": (probe.get("details") or {}).get("license_status", "unknown"),
                    "max_concurrency": profile.max_concurrency,
                    "capabilities": capabilities,
                    "last_probe_at": _iso_timestamp(probe.get("probed_at")),
                    "diagnostic": (probe.get("details") or {}).get("diagnostic"),
                }
            )
        for identifier, error in self._profile_errors.items():
            result.append(
                {
                    "id": identifier,
                    "name": identifier,
                    "available": False,
                    "status": "unavailable",
                    "license_status": "unknown",
                    "capabilities": [],
                    "diagnostic": error,
                }
            )
        return result

    def probe_toolchain(self, identifier: str) -> dict[str, Any]:
        """Run version probes and real bounded commercial-license smokes."""

        profile = self._profiles.get(identifier)
        if profile is None:
            raise KeyError(identifier)
        alias_adapters = {
            "picker": "picker",
            "vcs": "vcs",
            "urg": "urg",
            "vcf": "vc_formal",
            "formalmc": "formal_mc",
            "sby": "sby",
            "yosys": "sby",
            "yosys-smtbmc": "sby",
            "z3": "sby",
        }
        capabilities = []
        all_available = True
        license_statuses: list[LicenseStatus] = []
        timestamp = f"{int(time.time() * 1000)}-{secrets.token_hex(4)}"
        probe_root = (
            Path(".ucagent")
            / "platform"
            / "toolchain-probes"
            / identifier
            / timestamp
        )
        secret_values = tuple(profile.environment.values())

        def bounded_logs(result: Any) -> str:
            """Read a bounded redacted excerpt from one signed probe result."""

            parts = []
            remaining = 1024 * 1024
            for log_path in (result.stdout_log, result.stderr_log):
                if remaining <= 0 or not log_path or not log_path.is_file():
                    continue
                with log_path.open("rb") as stream:
                    value = stream.read(remaining)
                parts.append(value.decode("utf-8", errors="replace"))
                remaining -= len(value)
            return str(redact_data("\n".join(parts), secret_values))

        for alias, executable in sorted(profile.tools.items()):
            binary_available = bool(Path(executable).is_file() or shutil.which(executable))
            capability: dict[str, Any] = {
                "name": alias,
                "available": binary_available,
                "binary_available": binary_available,
                "license_status": LicenseStatus.UNKNOWN.value,
            }
            adapter_name = alias_adapters.get(alias)
            if binary_available and adapter_name is not None:
                adapter = get_adapter(adapter_name)
                try:
                    commands = [
                        command
                        for command in adapter.probe_commands(profile)
                        if command.tool == alias
                    ]
                    for command_index, command in enumerate(commands):
                        probe = RunRequest(
                            run_id=f"probe.{identifier}.{timestamp}.{alias}.version.{command_index}",
                            workspace=self.workspace,
                            output_dir=probe_root
                            / "version"
                            / alias
                            / str(command_index),
                            command=command,
                            verification_hint=VerificationStatus.PASSED,
                            test_name=f"{alias}_probe",
                            metadata={
                                "adapter": adapter_name,
                                "probe": True,
                                "probe_kind": "version",
                            },
                        )
                        result = self._runner.run(probe, profile)
                        version_available = result.execution_status == ExecutionStatus.COMPLETED
                        capability["available"] = bool(capability["available"]) and version_available
                        capability["version_probe_status"] = result.execution_status.value
                        output_lines = [
                            line.strip()
                            for line in bounded_logs(result).splitlines()
                            if line.strip()
                        ]
                        if output_lines:
                            capability["version"] = output_lines[0][:240]
                        if result.diagnostics:
                            capability["reason"] = result.diagnostics[0].get("error")

                    if alias in {"vcs", "vcf"}:
                        license_request = build_license_probe_request(
                            adapter_name,
                            workspace=self.workspace,
                            input_dir=probe_root / "inputs" / alias,
                            output_dir=probe_root / "license" / alias,
                            run_id=f"probe.{identifier}.{timestamp}.{alias}.license",
                            timeout_seconds=120,
                        )
                        if license_request is None:
                            raise RuntimeError(
                                f"adapter {adapter_name!r} has no commercial license smoke"
                            )
                        license_result = self._runner.run(license_request, profile)
                        license_output = bounded_logs(license_result)
                        observed_license = classify_license_probe(
                            license_output,
                            execution_status=license_result.execution_status,
                            diagnostics=license_result.diagnostics,
                        )
                        license_statuses.append(observed_license)
                        capability["license_status"] = observed_license.value
                        capability["license_probe_status"] = license_result.execution_status.value
                        capability["available"] = bool(capability["available"]) and (
                            observed_license == LicenseStatus.AVAILABLE
                        )
                        if observed_license == LicenseStatus.BUSY:
                            capability["reason"] = "Commercial license seats are currently busy."
                        elif observed_license == LicenseStatus.UNAVAILABLE:
                            capability["reason"] = "Commercial license checkout is unavailable."
                        elif observed_license == LicenseStatus.UNKNOWN:
                            capability["reason"] = (
                                "The commercial license smoke did not reach a conclusive state."
                            )
                except Exception as exc:
                    capability["available"] = False
                    capability["reason"] = redact_data(str(exc), secret_values)
                    if alias in {"vcs", "vcf"}:
                        license_statuses.append(LicenseStatus.UNKNOWN)
            if capability.get("reason") is not None:
                capability["reason"] = redact_data(capability["reason"], secret_values)
            capabilities.append(capability)
            all_available = all_available and bool(capability["available"])
        if LicenseStatus.UNAVAILABLE in license_statuses:
            license_status = LicenseStatus.UNAVAILABLE
        elif LicenseStatus.BUSY in license_statuses:
            license_status = LicenseStatus.BUSY
        elif LicenseStatus.UNKNOWN in license_statuses:
            license_status = LicenseStatus.UNKNOWN
        elif license_statuses:
            license_status = LicenseStatus.AVAILABLE
        else:
            license_status = LicenseStatus.UNKNOWN
        status = "healthy" if all_available else "degraded"
        details: dict[str, Any] = {
            "capabilities": capabilities,
            "license_status": license_status.value,
            "diagnostic": None
            if all_available
            else "One or more executable probes did not complete successfully.",
        }
        self.store.save_toolchain_probe(identifier, status, details)
        return next(item for item in self.toolchains_public() if item["id"] == identifier)

    def overview(self) -> dict[str, Any]:
        """Return aggregate run, toolchain, disk, and queue health."""

        usage = shutil.disk_usage(self.run_root)
        counters = self.store.overview()
        with self._runtime_lock:
            active = sum(1 for thread in self._threads.values() if thread.is_alive())
        return {
            **counters,
            "active_jobs": active,
            "queued_jobs": counters["execution"].get("queued", 0),
            "disk": {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "minimum_free_bytes": int(
                    float(self.settings.get("minimum_free_disk_gb", 10)) * 1024**3
                ),
                "gate_open": usage.free
                >= int(float(self.settings.get("minimum_free_disk_gb", 10)) * 1024**3),
            },
            "toolchains": self.toolchains_public(),
        }

    def resolve_artifact(self, artifact_id: str) -> tuple[dict[str, Any], Path]:
        """Resolve an indexed artifact and prove it belongs to its project root."""

        artifact = self.store.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        run = self.store.get_run(artifact["run_id"])
        if run is None:
            raise KeyError(artifact_id)
        project = self.store.get_project(run["project_id"])
        if project is None:
            raise KeyError(artifact_id)
        root = Path(project["source_root"]).resolve(strict=True)
        path = Path(artifact["path"])
        try:
            resolved = resolve_within(root, path, must_exist=True, allow_root=False)
        except (PathSecurityError, FileNotFoundError) as exc:
            raise ValueError(f"artifact path is unavailable or outside its project: {artifact_id}") from exc
        if not resolved.is_file():
            raise ValueError(f"artifact is not a downloadable file: {artifact_id}")
        expected_hash = str(artifact.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError(f"artifact has no valid signed digest: {artifact_id}")
        if not secrets.compare_digest(sha256_file(resolved), expected_hash):
            raise ValueError(f"artifact content no longer matches its recorded digest: {artifact_id}")
        return artifact, resolved

    def verify_artifact_provenance(
        self,
        run_id: str,
        artifact_id: str,
    ) -> tuple[dict[str, Any], Path, dict[str, Any]]:
        """Verify that a signed Job manifest covers an exact downloadable artifact."""

        artifact, path = self.resolve_artifact(artifact_id)
        if artifact.get("run_id") != run_id:
            raise ValueError("artifact does not belong to the declared run")
        parent_id = str(
            (artifact.get("metadata") or {}).get("covered_by_artifact_id")
            or artifact_id
        )
        run = self.store.get_run(run_id)
        project = self.store.get_project(run["project_id"]) if run is not None else None
        if project is None:
            raise ValueError("artifact run has no project workspace")
        workspace = Path(project["source_root"]).resolve(strict=True)
        for manifest_artifact in self.store.list_artifacts(run_id):
            if manifest_artifact.get("kind") != "manifest":
                continue
            try:
                _, manifest_path = self.resolve_artifact(manifest_artifact["artifact_id"])
                manifest = verify_manifest(
                    manifest_path,
                    self._manifest_key,
                    workspace=workspace,
                    verify_files=True,
                )
            except (KeyError, ValueError, ManifestVerificationError, OSError):
                continue
            for signed_artifact in manifest.get("artifacts") or []:
                if str(signed_artifact.get("id") or "") != parent_id:
                    continue
                signed_path = resolve_within(
                    manifest_path.parent,
                    Path(str(signed_artifact.get("path") or "")),
                    must_exist=True,
                )
                covered = path == signed_path
                if signed_artifact.get("is_directory"):
                    try:
                        path.relative_to(signed_path)
                        covered = True
                    except ValueError:
                        covered = False
                if covered:
                    return artifact, path, {
                        "manifest_artifact_id": manifest_artifact["artifact_id"],
                        "manifest_sha256": manifest_artifact["sha256"],
                        "signed_parent_artifact_id": parent_id,
                    }
        raise ValueError("artifact is not covered by a valid current signed Job manifest")


def _collection(items: list[Any]) -> dict[str, Any]:
    """Wrap a list in the canonical collection response."""

    return {"items": items, "total": len(items)}


def _stream_file(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    """Yield an inclusive byte range without loading a large artifact into memory."""

    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            block = handle.read(min(chunk_size, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def register_platform_routes(app: Any, server: Any, check_password: Callable[..., Any]) -> PlatformRuntime:
    """Attach the canonical ``/api/v1`` and authenticated React SPA routes."""

    runtime = PlatformRuntime(server)
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_password)])

    async def check_csrf(request: Request) -> None:
        """Reject cross-origin browser mutations while allowing non-browser clients."""

        fetch_site = request.headers.get("sec-fetch-site", "").casefold()
        if fetch_site in {"cross-site", "same-site"}:
            raise HTTPException(status_code=403, detail="Cross-origin state changes are not allowed.")
        origin = request.headers.get("origin")
        if not origin:
            return
        parsed = urlsplit(origin)
        request_host = request.headers.get("host", "")
        if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != request_host.casefold():
            raise HTTPException(status_code=403, detail="Cross-origin state changes are not allowed.")

    @router.get("/overview", summary="Platform health and activity")
    def overview() -> dict[str, Any]:
        """Return tool, run, queue, and disk-gate health."""

        return runtime.overview()

    @router.get("/workflows", summary="Complete workflow catalog")
    def workflows(formal_engine: Literal["formalmc", "sby"] = "formalmc") -> dict[str, Any]:
        """Return full DAGs, including disabled conditional stages and reasons."""

        return _collection(runtime.workflow_catalog(formal_engine))

    @router.get("/toolchains", summary="Administrator toolchain profiles")
    def toolchains() -> dict[str, Any]:
        """Return redacted toolchain and latest probe status."""

        runtime.reload_toolchains()
        return _collection(runtime.toolchains_public())

    @router.post(
        "/toolchains/{profile_id}/probe",
        summary="Probe a toolchain",
        dependencies=[Depends(check_csrf)],
    )
    def probe_toolchain(profile_id: str) -> dict[str, Any]:
        """Probe configured binaries without exposing secrets."""

        try:
            return runtime.probe_toolchain(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Toolchain profile not found.") from exc

    @router.get("/projects", summary="List projects")
    def projects() -> dict[str, Any]:
        """Return imported platform projects."""

        return _collection([runtime.project_public(item) for item in runtime.store.list_projects()])

    @router.post("/projects", summary="Import project", dependencies=[Depends(check_csrf)])
    def create_project(body: ProjectCreateRequest) -> dict[str, Any]:
        """Import a project from a configured server root."""

        try:
            return runtime.create_project(body)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/projects/{project_id}", summary="Get project")
    def get_project(project_id: str) -> dict[str, Any]:
        """Return one imported project."""

        project = runtime.store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        return runtime.project_public(project)

    @router.post(
        "/projects/{project_id}/files",
        summary="Upload project files",
        dependencies=[Depends(check_csrf)],
    )
    async def upload_project_files(
        project_id: str,
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        """Stream uploads into a project-local directory without overwriting files."""

        project = runtime.store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        root = Path(project["source_root"]).resolve(strict=True)
        metadata_dir = resolve_within(root, ".ucagent", must_exist=False)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        upload_dir = resolve_within(root, metadata_dir / "uploads", must_exist=False)
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_dir = resolve_within(root, upload_dir, must_exist=True)
        created = []
        for upload in files:
            filename = Path(upload.filename or "").name
            if not filename or filename != (upload.filename or "") or filename in {".", ".."}:
                raise HTTPException(status_code=400, detail="Upload filenames must not contain paths.")
            target = resolve_within(upload_dir, filename, must_exist=False, allow_root=False)
            if target.exists():
                raise HTTPException(status_code=409, detail=f"Uploaded file already exists: {filename}")
            temporary = target.with_suffix(target.suffix + ".upload")
            size = 0
            try:
                with temporary.open("xb") as handle:
                    while True:
                        block = await upload.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        handle.write(block)
                os.replace(temporary, target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            finally:
                await upload.close()
            created.append({"name": filename, "path": str(target.relative_to(root)), "size": size})
        return _collection(created)

    @router.post(
        "/projects/{project_id}/uvm/scaffold",
        summary="Generate UVM 1.2 scaffold",
        dependencies=[Depends(check_csrf)],
    )
    def create_uvm_scaffold(project_id: str, body: UvmScaffoldRequest) -> dict[str, Any]:
        """Generate and structurally validate a project-local UVM environment."""

        project = runtime.store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        try:
            result = generate_uvm_scaffold(
                project["source_root"],
                body.output_dir,
                body.spec,
                overwrite=False,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime.store.add_audit_event(
            "uvm.scaffold.generated",
            "project",
            project_id,
            {"output_dir": body.output_dir, "file_count": len(result.files)},
        )
        return result.model_dump(mode="json")

    @router.get(
        "/projects/{project_id}/uvm/scaffold/validation",
        summary="Validate UVM scaffold",
    )
    def get_uvm_scaffold_validation(
        project_id: str,
        output_dir: str = Query(min_length=1, max_length=1024),
    ) -> dict[str, Any]:
        """Revalidate a generated UVM tree without invoking a simulator."""

        project = runtime.store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        try:
            return validate_uvm_scaffold(
                project["source_root"], output_dir
            ).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/runs", summary="List runs")
    def runs(project_id: str | None = Query(default=None)) -> dict[str, Any]:
        """Return recent runs, optionally limited to one project."""

        return _collection([runtime.run_public(item) for item in runtime.store.list_runs(project_id)])

    @router.post("/runs", summary="Create run", dependencies=[Depends(check_csrf)])
    def create_run(body: RunCreateRequest) -> dict[str, Any]:
        """Start a structured simulation or formal workflow."""

        try:
            return runtime.create_run(body)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project not found.") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/runs/preview", summary="Check run readiness", response_model=RunPreview, dependencies=[Depends(check_csrf)])
    def preview_run_request(body: RunCreateRequest) -> RunPreview:
        """Check inputs, selected tools, disk, and the exact simulation plan without dispatch."""

        try:
            return preview_run(runtime, body)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project not found.") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/runs/{run_id}", summary="Get run")
    def get_run(run_id: str) -> dict[str, Any]:
        """Return persisted run state after any service restart."""

        run = runtime.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return runtime.run_public(run)

    @router.post(
        "/runs/{run_id}/cancel",
        summary="Cancel run",
        dependencies=[Depends(check_csrf)],
    )
    def cancel_run(run_id: str) -> dict[str, Any]:
        """Request cancellation of the run's current process tree."""

        try:
            return runtime.cancel_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found.") from exc

    @router.get("/runs/{run_id}/events", summary="Resume run event stream")
    async def run_events(run_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
        """Stream ordered events with a resumable sequence cursor."""

        if runtime.store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found.")

        async def generate():
            """Yield event-stream records and periodic keepalive comments."""

            cursor = after
            while True:
                events = await asyncio.to_thread(runtime.store.wait_for_events, run_id, cursor, 15.0)
                if not events:
                    yield ": keepalive\n\n"
                    continue
                for event in events:
                    cursor = max(cursor, int(event["sequence"]))
                    payload = {
                        "sequence": event["sequence"],
                        "type": event["event_type"],
                        "timestamp": _iso_timestamp(event["created_at"]),
                        "message": (event["payload"] or {}).get("message"),
                        "data": event["payload"],
                    }
                    yield f"id: {cursor}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/runs/{run_id}/stages", summary="List run stages")
    def run_stages(run_id: str) -> dict[str, Any]:
        """Return enabled and disabled stages captured for the run."""

        if runtime.store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return _collection(runtime.run_stages_public(run_id))

    @router.get("/runs/{run_id}/jobs", summary="List run jobs")
    def run_jobs(run_id: str) -> dict[str, Any]:
        """Return persisted EDA jobs and attempts."""

        if runtime.store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return _collection(runtime.jobs_public(run_id))

    def result_collection(run_id: str, category: str) -> dict[str, Any]:
        """Return one normalized result collection or a consistent 404."""

        if runtime.store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        rows = runtime.store.list_result_rows(run_id, category)
        normalized = []
        for row in rows:
            item = dict(row)
            if category == "tests":
                item["id"] = str(item.pop("record_id", item.get("test_name", "")))
                item["name"] = item.pop("test_name", item.get("name", "unknown"))
                item["uvm_errors"] = item.pop("error_count", item.get("uvm_errors", 0))
                item["uvm_fatals"] = item.pop("fatal_count", item.get("uvm_fatals", 0))
            elif category == "coverage":
                item["id"] = str(item.pop("record_id", ""))
                item["name"] = item.get("metric", item.get("name", "coverage"))
                item["kind"] = item.get("metric", item.get("kind"))
                item["percentage"] = item.get("percent", item.get("percentage", 0))
            elif category == "properties":
                item["id"] = str(item.pop("record_id", item.get("name", "")))
                item["name"] = item.pop("property_name", item.get("name", "property"))
                item["depth"] = item.get("proof_depth", item.get("depth"))
            elif category == "issues":
                item["id"] = item.pop("issue_id", item.pop("record_id", ""))
            normalized.append(item)
        return _collection(normalized)

    @router.get("/runs/{run_id}/tests", summary="List test results")
    def run_tests(run_id: str) -> dict[str, Any]:
        """Return normalized SV, UnityTest, and UVM results."""

        return result_collection(run_id, "tests")

    @router.get("/runs/{run_id}/coverage", summary="List coverage metrics")
    def run_coverage(run_id: str) -> dict[str, Any]:
        """Return normalized code and assertion coverage."""

        return result_collection(run_id, "coverage")

    @router.get("/runs/{run_id}/properties", summary="List formal properties")
    def run_properties(run_id: str) -> dict[str, Any]:
        """Return all canonical formal property statuses, including inconclusive."""

        return result_collection(run_id, "properties")

    @router.get("/runs/{run_id}/issues", summary="List issues")
    def run_issues(run_id: str) -> dict[str, Any]:
        """Return normalized bugs and infrastructure diagnostics."""

        return result_collection(run_id, "issues")

    @router.get("/runs/{run_id}/artifacts", summary="List artifacts")
    def run_artifacts(run_id: str) -> dict[str, Any]:
        """Return artifact metadata without reading large file bodies."""

        if runtime.store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        items = []
        for artifact in runtime.store.list_artifacts(run_id):
            items.append(
                {
                    "id": artifact["artifact_id"],
                    "name": artifact["name"],
                    "kind": artifact["kind"],
                    "media_type": artifact.get("media_type"),
                    "size": artifact["size_bytes"],
                    "sha256": artifact["sha256"],
                    "created_at": _iso_timestamp(artifact.get("created_at")),
                    "path": artifact.get("path"),
                    **(artifact.get("metadata") or {}),
                }
            )
        return _collection(items)

    @router.get(
        "/runs/{run_id}/counterexample-replays",
        summary="List counterexample replay attempts",
    )
    def counterexample_replays(run_id: str) -> dict[str, Any]:
        """Return current evidence-backed replay status for one formal run."""

        try:
            return runtime.reconcile_counterexample_replays(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found.") from exc

    @router.post(
        "/runs/{run_id}/counterexample-replays",
        summary="Start counterexample replay",
        dependencies=[Depends(check_csrf)],
    )
    def start_counterexample_replay(
        run_id: str,
        body: CounterexampleReplayStartRequest,
    ) -> dict[str, Any]:
        """Launch a real UVM or UnityTest run from a signed counterexample."""

        try:
            return runtime.start_counterexample_replay(run_id, body)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run or project not found.") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/artifacts/{artifact_id}/download", summary="Stream artifact")
    def download_artifact(artifact_id: str, request: Request):
        """Stream one verified artifact with single-range HTTP support."""

        try:
            artifact, path = runtime.resolve_artifact(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        size = path.stat().st_size
        range_header = request.headers.get("range")
        media_type = artifact.get("media_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        fallback_name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name) or "artifact"
        common_headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": (
                f'attachment; filename="{fallback_name}"; '
                f"filename*=UTF-8''{quote(path.name, safe='')}"
            ),
        }
        if not range_header:
            return StreamingResponse(
                _stream_file(path, 0, max(0, size - 1)),
                media_type=media_type,
                headers={**common_headers, "Content-Length": str(size)},
            )
        match = _RANGE.fullmatch(range_header.strip())
        if not match or size == 0:
            raise HTTPException(
                status_code=416,
                detail="Unsupported byte range.",
                headers={"Content-Range": f"bytes */{size}"},
            )
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        elif last:
            suffix = int(last)
            if suffix <= 0:
                raise HTTPException(
                    status_code=416,
                    detail="Unsupported byte range.",
                    headers={"Content-Range": f"bytes */{size}"},
                )
            start = max(0, size - suffix)
            end = size - 1
        else:
            raise HTTPException(status_code=416, detail="Unsupported byte range.")
        if start >= size or start > end:
            raise HTTPException(
                status_code=416,
                detail="Requested range is outside the artifact.",
                headers={"Content-Range": f"bytes */{size}"},
            )
        return StreamingResponse(
            _stream_file(path, start, end),
            status_code=206,
            media_type=media_type,
            headers={
                **common_headers,
                "Content-Length": str(end - start + 1),
                "Content-Range": f"bytes {start}-{end}/{size}",
            },
        )

    @router.post(
        "/stages/{stage_id}/approve",
        summary="Approve stage",
        dependencies=[Depends(check_csrf)],
    )
    def approve_stage(stage_id: str, body: StageActionRequest = StageActionRequest()) -> dict[str, Any]:
        """Persist an explicit human approval."""

        return _stage_action(runtime, stage_id, "approve", body.note)

    @router.post(
        "/stages/{stage_id}/reject",
        summary="Reject stage",
        dependencies=[Depends(check_csrf)],
    )
    def reject_stage(stage_id: str, body: StageActionRequest = StageActionRequest()) -> dict[str, Any]:
        """Persist an explicit human rejection."""

        return _stage_action(runtime, stage_id, "reject", body.note)

    @router.post(
        "/stages/{stage_id}/retry",
        summary="Retry stage",
        dependencies=[Depends(check_csrf)],
    )
    def retry_stage(stage_id: str, body: StageActionRequest = StageActionRequest()) -> dict[str, Any]:
        """Mark a failed stage pending for an explicit run retry."""

        return _stage_action(runtime, stage_id, "retry", body.note)

    @router.get("/mcp", summary="MCP service information")
    def mcp_info() -> dict[str, Any]:
        """Report the actual MCP host and safely projected active-agent schemas."""

        return _public_mcp_info(server)

    @router.get("/settings", summary="Get platform settings")
    def settings() -> dict[str, Any]:
        """Return non-secret platform settings."""

        return runtime.public_settings()

    @router.put("/settings", summary="Update platform settings", dependencies=[Depends(check_csrf)])
    def update_settings(body: PlatformSettingsUpdate) -> dict[str, Any]:
        """Persist bounded, non-secret platform settings."""

        return runtime.save_settings(body)

    from ucagent.server.api_campaign import register_campaign_routes
    register_campaign_routes(router, runtime, check_csrf)
    from ucagent.server.formal_sessions import register_formal_session_routes
    register_formal_session_routes(router, runtime, check_csrf)
    app.include_router(router)

    static_root = Path(__file__).resolve().parent / "static" / "platform"

    @app.get("/platform", include_in_schema=False, dependencies=[Depends(check_password)])
    def platform_redirect() -> RedirectResponse:
        """Normalize the visual-platform URL to its trailing-slash form."""

        return RedirectResponse(url="/platform/", status_code=307)

    @app.get("/platform/{spa_path:path}", include_in_schema=False, dependencies=[Depends(check_password)])
    def platform_spa(spa_path: str):
        """Serve immutable Vite assets or the SPA entry point for client routes."""

        if not static_root.is_dir():
            raise HTTPException(
                status_code=503,
                detail="The visual platform has not been built. Run the web production build first.",
            )
        candidate = (static_root / spa_path).resolve()
        try:
            candidate.relative_to(static_root.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Invalid platform asset path.") from exc
        if spa_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static_root / "index.html", media_type="text/html")

    return runtime


def _stage_action(runtime: PlatformRuntime, compound_id: str, action: str, note: str) -> dict[str, Any]:
    """Validate a globally addressable stage and persist its state transition."""

    run_id, separator, stage_id = compound_id.partition(":")
    if not separator or not run_id or not stage_id:
        raise HTTPException(status_code=400, detail="Run stage id must have the form <run-id>:<stage-id>.")
    if runtime.store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if runtime.store.get_run(run_id).get("adapter") == "campaign":
        from ucagent.server.campaign_service import CampaignConflict
        try:
            return runtime.campaigns.stage_action(run_id, stage_id, action, note)
        except CampaignConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    stages = {item.get("stage_id") or item.get("id"): item for item in runtime.store.list_run_stages(run_id)}
    stage = stages.get(stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage not found.")
    if not stage.get("enabled", True):
        raise HTTPException(status_code=409, detail=stage.get("disabled_reason") or "Stage is disabled.")
    run = runtime.store.get_run(run_id)
    assert run is not None
    if action == "retry":
        if run["execution_status"] not in _TERMINAL_EXECUTION_STATES:
            raise HTTPException(status_code=409, detail="An active run cannot be retried.")
        try:
            request = RunCreateRequest.model_validate(run.get("request") or {})
            replacement = runtime.create_run(request)
        except (KeyError, OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=f"Run retry could not be started: {exc}") from exc
        runtime.store.add_stage_action(run_id, stage_id, action, note)
        runtime.store.add_audit_event(
            "run.retry.created",
            "run",
            replacement["id"],
            {"source_run_id": run_id, "source_stage_id": stage_id},
        )
        return {
            "run_id": run_id,
            "stage_id": compound_id,
            "execution_status": stage.get("execution_status"),
            "verification_status": stage.get("verification_status"),
            "approval_status": stage.get("approval_status"),
            "action": action,
            "retry_run": replacement,
        }
    if stage.get("requires_human_approval") is not True:
        raise HTTPException(status_code=409, detail="Only a declared human gate can be approved or rejected.")
    if stage.get("approval_status") != "pending":
        raise HTTPException(status_code=409, detail="The human gate already has a decision.")
    if run["execution_status"] not in _TERMINAL_EXECUTION_STATES:
        raise HTTPException(
            status_code=409,
            detail="The human gate can be decided only after the current execution reaches a terminal state.",
        )
    approval_status = {"approve": "approved", "reject": "rejected"}[action]
    execution_status = "completed" if action == "approve" else "cancelled"
    verification_status = (
        "passed"
        if action == "approve" and run.get("verification_status") == "passed"
        else "failed"
        if action == "reject"
        else str(run.get("verification_status") or "unknown")
    )
    runtime.store.add_stage_action(run_id, stage_id, action, note)
    runtime.store.update_stage_approval(run_id, stage_id, approval_status)
    runtime.store.update_stage_execution(
        run_id, stage_id, execution_status, verification_status
    )
    if action == "reject":
        runtime.store.update_run_status(
            run_id,
            execution_status=str(run["execution_status"]),
            verification_status="failed",
            diagnostic={
                "error_code": "human_gate_rejected",
                "error": "A required human verification gate was rejected.",
                "stage_id": stage_id,
                "next_action": "Review the gate note, correct the evidence, and retry the run.",
            },
        )
    return {
        "run_id": run_id,
        "stage_id": compound_id,
        "execution_status": execution_status,
        "verification_status": verification_status,
        "approval_status": approval_status,
        "action": action,
    }
