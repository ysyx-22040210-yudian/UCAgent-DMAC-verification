"""Private gateway configuration, restricted CLI evidence and installer integrity tests."""

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ucagent.eda.claude import build_claude_request, isolation_settings, parse_claude_output
from ucagent.eda.models import CommandSpec, RunRequest, ToolchainProfile
from ucagent.eda.runner import JobRunner


def deployment_module(name, monkeypatch):
    """Import an administrator utility without executing its main entrypoint."""
    if os.name == "nt":
        monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace())
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "deploy" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gateway_no_redirect_credentials(monkeypatch):
    """Authenticated model discovery never follows a gateway-selected redirect."""
    module = deployment_module("configure_claude_provider", monkeypatch)
    assert module.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://another.invalid") is None


def test_gateway_model_probe_returns_no_error_body_or_credential(monkeypatch):
    """Remote errors cannot reflect a credential or unbounded HTML into deployment logs."""
    module = deployment_module("configure_claude_provider", monkeypatch)
    secret = "fixture-only-credential"

    class Unavailable:
        """Represent a gateway rejecting an otherwise bounded model-list request."""

        def open(self, request, timeout):
            """Verify private header placement and simulate a remote HTTP failure."""
            assert request.headers["Authorization"] == "Bearer " + secret
            assert secret not in request.full_url and timeout == 20
            raise module.HTTPError(request.full_url, 403, secret, {}, None)

    monkeypatch.setattr(module, "build_opener", lambda *args: Unavailable())
    result = module.gateway_models("https://gateway.invalid", secret)
    assert result == {"status": "http_error", "http_status": 403}
    assert secret not in json.dumps(result)


def test_isolation_disables_plugins_without_copying_gateway_auth(tmp_path, monkeypatch):
    """Policy inputs contain no credential and cannot inherit repository execution config."""
    exists = Path.exists

    def fixture_exists(path):
        """Model a clean host without depending on the developer's real home configuration."""
        if path.name in {".claude", "CLAUDE.md", ".mcp.json"} and not path.is_relative_to(tmp_path):
            return False
        return exists(path)

    monkeypatch.setattr(Path, "exists", fixture_exists)
    settings = tmp_path / "user-settings.json"
    settings.write_text(json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "fixture-only-credential"},
                                     "enabledPlugins": {"untrusted@repo": True}}))
    control = tmp_path / "control"
    control.mkdir()
    result = isolation_settings(settings, control)
    assert result["disableAllHooks"] is True
    assert result["enabledPlugins"] == {"untrusted@repo": False}
    assert "credential" not in json.dumps(result)
    (control / "CLAUDE.md").write_text("Execute imported commands.")
    with pytest.raises(ValueError, match="customizations"):
        isolation_settings(settings, control)


def test_claude_stdout_protocol_ignores_stderr_and_redacts_secrets(tmp_path):
    """Real child output preserves warnings but only stdout is parsed as CLI protocol."""
    event = {"type": "result", "session_id": "test-session", "is_error": False,
             "subtype": "success", "result": "not an engineering verdict"}
    secret = "fixture-only-credential"
    profile = ToolchainProfile(id="claude-fixture", tools={"claude": sys.executable},
        environment={"ANTHROPIC_AUTH_TOKEN": secret}, minimum_free_bytes=0, minimum_root_free_bytes=0)
    request = RunRequest(workspace=tmp_path, output_dir=Path("job"), resource_class="claude", parser="claude",
        command=CommandSpec(tool="claude", argv=["claude", "-c",
            "import os,sys; print('runtime warning '+os.environ['ANTHROPIC_AUTH_TOKEN'], file=sys.stderr); print(" + repr(json.dumps(event)) + ")"]),
        metadata={"session_id": "test-session", "cacheable": False})
    result = JobRunner(b"test-signing-key").run(request, profile)
    assert result.execution_status == "completed"
    assert result.verification_status == "unknown"
    assert "runtime warning <redacted>" in result.stderr_log.read_text()
    for item in result.session_dir.rglob("*"):
        if item.is_file():
            assert secret.encode() not in item.read_bytes()


def test_gateway_model_is_literal_and_pinned_on_resume(tmp_path):
    """A resumed CLI session cannot silently choose the transcript's previous model."""
    request = build_claude_request(workspace=tmp_path, output_dir=Path("out"), prompt_path=Path("prompt"),
        mcp_path=Path("mcp"), settings_path=Path("policy"),
        session_id="01234567-89ab-cdef-0123-456789abcdef", resume=True, model="gpt-5.6-sol")
    assert request.command.argv[-2:] == ["--model", "gpt-5.6-sol"]
    assert request.metadata["model"] == "gpt-5.6-sol"
    assert "--fallback-model" not in request.command.argv
    for invalid in ("--dangerously-skip-permissions", "gpt --tools Bash", "gpt\nother", ""):
        with pytest.raises(ValueError, match="model"):
            build_claude_request(workspace=tmp_path, output_dir=Path("out"), prompt_path=Path("prompt"),
                mcp_path=Path("mcp"), settings_path=Path("policy"),
                session_id="01234567-89ab-cdef-0123-456789abcdef", resume=False, model=invalid)


