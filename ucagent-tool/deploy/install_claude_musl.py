"""Install a pinned official Claude binary with a private Linux musl runtime.

This compatibility deployment never replaces system libc or installs packages
into the EDA operating system. Archives are downloaded separately and verified
against pinned integrity values before extracting an explicit regular-file set.
The runtime remains an empirically tested compatibility path, not a claim of
vendor support for CentOS 7.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import tarfile
import tempfile


VERSION = "2.1.263"
ARCHIVES = {
    "claude-mirror.tgz": (
        "sha512", "R6gtwGcW+sxoyANhikfUKPsat+mysEoLhl5rBUSaSHsey7x4oe/0zrWV2vbWw3t5X9XDsh0Bcl/n4/1Jgyc4vw==",
        {"package/claude": "claude.native", "package/LICENSE.md": "LICENSE.md",
         "package/README.md": "README.md", "package/package.json": "package.json"}),
    "musl.apk": (
        "sha256", "4990a5e0ba312e478f94cfe431a70efef1538004eb361c8ae424516848be45bb",
        {"lib/ld-musl-x86_64.so.1": "runtime/ld-musl-x86_64.so.1"}),
    "libstdcxx.apk": (
        "sha256", "939f7c99898f3e8154207a17f4acbe8bc40437e1bb1b43f5525620ca9e452a2e",
        {"usr/lib/libstdc++.so.6.0.33": "runtime/libstdc++.so.6"}),
    "libgcc.apk": (
        "sha256", "04f3467bc967e705221a843fe4d3de5850db826e571686e0c0ed453d38cb5c59",
        {"usr/lib/libgcc_s.so.1": "runtime/libgcc_s.so.1"}),
}


def main():
    """Verify the offline bundle and atomically publish a new private installation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0 or os.uname().machine != "x86_64":
        raise SystemExit("Requires a non-root Linux x86_64 execution identity")
    destination = args.destination.absolute()
    if (destination.exists() or destination.is_symlink() or destination.name != VERSION
            or destination.parent.resolve() != destination.parent):
        raise SystemExit("Use a new absolute version directory without parent symlinks")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".claude-install-", dir=str(destination.parent)))
    hashes = {}
    for filename, (algorithm, expected, selected) in ARCHIVES.items():
        archive = args.bundle / filename
        digest = hashlib.new(algorithm)
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024**2), b""):
                digest.update(chunk)
        actual = base64.b64encode(digest.digest()).decode("ascii") if algorithm == "sha512" else digest.hexdigest()
        if actual != expected:
            raise SystemExit("Archive integrity mismatch: " + filename)
        hashes[filename] = {"algorithm": algorithm, "digest": actual}
        found = set()
        # APK v2 contains concatenated gzip/tar members. Ignore tar padding only;
        # never extract archive-selected paths, symlinks, devices or executables.
        with tarfile.open(archive, "r:gz", ignore_zeros=True) as package:
            for member in package:
                if member.name not in selected:
                    continue
                if not member.isfile() or member.name in found or member.size > 300 * 1024**2:
                    raise SystemExit("Invalid selected archive member: " + member.name)
                found.add(member.name)
                target = staging / selected[member.name]
                target.parent.mkdir(parents=True, exist_ok=True)
                source = package.extractfile(member)
                with source, target.open("xb") as output:
                    for chunk in iter(lambda: source.read(1024**2), b""):
                        output.write(chunk)
        if found != set(selected):
            raise SystemExit("Required files absent from " + filename)
    (staging / "runtime/libc.musl-x86_64.so.1").symlink_to("ld-musl-x86_64.so.1")
    (staging / "claude.native").chmod(0o755)
    (staging / "runtime/ld-musl-x86_64.so.1").chmod(0o755)
    binary = destination / "claude.native"
    runtime = destination / "runtime"
    launcher = staging / "bin/claude"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n# Private loader; never export its libraries to EDA tools.\n"
        "export DISABLE_AUTOUPDATER=1 DISABLE_UPDATES=1\n"
        "exec " + shlex.quote(str(runtime / "ld-musl-x86_64.so.1"))
        + " --library-path " + shlex.quote(str(runtime)) + " "
        + shlex.quote(str(binary)) + ' "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    receipt = {"version": VERSION, "package": "@anthropic-ai/claude-code-linux-x64-musl",
        "integrity_source": "https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64-musl/" + VERSION,
        "runtime_source": "https://dl-cdn.alpinelinux.org/alpine/v3.22/main/x86_64/",
        "archives": hashes, "system_libc_modified": False,
        "acceptance": "pending_runtime_test", "files": {}}
    for item in staging.rglob("*"):
        if item.is_file() and not item.is_symlink():
            receipt["files"][item.relative_to(staging).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    (staging / "installation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.rename(staging, destination)
    print(json.dumps({"installed": str(destination), "version": VERSION,
                      "launcher": str(destination / "bin/claude"), "acceptance": "pending_runtime_test"}))


if __name__ == "__main__":
    main()
