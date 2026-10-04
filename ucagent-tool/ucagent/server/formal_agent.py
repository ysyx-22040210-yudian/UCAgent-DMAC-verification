"""Shared bounded AI authoring over the original formal-stage lifecycle, for either engine."""

from __future__ import annotations

from copy import deepcopy
import difflib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import threading
import time
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import yaml

from ucagent.eda.claude import build_claude_request, isolation_settings, validate_cli_capabilities
from ucagent.eda.models import CommandSpec, RunRequest
from ucagent.eda.security import is_secret_name, redact_text
from ucagent.eda.sby_guided import publish_text


def common_agent_profile(runtime):
    """Resolve one administrator-selected CLI and private model settings for both engines."""
    runtime.reload_toolchains()
    profiles = [profile for profile in runtime._profiles.values() if "claude" in profile.tools]
    if len(profiles) != 1:
        raise ValueError("Configure exactly one shared Claude toolchain profile before starting the formal Agent.")
    profile = profiles[0]
    home = Path(profile.environment.get("HOME", ""))
    if not home.is_absolute():
        raise ValueError("The shared Agent profile must declare the execution identity's absolute HOME.")
    settings_path = home / ".claude/settings.json"
    if settings_path.is_symlink() or not settings_path.is_file():
        raise ValueError("Configure the execution identity's private Claude settings and selected model first.")
    descriptor = os.open(settings_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1024 ** 2
                or os.name == "posix" and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077)):
            raise ValueError("Claude settings must be a bounded owner-only file under the execution identity.")
        try:
            settings = json.loads(stream.read(1024 ** 2 + 1))
        except (ValueError, UnicodeError):
            raise ValueError("Claude host settings are not valid JSON; ask the administrator to repair them.") from None
    environment = settings.get("env", {}) if isinstance(settings, dict) else None
    # Pin test instances without rewriting the shared execution identity's
    # private settings or changing the model of another instance's sessions.
    model = profile.claude_model or (settings.get("model") if isinstance(settings, dict) else None)
    if (not isinstance(model, str) or not model or not isinstance(environment, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in environment.items())):
        raise ValueError("Claude host settings must select a model and use string environment values.")
    # Values remain in process memory for CLI execution and log redaction only.
    # They never enter project configuration, the session row or prompt files.
    return profile.model_copy(update={"environment": {**profile.environment, **environment}}), model, settings_path


