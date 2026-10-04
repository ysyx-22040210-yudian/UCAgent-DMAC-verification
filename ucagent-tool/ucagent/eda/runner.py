"""Secure, cancellable process runner and signed evidence publisher for EDA jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Protocol, TextIO

import psutil

from .input_closure import (
    InputClosureSecurityError,
    merge_input_closures,
    resolve_tcl_source_closure,
    resolve_vcs_filelist_closure,
)
from .manifest import (
    ManifestVerificationError,
    canonical_json,
    collect_artifacts,
    compute_input_fingerprint,
    hash_workspace_inputs,
    sha256_path,
    verify_manifest,
    write_manifest,
)
from .models import (
    CoverageMetric,
    ExecutionStatus,
    FormalProperty,
    RunRequest,
    RunResult,
    TestResult,
    ToolchainProfile,
    VerificationStatus,
)
from .parsers import ParsedOutput, parse_formal_log, parse_pytest_log, parse_urg_output, parse_uvm_log
from .security import is_secret_name, redact_argv, redact_data, redact_text, resolve_within


class CancellationSignal(Protocol):
    """Define the minimal cancellation interface accepted by :meth:`JobRunner.run`."""

    def is_set(self) -> bool:
        """Return whether cancellation has been requested."""


EventCallback = Callable[[dict[str, Any]], None]


class DiskSpaceError(RuntimeError):
    """Report that the configured free-space gate rejected a new EDA job."""


class UnsupportedEnvironmentSetup(RuntimeError):
    """Report unsafe shell setup scripts that were not materialized by an administrator."""


class SessionInputError(RuntimeError):
    """Report a failed or unsafe copy into a job's private staging directory."""

    def __init__(self, error_code: str, message: str) -> None:
        """Retain a stable diagnostic code alongside the actionable message."""

        super().__init__(message)
        self.error_code = error_code


