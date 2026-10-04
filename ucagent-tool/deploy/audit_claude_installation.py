"""Audit private CLI installation integrity and secret-free probe evidence on Linux."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd

from configure_claude_provider import private_settings


def main():
    """Read the host credential privately and report only audit outcomes and paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run as the non-root execution identity")
    root = args.installation.resolve(strict=True)
    receipt = json.loads((root / "installation.json").read_text(encoding="utf-8"))
    mismatches = []
    for name, expected in receipt["files"].items():
        target = root / name
        if target.is_symlink() or not target.resolve(strict=True).is_relative_to(root):
            raise SystemExit("Installation receipt points outside its boundary")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            mismatches.append(name)
    user_root = Path(pwd.getpwuid(os.getuid()).pw_dir)
    settings, _ = private_settings(user_root / ".claude/settings.json")
    value = settings.get("env", {}).get("ANTHROPIC_AUTH_TOKEN")
    if not isinstance(value, str) or not value:
        raise SystemExit("No private credential is configured")
    secret = value.encode("utf-8")
    leaks, scanned = [], 0
    for directory in args.evidence:
        boundary = directory.resolve(strict=True)
        if not boundary.is_dir() or boundary == user_root:
            raise SystemExit("Supply specific evidence directories, never an entire home")
        for item in boundary.rglob("*"):
            if item.is_symlink() or not item.is_file():
                continue
            if item.suffix not in {".json", ".ndjson", ".jsonl", ".log", ".txt"}:
                continue
            if item.stat().st_size > 16 * 1024**2:
                raise SystemExit("Unexpectedly large probe evidence; audit separately")
            scanned += 1
            if secret in item.read_bytes():
                leaks.append(str(item))
    print(json.dumps({"version": receipt["version"], "installation_hash_mismatches": mismatches,
                      "evidence_files_scanned": scanned, "credential_leak_paths": leaks,
                      "credential_values_disclosed": False}))
    return 1 if mismatches or leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
