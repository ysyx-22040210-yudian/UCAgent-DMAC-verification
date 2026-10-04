"""Provision an explicitly approved gateway credential on its Linux execution host.

The credential is read from a no-echo terminal, never an argument, environment
dump or project file. Existing unrelated settings remain intact. This utility
does not start Claude or transmit any engineering input.
"""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    """Never forward a gateway credential to a different redirect destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Require the administrator to correct the configured URL explicitly."""
        return None


def private_settings(path):
    """Read a regular owner-only settings file without following a leaf symlink."""
    if not path.exists() and not path.is_symlink():
        return {}, None
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077 or metadata.st_size > 1024**2):
            raise ValueError("Existing settings must be a regular owner-only file (0600)")
        raw = stream.read(1024**2 + 1)
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("env", {}), dict):
        raise ValueError("Existing settings and env must be JSON objects")
    return value, hashlib.sha256(raw).digest()


def gateway_models(base_url, credential):
    """Inspect model identifiers with a bounded authenticated GET, withholding errors."""
    request = Request(base_url + "/v1/models", headers={
        "Authorization": "Bearer " + credential, "anthropic-version": "2023-06-01",
        "User-Agent": "claude-cli/2.1.263", "Accept": "application/json"})
    try:
        with build_opener(NoRedirect).open(request, timeout=20) as response:
            raw = response.read(1024**2 + 1)
            if len(raw) > 1024**2:
                return {"status": "response_too_large"}
            payload = json.loads(raw)
        models = payload.get("data", []) if isinstance(payload, dict) else []
        names = [item["id"] for item in models if isinstance(item, dict)
                 and isinstance(item.get("id"), str) and len(item["id"]) <= 200]
        return {"status": "reachable", "models": sorted(set(names))[:200]}
    except HTTPError as exc:
        return {"status": "http_error", "http_status": exc.code}
    except (URLError, TimeoutError, ValueError, OSError):
        return {"status": "unavailable"}


def main():
    """Atomically configure only the executing user's approved HTTPS gateway."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--use-stored-credential", action="store_true")
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run as the non-root Claude execution identity")
    parsed = urlsplit(args.base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise SystemExit("Use an HTTPS gateway origin without credentials, query or API suffix")
    base_url = args.base_url.rstrip("/")
    user_root = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    settings_dir = user_root / ".claude"
    if settings_dir.is_symlink():
        raise SystemExit("Claude settings directory must not be a symlink")
    settings_dir.mkdir(mode=0o700, exist_ok=True)
    metadata = settings_dir.stat()
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SystemExit("Claude settings directory must be owner-only (0700)")
    target = settings_dir / "settings.json"
    settings, before = private_settings(target)
    environment = dict(settings.get("env", {}))
    if args.use_stored_credential:
        if environment.get("ANTHROPIC_BASE_URL") != base_url:
            raise SystemExit("Stored credential belongs to a different gateway")
        credential = environment.get("ANTHROPIC_AUTH_TOKEN", "")
    else:
        if not os.isatty(0):
            raise SystemExit("Credential entry requires a no-echo terminal")
        credential = getpass.getpass("Gateway credential (input hidden): ")
    if (not isinstance(credential, str) or not 16 <= len(credential) <= 4096
            or any(char.isspace() or ord(char) < 32 for char in credential)):
        raise SystemExit("Invalid credential shape; value withheld")
    if "ANTHROPIC_API_KEY" in environment:
        raise SystemExit("Remove the conflicting API-key configuration explicitly before configuring a gateway token")
    environment.update({"ANTHROPIC_BASE_URL": base_url, "ANTHROPIC_AUTH_TOKEN": credential,
                        "DISABLE_AUTOUPDATER": "1", "DISABLE_UPDATES": "1",
                        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    settings["env"] = environment
    if args.model:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", args.model):
            raise SystemExit("Model must be a single bounded identifier")
        settings["model"] = args.model
        # Make the literal gateway ID visible; do not disguise it as an
        # Anthropic model or silently choose a fallback model on failure.
        environment.update({"ANTHROPIC_CUSTOM_MODEL_OPTION": args.model,
                            "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME": args.model,
                            "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION": "Explicitly selected gateway model"})
    descriptor, temporary = tempfile.mkstemp(prefix=".provider-", dir=str(settings_dir))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if private_settings(target)[1] != before:
            raise SystemExit("Settings changed concurrently; no configuration was replaced")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({"configured": True, "settings": str(target), "mode": "0600",
                      "base_url": base_url, "model": settings.get("model"), "credential": "withheld"}))
    if args.list_models:
        print(json.dumps(gateway_models(base_url, credential)))


if __name__ == "__main__":
    main()
