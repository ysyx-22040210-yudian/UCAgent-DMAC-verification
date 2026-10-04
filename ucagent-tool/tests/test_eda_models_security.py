"""Contract tests for EDA models, workspace paths, and secret redaction."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ucagent.eda import CommandSpec, FsdbPliProfile, RunRequest, SessionInput, ToolchainProfile
from ucagent.eda.security import PathSecurityError, redact_argv, redact_data, resolve_within


def test_command_and_run_paths_are_structurally_bounded(tmp_path: Path) -> None:
    """Reject control characters, absolute outputs, and traversal inputs."""

    with pytest.raises(ValidationError, match="control character"):
        CommandSpec(argv=["vcs", "bad\nargument"], tool="vcs")
    with pytest.raises(ValidationError, match="output_dir"):
        RunRequest(
            workspace=tmp_path.resolve(),
            output_dir=tmp_path.resolve() / "outside",
            command=CommandSpec(argv=["vcs"], tool="vcs"),
        )
    with pytest.raises(ValidationError, match="relative"):
        RunRequest(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/one"),
            input_paths=[Path("../secret")],
            command=CommandSpec(argv=["vcs"], tool="vcs"),
        )


def test_resolve_within_rejects_escape_and_symlink(tmp_path: Path) -> None:
    """Resolve paths against their real target rather than a lexical prefix."""

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    with pytest.raises(PathSecurityError):
        resolve_within(workspace, Path("../outside"))
    link = workspace / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available")
    with pytest.raises(PathSecurityError):
        resolve_within(workspace, link / "artifact.log")


def test_session_input_contract_rejects_traversal_reserved_and_overlapping_destinations(
    tmp_path: Path,
) -> None:
    """Keep staged copies inside a private session with deterministic destinations."""

    with pytest.raises(ValidationError, match="session input paths"):
        SessionInput(source=Path("../compile.vdb"), destination=Path("simv.vdb"))
    with pytest.raises(ValidationError, match="runner-reserved"):
        RunRequest(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/test"),
            command=CommandSpec(argv=["python"], tool="python"),
            session_inputs=[
                SessionInput(source=Path("compile.vdb"), destination=Path("stdout.log"))
            ],
        )
    with pytest.raises(ValidationError, match="non-overlapping"):
        RunRequest(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/test"),
            command=CommandSpec(argv=["python"], tool="python"),
            session_inputs=[
                SessionInput(source=Path("a.vdb"), destination=Path("simv.vdb")),
                SessionInput(source=Path("b.dat"), destination=Path("simv.vdb/design.dat")),
            ],
        )


def test_redaction_handles_options_urls_and_nested_license_values() -> None:
    """Remove credential-bearing values without hiding ordinary command fields."""

    argv = redact_argv(
        ["tool", "--token", "abc123", "--password=xyz", "https://user:pw@example.test/path", "-top", "tb"],
        ("abc123", "xyz"),
    )
    assert argv == [
        "tool",
        "--token",
        "<redacted>",
        "--password=<redacted>",
        "https://<redacted>@example.test/path",
        "-top",
        "tb",
    ]
    assert redact_data({"LM_LICENSE_FILE": "27000@server", "nested": ["token=abc"]}) == {
        "LM_LICENSE_FILE": "<redacted>",
        "nested": ["token=<redacted>"],
    }


def test_toolchain_requires_declared_tool_alias() -> None:
    """Fail a missing executable alias with available choices."""

    profile = ToolchainProfile(id="synopsys", tools={"vcs": "vcs"}, minimum_free_bytes=0)
    assert profile.require_tool("vcs") == "vcs"
    with pytest.raises(ValueError, match="available aliases: vcs"):
        profile.require_tool("vcf")


def test_toolchain_public_view_and_repr_never_expose_environment_values() -> None:
    """Keep host-resident license and credential values out of UI projections and reprs."""

    profile = ToolchainProfile(
        id="secure",
        tools={"vcs": "vcs"},
        environment={"LM_LICENSE_FILE": "27000@private-license-host", "EDA_MODE": "batch"},
        minimum_free_bytes=0,
    )
    public = profile.public_view()
    assert public["environment"] == {"LM_LICENSE_FILE": "<redacted>", "EDA_MODE": "<redacted>"}
    assert "private-license-host" not in repr(profile)


def test_toolchain_requires_explicit_existing_fsdb_pli_files(tmp_path: Path) -> None:
    """Fail FSDB preflight unless both administrator-declared PLI files exist."""

    table = tmp_path / "novas.tab"
    library = tmp_path / "pli.a"
    runtime_library = tmp_path / "lib"
    runtime_library.mkdir()
    table.write_text("tab", encoding="utf-8")
    library.write_bytes(b"pli")
    profile = ToolchainProfile(
        id="fsdb",
        tools={"vcs": "vcs"},
        fsdb_pli=FsdbPliProfile(
            table=table.resolve(),
            library=library.resolve(),
            runtime_library_dirs=(runtime_library.resolve(),),
        ),
        minimum_free_bytes=0,
    )
    assert profile.require_fsdb_pli() == (table.resolve(), library.resolve())
    assert profile.public_view()["fsdb_pli"] == {
        "table": str(table.resolve()),
        "library": str(library.resolve()),
        "runtime_library_dirs": [str(runtime_library.resolve())],
    }
    assert profile.fsdb_runtime_library_path() == str(runtime_library.resolve())
    library.unlink()
    with pytest.raises(ValueError, match="does not exist"):
        profile.require_fsdb_pli()
