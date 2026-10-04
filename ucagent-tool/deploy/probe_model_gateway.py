"""Bounded read-only gateway diagnostics, with credentials confined to process memory.

Compare the selected model across API protocols without changing any service,
model, host settings or project. Only synthetic text is sent; no tools execute.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    """Prevent authenticated requests from following a server-selected redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Return the original redirect as an error rather than forwarding credentials."""
        return None


def redact(value, credential):
    """Withhold the known credential and common key/token patterns before recording text."""
    text = str(value).replace(credential, "[REDACTED]")
    text = re.sub(r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[^\s\"<>]+)", "[REDACTED]", text)
    return text[:1500]


def response_summary(raw, content_type, credential, selected_model):
    """Keep bounded error evidence or model metadata, never a raw response dump."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return {"non_json_excerpt": redact(raw.decode("utf-8", errors="replace"), credential)[:500]}
    if not isinstance(data, dict):
        return {"json_shape": type(data).__name__}
    if "error" in data and data["error"]:
        error = data["error"]
        if isinstance(error, dict):
            return {"error": {key: redact(error[key], credential) for key in ("type", "code", "message", "param") if key in error}}
        return {"error": redact(error, credential)}
    if isinstance(data.get("data"), list):
        models = [item.get("id") for item in data["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)]
        return {"models_count": len(models), "selected_model_listed": selected_model in models,
                "related_model_ids": [redact(name, credential) for name in models if "5.4" in name][:30]}
    out = {key: redact(data[key], credential) for key in ("id", "object", "type", "model", "status", "stop_reason") if key in data}
    texts = [item.get("text", "") for item in data.get("content", []) if isinstance(item, dict) and item.get("type") == "text"]
    for item in data.get("output", []):
        if isinstance(item, dict):
            texts.extend(part.get("text", "") for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text")
    for choice in data.get("choices", []):
        if isinstance(choice, dict):
            texts.append((choice.get("message") or {}).get("content") or "")
    out["text"] = redact("".join(texts), credential)[:120]
    if isinstance(data.get("usage"), dict):
        out["usage"] = {key: value for key, value in data["usage"].items() if isinstance(value, (int, float))}
    return out


def main():
    """Run one small, explicitly selected request matrix and emit sanitized JSON lines."""
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--settings", type=Path)
    choice.add_argument("--connection-stdin", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=("matrix", "models", "models_no_auth", "messages", "responses", "responses_array", "chat"), default="matrix")
    parser.add_argument("--timeout", type=int, default=20, choices=range(5, 61))
    parser.add_argument("--proxy", choices=("direct", "environment"), default="direct")
    args = parser.parse_args()
    try:
        if args.connection_stdin:
            connection = json.loads(sys.stdin.read(1024 * 1024))
        else:
            from configure_claude_provider import private_settings
            settings, _ = private_settings(args.settings)
            env = settings.get("env", {})
            connection = {"base_url": env.get("ANTHROPIC_BASE_URL"), "model": settings.get("model"),
                          "credential": env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")}
        base_url, model, credential = (connection[key] for key in ("base_url", "model", "credential"))
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/") or not isinstance(credential, str) or not 16 <= len(credential) <= 4096
                or any(char.isspace() for char in credential) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model)):
            raise ValueError()
    except Exception:
        raise SystemExit("Cannot load a valid explicit HTTPS connection; credential and settings contents withheld.") from None
    base_url = base_url.rstrip("/")
    opener = build_opener(NoRedirect, ProxyHandler({}) if args.proxy == "direct" else ProxyHandler())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    prompt = "Reply with exactly OK."
    messages = [{"role": "user", "content": prompt}]
    cases = [("models", "/v1/models", None, "bearer"),
             ("messages", "/v1/messages", {"model": model, "max_tokens": 64, "messages": messages, "stream": False}, "bearer"),
             ("messages_x_api_key", "/v1/messages", {"model": model, "max_tokens": 64, "messages": messages, "stream": False}, "x-api-key"),
             ("responses", "/v1/responses", {"model": model, "input": prompt, "max_output_tokens": 64, "stream": False}, "bearer"),
             ("chat", "/v1/chat/completions", {"model": model, "messages": messages, "max_completion_tokens": 64, "stream": False}, "bearer")]
    if args.only == "models_no_auth":
        cases = [("models_no_auth", "/v1/models", None, "none")]
    elif args.only == "responses_array":
        cases = [("responses_array", "/v1/responses", {"model": model, "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                  "max_output_tokens": 64, "stream": False}, "bearer")]
    with args.output.open("x", encoding="utf-8") as report:
        def emit(row):
            """Flush only a sanitized result so tests remain visible during network waits."""
            text = json.dumps(row, ensure_ascii=False)
            assert credential not in text
            report.write(text + "\n")
            report.flush()
            print(text, flush=True)

        try:
            addresses = sorted(set(item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)))
        except OSError as exc:
            addresses = [type(exc).__name__]
        emit({"kind": "context", "utc": datetime.now(timezone.utc).isoformat(), "platform": platform.system(),
              "base_url": base_url, "model": model, "proxy_mode": args.proxy, "resolved_addresses": addresses,
              "timeout_seconds": args.timeout, "automatic_retries": 0, "source_data_sent": False,
              "proxy_environment_present": any(os.environ.get(key) for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"))})
        for name, path, payload, auth in cases:
            if args.only != "matrix" and name != args.only:
                continue
            headers = {"User-Agent": "claude-cli/2.1.263", "Accept": "application/json", "Content-Type": "application/json"}
            if auth != "none":
                headers["Authorization" if auth == "bearer" else "x-api-key"] = "Bearer " + credential if auth == "bearer" else credential
            if path == "/v1/messages":
                headers["anthropic-version"] = "2023-06-01"
            request = Request(base_url + path, data=json.dumps(payload).encode() if payload else None, headers=headers)
            started = time.monotonic()
            row = {"kind": "request", "case": name, "path": path, "auth": auth, "utc": datetime.now(timezone.utc).isoformat()}
            try:
                try:
                    response = opener.open(request, timeout=args.timeout)
                except HTTPError as exc:
                    response = exc
                with response:
                    row.update(http_status=response.code, content_type=response.headers.get("content-type", ""))
                    row["response_headers"] = {key: redact(response.headers[key], credential) for key in
                        ("server", "request-id", "x-request-id", "x-oneapi-request-id", "cf-ray", "retry-after") if key in response.headers}
                    raw = response.read(1024 * 1024 + 1)
                    row["body_bytes"] = len(raw)
                    row["body_sha256"] = hashlib.sha256(raw).hexdigest()
                    row["truncated"] = len(raw) > 1024 * 1024
                    row["response"] = response_summary(raw[:1024 * 1024], row["content_type"], credential, model)
            except (URLError, OSError, TimeoutError) as exc:
                row.update(transport_error=type(exc).__name__, detail=redact(str(exc), credential))
            row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            emit(row)


if __name__ == "__main__":
    main()
