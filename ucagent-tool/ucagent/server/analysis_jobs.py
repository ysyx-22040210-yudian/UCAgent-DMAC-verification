"""Persist adapter-owned auxiliary jobs through the platform's sole JobRunner."""

import threading

from ucagent.eda.security import redact_data


def start_analysis_job(runtime, *, project_id, profile, request, kind):
    """Run one trusted request with existing events, attempts, artifacts and cancellation.

    This function accepts a constructed RunRequest from platform code, never
    command arrays or environment dictionaries supplied over an API.
    """
    persisted = runtime.store.create_run(project_id=project_id, workflow=kind, adapter=kind,
        request={"toolchain": profile.id, "kind": kind, "job_run_id": request.run_id})
    run_id = persisted["run_id"]
    runtime.store.replace_run_stages(run_id, [{"id": kind, "name": kind,
        "enabled": True, "execution_status": "queued", "verification_status": "unknown"}])
    safe_command = redact_data({"argv": request.command.argv, "job_run_id": request.run_id},
                               tuple(profile.environment.values()))
    job_id = runtime.store.create_job(run_id=run_id, stage_id=kind, kind=kind, command=safe_command)
    attempt_id = runtime.store.create_attempt(job_id=job_id, number=1, execution_status="queued",
        manifest_path=str(request.workspace / request.output_dir / "manifest.json"))
    cancel = threading.Event()

    def execute():
        """Publish normalized results atomically; no LLM text can set verification pass."""
        runtime.store.update_run_status(run_id, execution_status="running")

        def on_event(event):
            """Persist bounded runner events on the same resumable run event stream."""
            if event["type"] == "running":
                runtime.store.update_job_status(job_id, execution_status="running")
                runtime.store.update_attempt(attempt_id, execution_status="running")
                runtime.store.update_stage_execution(run_id, kind, "running")
            runtime.store.append_event(run_id, event["type"], {"job_id": job_id, **event.get("payload", {})})

        try:
            result = runtime._runner.run(request, profile, on_event=on_event, cancel_event=cancel)
            data = result.model_dump(mode="json")
            merged = runtime._merge_results(run_id, [data])
            runtime.store.commit_job_result(run_id=run_id, job_id=job_id, attempt_id=attempt_id,
                execution_status=result.execution_status.value, verification_status=result.verification_status.value,
                result=data, manifest_path=str(result.manifest_path) if result.manifest_path else None,
                normalized_result=merged)
            runtime.store.update_stage_execution(run_id, kind, result.execution_status.value,
                                                 result.verification_status.value)
            runtime.store.update_run_status(run_id, execution_status=result.execution_status.value,
                verification_status=result.verification_status.value,
                diagnostic=(result.diagnostics or [None])[0])
        except Exception:
            # Do not leak profile contents through exception repr or a traceback.
            diagnostic = {"error_code": "analysis_job_error", "error": "Analysis evidence could not be published.",
                          "next_action": "Inspect the job manifest and retry as a new bounded query."}
            runtime.store.finish_job(job_id, execution_status="error", verification_status="unknown", result={"diagnostics": [diagnostic]})
            runtime.store.update_attempt(attempt_id, execution_status="error", result={"diagnostics": [diagnostic]})
            runtime.store.update_stage_execution(run_id, kind, "error")
            runtime.store.update_run_status(run_id, execution_status="error", verification_status="unknown", diagnostic=diagnostic)
        finally:
            with runtime._runtime_lock:
                runtime._cancel_events.pop(run_id, None)
                runtime._threads.pop(run_id, None)

    thread = threading.Thread(target=execute, name="ucagent-analysis-" + run_id[:12], daemon=True)
    with runtime._runtime_lock:
        runtime._cancel_events[run_id] = cancel
        runtime._threads[run_id] = thread
    thread.start()
    return runtime.run_public(runtime.store.get_run(run_id))
