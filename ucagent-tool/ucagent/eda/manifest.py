"""Create and verify content-addressed, HMAC-signed EDA run manifests."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

from .models import Artifact
from .security import PathSecurityError, resolve_within


class ManifestVerificationError(ValueError):
    """Report malformed, unsigned, or content-inconsistent run evidence."""


def canonical_json(value: Mapping[str, Any]) -> bytes:
    """Serialize a manifest payload deterministically for signing and comparison."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    """Hash one regular file without loading large EDA artifacts into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_path(path: Path, *, exclude_paths: Iterable[Path] = ()) -> str:
    """Hash a file or directory tree using stable relative names and file digests."""

    resolved = path.resolve(strict=True)
    if resolved.is_symlink():
        raise PathSecurityError(f"symbolic links are not accepted as evidence: {path}")
    if resolved.is_file():
        return sha256_file(resolved)
    if not resolved.is_dir():
        raise ValueError(f"unsupported evidence path type: {path}")
    excluded = {item.as_posix().strip("/") for item in exclude_paths}
    digest = hashlib.sha256()
    for child in sorted(resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix()):
        relative = child.relative_to(resolved).as_posix()
        if any(relative == item or relative.startswith(item + "/") for item in excluded):
            continue
        if child.is_symlink():
            raise PathSecurityError(f"symbolic links are not accepted inside evidence directories: {child}")
        if child.is_dir():
            digest.update(f"D\0{relative}\0".encode("utf-8"))
        elif child.is_file():
            digest.update(f"F\0{relative}\0{sha256_file(child)}\0".encode("utf-8"))
    return digest.hexdigest()


def hash_workspace_inputs(
    workspace: Path,
    paths: Iterable[Path],
    *,
    exclude_paths: Iterable[Path] = (),
) -> dict[str, str]:
    """Hash declared inputs while omitting signed runner-owned output subtrees."""

    root = workspace.resolve(strict=True)
    exclusions = [resolve_within(root, item, must_exist=False) for item in exclude_paths]
    result: dict[str, str] = {}
    for relative in paths:
        resolved = resolve_within(root, relative, must_exist=True)
        relative_exclusions: list[Path] = []
        if resolved.is_dir():
            for exclusion in exclusions:
                try:
                    nested = exclusion.relative_to(resolved)
                except ValueError:
                    continue
                # An explicitly declared directory remains authoritative even if it
                # is also the broad namespace containing generated run outputs.
                if nested != Path("."):
                    relative_exclusions.append(nested)
        result[resolved.relative_to(root).as_posix()] = sha256_path(
            resolved,
            exclude_paths=relative_exclusions,
        )
    return dict(sorted(result.items()))


