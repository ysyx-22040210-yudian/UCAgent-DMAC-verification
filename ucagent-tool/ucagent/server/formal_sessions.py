"""Durable, serialized GUI operations over the original formal stage lifecycle."""

from copy import deepcopy
from contextlib import nullcontext
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Literal
from uuid import uuid4
from urllib.parse import urlencode

import yaml

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ucagent.platform.formal_session import FormalSession, digest
from ucagent.eda.security import redact_text
from ucagent.eda.manifest import sha256_file


class SessionCreate(BaseModel):
    """Select a project and explicit engine without accepting executable configuration."""
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1, max_length=100)
    dut: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
    engine: Literal["formalmc", "sby"] = "formalmc"
    toolchain: str = Field(default="sby", pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")
    cex_replay: bool = False
    static_review: bool = False
    human_review: bool = True


class FormalMigrationRequest(BaseModel):
    """Bind a migration to a saved session revision and an idempotent request."""
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,80}$")


class SessionAction(BaseModel):
    """Guard each mutation by revision, stage identity and a unique retry-safe request ID."""
    model_config = ConfigDict(extra="forbid")
    action: Literal["agent", "check", "complete", "journal", "approve", "reject", "pause", "resume", "cancel", "reopen", "save"]
    revision: int = Field(ge=0, strict=True)
    stage_index: int = Field(ge=0, strict=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,80}$")
    journal: str = Field(default="", max_length=20000)
    timeout: int = Field(default=300, ge=1, le=86400, strict=True)
    prompt: str = Field(default="", max_length=20000)
    max_turns: int = Field(default=12, ge=1, le=30, strict=True)
    path: str = Field(default="", max_length=400)
    content: str = Field(default="", max_length=200000)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class FormalSessions:
    """Persist session metadata in the platform WAL database, not a second stage engine."""

    def __init__(self, runtime):
        """Initialize durable operation records and mark interrupted work as resumable."""
        self.runtime = runtime
        self.store = runtime.store
        self.root = runtime.state_dir / "formal_sessions"
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.live = {}
        self.worker = None
        self.active_id = None
        with self.store._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS formal_sessions (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS formal_session_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS formal_session_operations (
                    session_id TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                    PRIMARY KEY(session_id, request_id));
                CREATE TABLE IF NOT EXISTS formal_project_migrations (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
                    source_session_id TEXT NOT NULL REFERENCES formal_sessions(id),
                    request_id TEXT NOT NULL);
            """)
        for item in self.list():
            if item["state"] == "running":
                row = self.load(item["id"])
                row.update(state="paused", execution_status="error", verification_status="unknown",
                           last_result={"error_code": "INTERRUPTED", "next_action": "Resume and re-check the current stage; interrupted operations are not replayed."})
                self.persist(row, "interrupted")

    def load(self, identifier):
        """Authenticate the durable checkpoint before allowing any restore or action."""
        with self.store._connection() as db:
            row = db.execute("SELECT payload,signature FROM formal_sessions WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        expected = hmac.new(self.runtime._manifest_key, row["payload"].encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, row["signature"]):
            raise ValueError("Session checkpoint signature mismatch; progress cannot be trusted.")
        return json.loads(row["payload"])

    def persist(self, row, event, operation=None, connection=None):
        """Atomically sign one native checkpoint projection and append a monotonic event."""
        row["revision"] += 1
        row["updated_at"] = time.time()
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        signature = hmac.new(self.runtime._manifest_key, payload.encode(), hashlib.sha256).hexdigest()
        with (nullcontext(connection) if connection is not None else self.store._connection()) as db:
            if operation:
                db.execute("INSERT INTO formal_session_operations VALUES (?,?,?)", (row["id"], *operation))
            db.execute("INSERT OR REPLACE INTO formal_sessions VALUES (?,?,?)", (row["id"], payload, signature))
            db.execute("INSERT INTO formal_session_events(session_id,payload) VALUES (?,?)",
                       (row["id"], json.dumps({"type": event, "revision": row["revision"], "time": row["updated_at"], "result": row.get("last_result")})))

    def public(self, row):
        """Exclude checkpoint internals while retaining explicit evidence limitations."""
        return {key: value for key, value in row.items() if key not in {"checkpoint", "inputs"}}

    def list(self):
        """Return authenticated metadata for existing sessions without starting tools."""
        with self.store._connection() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM formal_sessions ORDER BY rowid DESC")]
        return [self.public(self.load(identifier)) for identifier in ids]

    def capabilities(self, engine):
        """Describe this integration, not all possible capabilities of an engine family."""
        sby = engine == "sby"
        return {"engine": engine, "stage_control": "original_stage_manager", "authoring": "shared_agent_with_manual_review",
                "property_syntax": "native_yosys_expressions" if sby else "formalmc_sva",
                "coi": "unsupported" if sby else "requires_real_fanin_report",
                "vacuity": "not_established_trigger_cover_only" if sby else "requires_real_trivially_true_report",
                "liveness": "not_established" if sby else "depends_on_tool_and_property",
                "bounded_proof": "bmc_no_counterexample_is_inconclusive",
                "dynamic_replay": "requires_actual_simulation_receipt", "automatic_fallback": False,
                "tool_acceptance": "not_run_in_this_session"}

    def create(self, request):
        """Snapshot bounded text inputs and create the actual original formal stage state."""
        with self.lock:
            if self.active_id:
                raise ValueError("A stage operation is running; wait before creating another session.")
            project = self.store.get_project(request.project_id)
            if not project:
                raise ValueError("Project not found; import the project first.")
            source = self.runtime.resolve_project_root(project["source_root"])
            identifier = uuid4().hex
            workspace = self.root / identifier
            # Allowlist small authoring inputs; do not inherit .ucagent, hooks,
            # settings, executable scripts, old logs, databases or proof receipts.
            files = []
            total = 0
            for current, dirs, names in os.walk(source, followlinks=False):
                dirs[:] = [name for name in dirs if not name.startswith(".") and name not in {"node_modules", "output", "formal_out", "formal_test", "formal_sby", "Guide_Doc", "build", "dist", "venv"}]
                for name in names:
                    path = Path(current) / name
                    if path.suffix.lower() not in {".sv", ".v", ".svh", ".vh", ".md", ".txt", ".f", ".mem", ".hex"}:
                        continue
                    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != source.parent):
                        raise ValueError("Input snapshot cannot contain symbolic links.")
                    total += path.stat().st_size
                    files.append(path)
                    if len(files) > 10000 or total > 128 * 1024 * 1024:
                        raise ValueError("Project input snapshot exceeds 10000 files or 128 MiB; import a smaller RTL project root.")
            if not any(path.suffix.lower() in {".sv", ".v"} for path in files):
                raise ValueError("No RTL sources found in the imported project.")
            if shutil.disk_usage(self.root).free < total + 1024 ** 3:
                raise ValueError("Insufficient disk space for a new session; no input data was removed.")
            workspace.mkdir()
            inputs = {}
            # Original formal guidance expects RTL beneath {DUT}; preserve nested
            # include/filelist relationships inside that isolated input directory.
            for path in files:
                relative = Path(request.dut) / path.relative_to(source)
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                inputs[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
            options = request.model_dump()
            session = FormalSession(workspace, options)
            row = {"id": identifier, "options": options, "workspace": str(workspace), "inputs": inputs,
                   "revision": 0, "state": "ready", "execution_status": "completed", "verification_status": "unknown",
                   "checkpoint": session.checkpoint(), "view": session.projection(), "last_result": None,
                   "capabilities": self.capabilities(request.engine)}
            self.live[identifier] = session
            self.persist(row, "created")
            return self.public(row)

    def session(self, row):
        """Reject changed imported inputs and lazily restore authenticated native progress."""
        workspace = self.root / row["id"]
        if str(workspace) != row["workspace"] or workspace.is_symlink() or workspace.resolve() != workspace:
            raise ValueError("Session workspace identity mismatch.")
        for relative, expected in row["inputs"].items():
            path = workspace / relative
            if path.is_symlink() or not path.resolve().is_relative_to(workspace) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Imported inputs changed; create a new session to verify the new design.")
        for relative, expected in row["checkpoint"].get("authoring_hashes", {}).items():
            path = workspace / relative
            if path.is_symlink() or not path.resolve().is_relative_to(workspace) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Authoring inputs changed outside the managed editor; saved completion is stale. Preserve the changed files and create a new session.")
        if row["id"] not in self.live:
            self.live[row["id"]] = FormalSession(workspace, row["options"], row["checkpoint"])
        return self.live[row["id"]]

    def migration_for_project(self, project_id):
        """Return the authenticated source receipt for an internally migrated project."""
        with self.store._connection() as db:
            link = db.execute("SELECT source_session_id,request_id FROM formal_project_migrations WHERE project_id=?",
                              (project_id,)).fetchone()
        if not link:
            return None
        receipt = self.load(link["source_session_id"]).get("migrations", {}).get(link["request_id"])
        if not receipt or receipt["project_id"] != project_id:
            raise ValueError("Migration source receipt is missing or inconsistent.")
        return receipt

    def migrate_formalmc(self, identifier, request):
        """Create a linked native project atomically without a ZIP, model call, or tool run."""
        from ucagent.eda.formalmc_conversion import (
            convert_sby_to_formalmc, verify_converted_project, FormalConversionError)
        from ucagent.eda.security import resolve_within
        from ucagent.platform.project import load_project_config
        import tempfile

        with self.lock:
            row = self.load(identifier)
            request_hash = digest({"action": "migrate_formalmc", **request.model_dump()})
            with self.store._connection() as db:
                prior = db.execute("SELECT request_hash FROM formal_session_operations WHERE session_id=? AND request_id=?",
                                   (identifier, request.request_id)).fetchone()
            if prior:
                if prior[0] != request_hash:
                    raise ValueError("request_id was reused with different migration parameters.")
                receipt = row.get("migrations", {}).get(request.request_id)
                if not receipt:
                    raise ValueError("Migration receipt is absent; refresh before retrying.")
                project = self.store.get_project(receipt["project_id"])
                if not project or project["source_root"] != receipt["workspace"]:
                    raise ValueError("Migrated project is absent or moved; create a fresh migration.")
                verify_converted_project(receipt["workspace"], receipt["manifest_sha256"])
                return {"migration": receipt, "project": self.runtime.project_public(project), "session": self.public(row)}
            if request.revision != row["revision"]:
                raise ValueError("Session revision changed; refresh before migrating.")
            if self.active_id or row["state"] == "running":
                raise ValueError("Wait for the running operation before migrating.")
            if row["options"]["engine"] != "sby":
                raise ValueError("Select a guided SBY session to migrate to FormalMC.")
            self.session(row)
            key_path = Path.home() / ".ucagent/formal-manifest.key"
            if key_path.is_symlink() or not key_path.is_file():
                raise ValueError("Source SBY signing key is absent; run SBY Check on this execution host.")
            if os.name != "nt" and key_path.stat().st_mode & 0o077:
                raise ValueError("Source SBY signing key requires owner-only permissions.")
            try:
                files, report = convert_sby_to_formalmc(Path(row["workspace"]), row["options"]["dut"], key_path.read_bytes())
            except FormalConversionError:
                raise
            except (ValueError, OSError, KeyError, TypeError) as exc:
                raise FormalConversionError("Invalid current SBY inputs/evidence: " + redact_text(str(exc))[:1200]) from exc
            # A second click on the same input version opens the existing target.
            for receipt in row.get("migrations", {}).values():
                if (receipt["input_sha256"], receipt["source_records_sha256"]) != (report["input_sha256"], report["source_records_sha256"]):
                    continue
                project = self.store.get_project(receipt["project_id"])
                if project and project["source_root"] == receipt["workspace"]:
                    verify_converted_project(receipt["workspace"], receipt["manifest_sha256"])
                    row.setdefault("migrations", {})[request.request_id] = receipt
                    self.persist(row, "formalmc_migration_reused", (request.request_id, request_hash))
                    return {"migration": receipt, "project": self.runtime.project_public(project), "session": self.public(row)}
            parent = resolve_within(self.runtime.workspace, self.runtime.state_dir / "formal_projects", must_exist=False)
            parent.mkdir(parents=True, exist_ok=True)
            project_id = uuid4().hex
            destination = parent / project_id
            temporary = Path(tempfile.mkdtemp(prefix=".migration-", dir=parent))
            published = False
            try:
                for name, content in files.items():
                    target = resolve_within(temporary, name, must_exist=False)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                manifest = json.loads(files["conversion_inputs.json"])
                for name in manifest["include_dirs"]:
                    resolve_within(temporary, name, must_exist=False).mkdir(parents=True, exist_ok=True)
                config = load_project_config(temporary).model_dump(mode="json")
                verify_converted_project(temporary)
                source_root = Path(row["workspace"])
                if (sha256_file(source_root / "formal_out/.formal_records.yaml") != report["source_records_sha256"]
                        or any(sha256_file(source_root / name) != value for name, value in report["source_dependency_sha256"].items())):
                    raise FormalConversionError("Source changed before migration publication; retry stable inputs")
                receipt = {"project_id": project_id, "workspace": str(destination),
                           "source_session_id": identifier, "source_project_id": row["options"]["project_id"],
                           "source_revision": request.revision, "input_sha256": report["input_sha256"],
                           "source_records_sha256": report["source_records_sha256"],
                           "manifest_sha256": hashlib.sha256(files["conversion_inputs.json"]).hexdigest(),
                           "conversion_status": report["conversion_status"], "property_count": len(report["properties"]),
                           "initial_verification_status": "not_run", "formalmc_acceptance": "not_run"}
                # Project registration and source receipt commit together. On failure
                # only this unpublished snapshot is removed; source evidence is untouched.
                with self.store._lock, self.store._connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if self.load(identifier)["revision"] != request.revision:
                        raise ValueError("Session revision changed during migration; retry.")
                    temporary.rename(destination)
                    db.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)",
                               (project_id, row["options"]["dut"] + " FormalMC", str(destination),
                                json.dumps(config, ensure_ascii=False, sort_keys=True), time.time(), time.time()))
                    db.execute("INSERT INTO formal_project_migrations VALUES (?,?,?)", (project_id, identifier, request.request_id))
                    row.setdefault("migrations", {})[request.request_id] = receipt
                    self.persist(row, "formalmc_migrated", (request.request_id, request_hash), connection=db)
                published = True
            finally:
                if not published:
                    shutil.rmtree(temporary, ignore_errors=True)
                    if destination.exists():
                        shutil.rmtree(destination)
            project = self.store.get_project(project_id)
            return {"migration": receipt, "project": self.runtime.project_public(project), "session": self.public(row)}

    def action(self, identifier, request):
        """Serialize mutations, deduplicate retries and run expensive Check actions asynchronously."""
        with self.lock:
            row = self.load(identifier)
            request_hash = digest(request.model_dump())
            with self.store._connection() as db:
                prior = db.execute("SELECT request_hash FROM formal_session_operations WHERE session_id=? AND request_id=?", (identifier, request.request_id)).fetchone()
            if prior:
                if prior[0] != request_hash:
                    raise ValueError("request_id was reused with different action parameters.")
                return self.public(row)
            if request.action == "cancel" and self.active_id == identifier:
                # Stopping is safe across progress updates; never make an operator
                # race a busy Agent's checkpoint revisions just to cancel it.
                self.live[identifier].cancel()
                row["cancel_requested"] = True
                self.persist(row, "cancel_requested", (request.request_id, request_hash))
                return self.public(row)
            if request.revision != row["revision"]:
                raise ValueError("Session revision changed; refresh before submitting the action.")
            if self.active_id:
                raise ValueError("Another stage operation is running; mutation is locked until it stops.")
            if row["state"] == "paused" and request.action != "resume":
                raise ValueError("Resume the session before modifying its stage work.")
            session = self.session(row)
            if request.action != "reopen" and request.stage_index != session.stage_manager.stage_index:
                raise ValueError("The current stage changed; refresh the session.")
            if request.action in {"approve", "reject", "journal"} and not request.journal.strip():
                raise ValueError("A non-empty review reason or journal is required.")
            if request.action == "save" and row["view"]["all_completed"]:
                raise ValueError("Reopen a reached stage before editing a completed session.")
            if request.action == "agent":
                from ucagent.server.formal_agent import common_agent_profile
                common_agent_profile(self.runtime)
                if session.stage_manager.all_completed:
                    raise ValueError("Reopen a reached stage before starting another Agent turn.")
                session.cancelled.clear()
            if request.action in {"agent", "check", "complete"}:
                session.cancelled.clear()
                row.update(state="running", execution_status="running", verification_status="unknown", cancel_requested=False)
                self.persist(row, "operation_started", (request.request_id, request_hash))
                self.active_id = identifier
                self.worker = threading.Thread(target=self.execute, args=(identifier, request), daemon=True)
                self.worker.start()
            else:
                session.cancelled.clear()
                if request.action == "save":
                    row["last_result"] = session.write(request.path, request.content, request.sha256)
                elif request.action == "reopen":
                    session.rewind(request.stage_index)
                    row["state"] = "ready"
                    row["last_result"] = {"reopened": request.stage_index, "downstream_progress_invalidated": True}
                elif request.action in {"pause", "cancel"}:
                    row["state"] = "paused"
                elif request.action == "resume":
                    row["state"] = "ready"
                else:
                    row["last_result"] = session.act(request.action, request.stage_index, request.journal)
                row.update(checkpoint=session.checkpoint(), view=session.projection())
                if request.action in {"save", "reopen"}:
                    row["verification_status"] = "unknown"
                    row.pop("evidence", None)
                self.persist(row, request.action, (request.request_id, request_hash))
            return self.public(row)

    def execute(self, identifier, request):
        """Finish one native operation and preserve errors, failures and inconclusive evidence distinctly."""
        session = self.live[identifier]
        status = "completed"
        try:
            if request.action == "agent":
                from ucagent.server.formal_agent import FormalAgentTurn
                result = FormalAgentTurn(self, identifier, request).run()
                status = result["agent_execution_status"]
            else:
                for checker in session.stage_manager.get_current_stage().checker:
                    if hasattr(checker, "event_callback"):
                        checker.event_callback = lambda event: self.record_tool_event(identifier, event)
                result = session.act(request.action, request.stage_index, request.journal, request.timeout)
        except Exception as exc:
            status = "error"
            result = {"error_code": "STAGE_OPERATION_ERROR", "error": redact_text(str(exc))[:2000], "next_action": "Inspect the stage inputs and retry Check; no stage completion was inferred."}
        with self.lock:
            try:
                row = self.load(identifier)
                cancelled = row.get("cancel_requested", False)
                if cancelled:
                    # A late cancellation must not publish a concurrently completed
                    # stage as approved progress. Retain files, restore the prior gate.
                    session = FormalSession(row["workspace"], row["options"], row["checkpoint"])
                    self.live[identifier] = session
                    current_stage = session.stage_manager.get_current_stage()
                    if current_stage:
                        current_stage._hum_check_passed = None
                row.update(checkpoint=session.checkpoint(), view=session.projection(), last_result=result,
                           execution_status="cancelled" if cancelled else status,
                           state="paused" if cancelled else "completed" if session.stage_manager.all_completed else "ready")
                # Lifecycle completion is not a DUT pass. Only verified tool
                # evidence can promote the verification conclusion.
                if cancelled or request.action != "agent":
                    row["verification_status"] = "unknown"
                    row.pop("evidence", None)
                if request.action == "agent" and row.get("agent"):
                    row["agent"]["status"] = "cancelled" if cancelled else status
                if not cancelled and status == "completed" and request.action != "agent":
                    stage = session.stage_manager.stages[request.stage_index]
                    for checker in stage.checker:
                        evidence = getattr(checker, "last_evidence", None)
                        if evidence is not None:
                            row["capabilities"]["tool_acceptance"] = "real_signed_execution"
                            row["verification_status"] = evidence["verification_status"]
                            row["evidence"] = evidence
                self.persist(row, "operation_finished")
            except Exception as exc:
                # Preserve the last authenticated checkpoint if publication fails.
                # Discard the live manager so a retry cannot inherit unsaved progress.
                self.live.pop(identifier, None)
                row = self.load(identifier)
                row.update(state="paused", execution_status="error", verification_status="unknown",
                           last_result={"error_code": "STAGE_CHECKPOINT_ERROR", "error": redact_text(str(exc))[:2000],
                                        "next_action": "Preserve the artifacts and inspect the storage error. Resume and re-check only after restoring writable storage."})
                row.pop("evidence", None)
                self.persist(row, "checkpoint_error")
            finally:
                self.active_id = None

    def record_tool_event(self, identifier, event):
        """Persist already-redacted JobRunner events for reconnectable GUI log output."""
        payload = {"type": "eda." + event["type"], "job": event.get("run_id"),
                   "time": event.get("timestamp"), "payload": event.get("payload", {})}
        with self.store._connection() as db:
            db.execute("INSERT INTO formal_session_events(session_id,payload) VALUES (?,?)", (identifier, json.dumps(payload)))

    def read(self, identifier, path):
        """Expose bounded authoring text and record native reference-read evidence."""
        with self.lock:
            if self.active_id:
                raise ValueError("Wait for the running operation before changing reference-read state.")
            row = self.load(identifier)
            session = self.session(row)
            result = session.read(path)
            row.update(checkpoint=session.checkpoint(), view=session.projection())
            self.persist(row, "file_read")
            result["session"] = self.public(row)
            return result

    def files(self, identifier):
        """List bounded authoring files and actual artifacts without following symlinks."""
        row = self.load(identifier)
        root = self.root / identifier
        items = []
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(".") and not (Path(current) / d).is_symlink()]
            for name in names:
                path = Path(current) / name
                if path.is_symlink() or (name.startswith(".") and name != ".formal_records.yaml"):
                    continue
                items.append({"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size})
                if len(items) == 2000:
                    return {"items": items, "truncated": True}
        return {"items": items, "truncated": False}

    def events(self, identifier, after):
        """Return a replayable monotonically ordered event page for GUI reconnection."""
        self.load(identifier)
        with self.store._connection() as db:
            rows = db.execute("SELECT sequence,payload FROM formal_session_events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT 100", (identifier, after)).fetchall()
        return {"items": [{"sequence": row[0], **json.loads(row[1])} for row in rows]}

    def shutdown(self):
        """Cancel an active checker without deleting any work or claiming it completed."""
        if self.active_id:
            self.live[self.active_id].cancel()
        if self.worker:
            self.worker.join(timeout=5)


def register_formal_session_routes(router, runtime, check_csrf):
    """Expose structured stage actions with the platform's authentication and CSRF guard."""
    service = runtime.formal_sessions

    def invoke(function, *args):
        """Map invalid or conflicting session operations to actionable HTTP errors."""
        try:
            return function(*args)
        except KeyError as exc:
            raise HTTPException(404, "Formal session not found.") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)[:2000]) from exc

    @router.get("/formal-sessions")
    def sessions():
        """List durable shared-Agent and human-reviewed formal sessions."""
        return {"items": invoke(service.list)}

    @router.get("/formal-sessions/capabilities")
    def capabilities(engine: Literal["formalmc", "sby"] = "formalmc"):
        """Report explicit syntax, COI, vacuity and liveness differences."""
        return service.capabilities(engine)

    @router.post("/formal-sessions", dependencies=[Depends(check_csrf)])
    def create(body: SessionCreate):
        """Initialize an isolated original-stage workflow, not a native EDA-only run."""
        return invoke(service.create, body)

    @router.get("/formal-sessions/{identifier}")
    def detail(identifier: str):
        """Read the last persisted actual stage projection."""
        return service.public(invoke(service.load, identifier))

    @router.post("/formal-sessions/{identifier}/actions", dependencies=[Depends(check_csrf)])
    def action(identifier: str, body: SessionAction):
        """Apply one bounded, revision-checked lifecycle operation."""
        return invoke(service.action, identifier, body)

    @router.post("/formal-sessions/{identifier}/migrate-formalmc", dependencies=[Depends(check_csrf)])
    def migrate_formalmc(identifier: str, body: FormalMigrationRequest):
        """Create a linked FormalMC project from fixed SBY inputs."""
        from ucagent.eda.formalmc_conversion import FormalConversionError
        try:
            return invoke(service.migrate_formalmc, identifier, body)
        except HTTPException as exc:
            cause = exc.__cause__
            if isinstance(cause, FormalConversionError):
                raise HTTPException(409, cause.diagnostic) from cause
            raise

    @router.get("/formal-sessions/{identifier}/files")
    def files(identifier: str):
        """List sources, editable documents and generated evidence."""
        return invoke(service.files, identifier)

    @router.post("/formal-sessions/{identifier}/read", dependencies=[Depends(check_csrf)])
    def read(identifier: str, path: str = Query(max_length=400)):
        """Read a text file and record genuine access for the reference-file gate."""
        return invoke(service.read, identifier, path)

    @router.get("/formal-sessions/{identifier}/events")
    def events(identifier: str, after: int = Query(default=0, ge=0)):
        """Resume an event stream by sequence without re-executing operations."""
        return invoke(service.events, identifier, after)

    @router.get("/formal-sessions/{identifier}/records")
    def records(identifier: str):
        """Provide the current authoring record as JSON, not as trusted verification evidence."""
        with service.lock:
            if service.active_id:
                raise HTTPException(409, "Wait for the running stage before reading authoring records.")
            row = invoke(service.load, identifier)
            session = invoke(service.session, row)
            path = session.file_path("formal_out/.formal_records.yaml")
            if path.stat().st_size > 200000:
                raise HTTPException(413, "Authoring record exceeds the editor limit.")
            return yaml.safe_load(path.read_text(encoding="utf-8"))

    @router.get("/formal-sessions/{identifier}/artifact")
    def artifact(identifier: str, path: str = Query(max_length=400)):
        """Hash the selected actual file before a streaming, integrity-checked download."""
        with service.lock:
            if service.active_id == identifier:
                raise HTTPException(409, "Wait for the active operation before downloading its artifacts.")
            row = invoke(service.load, identifier)
            session = invoke(service.session, row)
            target = invoke(session.file_path, path)
            if not target.is_file():
                raise HTTPException(404, "Artifact not found.")
            return {"id": identifier, "name": target.name, "size": target.stat().st_size, "sha256": sha256_file(target),
                    "is_directory": False, "download_path": "/formal-sessions/" + identifier + "/download?" + urlencode({"path": path})}

    @router.get("/formal-sessions/{identifier}/download")
    def download(identifier: str, path: str = Query(max_length=400)):
        """Stream a real file; disallow hidden control state and path traversal."""
        with service.lock:
            row = invoke(service.load, identifier)
            session = invoke(service.session, row)
            target = invoke(session.file_path, path)
            if not target.is_file():
                raise HTTPException(404, "Artifact not found.")
            return FileResponse(target, filename=target.name)
