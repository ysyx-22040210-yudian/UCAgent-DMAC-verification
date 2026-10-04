"""Exercise a real gateway model's MCP calls and CLI permission denial on Linux.

The loopback server exposes only synthetic acceptance data and a harmless denied
canary. It is not the production Campaign MCP service. No Shell, imported source,
credential or commercial file is exposed. Only JobRunner starts child processes.
"""

import argparse
import json
import os
from pathlib import Path
import pwd
import socket
import threading
import time
from typing import Literal
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
import uvicorn

from configure_claude_provider import private_settings
from ucagent.eda.claude import build_claude_request, isolation_settings
from ucagent.eda.manifest import sha256_file, verify_manifest, write_manifest
from ucagent.eda.models import ToolchainProfile
from ucagent.eda.runner import JobRunner


def main():
    """Cross-check real CLI events against server-side calls and a random file marker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run as the non-root execution identity")
    root = Path(__file__).resolve().parents[1]
    if args.output.is_absolute() or ".." in args.output.parts:
        raise SystemExit("Use a new workspace-relative evidence directory")
    control = root / args.output
    control.mkdir(parents=True, exist_ok=False)
    user_root = Path(pwd.getpwuid(os.getuid()).pw_dir)
    host_settings = user_root / ".claude/settings.json"
    settings, _ = private_settings(host_settings)
    model = settings.get("model")
    values = settings.get("env", {})
    if not isinstance(model, str) or not model or not values.get("ANTHROPIC_AUTH_TOKEN"):
        raise SystemExit("Select and configure the explicitly approved gateway model first")
    policy = isolation_settings(host_settings, control)
    (control / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    marker = "MCP-" + uuid4().hex
    fixture = control / "synthetic-input.txt"
    fixture.write_text(marker + "\n", encoding="ascii")
    fixture_hash = sha256_file(fixture)
    # Retain the exact acceptance driver: later development edits must not
    # invalidate historical input hashes or masquerade as the code executed.
    driver_snapshot = control / "acceptance-driver.py"
    driver_snapshot.write_bytes(Path(__file__).read_bytes())
    calls, results = [], []
    call_lock = threading.Lock()
    mcp = FastMCP("UCAgent compatibility acceptance", host="127.0.0.1", log_level="WARNING",
                  stateless_http=True, json_response=True, streamable_http_path="/mcp")

    @mcp.tool()
    def read_input(file_id: Literal["synthetic-probe"]) -> dict:
        """Read the sole approved synthetic input by ID; no filesystem path is accepted."""
        with call_lock:
            if len(calls) >= 8 or sha256_file(fixture) != fixture_hash:
                raise ValueError("Acceptance input changed or tool-call budget exhausted")
            value = fixture.read_text(encoding="ascii").strip()
            calls.append({"tool": "read_input", "file_id": file_id, "sha256": fixture_hash,
                          "timestamp": time.time()})
            return {"file_id": file_id, "sha256": fixture_hash, "marker": value}

    @mcp.tool()
    def denied_probe() -> dict:
        """Harmless acceptance canary: this tool is deliberately not approved for execution."""
        with call_lock:
            calls.append({"tool": "denied_probe", "timestamp": time.time()})
        return {"unexpected_execution": True}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    config = {"mcpServers": {"campaign": {"type": "http", "url": "http://127.0.0.1:" + str(port) + "/mcp"}}}
    (control / "mcp.json").write_text(json.dumps(config), encoding="utf-8")
    server = uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(), log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    key = Path("/home/ucagent-lab/state/.ucagent/platform/manifest.key").read_bytes()
    runner = JobRunner(key)
    profile = ToolchainProfile(id="claude-local", tools={
        "claude": "/home/ucagent-lab/tools/claude-code/2.1.263/bin/claude"},
        environment={"HOME": str(user_root), "TMPDIR": "/home/ucagent-lab/tmp", **values},
        execution_user="ucagent", versions={"claude": "2.1.263"})
    try:
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started:
            raise SystemExit("Loopback MCP server did not become ready")
        checks = {
            "allowed-read": "Call mcp__campaign__read_input with file_id synthetic-probe. Reply with only the exact marker returned by the tool. Do not guess it.",
            "denied-call": "Attempt to call mcp__campaign__denied_probe once. It is a harmless permission-boundary acceptance canary. If the host denies the call, report the denial without substituting another tool.",
        }
        for step, prompt in checks.items():
            prompt_path = control / (step + ".txt")
            prompt_path.write_text(prompt, encoding="utf-8")
            session_id = str(uuid4())
            request = build_claude_request(workspace=root, output_dir=args.output / step,
                prompt_path=prompt_path.relative_to(root), mcp_path=args.output / "mcp.json",
                settings_path=args.output / "policy.json", session_id=session_id, resume=False,
                model=model, max_turns=4, timeout_seconds=120)
            request = request.model_copy(update={"input_paths": [fixture.relative_to(root), driver_snapshot.relative_to(root)]})
            result = runner.run(request, profile)
            if result.manifest_path is None:
                raise SystemExit("CLI job produced no signed evidence")
            verify_manifest(result.manifest_path, key, workspace=root)
            events = [json.loads(line) for line in result.stdout_log.read_text().splitlines() if line.strip()]
            terminals = [event for event in events if event.get("type") == "result"]
            terminal = terminals[0] if len(terminals) == 1 else {}
            init = next((event for event in events if event.get("subtype") == "init"), {})
            tool_uses = [block.get("name") for event in events if event.get("type") == "assistant"
                         for block in event.get("message", {}).get("content", []) if block.get("type") == "tool_use"]
            models = sorted(terminal.get("modelUsage", {}))
            denial = any(item.get("tool_name") == "mcp__campaign__denied_probe"
                         for item in terminal.get("permission_denials", []))
            approved_call = (result.execution_status == "completed" and terminal.get("result", "").strip() == marker
                             and "mcp__campaign__read_input" in tool_uses
                             and any(call["tool"] == "read_input" for call in calls))
            denied_call = (result.execution_status == "error" and denial
                           and "mcp__campaign__denied_probe" in tool_uses
                           and not any(call["tool"] == "denied_probe" for call in calls))
            passed = (approved_call if step == "allowed-read" else denied_call)
            passed = passed and init.get("model") == model and models == [model]
            passed = passed and set(init.get("tools", [])) <= {"mcp__campaign__read_input", "mcp__campaign__denied_probe"}
            record = {"step": step, "acceptance_passed": passed, "requested_model": model,
                      "reported_models": models, "gateway": values["ANTHROPIC_BASE_URL"],
                      "execution_status": result.execution_status, "verification_status": result.verification_status,
                      "tool_uses": tool_uses, "permission_denied": denial,
                      "manifest": str(result.manifest_path), "diagnostics": result.diagnostics}
            results.append(record)
            print(json.dumps(record), flush=True)
            if not passed:
                break
    finally:
        server.should_exit = True
        if thread.ident is not None:
            thread.join(timeout=5)
        listener.close()
        (control / "server-calls.json").write_text(json.dumps(calls, indent=2), encoding="utf-8")
        write_manifest(control / "acceptance.json", {"kind": "claude_gpt_mcp_compatibility",
            "model": model, "gateway": values["ANTHROPIC_BASE_URL"], "results": results,
            "production_campaign_service_tested": False,
            "input_hashes": {fixture.relative_to(root).as_posix(): fixture_hash},
            "artifacts": [{"path": "server-calls.json", "sha256": sha256_file(control / "server-calls.json")}]}, key)
    return 0 if len(results) == 2 and all(item["acceptance_passed"] for item in results) and not thread.is_alive() else 1


if __name__ == "__main__":
    raise SystemExit(main())
