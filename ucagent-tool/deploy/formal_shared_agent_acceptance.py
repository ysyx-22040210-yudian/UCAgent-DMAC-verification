"""Real shared-Claude stage acceptance on a public Counter, never simulated AI output.

Approval is an explicitly labelled test-harness operation on this disposable
fixture, not human signoff of a user's design or commercial-engine acceptance.
"""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from ucagent.server.formal_sessions import SessionAction, SessionCreate
from ucagent.server.platform_main import create_platform_app


def main():
    """Exercise real AI authoring, native gates and exact-session resume for either engine."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", choices=("sby", "formalmc"), required=True)
    parser.add_argument("--toolchains", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run under the non-root execution identity.")
    args.output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / "acceptance/formal_gui_fixture"
    app = create_platform_app(workspace=args.output, import_roots=[source], toolchains_file=args.toolchains)
    runtime = app.state.platform_runtime
    service = runtime.formal_sessions
    project = runtime.store.create_project(name="Public Counter AI acceptance", source_root=str(source), config={})
    row = service.create(SessionCreate(project_id=project["project_id"], dut="Counter", engine=args.engine))
    report = {"engine": args.engine, "session": row["id"], "scope": "Real AI planning and native human gate; not engine proof acceptance", "turns": []}
    try:
        for step in range(2):
            row = service.load(row["id"])
            prompt = ("Prepare only the CURRENT planning stage from the real RTL and input documentation. Read its Guide_Doc and record template, edit planning, Check, set the journal and try Complete. Stop for human review; do not work on later stages."
                      if step == 0 else "The test harness has approved the planning stage. Call CurrentTips and Complete to advance it, then stop immediately at stage 1. Do not modify planning or start preparing stage 1.")
            request = SessionAction(action="agent", revision=row["revision"], stage_index=row["view"]["current_index"],
                request_id=uuid4().hex, timeout=600, max_turns=24, prompt=prompt)
            service.action(row["id"], request)
            while service.worker.is_alive():
                service.worker.join(timeout=5)
            row = service.load(row["id"])
            result = {"execution_status": row["execution_status"], "verification_status": row["verification_status"],
                      "stage": row["view"]["current_index"], "agent": row.get("agent"), "result": row["last_result"]}
            report["turns"].append(result)
            (args.output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"step": step, "execution_status": row["execution_status"], "stage": result["stage"],
                              "tool_calls": (row.get("agent") or {}).get("tool_calls"), "result": row["last_result"]}), flush=True)
            assert row["execution_status"] == "completed", row["last_result"]
            assert row["verification_status"] == "unknown"
            if step == 0:
                current = service.live[row["id"]].stage_manager.get_current_stage()
                assert row["view"]["current_index"] == 0 and current.is_hmcheck_needed()
                assert row["view"]["stages"][0]["details"]["check_pass"]
                service.action(row["id"], SessionAction(action="approve", revision=row["revision"], stage_index=0,
                    request_id=uuid4().hex, journal="AUTOMATED ACCEPTANCE FIXTURE ONLY: test the engineer approval API after a real passing planning Check."))
            else:
                assert row["view"]["current_index"] == 1
                assert report["turns"][0]["agent"]["session_id"] == row["agent"]["session_id"]
        report["passed"] = True
        (args.output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    main()