class FormalAgentTurn:
    """Expose the same stage tools and AI driver regardless of the selected formal engine."""

    def __init__(self, service, identifier, request):
        """Bind one bounded turn to an existing, authenticated stage session."""
        self.service = service
        self.identifier = identifier
        self.request = request
        self.tool_lock = threading.Lock()
        self.calls = 0
        self.stalled = 0
        self.closed = False
        self.deadline = time.monotonic() + request.timeout

    def call(self, name, **arguments):
        """Apply a serialized original stage operation; AI cannot approve, skip, or sign results."""
        with self.tool_lock:
            with self.service.lock:
                if self.closed or self.service.active_id != self.identifier or time.monotonic() >= self.deadline:
                    raise ValueError("Agent turn is no longer active; return control to the engineer.")
                row = self.service.load(self.identifier)
                session = self.service.session(row)
                if row.get("cancel_requested") or session.cancelled.is_set():
                    raise ValueError("Agent turn was cancelled; do not perform further operations.")
                self.calls += 1
                if self.calls > self.request.max_turns * 8:
                    raise ValueError("Tool-call budget exhausted; summarize remaining work without claiming completion.")
                index = session.stage_manager.stage_index
                if name == "RoleInfo":
                    result = {"role": session.cfg.mission.prompt.system.replace("{skill_system}", ""),
                            "capabilities": self.service.capabilities(row["options"]["engine"])}
                elif name == "CurrentTips":
                    result = session.stage_manager.get_current_tips()
                elif name == "ReadTextFile":
                    result = session.read(arguments["path"])
                elif name in {"ReadCheckPoints", "UpdateCheckPoints"}:
                    path = "formal_out/.formal_records.yaml"
                    opened = session.read(path)
                    document = yaml.safe_load(opened["content"])
                    checks = {check["id"]: check for group in document.get("spec", {}).get("function_groups", [])
                              for function in group["functions"] for check in function["check_points"]}
                    if name == "ReadCheckPoints":
                        ids = arguments["ids"]
                        if not 1 <= len(ids) <= 16 or len(set(ids)) != len(ids) or any(i not in checks for i in ids):
                            raise ValueError("Read 1–16 unique existing CK identifiers per batch.")
                        result = {"path": path, "sha256": opened["sha256"], "check_points": [checks[i] for i in ids]}
                    else:
                        updates = arguments["check_points"]
                        if not 1 <= len(updates) <= 16 or not arguments.get("expected_sha256"):
                            raise ValueError("Update 1–16 existing CKs with their current record hash.")
                        seen = set()
                        for update in updates:
                            if (not isinstance(update, dict) or update.get("id") not in checks
                                    or update["id"] in seen
                                    or not set(update) <= {"id", "sva_body", "sby_guard", "sby_trigger"}
                                    or not set(update) - {"id"}
                                    or any(not isinstance(value, str) for value in update.values())):
                                raise ValueError("Only unique existing CK ids and string property/guard/trigger fields may be updated.")
                            seen.add(update["id"])
                            checks[update["id"]].update({key: value for key, value in update.items() if key != "id"})
                        result = session.write(path, yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                                               arguments["expected_sha256"])
                        result["updated_ck_ids"] = sorted(seen)
                        row["verification_status"] = "unknown"
                        row.pop("evidence", None)
                elif name == "EditTextFile":
                    path, content = arguments["path"], arguments["content"]
                    if len(content.encode("utf-8")) > 200000:
                        raise ValueError("Editor input exceeds 200000 bytes; reduce the current artifact.")
                    target = session.file_path(path)
                    before = target.read_text(encoding="utf-8") if target.exists() else ""
                    result = session.write(path, content, arguments.get("expected_sha256"))
                    result["diff"] = "".join(difflib.unified_diff(before.splitlines(True), content.splitlines(True),
                                                                fromfile=path, tofile=path))[:20000]
                    row["verification_status"] = "unknown"
                    row.pop("evidence", None)
                elif name == "SetCurrentStageJournal":
                    if not arguments["journal"].strip() or len(arguments["journal"]) > 20000:
                        raise ValueError("Stage journal must explain the work actually performed.")
                    result = session.act("journal", index, arguments["journal"])
                elif name not in {"Check", "Complete"}:
                    raise ValueError("This tool is not exposed to the formal Agent.")
            if name in {"Check", "Complete"}:
                # Do not hold the API lock during an EDA check: cancellation must
                # remain reachable even when the CLI is waiting on this MCP call.
                stage = session.stage_manager.get_current_stage()
                if not stage:
                    return {"all_completed": True, "next_action": "Return the verified final report."}
                if self.stalled >= 3:
                    raise ValueError("Three checks made no effective progress. Stop and request engineer review.")
                for checker in stage.checker:
                    if hasattr(checker, "event_callback"):
                        checker.event_callback = lambda event: self.service.record_tool_event(self.identifier, event)
                result = session.act(name.lower(), index, timeout=max(1, min(300, int(self.deadline - time.monotonic()))))
                with self.service.lock:
                    row = self.service.load(self.identifier)
                    row["verification_status"] = "unknown"
                    row.pop("evidence", None)
                    for checker in stage.checker:
                        evidence = getattr(checker, "last_evidence", None)
                        if evidence is not None:
                            row["verification_status"] = evidence["verification_status"]
                            row["evidence"] = evidence
                            row["capabilities"]["tool_acceptance"] = "real_signed_execution"
                success = bool(isinstance(result, dict) and result.get("check_pass")) or session.stage_manager.stage_index != index
                self.stalled = 0 if success else self.stalled + 1
            with self.service.lock:
                # Reload cancellation metadata that may have arrived during Check.
                latest = self.service.load(self.identifier)
                if latest.get("cancel_requested"):
                    raise ValueError("Operation was cancelled; retain files but do not publish stage progress.")
                row["cancel_requested"] = latest.get("cancel_requested", False)
                row["revision"] = latest["revision"]
                row.update(checkpoint=session.checkpoint(), view=session.projection())
                row["last_result"] = result
                self.service.persist(row, "agent.tool." + name)
            return result

    def run(self):
        """Run the configured CLI through JobRunner and an authenticated ephemeral MCP endpoint."""
        service = self.service
        profile, model, settings_path = common_agent_profile(service.runtime)
        row = service.load(self.identifier)
        session = service.live[self.identifier]
        workspace = Path(session.workspace)
        control = workspace / ".agent-control" / self.request.request_id
        control.mkdir(parents=True, exist_ok=False)
        policy = isolation_settings(settings_path, control)
        run_root = Path("formal_out/agent_runs") / self.request.request_id
        for flag in ("--version", "--help"):
            probe = RunRequest(workspace=workspace, output_dir=run_root / flag[2:], resource_class="claude",
                command=CommandSpec(tool="claude", argv=["claude", flag], cwd=Path("{SESSION_DIR}"), timeout_seconds=30),
                output_limit_bytes=256 * 1024, metadata={"adapter": "claude_probe", "cacheable": False})
            observed = service.runtime._runner.run(probe, profile, cancel_event=session.cancelled)
            if observed.execution_status != "completed":
                raise ValueError("Shared Agent CLI probe failed; inspect the retained probe manifest.")
            if flag == "--help" and validate_cli_capabilities(observed.stdout_log.read_text(encoding="utf-8")):
                raise ValueError("The installed Claude CLI lacks the required isolated-session capabilities.")
        agent = deepcopy(row.get("agent") or {})
        if agent.get("model") and agent["model"] != model:
            raise ValueError("The configured model changed. Create a new stage task; do not silently resume another model.")
        agent.update(session_id=agent.get("session_id") or str(uuid4()), model=model,
                     turns=agent.get("turns", 0) + 1, status="running")
        with service.lock:
            row = service.load(self.identifier)
            row["agent"] = agent
            service.persist(row, "agent.started")
        token = secrets.token_urlsafe(32)
        profile = profile.model_copy(update={"environment": {**profile.environment, "UCAGENT_FORMAL_MCP_TOKEN": token}})
        mcp = FastMCP("UCAgent shared formal workflow", host="127.0.0.1", log_level="WARNING",
                      stateless_http=True, json_response=True, streamable_http_path="/mcp")

        @mcp.tool()
        def RoleInfo() -> dict:
            """Read the selected engine's role, allowed property syntax and evidence limitations."""
            return self.call("RoleInfo")

        @mcp.tool()
        def CurrentTips() -> dict | str:
            """Read the actual current stage, required artifacts, reference files and completion gates."""
            return self.call("CurrentTips")

        @mcp.tool()
        def ReadTextFile(path: str) -> dict:
            """Read one bounded workspace-relative text file and its SHA-256; control files are not exposed."""
            return self.call("ReadTextFile", path=path)

        @mcp.tool()
        def EditTextFile(path: str, content: str, expected_sha256: str | None = None) -> dict:
            """Save complete UTF-8 authoring text using the hash from ReadTextFile; source RTL and tool results are protected."""
            return self.call("EditTextFile", path=path, content=content, expected_sha256=expected_sha256)

        @mcp.tool()
        def ReadCheckPoints(ids: list[str]) -> dict:
            """Read 1–16 existing CKs and the authoritative full-record hash without repeating unrelated metadata."""
            return self.call("ReadCheckPoints", ids=ids)

        @mcp.tool()
        def UpdateCheckPoints(check_points: list[dict], expected_sha256: str) -> dict:
            """Save string sva_body/guard/trigger fields for 1–16 existing CKs through the version-checked editor; results and CK metadata stay protected."""
            return self.call("UpdateCheckPoints", check_points=check_points, expected_sha256=expected_sha256)

        @mcp.tool()
        def Check() -> dict:
            """Execute the real current-stage check and use its diagnostics; passing does not itself advance the stage."""
            return self.call("Check")

        @mcp.tool()
        def Complete() -> dict:
            """Recheck and advance only if all native gates pass; stop for human approval when required."""
            return self.call("Complete")

        @mcp.tool()
        def SetCurrentStageJournal(journal: str) -> dict | str:
            """Record performed work, remaining issues and evidence scope before completing the current stage."""
            return self.call("SetCurrentStageJournal", journal=journal)

        app = mcp.streamable_http_app()
        async def authorize(request, call_next):
            """Require a per-turn capability that exists only in process memory and the child environment."""
            from starlette.responses import JSONResponse
            if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return await call_next(request)

        app.add_middleware(BaseHTTPMiddleware, dispatch=authorize)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        try:
            thread.start()
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            if not server.started:
                raise ValueError("Formal Agent tool endpoint did not start.")
            config = {"mcpServers": {"formal": {"type": "http", "url": "http://127.0.0.1:" + str(port) + "/mcp",
                       "headers": {"Authorization": "Bearer ${UCAGENT_FORMAL_MCP_TOKEN}"}}}}
            prompt_resource = Path(__file__).parents[1] / "lang" / session.cfg.lang / "config/formal_gui_agent.txt"
            prompt = prompt_resource.read_text(encoding="utf-8") + "\n\n" + self.request.prompt
            for name, content in (("policy.json", json.dumps(policy)), ("mcp.json", json.dumps(config)), ("prompt.txt", prompt)):
                publish_text(workspace, control / name, content)
            request = build_claude_request(workspace=workspace, output_dir=run_root / "turn",
                prompt_path=(control / "prompt.txt").relative_to(workspace), mcp_path=(control / "mcp.json").relative_to(workspace),
                settings_path=(control / "policy.json").relative_to(workspace), session_id=agent["session_id"],
                resume=bool(agent.get("can_resume")), timeout_seconds=max(1, self.deadline - time.monotonic()),
                max_turns=self.request.max_turns, model=model, tool_scope="formal")
            observed = service.runtime._runner.run(request, profile, cancel_event=session.cancelled,
                on_event=lambda event: service.record_tool_event(self.identifier, event))
            if observed.execution_status != "completed":
                session.cancel()
            message, seen_session = "", False
            if observed.stdout_log and observed.stdout_log.is_file():
                for line in observed.stdout_log.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("session_id") == agent["session_id"]:
                        seen_session = True
                        if event.get("type") == "result":
                            message = str(event.get("result", ""))[:20000]
            with service.lock:
                row = service.load(self.identifier)
                # Ordinary environment values such as "1" are not credentials;
                # redacting them would corrupt signal widths and stage numbers.
                secret_values = tuple(value for name, value in profile.environment.items()
                                      if is_secret_name(name) or name in profile.license_environment_names)
                row["agent"].update(status=observed.execution_status.value, can_resume=seen_session,
                                    manifest=str(observed.manifest_path) if observed.manifest_path else None,
                                    tool_calls=self.calls, message=redact_text(message, secret_values))
                service.persist(row, "agent.finished")
            return {"agent_execution_status": observed.execution_status.value,
                    "diagnostics": observed.diagnostics, "tool_calls": self.calls,
                    "next_action": "Inspect current stage evidence. Review and approve when required, then continue the same Agent session."}
        finally:
            self.closed = True
            if not self.tool_lock.acquire(blocking=False):
                session.cancel()
                # Keep the session mutation lock owned until an in-flight native
                # checker has stopped; another GUI action must not race it.
                self.tool_lock.acquire()
            self.tool_lock.release()
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