class JobRunner:
    """Run one trusted adapter command with isolation, streaming, and signed evidence."""

    def __init__(self, hmac_key: bytes, *, event_flush: bool = True, max_parse_bytes: int = 16 * 1024**2):
        """Create a runner with a stable host-owned manifest signing key."""

        if not isinstance(hmac_key, bytes) or not hmac_key:
            raise ValueError("hmac_key must be non-empty bytes")
        if max_parse_bytes < 1024:
            raise ValueError("max_parse_bytes must be at least 1024")
        self._hmac_key = hmac_key
        self._event_flush = event_flush
        self._max_parse_bytes = max_parse_bytes
        self._semaphores: dict[tuple[str, str, int], threading.BoundedSemaphore] = {}
        self._semaphore_lock = threading.Lock()

    def run(
        self,
        request: RunRequest,
        profile: ToolchainProfile,
        on_event: EventCallback | None = None,
        cancel_event: CancellationSignal | None = None,
    ) -> RunResult:
        """Execute ``request`` synchronously and atomically publish its terminal evidence."""

        queued_at = datetime.now(timezone.utc)
        semaphore = self._profile_semaphore(profile, request.resource_class)
        initial_event = {
            "sequence": 0,
            "timestamp": queued_at.isoformat(),
            "run_id": request.run_id,
            "type": "queued",
            "payload": {"toolchain_id": profile.id},
        }
        self._notify(on_event, initial_event)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                completed = datetime.now(timezone.utc)
                return RunResult(
                    run_id=request.run_id,
                    execution_status=ExecutionStatus.CANCELLED,
                    verification_status=VerificationStatus.UNKNOWN,
                    started_at=queued_at,
                    completed_at=completed,
                    diagnostics=[
                        {
                            "error_code": "cancelled_while_queued",
                            "error": "The run was cancelled before a tool slot became available.",
                            "next_action": "Start a new run when execution is still required.",
                        }
                    ],
                )
            if semaphore.acquire(timeout=0.1):
                break
        try:
            return self._run_acquired(request, profile, queued_at, on_event, cancel_event)
        finally:
            semaphore.release()

    def _profile_semaphore(self, profile: ToolchainProfile, resource_class: str = "eda") -> threading.BoundedSemaphore:
        """Return the process-wide license/concurrency gate for one profile configuration."""

        capacity = {"eda": profile.max_concurrency, "claude": profile.agent_max_concurrency,
                    "analysis": profile.analysis_max_concurrency}[resource_class]
        key = (profile.id, resource_class, capacity)
        with self._semaphore_lock:
            semaphore = self._semaphores.get(key)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(capacity)
                self._semaphores[key] = semaphore
            return semaphore

    def _run_acquired(
        self,
        request: RunRequest,
        profile: ToolchainProfile,
        queued_at: datetime,
        on_event: EventCallback | None,
        cancel_event: CancellationSignal | None,
    ) -> RunResult:
        """Perform a run after its toolchain concurrency slot has been acquired."""

        workspace = request.workspace.resolve(strict=True)
        final_dir = resolve_within(workspace, request.output_dir, must_exist=False, allow_root=False)
        final_parent = resolve_within(workspace, final_dir.parent, must_exist=False)
        final_parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            raise FileExistsError(f"run output already exists and will not be overwritten: {final_dir}")
        disk_targets: dict[str, Path] = {"workspace": workspace}
        temp_value = (
            request.command.env.get("TMPDIR")
            or profile.environment.get("TMPDIR")
            or os.environ.get("TMPDIR")
            or tempfile.gettempdir()
        )
        temp_path = Path(temp_value).expanduser()
        if not temp_path.is_absolute() or not temp_path.is_dir():
            completed = datetime.now(timezone.utc)
            diagnostic = {
                "error_code": "temporary_directory_unavailable",
                "error": "The configured EDA temporary directory is not an existing absolute directory.",
                "observed": {"temporary_directory": str(temp_path)},
                "expected": "An administrator-owned writable temporary directory on the artifact volume",
                "next_action": "Create the configured TMPDIR on an approved volume before retrying.",
            }
            self._notify(
                on_event,
                {
                    "sequence": 1,
                    "timestamp": completed.isoformat(),
                    "run_id": request.run_id,
                    "type": "error",
                    "payload": diagnostic,
                },
            )
            return RunResult(
                run_id=request.run_id,
                execution_status=ExecutionStatus.ERROR,
                verification_status=VerificationStatus.UNKNOWN,
                started_at=queued_at,
                completed_at=completed,
                diagnostics=[diagnostic],
            )
        disk_targets["temporary_directory"] = temp_path.resolve(strict=True)
        disk_observations = {
            label: {
                "path": str(path),
                "free_bytes": shutil.disk_usage(path).free,
            }
            for label, path in disk_targets.items()
        }
        below_gate = {
            label: observation
            for label, observation in disk_observations.items()
            if observation["free_bytes"] < profile.minimum_free_bytes
        }
        if os.name != "nt" and shutil.disk_usage("/").free < profile.minimum_root_free_bytes:
            below_gate["root"] = {"path": "/", "free_bytes": shutil.disk_usage("/").free,
                                  "minimum_free_bytes": profile.minimum_root_free_bytes}
        if below_gate:
            completed = datetime.now(timezone.utc)
            diagnostic = {
                "error_code": "insufficient_disk_space",
                "error": "A workspace or temporary-volume free-space gate rejected the run.",
                "observed": {"volumes": below_gate},
                "expected": {"minimum_free_bytes": profile.minimum_free_bytes},
                "next_action": "Free storage or select administrator-approved workspace and temporary volumes.",
            }
            self._notify(
                on_event,
                {
                    "sequence": 1,
                    "timestamp": completed.isoformat(),
                    "run_id": request.run_id,
                    "type": "error",
                    "payload": diagnostic,
                },
            )
            return RunResult(
                run_id=request.run_id,
                execution_status=ExecutionStatus.ERROR,
                verification_status=VerificationStatus.UNKNOWN,
                started_at=queued_at,
                completed_at=completed,
                diagnostics=[diagnostic],
            )
        if profile.setup_scripts:
            completed = datetime.now(timezone.utc)
            diagnostic = {
                "error_code": "setup_script_not_materialized",
                "error": "Toolchain setup scripts cannot be sourced by the argv-only job runner.",
                "observed": {"script_count": len(profile.setup_scripts)},
                "expected": "An administrator-materialized ToolchainProfile.environment mapping",
                "next_action": "Probe the setup scripts outside the service and store only the resulting explicit environment mapping.",
            }
            self._notify(
                on_event,
                {
                    "sequence": 1,
                    "timestamp": completed.isoformat(),
                    "run_id": request.run_id,
                    "type": "error",
                    "payload": diagnostic,
                },
            )
            return RunResult(
                run_id=request.run_id,
                execution_status=ExecutionStatus.ERROR,
                verification_status=VerificationStatus.UNKNOWN,
                started_at=queued_at,
                completed_at=completed,
                diagnostics=[diagnostic],
            )

        staging_dir = Path(tempfile.mkdtemp(prefix=f".{final_dir.name}.", suffix=".tmp", dir=final_parent))
        events_path = staging_dir / "events.ndjson"
        stdout_path = staging_dir / "stdout.log"
        stderr_path = staging_dir / "stderr.log"
        process: subprocess.Popen[str] | None = None
        started_at = datetime.now(timezone.utc)
        execution = ExecutionStatus.ERROR
        verification = VerificationStatus.UNKNOWN
        return_code: int | None = None
        parsed = ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
        )
        diagnostics: list[dict[str, Any]] = []
        secret_values = self._secret_values(profile, request)
        logical_argv = list(request.command.argv)
        if request.command.tool and request.command.tool in profile.tools:
            logical_argv[0] = profile.tools[request.command.tool]
        display_argv = redact_argv(
            [
                value.replace("{WORKSPACE}", str(workspace)).replace("{SESSION_DIR}", str(final_dir))
                for value in logical_argv
            ],
            secret_values,
        )
        fingerprint_argv = redact_argv(logical_argv, secret_values)
        input_hashes: dict[str, str] = {}
        input_hashes_ready = False
        input_fingerprint = ""
        sequence = 0
        effective_input_paths = list(
            dict.fromkeys(
                [request_path for request_path in request.input_paths]
                + [item.source for item in request.session_inputs]
            )
        )
        closure_metadata = request.metadata.get("input_closure")
        # Broad include directories such as ``.`` must not fingerprint the
        # runner's own cache or run namespace. Explicit files/directories below
        # these namespaces are still hashed by ``hash_workspace_inputs``.
        output_namespace = Path(request.output_dir.parts[0])
        stable_input_excludes = list(dict.fromkeys((Path(".ucagent"), output_namespace)))
        runtime_input_excludes = [
            *stable_input_excludes,
            request.output_dir,
            staging_dir.relative_to(workspace),
        ]
        signed_input_excludes = list(dict.fromkeys((*stable_input_excludes, request.output_dir)))

        try:
            if isinstance(closure_metadata, dict):
                resolver_specs = closure_metadata.get("resolvers")
                if resolver_specs is not None:
                    if not isinstance(resolver_specs, list) or len(resolver_specs) > 8:
                        raise InputClosureSecurityError(
                            "input_closure_spec_invalid",
                            "input closure resolvers must be a list with at most eight entries",
                        )
                    resolved_closures = []
                    for resolver_spec in resolver_specs:
                        if not isinstance(resolver_spec, dict):
                            raise InputClosureSecurityError(
                                "input_closure_spec_invalid",
                                "each input closure resolver must be an object",
                            )
                        kind = resolver_spec.get("kind")
                        if kind == "vcs_filelist":
                            path_fields: dict[str, list[Path]] = {}
                            for field in ("filelists", "sources", "include_dirs"):
                                raw_paths = resolver_spec.get(field, [])
                                if (
                                    not isinstance(raw_paths, list)
                                    or len(raw_paths) > 100000
                                    or not all(isinstance(item, str) for item in raw_paths)
                                ):
                                    raise InputClosureSecurityError(
                                        "input_closure_spec_invalid",
                                        f"input closure resolver field {field} must be a bounded string list",
                                    )
                                path_fields[field] = [Path(item) for item in raw_paths]
                            root_mode = resolver_spec.get("root_mode")
                            if root_mode not in {"f", "F"}:
                                raise InputClosureSecurityError(
                                    "input_closure_spec_invalid",
                                    "VCS input closure root_mode must be 'f' or 'F'",
                                )
                            resolved_closures.append(
                                resolve_vcs_filelist_closure(
                                    workspace,
                                    filelists=path_fields["filelists"],
                                    sources=path_fields["sources"],
                                    include_dirs=path_fields["include_dirs"],
                                    root_mode=root_mode,
                                )
                            )
                        elif kind == "tcl_source":
                            raw_scripts = resolver_spec.get("scripts", [])
                            if (
                                not isinstance(raw_scripts, list)
                                or len(raw_scripts) > 100000
                                or not all(isinstance(item, str) for item in raw_scripts)
                            ):
                                raise InputClosureSecurityError(
                                    "input_closure_spec_invalid",
                                    "Tcl input closure scripts must be a bounded string list",
                                )
                            resolved_closures.append(
                                resolve_tcl_source_closure(
                                    workspace,
                                    [Path(item) for item in raw_scripts],
                                )
                            )
                        else:
                            raise InputClosureSecurityError(
                                "input_closure_spec_invalid",
                                "input closure resolver kind is not supported",
                            )
                    current_closure = merge_input_closures(*resolved_closures)
                    declared_paths = closure_metadata.get("input_paths")
                    if (
                        not isinstance(declared_paths, list)
                        or not all(isinstance(item, str) for item in declared_paths)
                    ):
                        raise InputClosureSecurityError(
                            "input_closure_spec_invalid",
                            "input closure input_paths must be a string list",
                        )
                    current_paths = [path.as_posix() for path in current_closure.input_paths]
                    if (
                        current_paths != declared_paths
                        or current_closure.complete is not closure_metadata.get("complete")
                        or not set(current_closure.input_paths).issubset(effective_input_paths)
                    ):
                        raise InputClosureSecurityError(
                            "input_closure_changed_before_run",
                            "input closure changed after the job was constructed; create a new run",
                        )
            for session_input in request.session_inputs:
                source_lexical = workspace / session_input.source
                try:
                    source = resolve_within(workspace, source_lexical, must_exist=True)
                except (FileNotFoundError, OSError, ValueError) as exc:
                    raise SessionInputError(
                        "session_input_missing",
                        f"session input source is missing or outside the workspace: {session_input.source.as_posix()}",
                    ) from exc
                if source_lexical.is_symlink():
                    raise SessionInputError(
                        "session_input_symlink",
                        f"session input source must not be a symbolic link: {session_input.source.as_posix()}",
                    )
            input_hashes = hash_workspace_inputs(
                workspace,
                effective_input_paths,
                exclude_paths=runtime_input_excludes,
            )
            input_hashes_ready = True
            for name, expected in request.prepared_input_hashes.items():
                if input_hashes.get(name) != expected:
                    raise SessionInputError("prepared_inputs_changed", f"Prepared control input changed before execution: {name}; regenerate the request from stable inputs.")
            functional_environment = {
                name: value
                for name, value in {**profile.environment, **request.command.env}.items()
                if not is_secret_name(name) and name not in set(profile.license_environment_names)
            }
            input_fingerprint = compute_input_fingerprint(
                input_hashes=input_hashes,
                command=fingerprint_argv,
                toolchain_id=profile.id,
                tool_version=profile.versions.get(request.command.tool or ""),
                metadata=self._json_safe(redact_data(request.metadata, secret_values)),
                command_context={
                    "artifact_paths": [path.as_posix() for path in request.artifact_paths],
                    "cwd": str(request.command.cwd),
                    "environment_sha256": hashlib.sha256(canonical_json(functional_environment)).hexdigest(),
                    "execution_user": profile.execution_user,
                    "parser": request.parser,
                    "property_set": request.property_set,
                    "result_paths": [path.as_posix() for path in request.result_paths],
                    "session_inputs": [
                        {
                            "source": item.source.as_posix(),
                            "destination": item.destination.as_posix(),
                        }
                        for item in request.session_inputs
                    ],
                    "seed": request.seed,
                    "success_markers": list(request.success_markers),
                    "suite": request.suite,
                    "test_name": request.test_name,
                    "timeout_seconds": request.command.timeout_seconds,
                    "stdin_path": request.stdin_path.as_posix() if request.stdin_path else None,
                    "memory_limit_bytes": request.memory_limit_bytes,
                    "output_limit_bytes": request.output_limit_bytes,
                    "verification_hint": request.verification_hint.value,
                },
            )
            cached = self._restore_cached_run(
                request=request,
                profile=profile,
                workspace=workspace,
                staging_dir=staging_dir,
                final_dir=final_dir,
                started_at=started_at,
                input_hashes=input_hashes,
                effective_input_paths=effective_input_paths,
                input_hash_excludes=signed_input_excludes,
                input_fingerprint=input_fingerprint,
                display_argv=display_argv,
                secret_values=secret_values,
                on_event=on_event,
            )
            if cached is not None:
                return cached
            for session_input in request.session_inputs:
                source = resolve_within(workspace, session_input.source, must_exist=True)
                destination = resolve_within(
                    staging_dir,
                    session_input.destination,
                    must_exist=False,
                    allow_root=False,
                )
                if destination.exists():
                    raise SessionInputError(
                        "session_input_destination_conflict",
                        f"session input destination already exists: {session_input.destination.as_posix()}",
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if source.is_dir():
                        shutil.copytree(source, destination)
                    elif source.is_file():
                        shutil.copy2(source, destination)
                    else:
                        raise SessionInputError(
                            "session_input_unsupported",
                            f"session input source is not a regular file or directory: {session_input.source.as_posix()}",
                        )
                except SessionInputError:
                    raise
                except (OSError, shutil.Error) as exc:
                    raise SessionInputError(
                        "session_input_copy_failed",
                        f"failed to copy session input {session_input.source.as_posix()} to "
                        f"{session_input.destination.as_posix()}: {exc}",
                    ) from exc
                source_key = source.relative_to(workspace).as_posix()
                if sha256_path(destination) != input_hashes[source_key]:
                    raise SessionInputError(
                        "session_input_copy_mismatch",
                        f"copied session input does not match its signed source: {session_input.source.as_posix()}",
                    )
            argv, cwd, command_environment = self._prepare_command(
                request, profile, workspace, staging_dir
            )
            # A commercial license or API credential must not leak to a different
            # engine through ambient inheritance. Explicit profile values follow.
            environment = {name: value for name, value in os.environ.items() if not is_secret_name(name)}
            environment.update(profile.environment)
            environment.update(command_environment)
            parse_parts: list[str] = []
            parse_size = 0

            with (
                events_path.open("w", encoding="utf-8", newline="\n") as event_stream,
                stdout_path.open("w", encoding="utf-8", newline="") as stdout_stream,
                stderr_path.open("w", encoding="utf-8", newline="") as stderr_stream,
            ):
                def emit(event_type: str, payload: dict[str, Any]) -> None:
                    """Persist and forward one redacted, monotonically sequenced event."""

                    nonlocal sequence
                    sequence += 1
                    event = {
                        "sequence": sequence,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "run_id": request.run_id,
                        "type": event_type,
                        "payload": redact_data(payload, secret_values),
                    }
                    event_stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                    if self._event_flush:
                        event_stream.flush()
                    self._notify(on_event, event)

                emit("queued", {"toolchain_id": profile.id})
                closure_diagnostics = (
                    closure_metadata.get("diagnostics")
                    if isinstance(closure_metadata, dict)
                    else None
                )
                if (
                    request.metadata.get("cacheable") is False
                    and isinstance(closure_metadata, dict)
                    and closure_metadata.get("complete") is False
                ):
                    emit(
                        "cache_disabled",
                        {
                            "reason": "input_closure_unproven",
                            "diagnostics": (
                                closure_diagnostics
                                if isinstance(closure_diagnostics, list)
                                else []
                            ),
                        },
                    )
                emit("running", {"command": display_argv, "cwd": str(cwd)})
                popen_options: dict[str, Any] = {
                    "args": argv,
                    "cwd": cwd,
                    "env": environment,
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                    "bufsize": 1,
                    "shell": False,
                }
                if os.name == "nt":
                    popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    popen_options["start_new_session"] = True
                # A staged file avoids pipe deadlocks and binds prompts to the same
                # immutable input fingerprint as every other tool input.
                stdin_stream = None
                try:
                    if request.stdin_path is not None:
                        stdin_source = resolve_within(staging_dir, request.stdin_path, must_exist=True)
                        if not stdin_source.is_file() or stdin_source.stat().st_size > 1024**2:
                            raise ValueError("stdin input must be a regular file of at most 1 MiB")
                        stdin_stream = stdin_source.open("rb")
                        popen_options["stdin"] = stdin_stream
                    process = subprocess.Popen(**popen_options)
                finally:
                    if stdin_stream is not None:
                        stdin_stream.close()
                output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=1024)

                def read_pipe(name: str, pipe: TextIO) -> None:
                    """Move a child stream into the central event queue without blocking its peer."""

                    try:
                        for line in iter(lambda: pipe.readline(65536), ""):
                            output_queue.put((name, line))
                    finally:
                        pipe.close()
                        output_queue.put((name, None))

                assert process.stdout is not None and process.stderr is not None
                threads = [
                    threading.Thread(target=read_pipe, args=("stdout", process.stdout), daemon=True),
                    threading.Thread(target=read_pipe, args=("stderr", process.stderr), daemon=True),
                ]
                for thread in threads:
                    thread.start()
                closed_streams: set[str] = set()
                timed_out = False
                cancelled = False
                deadline = time.monotonic() + request.command.timeout_seconds
                termination_requested = False
                output_bytes = 0
                resource_failure = None
                next_memory_check = 0.0
                while len(closed_streams) < 2:
                    now = time.monotonic()
                    if not termination_requested and request.memory_limit_bytes and now >= next_memory_check:
                        next_memory_check = now + 0.25
                        try:
                            parent = psutil.Process(process.pid)
                            processes = [parent, *parent.children(recursive=True)]
                            rss = 0
                            for item in processes:
                                try:
                                    rss += item.memory_info().rss
                                except psutil.NoSuchProcess:
                                    pass
                            if rss > request.memory_limit_bytes:
                                resource_failure = "memory_limit_exceeded"
                                termination_requested = True
                                self._terminate_process_tree(process)
                        except psutil.NoSuchProcess:
                            pass
                    if not termination_requested and cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        termination_requested = True
                        emit("cancelling", {})
                        self._terminate_process_tree(process)
                    elif not termination_requested and now >= deadline:
                        timed_out = True
                        termination_requested = True
                        emit("timing_out", {"timeout_seconds": request.command.timeout_seconds})
                        self._terminate_process_tree(process)
                    try:
                        stream_name, line = output_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if line is None:
                        closed_streams.add(stream_name)
                        continue
                    safe_line = redact_text(line, secret_values)
                    output_bytes += len(safe_line.encode("utf-8"))
                    if output_bytes > request.output_limit_bytes:
                        if not termination_requested:
                            resource_failure = "output_limit_exceeded"
                            termination_requested = True
                            self._terminate_process_tree(process)
                        continue
                    target = stdout_stream if stream_name == "stdout" else stderr_stream
                    target.write(safe_line)
                    target.flush()
                    emit(stream_name, {"text": safe_line})
                    encoded_size = len(safe_line.encode("utf-8"))
                    # Claude's machine protocol is stdout-only; benign stderr
                    # diagnostics must not corrupt an otherwise valid NDJSON
                    # stream. Both streams still retain redacted log evidence.
                    if parse_size < self._max_parse_bytes and (request.parser != "claude" or stream_name == "stdout"):
                        remaining = self._max_parse_bytes - parse_size
                        encoded = safe_line.encode("utf-8")[:remaining]
                        parse_parts.append(encoded.decode("utf-8", errors="ignore"))
                        parse_size += len(encoded)
                for thread in threads:
                    thread.join(timeout=1)
                return_code = process.wait(timeout=5)
                combined_output = "".join(parse_parts)
                if parse_size < self._max_parse_bytes:
                    for result_path in request.result_paths:
                        report = resolve_within(staging_dir, result_path, must_exist=False)
                        if not report.is_file():
                            continue
                        remaining = self._max_parse_bytes - len(combined_output.encode("utf-8"))
                        if remaining <= 0:
                            break
                        combined_output += self._sanitize_result_report(report, secret_values, remaining)
                if resource_failure:
                    execution = ExecutionStatus.ERROR
                    verification = VerificationStatus.UNKNOWN
                    diagnostics.append({"error_code": resource_failure,
                                        "error": "The process exceeded its approved resource budget.",
                                        "next_action": "Review partial evidence and approve a revised budget before retrying."})
                elif timed_out:
                    execution = ExecutionStatus.TIMEOUT
                    verification = VerificationStatus.UNKNOWN
                    diagnostics.append(
                        {
                            "error_code": "timeout",
                            "error": f"Tool execution exceeded {request.command.timeout_seconds} seconds.",
                            "next_action": "Inspect the partial logs, adjust the bounded timeout if justified, and retry.",
                        }
                    )
                elif cancelled:
                    execution = ExecutionStatus.CANCELLED
                    verification = VerificationStatus.UNKNOWN
                    diagnostics.append(
                        {
                            "error_code": "cancelled",
                            "error": "Tool execution was cancelled and its process tree was terminated.",
                            "next_action": "Start a new run if verification is still required.",
                        }
                    )
                else:
                    if request.parser == "sby":
                        from .sby_results import parse_sby_results

                        parsed = parse_sby_results(staging_dir, mode=request.metadata["mode"], depth=request.metadata["depth"], return_code=return_code)
                    else:
                        parsed = self._parse_output(request, return_code, combined_output)
                    execution = parsed.execution_status
                    verification = parsed.verification_status
                    diagnostics.extend(parsed.diagnostics)
                emit(
                    "finished",
                    {
                        "execution_status": execution.value,
                        "verification_status": verification.value,
                        "return_code": return_code,
                    },
                )
        except (FileNotFoundError, PermissionError, OSError, ValueError, SessionInputError) as exc:
            completed_at = datetime.now(timezone.utc)
            execution = ExecutionStatus.ERROR
            verification = VerificationStatus.UNKNOWN
            safe_error = redact_text(str(exc), secret_values)
            diagnostics.append(
                {
                    "error_code": (
                        exc.error_code
                        if isinstance(exc, (InputClosureSecurityError, SessionInputError))
                        else "process_start_error"
                    ),
                    "error": safe_error,
                    "next_action": (
                        "Restore the signed source input and retry in a new private session."
                        if isinstance(exc, SessionInputError)
                        else (
                            "Create a new run after replacing dynamic or unsafe closure inputs."
                            if isinstance(exc, InputClosureSecurityError)
                            else "Probe the configured tool executable and workspace paths, then retry."
                        )
                    ),
                }
            )
            if process is not None and process.poll() is None:
                self._terminate_process_tree(process)
            if not events_path.exists():
                events_path.write_text(
                    json.dumps(
                        {
                            "sequence": 1,
                            "timestamp": completed_at.isoformat(),
                            "run_id": request.run_id,
                            "type": "error",
                            "payload": diagnostics[-1],
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            stdout_path.touch(exist_ok=True)
            stderr_path.touch(exist_ok=True)

        completed_at = datetime.now(timezone.utc)
        if parsed.tests:
            elapsed_seconds = max(0.0, (completed_at - started_at).total_seconds())
            parsed.tests = [
                item
                if item.duration_seconds is not None
                else item.model_copy(update={"duration_seconds": elapsed_seconds})
                for item in parsed.tests
            ]
        try:
            if input_hashes_ready:
                try:
                    current_hashes = hash_workspace_inputs(
                        workspace,
                        effective_input_paths,
                        exclude_paths=runtime_input_excludes,
                    )
                except (OSError, ValueError) as exc:
                    current_hashes = {}
                    input_change_observed: Any = {"error": redact_text(str(exc), secret_values)}
                else:
                    input_change_observed = current_hashes
                if current_hashes != input_hashes:
                    execution = ExecutionStatus.ERROR
                    verification = VerificationStatus.UNKNOWN
                    diagnostics.append(
                        {
                            "error_code": "inputs_changed_during_run",
                            "error": "One or more signed inputs changed while the tool was running.",
                            "expected": input_hashes,
                            "observed": input_change_observed,
                            "next_action": "Rerun against a stable project snapshot.",
                        }
                    )
            missing_artifacts = self._missing_artifacts(staging_dir, request.artifact_paths)
            if missing_artifacts:
                execution = ExecutionStatus.ERROR
                verification = VerificationStatus.UNKNOWN
                diagnostics.append(
                    {
                        "error_code": "missing_declared_artifact",
                        "error": "The tool completed without every declared artifact.",
                        "observed": {"missing": missing_artifacts},
                        "next_action": "Inspect the tool log and output options, then rerun without weakening the artifact contract.",
                    }
                )
            declared_artifacts = [Path("stdout.log"), Path("stderr.log"), Path("events.ndjson"), *request.artifact_paths]
            if request.parser == "sby":
                # Directory hashes retain the full proof database, while explicit
                # property evidence must also be addressable/downloadable in UI.
                declared_artifacts.extend(
                    Path(value)
                    for prop in parsed.properties
                    for value in (prop.evidence_path, prop.counterexample_path, prop.details.get("trace_path"))
                    if value
                )
                declared_artifacts.extend(
                    Path(value) for value in ("proof/status", "proof/logfile.txt")
                    if (staging_dir / value).is_file()
                )
            artifacts = collect_artifacts(request.run_id, staging_dir, declared_artifacts)
            payload = {
                "schema_version": 1,
                "run_id": request.run_id,
                "toolchain_id": profile.id,
                "tool": request.command.tool,
                "tool_version": profile.versions.get(request.command.tool or ""),
                "execution_host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown",
                "execution_user": profile.execution_user,
                "command": display_argv,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "execution_status": execution.value,
                "verification_status": verification.value,
                "return_code": return_code,
                "input_hashes": input_hashes,
                "prepared_input_hashes": request.prepared_input_hashes,
                "input_hash_excludes": [path.as_posix() for path in signed_input_excludes],
                "input_fingerprint": input_fingerprint,
                "session_inputs": [
                    {
                        "source": item.source.as_posix(),
                        "destination": item.destination.as_posix(),
                    }
                    for item in request.session_inputs
                ],
                "cache_hit": False,
                "source_manifest": None,
                "test": request.test_name,
                "suite": request.suite,
                "seed": request.seed,
                "property_set": request.property_set,
                "metadata": self._json_safe(redact_data(request.metadata, secret_values)),
                "tests": [item.model_dump(mode="json") for item in parsed.tests],
                "coverage": [item.model_dump(mode="json") for item in parsed.coverage],
                "properties": [item.model_dump(mode="json") for item in parsed.properties],
                "diagnostics": self._json_safe(redact_data(diagnostics, secret_values)),
                "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
            }
            manifest_path = staging_dir / "manifest.json"
            write_manifest(manifest_path, payload, self._hmac_key)
            verify_manifest(manifest_path, self._hmac_key, verify_files=True)
            os.replace(staging_dir, final_dir)
            if execution == ExecutionStatus.COMPLETED and request.metadata.get("cacheable") is True:
                try:
                    self._write_cache_index(workspace, profile, input_fingerprint, final_dir / "manifest.json")
                except (OSError, ValueError):
                    # A cache-index failure cannot invalidate evidence already published and verified.
                    pass
        except Exception as exc:
            if staging_dir.exists() and not final_dir.exists():
                failure_dir = final_dir.with_name(final_dir.name + ".evidence-error")
                if not failure_dir.exists():
                    os.replace(staging_dir, failure_dir)
            raise RuntimeError(f"failed to atomically publish signed run evidence: {exc}") from exc

        return RunResult(
            run_id=request.run_id,
            execution_status=execution,
            verification_status=verification,
            return_code=return_code,
            started_at=started_at,
            completed_at=completed_at,
            session_dir=final_dir,
            command=display_argv,
            stdout_log=final_dir / "stdout.log",
            stderr_log=final_dir / "stderr.log",
            events_path=final_dir / "events.ndjson",
            manifest_path=final_dir / "manifest.json",
            artifacts=artifacts,
            tests=parsed.tests,
            coverage=parsed.coverage,
            properties=parsed.properties,
            diagnostics=diagnostics,
        )

    def _restore_cached_run(
        self,
        *,
        request: RunRequest,
        profile: ToolchainProfile,
        workspace: Path,
        staging_dir: Path,
        final_dir: Path,
        started_at: datetime,
        input_hashes: dict[str, str],
        effective_input_paths: list[Path],
        input_hash_excludes: list[Path],
        input_fingerprint: str,
        display_argv: list[str],
        secret_values: tuple[str, ...],
        on_event: EventCallback | None,
    ) -> RunResult | None:
        """Restore an exact, fully verified cache entry into a newly signed run directory."""

        if request.metadata.get("cacheable") is not True:
            return None
        index_path = workspace / ".ucagent" / "eda-cache" / profile.id / f"{input_fingerprint}.json"
        if not index_path.is_file():
            return None
        restore_dir: Path | None = None
        moved_entries: list[Path] = []
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(index, dict) or index.get("input_fingerprint") != input_fingerprint:
                return None
            source_relative = Path(str(index["source_manifest"]))
            source_manifest = resolve_within(workspace, source_relative, must_exist=True)
            if source_manifest.name != "manifest.json":
                return None
            source = verify_manifest(source_manifest, self._hmac_key, workspace=workspace, verify_files=True)
            if (
                source.get("input_fingerprint") != input_fingerprint
                or source.get("execution_status") != ExecutionStatus.COMPLETED.value
                or source.get("toolchain_id") != profile.id
                or source.get("tool") != request.command.tool
            ):
                return None
            parsed = ParsedOutput(
                execution_status=ExecutionStatus(source["execution_status"]),
                verification_status=VerificationStatus(source["verification_status"]),
                tests=[TestResult.model_validate(item) for item in source.get("tests", [])],
                coverage=[CoverageMetric.model_validate(item) for item in source.get("coverage", [])],
                properties=[FormalProperty.model_validate(item) for item in source.get("properties", [])],
                diagnostics=[dict(item) for item in source.get("diagnostics", [])],
            )
            restore_dir = Path(tempfile.mkdtemp(prefix=".cache-restore.", dir=staging_dir))
            source_dir = source_manifest.parent
            control_names = {"manifest.json", "stdout.log", "stderr.log", "events.ndjson"}
            copied: set[Path] = set()
            for relative in request.artifact_paths:
                if relative == Path("."):
                    source_entries = [entry for entry in source_dir.iterdir() if entry.name not in control_names]
                    pairs = [(entry, Path(entry.name)) for entry in source_entries]
                else:
                    source_entry = resolve_within(source_dir, relative, must_exist=False)
                    if not source_entry.exists():
                        continue
                    pairs = [(source_entry, relative)]
                for source_entry, destination_relative in pairs:
                    if destination_relative in copied:
                        continue
                    if source_entry.is_symlink():
                        raise ValueError(f"cached artifact is a symbolic link: {destination_relative}")
                    destination = resolve_within(restore_dir, destination_relative, must_exist=False)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if source_entry.is_dir():
                        shutil.copytree(source_entry, destination)
                    elif source_entry.is_file():
                        shutil.copy2(source_entry, destination)
                    copied.add(destination_relative)
            for entry in restore_dir.iterdir():
                destination = staging_dir / entry.name
                os.replace(entry, destination)
                moved_entries.append(destination)
            restore_dir.rmdir()
            restore_dir = None
        except (KeyError, OSError, ValueError, TypeError, ManifestVerificationError, shutil.Error):
            if restore_dir is not None and restore_dir.exists():
                checked_restore = resolve_within(staging_dir, restore_dir, must_exist=True, allow_root=False)
                shutil.rmtree(checked_restore)
            for destination in reversed(moved_entries):
                if not destination.exists():
                    continue
                checked_destination = resolve_within(staging_dir, destination, must_exist=True, allow_root=False)
                if checked_destination.is_dir():
                    shutil.rmtree(checked_destination)
                else:
                    checked_destination.unlink()
            return None

        completed_at = datetime.now(timezone.utc)
        diagnostics = list(parsed.diagnostics)
        try:
            current_hashes = hash_workspace_inputs(
                workspace,
                effective_input_paths,
                exclude_paths=[*input_hash_excludes, staging_dir.relative_to(workspace)],
            )
        except (OSError, ValueError) as exc:
            current_hashes = {}
            observed: Any = {"error": redact_text(str(exc), secret_values)}
        else:
            observed = current_hashes
        execution = parsed.execution_status
        verification = parsed.verification_status
        if current_hashes != input_hashes:
            execution = ExecutionStatus.ERROR
            verification = VerificationStatus.UNKNOWN
            diagnostics.append(
                {
                    "error_code": "inputs_changed_during_cache_restore",
                    "error": "One or more signed inputs changed during cache restoration.",
                    "expected": input_hashes,
                    "observed": observed,
                    "next_action": "Rerun against a stable project snapshot.",
                }
            )
        missing_artifacts = self._missing_artifacts(staging_dir, request.artifact_paths)
        if missing_artifacts:
            execution = ExecutionStatus.ERROR
            verification = VerificationStatus.UNKNOWN
            diagnostics.append(
                {
                    "error_code": "missing_declared_artifact",
                    "error": "The verified cache entry does not contain every declared artifact.",
                    "observed": {"missing": missing_artifacts},
                    "next_action": "Reject the cache entry and execute the stage against a complete output contract.",
                }
            )

        events_path = staging_dir / "events.ndjson"
        stdout_path = staging_dir / "stdout.log"
        stderr_path = staging_dir / "stderr.log"
        source_reference = source_manifest.relative_to(workspace).as_posix()
        with (
            events_path.open("w", encoding="utf-8", newline="\n") as event_stream,
            stdout_path.open("w", encoding="utf-8", newline="") as stdout_stream,
            stderr_path.open("w", encoding="utf-8", newline=""),
        ):
            stdout_stream.write(f"Verified cache hit: {source_reference}\n")
            for sequence, (event_type, payload) in enumerate(
                (
                    ("queued", {"toolchain_id": profile.id}),
                    ("cache_hit", {"source_manifest": source_reference, "input_fingerprint": input_fingerprint}),
                    (
                        "finished",
                        {
                            "execution_status": execution.value,
                            "verification_status": verification.value,
                            "return_code": source.get("return_code"),
                        },
                    ),
                ),
                start=1,
            ):
                event = {
                    "sequence": sequence,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": request.run_id,
                    "type": event_type,
                    "payload": redact_data(payload, secret_values),
                }
                event_stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                if self._event_flush:
                    event_stream.flush()
                self._notify(on_event, event)

        declared_artifacts = [Path("stdout.log"), Path("stderr.log"), Path("events.ndjson"), *request.artifact_paths]
        artifacts = collect_artifacts(request.run_id, staging_dir, declared_artifacts)
        payload = {
            "schema_version": 1,
            "run_id": request.run_id,
            "toolchain_id": profile.id,
            "tool": request.command.tool,
            "tool_version": profile.versions.get(request.command.tool or ""),
            "execution_host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown",
            "execution_user": profile.execution_user,
            "command": display_argv,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "execution_status": execution.value,
            "verification_status": verification.value,
            "return_code": source.get("return_code"),
            "input_hashes": input_hashes,
            "input_hash_excludes": [path.as_posix() for path in input_hash_excludes],
            "input_fingerprint": input_fingerprint,
            "session_inputs": [
                {
                    "source": item.source.as_posix(),
                    "destination": item.destination.as_posix(),
                }
                for item in request.session_inputs
            ],
            "cache_hit": True,
            "source_manifest": source_reference,
            "test": request.test_name,
            "suite": request.suite,
            "seed": request.seed,
            "property_set": request.property_set,
            "metadata": self._json_safe(redact_data(request.metadata, secret_values)),
            "tests": [item.model_dump(mode="json") for item in parsed.tests],
            "coverage": [item.model_dump(mode="json") for item in parsed.coverage],
            "properties": [item.model_dump(mode="json") for item in parsed.properties],
            "diagnostics": self._json_safe(redact_data(diagnostics, secret_values)),
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        }
        manifest_path = staging_dir / "manifest.json"
        write_manifest(manifest_path, payload, self._hmac_key)
        verify_manifest(manifest_path, self._hmac_key, verify_files=True)
        os.replace(staging_dir, final_dir)
        if execution == ExecutionStatus.COMPLETED:
            try:
                self._write_cache_index(workspace, profile, input_fingerprint, final_dir / "manifest.json")
            except (OSError, ValueError):
                # The restored run remains valid even if it cannot become the next cache source.
                pass
        return RunResult(
            run_id=request.run_id,
            execution_status=execution,
            verification_status=verification,
            return_code=source.get("return_code"),
            started_at=started_at,
            completed_at=completed_at,
            session_dir=final_dir,
            command=display_argv,
            stdout_log=final_dir / "stdout.log",
            stderr_log=final_dir / "stderr.log",
            events_path=final_dir / "events.ndjson",
            manifest_path=final_dir / "manifest.json",
            artifacts=artifacts,
            tests=parsed.tests,
            coverage=parsed.coverage,
            properties=parsed.properties,
            diagnostics=diagnostics,
        )

    def _write_cache_index(
        self,
        workspace: Path,
        profile: ToolchainProfile,
        input_fingerprint: str,
        source_manifest: Path,
    ) -> None:
        """Atomically point one fingerprint at a signed, workspace-contained source manifest."""

        cache_dir = resolve_within(workspace, Path(".ucagent") / "eda-cache" / profile.id, must_exist=False)
        cache_dir.mkdir(parents=True, exist_ok=True)
        relative_manifest = source_manifest.resolve(strict=True).relative_to(workspace).as_posix()
        record = {
            "schema_version": 1,
            "input_fingerprint": input_fingerprint,
            "source_manifest": relative_manifest,
        }
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{input_fingerprint}.", suffix=".tmp", dir=cache_dir)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            os.replace(temporary, cache_dir / f"{input_fingerprint}.json")
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _missing_artifacts(session_dir: Path, paths: list[Path]) -> list[str]:
        """List declared session outputs that do not exist after tool completion."""

        missing: list[str] = []
        for relative in paths:
            candidate = resolve_within(session_dir, relative, must_exist=False)
            if not candidate.exists():
                missing.append(relative.as_posix())
        return missing

    def _prepare_command(
        self,
        request: RunRequest,
        profile: ToolchainProfile,
        workspace: Path,
        staging_dir: Path,
    ) -> tuple[list[str], Path, dict[str, str]]:
        """Resolve bounded placeholders, executable trust, cwd, and command environment."""

        def expand(value: str) -> str:
            """Expand only the two runner-owned path placeholders."""

            return value.replace("{WORKSPACE}", str(workspace)).replace("{SESSION_DIR}", str(staging_dir))

        argv = [expand(value) for value in request.command.argv]
        command_environment: dict[str, str] = {}
        for name, value in request.command.env.items():
            placeholders = set(re.findall(r"\{([A-Z][A-Z0-9_]*)\}", value))
            unsupported = sorted(placeholders.difference({"WORKSPACE", "SESSION_DIR"}))
            if unsupported:
                raise ValueError(
                    f"environment variable {name!r} contains unsupported runner placeholders: "
                    + ", ".join(unsupported)
                )
            command_environment[name] = expand(value)
        cwd_text = expand(str(request.command.cwd))
        cwd_candidate = Path(cwd_text)
        cwd = resolve_within(workspace, cwd_candidate if cwd_candidate.is_absolute() else workspace / cwd_candidate, must_exist=True)
        if request.command.tool is not None:
            argv[0] = profile.require_tool(request.command.tool)
        else:
            executable = Path(argv[0])
            if not executable.is_absolute():
                executable = cwd / executable
            executable = resolve_within(workspace, executable, must_exist=True)
            if not executable.is_file():
                raise ValueError(f"workspace executable is not a file: {executable}")
            argv[0] = str(executable)
        return argv, cwd, command_environment

    def _parse_output(self, request: RunRequest, return_code: int, output: str) -> ParsedOutput:
        """Dispatch bounded output to the deterministic parser selected by the adapter."""

        if request.parser == "claude":
            from .claude import parse_claude_output
            return parse_claude_output(output, return_code=return_code,
                                       session_id=str(request.metadata["session_id"]),
                                       expected_model=request.metadata.get("model"))
        if request.parser == "pytest":
            return parse_pytest_log(
                output,
                return_code=return_code,
                test_name=request.test_name or "unknown",
                suite=request.suite,
                seed=request.seed,
            )
        if request.parser == "uvm":
            return parse_uvm_log(
                output,
                return_code=return_code,
                test_name=request.test_name or "unknown",
                suite=request.suite,
                seed=request.seed,
                success_markers=request.success_markers,
            )
        if request.parser == "urg":
            return parse_urg_output(output, return_code=return_code)
        if request.parser == "formal":
            return parse_formal_log(
                output,
                return_code=return_code,
                engine=str(request.metadata.get("engine") or request.command.tool or "formal"),
                expected_properties=request.metadata.get("expected_properties"),
            )
        if return_code == 0:
            verification = request.verification_hint
            return ParsedOutput(execution_status=ExecutionStatus.COMPLETED, verification_status=verification)
        if request.verification_hint in {VerificationStatus.FAILED, VerificationStatus.INCONCLUSIVE}:
            return ParsedOutput(execution_status=ExecutionStatus.COMPLETED, verification_status=request.verification_hint)
        return ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            diagnostics=[
                {
                    "error_code": "tool_exit_error",
                    "error": f"Tool exited with return code {return_code}.",
                    "next_action": "Inspect stdout.log and stderr.log, then correct the tool or input failure.",
                }
            ],
        )

    @staticmethod
    def _secret_values(profile: ToolchainProfile, request: RunRequest) -> tuple[str, ...]:
        """Collect configured values that must be removed from logs and evidence."""

        explicit_names = set(profile.license_environment_names)
        values = [
            value
            for name, value in {**profile.environment, **request.command.env}.items()
            if is_secret_name(name) or name in explicit_names
        ]
        return tuple(value for value in values if value)

    @staticmethod
    def _notify(callback: EventCallback | None, event: dict[str, Any]) -> None:
        """Invoke a UI event callback without allowing it to terminate an EDA process."""

        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            return

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str], grace_seconds: float = 3.0) -> None:
        """Terminate descendants first, then kill survivors after a bounded grace period."""

        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    continue
            try:
                parent.terminate()
            except psutil.NoSuchProcess:
                pass
            _, alive = psutil.wait_procs([*children, parent], timeout=grace_seconds)
            for survivor in alive:
                try:
                    survivor.kill()
                except psutil.NoSuchProcess:
                    continue
        except psutil.NoSuchProcess:
            return
        except Exception:
            try:
                process.kill()
            except Exception:
                return

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Convert metadata to deterministic JSON-compatible values without executing hooks."""

        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): JobRunner._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [JobRunner._json_safe(item) for item in value]
        return str(value)

    @staticmethod
    def _sanitize_result_report(path: Path, secret_values: tuple[str, ...], limit: int) -> str:
        """Redact a declared text report in place and return a bounded parser excerpt."""

        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".redacting", dir=path.parent)
        temporary = Path(temporary_name)
        excerpt_parts: list[str] = []
        excerpt_bytes = 0
        try:
            with (
                path.open("r", encoding="utf-8", errors="replace", newline="") as source,
                os.fdopen(descriptor, "w", encoding="utf-8", newline="") as target,
            ):
                for line in source:
                    safe_line = redact_text(line, secret_values)
                    target.write(safe_line)
                    if excerpt_bytes < limit:
                        encoded = safe_line.encode("utf-8")[: limit - excerpt_bytes]
                        excerpt_parts.append(encoded.decode("utf-8", errors="ignore"))
                        excerpt_bytes += len(encoded)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return "".join(excerpt_parts)
