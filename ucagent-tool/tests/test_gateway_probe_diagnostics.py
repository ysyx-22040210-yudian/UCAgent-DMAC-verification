"""Ensure diagnostic-only gateway reports retain errors without credential disclosure."""

import importlib.util
import json
from pathlib import Path


def test_probe_error_redaction_and_model_list_are_bounded():
    """Error evidence is safe to share and a model listing is not treated as successful inference."""
    source = Path(__file__).parents[1] / "deploy/probe_model_gateway.py"
    spec = importlib.util.spec_from_file_location("probe_model_gateway", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    credential = "sk-fixture-only-not-a-real-credential"
    raw = json.dumps({"error": {"type": "model_not_found", "message": "No channel: " + credential}}).encode()
    summary = module.response_summary(raw, "application/json", credential, "gpt-5.4")
    assert summary["error"]["type"] == "model_not_found"
    assert credential not in json.dumps(summary)
    raw = json.dumps({"data": [{"id": "gpt-5.4"}]}).encode()
    summary = module.response_summary(raw, "application/json", credential, "gpt-5.4")
    assert summary == {"models_count": 1, "selected_model_listed": True, "related_model_ids": ["gpt-5.4"]}
    assert module.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://another.invalid") is None
    assert len(module.redact("x" * 3000, credential)) == 1500
