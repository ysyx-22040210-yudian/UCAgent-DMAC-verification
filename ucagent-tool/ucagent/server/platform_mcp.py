"""Embedded MCP surface backed by the commercial verification platform runtime.

The tools in this module are deliberately thin projections of the same typed
runtime used by ``/api/v1``.  They do not accept shell command strings and they
do not create a second execution path around :class:`JobRunner`.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ucagent.server.api_mcp import project_fastmcp_tools
from ucagent.server.api_platform import (
    CounterexampleReplayStartRequest,
    PlatformRuntime,
    ProjectCreateRequest,
    RunCreateRequest,
    _stage_action,
)
from ucagent.server.platform_workbench import preview_run


def _collection(items: list[Any]) -> dict[str, Any]:
    """Return the stable collection envelope shared with the HTTP API."""

    return {"items": items, "count": len(items)}


class PlatformMcpService:
    """Own the in-process FastMCP server and its public protocol metadata."""

    def __init__(self, runtime: PlatformRuntime, *, host: str, port: int) -> None:
        """Register typed platform tools against one authoritative runtime."""

        self.runtime = runtime
        self.host = host
        self.port = port
        self.server = FastMCP(
            "UCAgent Verification Platform",
            instructions=(
                "Manage structured hardware-verification projects and runs. "
                "All EDA execution is validated by the platform JobRunner; "
                "arbitrary shell commands are not accepted."
            ),
            host=host,
            port=port,
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
        )
        self._register_tools()
        self.app = self.server.streamable_http_app()
        self.tools = project_fastmcp_tools(self.server)

    @property
    def is_running(self) -> bool:
        """Report that the protocol application is mounted in the host process."""

        return True

    def url(self) -> str:
        """Return the exact streamable-HTTP endpoint mounted by the platform."""

        return f"http://{self.host}:{self.port}/mcp"

    def _require_run(self, run_id: str) -> dict[str, Any]:
        """Load one persisted run or raise an actionable MCP tool error."""

        run = self.runtime.store.get_run(run_id)
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        return run

    def _register_tools(self) -> None:
        """Register the bounded read and mutation operations exposed over MCP."""

        runtime = self.runtime
        require_run = self._require_run

        @self.server.tool()
        def list_capabilities() -> dict[str, Any]:
            """Read feature-specific acceptance and configuration without inferring license readiness."""
            return runtime.campaigns.capabilities()

        @self.server.tool()
        def list_campaigns() -> dict[str, Any]:
            """Read complete design-verification tasks, blockers and immutable input versions."""
            return runtime.campaigns.list()

        @self.server.tool()
        def get_campaign(campaign_id: str) -> dict[str, Any]:
            """Read the full Campaign DAG and reviewable candidate patches."""
            return runtime.campaigns.get(campaign_id)

        @self.server.tool()
        def get_npi_query(query_id: str) -> dict[str, Any]:
            """Read validated NPI evidence; unavailable signals/bins remain explicit gaps."""
            return runtime.npi.get(query_id)

        @self.server.tool()
        def get_overview() -> dict[str, Any]:
            """Return run, queue, disk-gate, and toolchain health."""

            return runtime.overview()

        @self.server.tool()
        def preview_verification_run(request: RunCreateRequest) -> dict[str, Any]:
            """Check selected inputs, tools, licenses, disk, and jobs before creating a run."""

            return preview_run(runtime, request).model_dump(mode="json")

        @self.server.tool()
        def list_workflows() -> dict[str, Any]:
            """List complete workflow DAGs, including disabled stages and reasons."""

            return _collection(runtime.workflow_catalog())

        @self.server.tool()
        def list_toolchains() -> dict[str, Any]:
            """List administrator-configured toolchains without secret values."""

            return _collection(runtime.toolchains_public())

        @self.server.tool()
        def probe_toolchain(toolchain_id: str) -> dict[str, Any]:
            """Run binary, version, and license-smoke checks for one toolchain."""

            if toolchain_id not in runtime._profiles:
                raise ValueError(f"toolchain not found: {toolchain_id}")
            return runtime.probe_toolchain(toolchain_id)

        @self.server.tool()
        def list_projects() -> dict[str, Any]:
            """List imported projects and their validated structured configuration."""

            return _collection(
                [runtime.project_public(item) for item in runtime.store.list_projects()]
            )

        @self.server.tool()
        def get_project(project_id: str) -> dict[str, Any]:
            """Return one imported project by its stable identifier."""

            project = runtime.store.get_project(project_id)
            if project is None:
                raise ValueError(f"project not found: {project_id}")
            return runtime.project_public(project)

        @self.server.tool()
        def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
            """Import an allowed server directory using the project schema."""

            return runtime.create_project(request)

        @self.server.tool()
        def list_runs(project_id: str | None = None) -> dict[str, Any]:
            """List persisted runs, optionally restricted to one project."""

            return _collection(
                [runtime.run_public(item) for item in runtime.store.list_runs(project_id)]
            )

        @self.server.tool()
        def get_run(run_id: str) -> dict[str, Any]:
            """Return execution and verification status for one persisted run."""

            return runtime.run_public(require_run(run_id))

        @self.server.tool()
        def create_run(request: RunCreateRequest) -> dict[str, Any]:
            """Start a typed simulation, UVM, UnityTest, or formal workflow."""

            return runtime.create_run(request)

        @self.server.tool()
        def cancel_run(run_id: str) -> dict[str, Any]:
            """Request process-tree cancellation for an active run."""

            require_run(run_id)
            return runtime.cancel_run(run_id)

        @self.server.tool()
        def list_run_stages(run_id: str) -> dict[str, Any]:
            """List all enabled and disabled stages captured for one run."""

            require_run(run_id)
            return _collection(runtime.run_stages_public(run_id))

        @self.server.tool()
        def list_run_jobs(run_id: str) -> dict[str, Any]:
            """List persisted EDA jobs and attempts for one run."""

            require_run(run_id)
            return _collection(runtime.jobs_public(run_id))

        @self.server.tool()
        def list_run_results(
            run_id: str,
            category: Literal["tests", "coverage", "properties", "issues", "artifacts"],
        ) -> dict[str, Any]:
            """List one normalized result category for a persisted run."""

            require_run(run_id)
            if category == "artifacts":
                return _collection(runtime.store.list_artifacts(run_id))
            return _collection(runtime.store.list_result_rows(run_id, category))

        @self.server.tool()
        def list_counterexample_replays(source_run_id: str) -> dict[str, Any]:
            """List evidence-backed dynamic replays for one formal run."""

            require_run(source_run_id)
            return runtime.reconcile_counterexample_replays(source_run_id)

        @self.server.tool()
        def start_counterexample_replay(
            source_run_id: str,
            request: CounterexampleReplayStartRequest,
        ) -> dict[str, Any]:
            """Start an explicit UVM or UnityTest replay of a signed counterexample."""

            require_run(source_run_id)
            return runtime.start_counterexample_replay(source_run_id, request)

        @self.server.tool()
        def approve_stage(stage_id: str, note: str = "") -> dict[str, Any]:
            """Approve a declared pending human gate using a compound stage ID."""

            return _stage_action(runtime, stage_id, "approve", note)

        @self.server.tool()
        def reject_stage(stage_id: str, note: str = "") -> dict[str, Any]:
            """Reject a declared pending human gate using a compound stage ID."""

            return _stage_action(runtime, stage_id, "reject", note)

        @self.server.tool()
        def retry_stage(stage_id: str, note: str = "") -> dict[str, Any]:
            """Create a new run from the persisted request for a terminal stage."""

            return _stage_action(runtime, stage_id, "retry", note)


__all__ = ["PlatformMcpService"]
