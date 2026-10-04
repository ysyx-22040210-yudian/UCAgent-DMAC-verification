"""Build a hash-pinned Linux offline Studio distribution with its own EDA runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipapp


def build(source: Path, archive: Path, output: Path, *, runtime_support: Path, wheelhouse: Path | None = None) -> Path:
    """Verify upstream bytes, install only into staging, inventory and publish atomically.

    Only the builder needs network access when no wheelhouse is supplied. The
    delivered application neither invokes pip nor downloads tools or solvers.
    """
    source, archive = source.resolve(strict=True), archive.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite a distribution: {output}")
    lock = json.loads((source / "deploy/portable/runtime.lock.json").read_text())
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if archive.stat().st_size != lock["size"] or digest != lock["sha256"]:
        raise ValueError("OSS CAD Suite archive size/SHA-256 does not match runtime.lock.json")
    support_lock = json.loads((source / "deploy/portable/runtime-support.lock.json").read_text())
    runtime_support = runtime_support.resolve(strict=True)
    with runtime_support.open("rb") as stream:
        support_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if runtime_support.stat().st_size != support_lock["size"] or support_digest != support_lock["sha256"]:
        raise ValueError("Runtime support package size/SHA-256 does not match runtime-support.lock.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 12 * 1024**3:
        raise ValueError("Building the offline package requires at least 12 GiB free")
    with tempfile.TemporaryDirectory(prefix=".studio-build-", dir=output.parent) as temporary:
        stage = Path(temporary)
        with tarfile.open(archive, "r:gz") as bundle:
            for item in bundle.getmembers():
                if not (item.name == "oss-cad-suite" and item.isdir()) and not item.name.startswith("oss-cad-suite/"):
                    raise ValueError("Unexpected archive root")
            bundle.extractall(stage, filter="data")
        # The pinned upstream Python launchers omit quotes around the interpreter
        # path. Fix the wrappers only, so a relocated installation can contain spaces.
        for alias in ("sby", "yosys-smtbmc"):
            wrapper = stage / "oss-cad-suite/bin" / alias
            text = wrapper.read_text(encoding="utf-8")
            original = 'exec $release_bindir_abs/tabbypy3 '
            if text.count(original) != 1:
                raise ValueError(f"Unexpected upstream launcher contract: {alias}")
            wrapper.write_text(text.replace(original, 'exec "$release_bindir_abs/tabbypy3" '), encoding="utf-8", newline="\n")
        backend = stage / "backend"
        backend.mkdir()
        shutil.copytree(source / "ucagent", backend / "ucagent", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with tempfile.TemporaryDirectory(dir=stage, prefix=".desktop-") as desktop:
            desktop = Path(desktop)
            shutil.copytree(source / "desktop/ucagent_tk", desktop / "ucagent_tk", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copyfile(source / "desktop/ucagent_app.py", desktop / "__main__.py")
            zipapp.create_archive(desktop, target=stage / "UCAgent-Desktop.pyz", compressed=True)
        python = stage / "oss-cad-suite/bin/tabbypy3"
        env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "LD_")) and "LICENSE" not in key}
        env.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(stage)})
        subprocess.run([str(python), str(source / "deploy/extract_runtime_support.py"), str(runtime_support), str(stage / "oss-cad-suite")], env=env, check=True, timeout=30)
        install = [str(python), "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--ignore-installed", "--only-binary=:all:", "--no-compile", "--target", str(stage / "backend-deps"), "-r", str(source / "deploy/portable/requirements.txt")]
        if wheelhouse is not None:
            install.extend(["--no-index", "--find-links", str(wheelhouse.resolve(strict=True))])
        subprocess.run(install, env=env, check=True)
        tools = {}
        for alias, option in (("sby", "--version"), ("yosys", "-V"), ("z3", "--version"), ("yosys-smtbmc", "-h")):
            probe = subprocess.run([str(stage / "oss-cad-suite/bin" / alias), option], env=env, capture_output=True, text=True, timeout=30, check=True)
            tools[alias] = "SMTBMC bundled with " + tools["yosys"] if alias == "yosys-smtbmc" else probe.stdout.strip().splitlines()[0]
        env["PYTHONPATH"] = str(stage / "backend-deps") + os.pathsep + str(backend)
        subprocess.run([str(python), "-c", "import tkinter; from ucagent.server.portable_main import main; print('Offline imports OK')"], env=env, check=True, timeout=30)
        examples = stage / "examples"
        examples.mkdir()
        for name in ("sby_counter", "sby_counter_bug"):
            destination = examples / name
            shutil.copytree(source / "acceptance/sby_counter", destination, ignore=shutil.ignore_patterns("platform-runs", "platform-inputs", "__pycache__"))
            if name.endswith("_bug"):
                # The example enables an RTL defect, not a weakened property.
                config = destination / ".ucagent/project.yaml"
                config.write_text(config.read_text().replace("  sources: [counter.sv]", "  sources: [counter.sv]\n  defines: [INJECT_BUG]"), encoding="utf-8")
        shutil.copyfile(source / "deploy/portable/Start-UCAgent", stage / "Start-UCAgent")
        (stage / "Start-UCAgent").chmod(0o755)
        shutil.copyfile(source / "deploy/portable/runtime.lock.json", stage / "runtime.lock.json")
        shutil.copyfile(source / "deploy/portable/runtime-support.lock.json", stage / "runtime-support.lock.json")
        shutil.copyfile(source / "deploy/portable/README.md", stage / "README.md")
        shutil.copyfile(source / "deploy/portable/THIRD_PARTY.md", stage / "THIRD_PARTY.md")
        shutil.copyfile(source / "deploy/portable/Verify-Bundle.py", stage / "Verify-Bundle.py")
        ui_lock = json.loads((source / "deploy/portable/ui-assets.lock.json").read_text())
        fonts = stage / "fonts"
        fonts.mkdir()
        for asset in ui_lock["assets"]:
            path = archive.parent / asset["name"]
            if path.stat().st_size != asset["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
                raise ValueError(f"UI asset size/SHA-256 mismatch: {asset['name']}")
            shutil.copyfile(path, fonts / asset["name"])
        shutil.copyfile(source / "deploy/portable/fonts.conf", fonts / "fonts.conf")
        shutil.copyfile(source / "deploy/portable/ui-assets.lock.json", stage / "ui-assets.lock.json")
        dependencies = subprocess.run([str(python), "-c", "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions(path=['backend-deps'])},sort_keys=True))"], cwd=stage, env=env, capture_output=True, text=True, check=True)
        manifest = {"schema_version": 1, "version": "0.3.1", "platform": "linux-x86_64", "runtime": lock, "runtime_support": support_lock, "runtime_modifications": ["Quote interpreter paths in bin/sby and bin/yosys-smtbmc (UCAgent, 2026-09-06)"], "tools": tools, "python_dependencies": json.loads(dependencies.stdout)}
        (stage / "bundle.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        shutil.copyfile(source / "deploy/portable/toolchains.vcf.example.yaml", stage / "toolchains.vcf.example.yaml")
        links = {path.relative_to(stage).as_posix(): os.readlink(path) for path in stage.rglob("*") if path.is_symlink()}
        (stage / "SYMLINKS.json").write_text(json.dumps(links, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        inventory = {}
        for path in sorted(stage.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix != ".pyc":
                with path.open("rb") as stream:
                    inventory[path.relative_to(stage).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
        (stage / "SHA256SUMS.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(stage, output)
    return output


def main() -> None:
    """Build one explicitly selected version; never replace an existing release."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-support", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args()
    print(build(args.source, args.runtime_archive, args.output, runtime_support=args.runtime_support, wheelhouse=args.wheelhouse))


if __name__ == "__main__":
    main()
