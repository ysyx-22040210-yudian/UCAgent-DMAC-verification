"""Record real Claude CLI compatibility, gateway and explicit-resume evidence.

All child processes use JobRunner. Authentication is loaded only from the
execution identity's private host configuration and registered for redaction.
The prompts contain no RTL, credentials, commercial documentation or libraries.
"""

import argparse
import json
import os
from pathlib import Path
import pwd
from uuid import uuid4

from configure_claude_provider import private_settings
from ucagent.eda.claude import build_claude_request, isolation_settings, validate_cli_capabilities
from ucagent.eda.models import CommandSpec, RunRequest, ToolchainProfile
from ucagent.eda.runner import JobRunner


def main():
    """Run bounded probes and print paths/statuses only, never credential values."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("probe", "gateway", "resume"), default="probe")
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run as ucagent, not root")
    root = Path(__file__).resolve().parents[1]
    if args.output.is_absolute() or ".." in args.output.parts:
        raise SystemExit("Use a new workspace-relative output directory")
    control = root / args.output
    control.mkdir(parents=True, exist_ok=False)
    user_root = Path(pwd.getpwuid(os.getuid()).pw_dir)
    profile = ToolchainProfile(id="claude-local", tools={
        "claude": "/home/ucagent-lab/tools/claude-code/2.1.263/bin/claude"},
        environment={"HOME": str(user_root), "TMPDIR": "/home/ucagent-lab/tmp"},
        execution_user="ucagent", versions={"claude": "2.1.263"})
    runner = JobRunner(Path("/home/ucagent-lab/state/.ucagent/platform/manifest.key").read_bytes())
    for flag in ("--version", "--help"):
        request = RunRequest(workspace=root, output_dir=args.output / flag[2:], resource_class="claude",
            command=CommandSpec(tool="claude", argv=["claude", flag], cwd=Path("{SESSION_DIR}"), timeout_seconds=30),
            output_limit_bytes=256 * 1024, memory_limit_bytes=2 * 1024**3,
            metadata={"adapter": "claude_probe", "cacheable": False})
        result = runner.run(request, profile)
        print(json.dumps({"step": flag, "execution_status": result.execution_status,
                          "manifest": str(result.manifest_path), "diagnostics": result.diagnostics}), flush=True)
        if result.execution_status != "completed":
            return 1
        text = result.stdout_log.read_text(encoding="utf-8")
        if flag == "--version":
            print(json.dumps({"cli_version": text.strip()[:100]}), flush=True)
        elif validate_cli_capabilities(text):
            print(json.dumps({"missing_flags": validate_cli_capabilities(text)}), flush=True)
            return 1
    if args.mode == "probe":
        return 0
    host_settings = user_root / ".claude/settings.json"
    settings, _ = private_settings(host_settings)
    model = settings.get("model")
    if not isinstance(model, str) or not model:
        raise SystemExit("Select an explicit gateway model before authenticated acceptance")
    values = settings.get("env", {})
    if not values.get("ANTHROPIC_AUTH_TOKEN") or not values.get("ANTHROPIC_BASE_URL"):
        raise SystemExit("Configure an explicitly approved gateway before the authenticated probe")
    profile = profile.model_copy(update={"environment": {**profile.environment, **values}})
    policy = isolation_settings(host_settings, control)
    (control / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    (control / "mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    session_id = str(uuid4())
    token = "UCAgent-session-" + uuid4().hex[:12]
    for resumed in (False, True) if args.mode == "resume" else (False,):
        step = "resume" if resumed else "first-turn"
        prompt = ("What exact session marker did I give you previously? Reply with only that marker."
                  if resumed else "Remember this session marker: " + token + ". Reply with only that marker.")
        prompt_path = control / (step + ".txt")
        prompt_path.write_text(prompt, encoding="utf-8")
        request = build_claude_request(workspace=root, output_dir=args.output / step,
            prompt_path=prompt_path.relative_to(root), mcp_path=args.output / "mcp.json",
            settings_path=args.output / "policy.json", session_id=session_id, resume=resumed,
            timeout_seconds=120, max_turns=2, model=model)
        result = runner.run(request, profile)
        record = {"step": step, "execution_status": result.execution_status,
                  "verification_status": result.verification_status, "session_id": session_id,
                  "requested_model": model, "gateway": values["ANTHROPIC_BASE_URL"],
                  "manifest": str(result.manifest_path), "diagnostics": result.diagnostics}
        if result.execution_status == "completed":
            events = [json.loads(line) for line in result.stdout_log.read_text().splitlines() if line.strip()]
            terminal = next(item for item in events if item.get("type") == "result")
            record["marker_matches"] = terminal.get("result", "").strip() == token
            record["reported_usage"] = terminal.get("usage")
            record["reported_models"] = sorted(terminal.get("modelUsage", {}))
            record["reported_cost_usd"] = terminal.get("total_cost_usd")
            record["billing_verified"] = False
        print(json.dumps(record), flush=True)
        if result.execution_status != "completed" or not record.get("marker_matches"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
