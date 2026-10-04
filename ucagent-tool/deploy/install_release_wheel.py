"""Install the pure-Python UCAgent wheel into a cloned virtual environment.

This helper is intentionally dependency-free so deployment still works when the
validated base virtual environment has no ``pip`` module.  It only accepts the
UCAgent wheel, rejects path traversal and wheel-native payloads, and writes an
optional non-secret release receipt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import sysconfig
import tempfile
import zipfile


def _metadata(archive: zipfile.ZipFile) -> tuple[str, str, str]:
    """Validate wheel metadata and return its dist-info root, name, and version."""

    metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    wheel_names = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
    if len(metadata_names) != 1 or len(wheel_names) != 1:
        raise ValueError("wheel must contain exactly one METADATA and one WHEEL file")
    dist_info = metadata_names[0].split("/", 1)[0]
    if wheel_names[0].split("/", 1)[0] != dist_info:
        raise ValueError("wheel metadata directories do not agree")
    package = BytesParser().parsebytes(archive.read(metadata_names[0]))
    wheel = BytesParser().parsebytes(archive.read(wheel_names[0]))
    name = str(package.get("Name") or "")
    version = str(package.get("Version") or "")
    if re.sub(r"[-_.]+", "-", name).casefold() != "ucagent" or not version:
        raise ValueError("release wheel must contain the UCAgent distribution and a version")
    if str(wheel.get("Root-Is-Purelib") or "").casefold() != "true":
        raise ValueError("release wheel must be a pure-Python wheel")
    return dist_info, name, version


def _remove_previous_install(site_packages: Path) -> None:
    """Remove only cloned UCAgent package paths before extracting the new wheel."""

    for candidate in site_packages.iterdir():
        lowered = candidate.name.casefold()
        selected = (
            lowered == "ucagent"
            or lowered == "ucagent.py"
            or lowered in {"ucagent.pth", "ucagent.egg-link"}
            or (lowered.startswith("ucagent-") and lowered.endswith((".dist-info", ".egg-info")))
            or ("ucagent" in lowered and lowered.startswith("__editable__"))
        )
        if not selected:
            continue
        if candidate.is_dir() and not candidate.is_symlink():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()


def install_wheel(wheel_path: Path, receipt_path: Path | None, release_id: str) -> dict[str, str]:
    """Install one validated UCAgent wheel and optionally persist a release receipt."""

    if sys.prefix == sys.base_prefix:
        raise RuntimeError("install_release_wheel.py must run inside the cloned release virtual environment")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", release_id):
        raise ValueError("release id is not filesystem-safe")
    wheel_path = wheel_path.resolve(strict=True)
    if not wheel_path.is_file() or wheel_path.suffix != ".whl":
        raise ValueError("wheel path must name an existing .whl file")
    installation_paths = sysconfig.get_paths()
    site_packages = Path(installation_paths["purelib"]).resolve(strict=True)
    scripts_dir = Path(installation_paths["scripts"]).resolve(strict=True)
    with zipfile.ZipFile(wheel_path) as archive:
        dist_info, package_name, version = _metadata(archive)
        members: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in archive.infolist():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts or not member.parts:
                raise ValueError(f"unsafe wheel member: {info.filename!r}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"symbolic links are not accepted in release wheels: {info.filename!r}")
            if len(member.parts) >= 3 and member.parts[0].endswith(".data"):
                if member.parts[1] not in {"purelib", "platlib"}:
                    raise ValueError(f"unsupported wheel data scheme: {member.parts[1]!r}")
                relative = Path(*member.parts[2:])
            else:
                relative = Path(*member.parts)
            if not relative.parts or relative.parts[0] not in {"ucagent", dist_info}:
                raise ValueError(f"wheel contains a path outside the UCAgent distribution: {info.filename!r}")
            destination = (site_packages / relative).resolve()
            try:
                destination.relative_to(site_packages)
            except ValueError as exc:
                raise ValueError(f"wheel member escapes site-packages: {info.filename!r}") from exc
            members.append((info, destination))

        _remove_previous_install(site_packages)
        for info, destination in members:
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
            source_mode = info.external_attr >> 16
            destination.chmod(0o755 if source_mode & 0o111 else 0o644)

    installed_metadata = site_packages / dist_info / "METADATA"
    if not installed_metadata.is_file():
        raise RuntimeError("wheel extraction did not publish distribution metadata")
    for script_name, module in {
        "ucagent": "ucagent.cli",
        "ucagent-platform": "ucagent.server.platform_main",
    }.items():
        script_path = scripts_dir / script_name
        script_path.write_text(
            "#!/usr/bin/env sh\n"
            'exec "$(dirname -- "$0")/python" -m '
            f'{module} "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        script_path.chmod(0o755)
    with wheel_path.open("rb") as wheel_stream:
        wheel_digest = hashlib.file_digest(wheel_stream, "sha256").hexdigest()
    receipt = {
        "schema_version": "1",
        "release_id": release_id,
        "package": package_name,
        "version": version,
        "wheel": wheel_path.name,
        "wheel_sha256": wheel_digest,
        "python": sys.version.split()[0],
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    if receipt_path is not None:
        receipt_path = receipt_path.resolve()
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{receipt_path.name}.", suffix=".tmp", dir=receipt_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with open(descriptor, "w", encoding="utf-8", closefd=True) as stream:
                json.dump(receipt, stream, indent=2, sort_keys=True)
                stream.write("\n")
            temporary.replace(receipt_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    return receipt


def main() -> None:
    """Parse deployment-only arguments and install the requested local wheel."""

    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    receipt = install_wheel(args.wheel, args.receipt, args.release_id)
    print(f"installed {receipt['package']} {receipt['version']} from local wheel")


if __name__ == "__main__":
    main()