def compute_input_fingerprint(
    *,
    input_hashes: Mapping[str, str],
    command: list[str],
    toolchain_id: str,
    tool_version: str | None,
    metadata: Mapping[str, Any],
    command_context: Mapping[str, Any] | None = None,
) -> str:
    """Compute the exact cache key for reusable compilation or proof results."""

    payload = {
        "command": command,
        "command_context": dict(command_context or {}),
        "input_hashes": dict(sorted(input_hashes.items())),
        "metadata": metadata,
        "tool_version": tool_version,
        "toolchain_id": toolchain_id,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def collect_artifacts(run_id: str, session_dir: Path, paths: Iterable[Path]) -> list[Artifact]:
    """Collect each declared file or directory as exactly one normalized artifact record."""

    root = session_dir.resolve(strict=True)
    candidates: dict[str, Path] = {}
    for relative in paths:
        resolved = resolve_within(root, relative, must_exist=False)
        if not resolved.exists():
            continue
        if resolved.is_dir() or resolved.is_file():
            candidates[resolved.relative_to(root).as_posix()] = resolved
    artifacts: list[Artifact] = []
    for relative, path in sorted(candidates.items()):
        suffix = path.suffix.lower().lstrip(".")
        is_directory = path.is_dir()
        if is_directory:
            lowered = path.name.lower()
            if suffix == "vdb":
                kind = "coverage_database"
            elif any(token in lowered for token in ("proof", "formal", "session")):
                kind = "proof_directory"
            elif path == root:
                kind = "run_directory"
            else:
                kind = "directory"
        else:
            kind = {
                "fsdb": "waveform",
                "fst": "waveform",
                "vcd": "waveform",
                "vpd": "waveform",
                "log": "log",
                "json": "report",
                "html": "report",
                "xml": "report",
                "rpt": "report",
                "rep": "report",
            }.get(suffix, "file")
        exclusions = [Path("manifest.json")] if path == root else []
        if is_directory:
            size_bytes = sum(
                child.stat().st_size
                for child in path.rglob("*")
                if child.is_file()
                and not child.is_symlink()
                and not any(
                    child.relative_to(path).as_posix() == item.as_posix()
                    or child.relative_to(path).as_posix().startswith(item.as_posix() + "/")
                    for item in exclusions
                )
            )
            digest = sha256_path(path, exclude_paths=exclusions)
        else:
            size_bytes = path.stat().st_size
            digest = sha256_file(path)
        artifacts.append(
            Artifact(
                run_id=run_id,
                path=Path(relative),
                kind=kind,
                is_directory=is_directory,
                size_bytes=size_bytes,
                sha256=digest,
                media_type=(
                    "application/x-directory"
                    if is_directory
                    else mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                ),
                hash_excludes=exclusions,
            )
        )
    return artifacts


def sign_manifest(payload: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    """Attach an HMAC-SHA256 signature without mutating the supplied payload."""

    if not isinstance(key, bytes) or not key:
        raise ValueError("manifest signing key must be non-empty bytes")
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    digest = hmac.new(key, canonical_json(unsigned), hashlib.sha256).hexdigest()
    return {**unsigned, "signature": {"algorithm": "hmac-sha256", "digest": digest}}


def write_manifest(path: Path, payload: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    """Atomically write a signed manifest and return its serialized object."""

    signed = sign_manifest(payload, key)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(signed, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return signed


def verify_manifest(
    path: Path,
    key: bytes,
    *,
    workspace: Path | None = None,
    verify_files: bool = True,
) -> dict[str, Any]:
    """Verify signature and, by default, every referenced input and artifact hash."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestVerificationError(f"cannot read manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestVerificationError("manifest root must be an object")
    signature = data.get("signature")
    if not isinstance(signature, dict) or signature.get("algorithm") != "hmac-sha256":
        raise ManifestVerificationError("manifest has no supported signature")
    supplied = signature.get("digest")
    if not isinstance(supplied, str):
        raise ManifestVerificationError("manifest signature digest is missing")
    unsigned = dict(data)
    unsigned.pop("signature", None)
    expected = hmac.new(key, canonical_json(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise ManifestVerificationError("manifest signature mismatch")
    if not verify_files:
        return data
    session_dir = path.parent.resolve(strict=True)
    for artifact in data.get("artifacts", []):
        try:
            artifact_path = resolve_within(session_dir, artifact["path"], must_exist=True)
            if artifact.get("is_directory"):
                if not artifact_path.is_dir():
                    raise ManifestVerificationError(f"artifact is no longer a directory: {artifact.get('path')}")
                exclusions = [Path(item) for item in artifact.get("hash_excludes", [])]
                actual = sha256_path(artifact_path, exclude_paths=exclusions)
            else:
                if not artifact_path.is_file():
                    raise ManifestVerificationError(f"artifact is no longer a file: {artifact.get('path')}")
                actual = sha256_file(artifact_path)
        except (KeyError, OSError, PathSecurityError, TypeError) as exc:
            raise ManifestVerificationError(f"invalid artifact record: {exc}") from exc
        if actual != artifact.get("sha256"):
            raise ManifestVerificationError(f"artifact hash mismatch: {artifact.get('path')}")
    if workspace is not None:
        try:
            input_hashes = data.get("input_hashes", {})
            if not isinstance(input_hashes, dict):
                raise TypeError("input_hashes must be an object")
            exclusion_values = data.get("input_hash_excludes", [])
            if not isinstance(exclusion_values, list) or not all(
                isinstance(item, str) for item in exclusion_values
            ):
                raise TypeError("input_hash_excludes must be a string list")
            actual_hashes = hash_workspace_inputs(
                workspace,
                (Path(relative) for relative in input_hashes),
                exclude_paths=(Path(item) for item in exclusion_values),
            )
        except (OSError, PathSecurityError, TypeError, ValueError) as exc:
            raise ManifestVerificationError(f"invalid input record: {exc}") from exc
        for relative, expected_hash in input_hashes.items():
            if actual_hashes.get(relative) != expected_hash:
                raise ManifestVerificationError(f"input hash mismatch: {relative}")
    return data
