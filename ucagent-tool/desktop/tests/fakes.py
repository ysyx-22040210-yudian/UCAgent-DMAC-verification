"""Canonical platform fixtures served over real loopback HTTP for desktop contract tests."""

from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.parse import urlsplit


PROJECT = {"id": "project-1", "name": "Adder laboratory", "path": "/work/adder",
           "design": {"top": "tb_top", "sources": ["adder.sv", "tb_top.sv"], "filelists": [], "include_dirs": [], "defines": [], "parameters": {"WIDTH": 8}},
           "methodology": "systemverilog", "workflow_family": "simulation", "toolchain": "vcs-profile",
           "simulation": {"suites": [{"name": "ut", "level": "UT", "tests": ["ut_test"], "seeds": [11]}, {"name": "it", "level": "IT", "tests": ["it_test"], "seeds": [29]}]}, "formal": {}}
PROJECT["run_defaults"] = {"project_id": PROJECT["id"], "family": "simulation", "methodology": "systemverilog", "authoring_mode": "guided", "toolchain": "vcs-profile", "design": deepcopy(PROJECT["design"]),
                           "simulation": {"simulator": "vcs", "uvm_version": "1.2", "suites": ["UT"], "tests": ["native"], "unitytest_tests": [], "seeds": [11], "coverage": [], "waveform": "none", "plusargs": []}, "formal": None}
STAGES = [{"id": "run-1:wf:gate", "name": "gate", "description": "Review signed evidence", "parent_id": None, "enabled": True, "requires_human_approval": True, "approval_status": "pending", "execution_status": "completed", "verification_status": "failed"},
          {"id": "run-1:wf:optional", "name": "formal", "description": "Formal optional", "parent_id": "run-1:wf:gate", "enabled": False, "disabled_reason": "Not selected", "children": []}]
RUN = {"id": "run-1", "project_id": PROJECT["id"], "project_name": PROJECT["name"], "family": "simulation", "methodology": "systemverilog", "execution_status": "completed", "verification_status": "passed", "request": PROJECT["run_defaults"], "stages": STAGES, "summary": {"jobs_total": 2, "jobs_finished": 2, "tests_passed": 1}, "created_at": "2026-09-06T00:00:00Z"}
TOOLCHAIN = {"id": "vcs-profile", "name": "VCS", "status": "degraded", "capabilities": [{"name": "vcs", "available": True, "license_status": "available"}, {"name": "vcf", "available": False, "license_status": "unavailable"}]}
WAVEFORM = b"fixture-fsdb\x00" * 4096
ARTIFACT = {"id": "artifact-1", "name": "wave.fsdb", "kind": "fsdb", "size": len(WAVEFORM), "sha256": hashlib.sha256(WAVEFORM).hexdigest(), "is_directory": False}


