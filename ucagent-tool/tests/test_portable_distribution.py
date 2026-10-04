"""Portable distribution hash gates and read-only integrity checker contracts."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from deploy.build_portable import build


def test_builder_refuses_existing_release(tmp_path):
    """An existing release is never replaced, even when supplied new inputs."""
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / "runtime.tgz"
    archive.write_bytes(b"invalid")
    destination = tmp_path / "release"
    destination.mkdir()
    (destination / "keep").write_text("user-owned")
    with pytest.raises(FileExistsError):
        build(source, archive, destination, runtime_support=archive)
    assert (destination / "keep").read_text() == "user-owned"


def test_builder_rejects_unverified_upstream_bytes(tmp_path):
    """Validate upstream archive bytes before unpacking or creating staging directories."""
    source = tmp_path / "source"
    (source / "deploy/portable").mkdir(parents=True)
    (source / "deploy/portable/runtime.lock.json").write_text(json.dumps({"size": 6, "sha256": "0" * 64}))
    archive = tmp_path / "runtime.tgz"
    archive.write_bytes(b"tamper")
    with pytest.raises(ValueError, match="SHA-256"):
        build(source, archive, tmp_path / "releases/output", runtime_support=archive)
    assert not (tmp_path / "releases").exists()


@pytest.mark.parametrize("case", ["valid", "modified", "missing", "escaping"])
def test_bundle_inventory_fails_closed(tmp_path, case):
    """Read-only inventory validation detects corrupted, missing and escaping files."""
    spec = importlib.util.spec_from_file_location("verify_bundle", Path(__file__).resolve().parents[1] / "deploy/portable/Verify-Bundle.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    (tmp_path / "tool").write_bytes(b"expected")
    (tmp_path / "SYMLINKS.json").write_text("{}")
    name = "../outside" if case == "escaping" else "tool"
    (tmp_path / "SHA256SUMS.json").write_text(json.dumps({name: hashlib.sha256(b"expected").hexdigest()}))
    if case == "modified":
        (tmp_path / "tool").write_bytes(b"changed")
    elif case == "missing":
        (tmp_path / "tool").unlink()
    outcome = verifier.verify(tmp_path)
    assert outcome["passed"] == (case == "valid")