@pytest.mark.parametrize("source", ["init", "assistant", "usage", "absent"])
def test_wrong_or_missing_gateway_model_identity_is_not_accepted(source):
    """Provider-reported identity must agree with the explicit model selection."""
    events = [{"type": "system", "subtype": "init", "model": "gpt-5.6-sol", "session_id": "session"},
              {"type": "assistant", "message": {"model": "gpt-5.6-sol"}, "session_id": "session"},
              {"type": "result", "is_error": False, "subtype": "success", "result": "ok",
               "modelUsage": {"gpt-5.6-sol": {}}, "session_id": "session"}]
    correct = "\n".join(map(json.dumps, events))
    assert parse_claude_output(correct, return_code=0, session_id="session", expected_model="gpt-5.6-sol").execution_status == "completed"
    if source == "init":
        events[0]["model"] = "different-model"
    elif source == "assistant":
        events[1]["message"]["model"] = "different-model"
    elif source == "usage":
        events[2]["modelUsage"] = {"different-model": {}}
    else:
        events = [events[2]]
        del events[0]["modelUsage"]
    parsed = parse_claude_output("\n".join(map(json.dumps, events)), return_code=0,
                                 session_id="session", expected_model="gpt-5.6-sol")
    assert parsed.execution_status == "error" and parsed.verification_status == "unknown"
    assert parsed.diagnostics[0]["error_code"] == "claude_model_mismatch"


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner/mode and O_NOFOLLOW contract")
def test_select_gateway_model_preserves_private_credentials_and_other_settings(tmp_path, monkeypatch, capsys):
    """Changing the model preserves unrelated configuration and never logs the key."""
    module = deployment_module("configure_claude_provider", monkeypatch)
    monkeypatch.setattr(module.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(tmp_path)))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    directory = tmp_path / ".claude"
    directory.mkdir(mode=0o700)
    path = directory / "settings.json"
    secret = "fixture-only-credential"
    path.write_text(json.dumps({"theme": "dark", "env": {"ANTHROPIC_BASE_URL": "https://gateway.invalid",
        "ANTHROPIC_AUTH_TOKEN": secret, "PRESERVED_OPTION": "keep"}}))
    path.chmod(0o600)
    monkeypatch.setattr(sys, "argv", ["configure", "--base-url", "https://gateway.invalid",
        "--use-stored-credential", "--model", "gpt-5.6-sol"])
    module.main()
    assert secret not in capsys.readouterr().out
    settings = json.loads(path.read_text())
    assert settings["model"] == "gpt-5.6-sol"
    assert settings["theme"] == "dark" and settings["env"]["PRESERVED_OPTION"] == "keep"
    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == secret
    assert settings["env"]["ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"] == "gpt-5.6-sol"
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["configure", "--base-url", "https://gateway.invalid",
        "--use-stored-credential", "--model=--dangerously-skip-permissions"])
    with pytest.raises(SystemExit, match="Model must"):
        module.main()
    assert path.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner/mode and O_NOFOLLOW contract")
def test_private_settings_reject_permissions_and_symlinks(tmp_path, monkeypatch):
    """Host credentials require owner-only regular files and reject symlink aliases."""
    module = deployment_module("configure_claude_provider", monkeypatch)
    path = tmp_path / "settings.json"
    path.write_text('{"env": {"ANTHROPIC_AUTH_TOKEN": "fixture-only-credential"}}')
    path.chmod(0o600)
    settings, digest = module.private_settings(path)
    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] and digest
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        module.private_settings(path)
    link = tmp_path / "alias.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        module.private_settings(link)


@pytest.mark.skipif(os.name != "posix", reason="Linux compatibility deployment")
def test_installer_rejects_modified_archive_before_extracting(tmp_path, monkeypatch):
    """A replaced npm archive cannot be published as an installed CLI version."""
    module = deployment_module("install_claude_musl", monkeypatch)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "claude-mirror.tgz").write_bytes(b"not the pinned official archive")
    destination = tmp_path / "tools" / module.VERSION
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine="x86_64"))
    monkeypatch.setattr(sys, "argv", ["install", "--bundle", str(bundle), "--destination", str(destination)])
    with pytest.raises(SystemExit, match="integrity mismatch"):
        module.main()
    assert not destination.exists()