class PlatformServer:
    """Serve realistic canonical envelopes and record explicit desktop mutations."""

    def __init__(self):
        """Create isolated per-test state with no dependency on EDA or backend imports."""
        self.projects = [deepcopy(PROJECT)]
        self.runs = [deepcopy(RUN)]
        self.mutations = []
        self.requests = []
        self.preview_ready = True
        self.events = [{"sequence": 1, "type": "run.created", "message": "created", "timestamp": "now"}, {"sequence": 2, "type": "stage.approve", "message": "reviewed", "timestamp": "now"}]
        self.delay = 0
        self.error = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            """Respond with bounded deterministic fixtures using actual HTTP framing."""

            def log_message(self, fmt, *args):
                """Keep tests quiet without dumping submitted project configuration."""
                pass

            def do_GET(self):
                """Route one read-only API request through the fixture state."""
                self.route()

            def do_POST(self):
                """Record an explicitly requested mutation before returning its result."""
                self.route()

            def do_PUT(self):
                """Handle typed settings writes through the same fixture recorder."""
                self.route()

            def route(self):
                """Return canonical collections, streaming bytes, or explicit malformed boundaries."""
                path = urlsplit(self.path).path[len("/api/v1"):]
                outer.requests.append((self.command, self.path, self.headers.get("Origin")))
                if outer.delay:
                    time.sleep(outer.delay)
                if path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://example.invalid/")
                    self.end_headers()
                    return
                content = "application/json"
                status = 200
                if self.command != "GET":
                    raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    body = raw if self.headers.get("Content-Type", "").startswith("multipart/") else json.loads(raw) if raw else None
                    outer.mutations.append((self.command, path, body))
                if outer.error:
                    status, payload = outer.error
                elif path == "/malformed":
                    payload = b"{no-json"
                elif path == "/runs/preview":
                    sim = body.get("simulation") or {}
                    matrix = [{"test": name, "suite": (sim.get("suites") or [""])[0], "seed": seed} for name in sim.get("tests", []) for seed in sim.get("seeds", [])]
                    payload = {"ready": outer.preview_ready, "checks": [{"key": "disk", "status": "ready" if outer.preview_ready else "blocked", "message": "Observed disk gate"}], "jobs": [{"tool": "vcs", "command": ["vcs", "-f", "{WORKSPACE}/files.f"]}], "matrix": matrix, "job_count": len(matrix) + 1, "test_count": len(matrix)}
                elif path == "/projects":
                    if self.command == "POST":
                        project = {**deepcopy(PROJECT), "id": "project-2", "name": body["name"], "path": body["path"]}
                        project["run_defaults"]["project_id"] = project["id"]
                        outer.projects.insert(0, project)
                        payload = project
                    else:
                        payload = {"items": outer.projects}
                elif path == "/overview":
                    payload = {"projects": len(outer.projects), "runs": len(outer.runs), "active_jobs": 0, "queued_jobs": 0, "disk": {"free_bytes": 20 * 1024 ** 3, "gate_open": True}, "toolchains": [TOOLCHAIN]}
                elif path == "/toolchains":
                    payload = {"items": [TOOLCHAIN]}
                elif path.endswith("/probe"):
                    payload = TOOLCHAIN
                elif path == "/workflows":
                    payload = {"items": [{"id": "wf", "stages": STAGES, "name": "Workflow"}]}
                elif path == "/mcp":
                    payload = {"status": "healthy", "tools": [{"name": "list_runs", "description": "Read actual runs", "input_schema": {"type": "object"}}], "client_config": {"mcpServers": {}}}
                elif path == "/settings":
                    payload = {"minimum_free_disk_gb": 10, "max_concurrency": 1, "retention_days": None, "workspace_root": "/work"}
                elif path == "/runs":
                    if self.command == "POST":
                        run = {**deepcopy(RUN), "id": "run-" + str(len(outer.runs) + 1), "request": body, "project_id": body["project_id"], "verification_status": "failed" if "+INJECT_FAILURE" in (body.get("simulation") or {}).get("plusargs", []) else "passed"}
                        outer.runs.insert(0, run)
                        payload = run
                    else:
                        payload = {"items": outer.runs}
                elif path.startswith("/stages/"):
                    payload = {"approval_status": "approved", "retry_run": outer.runs[0] if path.endswith("/retry") else None}
                elif path.endswith("/counterexample-replays"):
                    payload = {"target_run_id": "run-1", "target_run": RUN} if self.command == "POST" else {"items": [], "reproduced": 0, "required_properties": []}
                elif path.endswith("/uvm/scaffold"):
                    payload = {"validation": {"valid": True}, "files": ["uvm/tb_top.sv"]}
                elif path.endswith("/files"):
                    payload = {"items": [{"name": "input.sv", "path": ".ucagent/uploads/input.sv"}]}
                elif path.startswith("/projects/"):
                    payload = next(project for project in outer.projects if project["id"] == path.split("/")[2])
                elif path.endswith("/download"):
                    content = "application/octet-stream"
                    payload = WAVEFORM
                elif path.endswith("/events"):
                    content = "text/event-stream"
                    payload = "".join("data: {}\n\n".format(json.dumps(event)) for event in outer.events).encode()
                elif path.startswith("/runs/"):
                    category = path.split("/")[-1]
                    run = next(run for run in outer.runs if run["id"] == path.split("/")[2])
                    if category == "cancel":
                        run["execution_status"] = "cancelled"
                        payload = run
                    elif category in ("jobs", "tests", "coverage", "properties", "issues", "artifacts", "stages"):
                        values = {"jobs": [{"id": "job-1", "name": "vcs", "execution_status": "completed", "command": ["vcs", "{WORKSPACE}/file.sv"]}],
                                  "tests": [{"id": "test-1", "name": "smoke", "seed": 11, "status": run["verification_status"], "uvm_errors": 0, "uvm_fatals": 0}],
                                  "coverage": [{"id": "coverage-1", "name": "line", "percentage": 10.3, "covered": None, "total": None}],
                                  "properties": [{"id": "property-1", "name": "p_correct", "status": "falsified", "counterexample_artifact_id": "artifact-1"}],
                                  "issues": [{"id": "issue-1", "title": "Assertion evidence"}], "artifacts": [ARTIFACT], "stages": STAGES}
                        payload = {"items": values[category]}
                    else:
                        payload = run
                else:
                    status, payload = 404, {"detail": "Unknown fixture route"}
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", content)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = "http://127.0.0.1:{}".format(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        """Release the isolated listening socket after test clients stop."""
        self.server.shutdown()
        self.server.server_close()
