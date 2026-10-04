"""Sequential workflow driver that aggregates independent execution and verification states."""

from __future__ import annotations

from typing import Any, Callable, Iterable
from uuid import uuid4

from pydantic import Field

from .models import ExecutionStatus, RunRequest, RunResult, StrictModel, ToolchainProfile, VerificationStatus
from .runner import CancellationSignal, JobRunner


class WorkflowResult(StrictModel):
    """Summarize an ordered compile, regression, coverage, or formal workflow."""

    workflow_id: str
    execution_status: ExecutionStatus
    verification_status: VerificationStatus
    jobs: list[RunResult] = Field(default_factory=list)


WorkflowEventCallback = Callable[[dict[str, Any]], None]
WorkflowJobResultCallback = Callable[[int, RunRequest, RunResult], None]


class WorkflowDriver:
    """Execute adapter-generated requests in order and stop on infrastructure failure."""

    def __init__(self, runner: JobRunner):
        """Bind the driver to the sole component authorized to start subprocesses."""

        self._runner = runner

    def run(
        self,
        requests: Iterable[RunRequest],
        profile: ToolchainProfile,
        *,
        workflow_id: str | None = None,
        on_event: WorkflowEventCallback | None = None,
        on_job_result: WorkflowJobResultCallback | None = None,
        cancel_event: CancellationSignal | None = None,
    ) -> WorkflowResult:
        """Run requests sequentially and publish each result before starting its successor."""

        identifier = workflow_id or uuid4().hex
        request_values = list(requests)
        if not request_values:
            raise ValueError("a workflow requires at least one adapter-generated RunRequest")
        jobs: list[RunResult] = []
        for job_index, request in enumerate(request_values):
            def forward(event: dict[str, Any]) -> None:
                """Add stable workflow/job coordinates to a runner event."""

                if on_event is None:
                    return
                on_event({**event, "workflow_id": identifier, "job_index": job_index, "job_run_id": request.run_id})

            result = self._runner.run(request, profile, on_event=forward, cancel_event=cancel_event)
            jobs.append(result)
            if on_job_result is not None:
                on_job_result(job_index, request, result)
            if result.execution_status != ExecutionStatus.COMPLETED:
                break
        return WorkflowResult(
            workflow_id=identifier,
            execution_status=self._aggregate_execution(jobs),
            verification_status=self._aggregate_verification(jobs),
            jobs=jobs,
        )

    @staticmethod
    def _aggregate_execution(results: list[RunResult]) -> ExecutionStatus:
        """Select the most severe terminal execution state across completed jobs."""

        if not results:
            return ExecutionStatus.COMPLETED
        priority = {
            ExecutionStatus.COMPLETED: 0,
            ExecutionStatus.QUEUED: 1,
            ExecutionStatus.RUNNING: 2,
            ExecutionStatus.CANCELLED: 3,
            ExecutionStatus.TIMEOUT: 4,
            ExecutionStatus.ERROR: 5,
        }
        return max((result.execution_status for result in results), key=priority.__getitem__)

    @staticmethod
    def _aggregate_verification(results: list[RunResult]) -> VerificationStatus:
        """Aggregate conclusions without reporting a partial workflow as passed."""

        conclusions = [result.verification_status for result in results if result.verification_status != VerificationStatus.UNKNOWN]
        incomplete = any(
            result.execution_status != ExecutionStatus.COMPLETED for result in results
        )
        if incomplete and VerificationStatus.FAILED not in conclusions:
            return VerificationStatus.INCONCLUSIVE
        if not conclusions:
            return VerificationStatus.UNKNOWN
        priority = {
            VerificationStatus.PASSED: 1,
            VerificationStatus.INCONCLUSIVE: 2,
            VerificationStatus.FAILED: 3,
            VerificationStatus.UNKNOWN: 0,
        }
        return max(conclusions, key=priority.__getitem__)
