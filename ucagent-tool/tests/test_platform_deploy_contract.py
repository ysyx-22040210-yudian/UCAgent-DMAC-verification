"""Static and behavioral checks for the offline versioned VM deployment contract."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest
import yaml

from deploy import install_release_wheel


REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY / "deploy" / "install-platform.sh"
ROLLBACK = REPOSITORY / "deploy" / "rollback-platform.sh"
SERVICE = REPOSITORY / "deploy" / "ucagent-platform.service"
PROFILE = REPOSITORY / "deploy" / "toolchains.synopsys-o2018.example.yaml"


def _wheel(path: Path, *, unsafe_member: str | None = None) -> Path:
    """Create a minimal pure-Python UCAgent wheel fixture without build tools."""

    metadata = "Metadata-Version: 2.1\nName: UCAgent\nVersion: 1.2.3\n\n"
    wheel = "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ucagent/__init__.py", "VERSION = 'new'\n")
        archive.writestr("ucagent-1.2.3.dist-info/METADATA", metadata)
        archive.writestr("ucagent-1.2.3.dist-info/WHEEL", wheel)
        archive.writestr("ucagent-1.2.3.dist-info/RECORD", "")
        if unsafe_member:
            archive.writestr(unsafe_member, "escape")
    return path


def test_offline_installer_prepares_before_atomic_switch_and_can_restore() -> None:
    """Keep package installation offline and leave current untouched until validation."""

    text = INSTALLER.read_text(encoding="utf-8")
    assert "install_release_wheel.py" in text
    assert "UCAGENT_BASE_VENV" in text
    assert "cp -a --reflink=auto" in text
    assert "pip install" not in text
    assert "git clone" not in text
    assert 'export TMPDIR="${install_root}/tmp"' in text
    validation = text.index("runuser -u ucagent")
    publish = text.index('mv -- "${staging_target}" "${release_target}"')
    switch = text.index('atomic_link "${release_target}" "${current_link}"')
    assert validation < publish < switch
    assert 'atomic_link "${old_current}" "${current_link}"' in text
    assert '"${published_release}" == "${release_target}"' in text
    assert '"${systemctl_bin}" is-active --quiet' in text
    assert "systemctl --no-pager --full status" not in text


def test_service_is_non_root_read_only_and_uses_home_backed_runtime_paths() -> None:
    """Constrain service writes to persistent /home paths and avoid console wrappers."""

    text = SERVICE.read_text(encoding="utf-8")
    assert "User=ucagent" in text
    assert "Group=ucagent" in text
    assert "User=root" not in text
    assert "current/venv/bin/python -m ucagent.server.platform_main" in text
    assert "--host 127.0.0.1 --port 8800" in text
    assert "--mcp-enabled" in text
    assert "Environment=TMPDIR=/home/ucagent-lab/tmp" in text
    assert "EnvironmentFile=-/etc/ucagent/eda.env" in text
    assert "/run/ucagent-eda.env" not in text
    assert "Environment=PYTHONNOUSERSITE=1" in text
    assert "ProtectSystem=full" in text
    assert "ProtectHome=read-only" in text
    assert "ReadOnlyDirectories=/home/ucagent-lab/current /home/ucagent-lab/config" in text
    read_write = next(line for line in text.splitlines() if line.startswith("ReadWriteDirectories="))
    for path in ("state", "workspaces", "artifacts", "tmp", "home"):
        assert f"/home/ucagent-lab/{path}" in read_write
    assert "node" not in text.casefold()


def test_synopsys_profile_uses_alias_matched_versions_and_secret_names_only() -> None:
    """Keep exact O-2018 tool paths while excluding license values from the profile."""

    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))["profiles"]["synopsys_o2018"]
    assert profile["execution_user"] == "ucagent"
    assert profile["max_concurrency"] == 1
    assert profile["minimum_free_bytes"] == 10 * 1024**3
    assert profile["tools"]["python"] == "/home/ucagent-lab/current/venv/bin/python"
    assert profile["tools"]["vcf"].endswith("/vcfca/bin/vcf")
    assert profile["versions"]["vcf"] == "O-2018.09-SP2"
    path_entries = profile["environment"]["PATH"].split(":")
    assert path_entries.index("/usr/bin") < path_entries.index(
        "/opt/rh/devtoolset-11/root/usr/bin"
    )
    assert path_entries[-1] == "/opt/rh/devtoolset-11/root/usr/bin"
    assert set(profile["license_environment_names"]) == {
        "SNPSLMD_LICENSE_FILE",
        "LM_LICENSE_FILE",
    }
    assert not set(profile["license_environment_names"]) & set(profile["environment"])


def test_dependency_free_wheel_installer_replaces_only_ucagent(tmp_path, monkeypatch) -> None:
    """Install a local wheel without pip while preserving unrelated cloned dependencies."""

    site_packages = tmp_path / "venv" / "site-packages"
    scripts = tmp_path / "venv" / "bin"
    scripts.mkdir(parents=True)
    old_package = site_packages / "ucagent"
    old_package.mkdir(parents=True)
    (old_package / "stale.py").write_text("stale = True\n", encoding="utf-8")
    unrelated = site_packages / "fastapi"
    unrelated.mkdir()
    (unrelated / "__init__.py").write_text("# preserved\n", encoding="utf-8")
    wheel_path = _wheel(tmp_path / "ucagent-1.2.3-py3-none-any.whl")
    receipt = tmp_path / "release.json"
    monkeypatch.setattr(install_release_wheel.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(install_release_wheel.sys, "base_prefix", str(tmp_path / "base"))
    monkeypatch.setattr(
        install_release_wheel.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_packages), "scripts": str(scripts)},
    )

    result = install_release_wheel.install_wheel(wheel_path, receipt, "release-1")

    assert not (old_package / "stale.py").exists()
    assert (old_package / "__init__.py").read_text(encoding="utf-8") == "VERSION = 'new'\n"
    assert (unrelated / "__init__.py").is_file()
    assert "ucagent.server.platform_main" in (scripts / "ucagent-platform").read_text(
        encoding="utf-8"
    )
    assert result["release_id"] == "release-1"
    assert result["wheel_sha256"] == hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    assert receipt.is_file()


def test_wheel_installer_rejects_traversal_before_replacing_package(tmp_path, monkeypatch) -> None:
    """Reject malicious wheel members without touching the cloned environment."""

    site_packages = tmp_path / "venv" / "site-packages"
    scripts = tmp_path / "venv" / "bin"
    scripts.mkdir(parents=True)
    package = site_packages / "ucagent"
    package.mkdir(parents=True)
    sentinel = package / "keep.py"
    sentinel.write_text("keep = True\n", encoding="utf-8")
    wheel_path = _wheel(tmp_path / "ucagent-unsafe.whl", unsafe_member="../escaped.py")
    monkeypatch.setattr(install_release_wheel.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(install_release_wheel.sys, "base_prefix", str(tmp_path / "base"))
    monkeypatch.setattr(
        install_release_wheel.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_packages), "scripts": str(scripts)},
    )

    with pytest.raises(ValueError, match="unsafe wheel member"):
        install_release_wheel.install_wheel(wheel_path, None, "release-unsafe")

    assert sentinel.is_file()
    assert not (tmp_path / "venv" / "escaped.py").exists()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable on this host")
@pytest.mark.parametrize("script", [INSTALLER, ROLLBACK])
def test_deployment_shell_syntax(script: Path) -> None:
    """Ask Bash to parse deployment scripts when the host provides Bash."""

    subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, text=True)
