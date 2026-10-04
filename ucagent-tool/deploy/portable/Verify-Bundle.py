"""Verify offline package file hashes without changing, installing or downloading files."""

import argparse
import hashlib
import json
from pathlib import Path


def verify(root):
    """Check the release inventory and report bounded corruption/missing-file diagnostics."""
    root = Path(root).resolve(strict=True)
    inventory = json.loads((root / "SHA256SUMS.json").read_text(encoding="utf-8"))
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("Package inventory is empty or malformed")
    failures = []
    for name, expected in inventory.items():
        try:
            path = (root / name).resolve(strict=True)
            path.relative_to(root)
            if not path.is_file():
                raise ValueError("Not a regular file")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError("SHA-256 mismatch")
        except (OSError, ValueError) as exc:
            failures.append({"path": name, "error": str(exc)[:300]})
            if len(failures) >= 20:
                break
    for name, target in json.loads((root / "SYMLINKS.json").read_text(encoding="utf-8")).items():
        path = root / name
        try:
            path.resolve(strict=True).relative_to(root)
            if not path.is_symlink() or str(path.readlink()) != target:
                raise ValueError("Symlink target changed")
        except (OSError, ValueError) as exc:
            failures.append({"path": name, "error": str(exc)[:300]})
            if len(failures) >= 20:
                break
    return {"passed": not failures, "inventory_files": len(inventory), "failures": failures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    outcome = verify(parser.parse_args().bundle)
    print(json.dumps(outcome, indent=2))
    raise SystemExit(0 if outcome["passed"] else 1)
