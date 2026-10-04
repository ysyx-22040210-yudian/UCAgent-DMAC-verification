"""Focused tests for deterministic VCS and VC Formal input closure resolution."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from ucagent.eda import (
    CommandSpec,
    InputClosureSecurityError,
    JobRunner,
    RunRequest,
    ToolchainProfile,
    get_adapter,
    resolve_tcl_source_closure,
    resolve_vcs_filelist_closure,
)
from ucagent.eda.manifest import hash_workspace_inputs


def _write(path: Path, content: str) -> None:
    """Create one UTF-8 fixture below the temporary workspace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_vcs_filelist_closure_honors_nested_f_and_capital_f_bases(tmp_path: Path) -> None:
    """Resolve nested lists, sources, and include trees using VCS path-base rules."""

    _write(tmp_path / "rtl" / "dut.sv", "module dut; endmodule\n")
    _write(tmp_path / "tb" / "tb_top.sv", "module tb_top; endmodule\n")
    _write(tmp_path / "rtl" / "include" / "defs.svh", "`define WIDTH 8\n")
    _write(tmp_path / "workspace.f", "tb/tb_top.sv\n")
    _write(
        tmp_path / "rtl" / "lists" / "root.f",
        "-F nested/child.f\n",
    )
    _write(
        tmp_path / "rtl" / "lists" / "nested" / "child.f",
        "+incdir+../../include\n../../dut.sv\n-f ../../../workspace.f\n",
    )

    closure = resolve_vcs_filelist_closure(
        tmp_path,
        filelists=[Path("rtl/lists/root.f")],
        root_mode="F",
    )

    assert closure.complete is True
    assert {path.as_posix() for path in closure.filelists} == {
        "rtl/lists/root.f",
        "rtl/lists/nested/child.f",
        "workspace.f",
    }
    assert {path.as_posix() for path in closure.sources} == {
        "rtl/dut.sv",
        "tb/tb_top.sv",
    }
    assert closure.include_dirs == (Path("rtl/include"),)
    assert set(closure.input_paths) == {
        *closure.filelists,
        *closure.sources,
        *closure.include_dirs,
    }


def test_vcs_adapter_hashes_transitive_sources_and_disables_stale_cache(tmp_path: Path) -> None:
    """Put nested RTL and include contents into the exact adapter fingerprint inputs."""

    _write(tmp_path / "rtl" / "dut.sv", "module dut; endmodule\n")
    _write(tmp_path / "rtl" / "inc" / "defs.svh", "`define WIDTH 8\n")
    _write(tmp_path / "rtl" / "files.f", "+incdir+inc\ndut.sv\n")

    request = get_adapter("vcs").build_compile_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/compile"),
        top="dut",
        filelists=[Path("rtl/files.f")],
    )
    before = hash_workspace_inputs(tmp_path, request.input_paths)
    _write(tmp_path / "rtl" / "dut.sv", "module dut; wire changed; endmodule\n")
    after_source = hash_workspace_inputs(tmp_path, request.input_paths)
    _write(tmp_path / "rtl" / "inc" / "defs.svh", "`define WIDTH 16\n")
    after_include = hash_workspace_inputs(tmp_path, request.input_paths)

    assert request.metadata["cacheable"] is True
    assert request.metadata["input_closure"]["complete"] is True
    assert Path("rtl/dut.sv") in request.input_paths
    assert Path("rtl/inc") in request.input_paths
    assert before != after_source
    assert after_source != after_include


def test_literal_hdl_includes_are_resolved_transitively_outside_incdirs(tmp_path: Path) -> None:
    """Capture source-relative nested headers even when no broad include directory is declared."""

    _write(
        tmp_path / "rtl" / "dut.sv",
        '// `include "ignored.svh"\n`include "headers/first.svh"\nmodule dut; endmodule\n',
    )
    _write(
        tmp_path / "rtl" / "headers" / "first.svh",
        '/* `include "ignored_too.svh" */\n`include "second.svh"\n',
    )
    _write(tmp_path / "rtl" / "headers" / "second.svh", "`define WIDTH 8\n")
    _write(tmp_path / "rtl" / "files.f", "dut.sv\n")

    closure = resolve_vcs_filelist_closure(
        tmp_path,
        filelists=[Path("rtl/files.f")],
    )

    assert closure.complete is True
    assert closure.includes == (
        Path("rtl/headers/first.svh"),
        Path("rtl/headers/second.svh"),
    )
    assert Path("rtl/headers/first.svh") in closure.input_paths
    assert Path("rtl/headers/second.svh") in closure.input_paths


def test_dynamic_or_escaping_hdl_include_cannot_be_cached(tmp_path: Path) -> None:
    """Diagnose macro includes and reject literal headers that can escape the workspace."""

    _write(tmp_path / "rtl" / "dynamic.sv", "`include HEADER_FILE\n")
    dynamic = resolve_vcs_filelist_closure(
        tmp_path,
        sources=[Path("rtl/dynamic.sv")],
    )
    assert dynamic.complete is False
    assert dynamic.diagnostics[0]["error_code"] == "dynamic_hdl_include"

    _write(tmp_path / "rtl" / "escaping.sv", '`include "../../outside.svh"\n')
    with pytest.raises(InputClosureSecurityError) as escaping:
        resolve_vcs_filelist_closure(
            tmp_path,
            sources=[Path("rtl/escaping.sv")],
        )
    assert escaping.value.error_code == "hdl_include_path_escape"


def test_transitive_closure_is_signed_and_controls_runner_cache_reuse(tmp_path: Path) -> None:
    """Persist closure hashes in manifests and invalidate cache after nested RTL changes."""

    _write(tmp_path / "rtl" / "dut.sv", "module dut; endmodule\n")
    _write(tmp_path / "rtl" / "inc" / "defs.svh", "`define WIDTH 8\n")
    _write(tmp_path / "rtl" / "files.f", "+incdir+inc\ndut.sv\n")
    compile_request = get_adapter("vcs").build_compile_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/unused"),
        top="dut",
        filelists=[Path("rtl/files.f")],
    )
    code = (
        "import pathlib,sys;"
        "pathlib.Path(sys.argv[1]).write_text('compiled', encoding='utf-8')"
    )
    runner = JobRunner(b"closure-cache-key")
    profile = ToolchainProfile(
        id="fake",
        tools={"python": sys.executable},
        minimum_free_bytes=0,
    )

    def run(run_id: str) -> dict[str, object]:
        """Execute one fake compile using the adapter's exact closure contract."""

        request = RunRequest(
            run_id=run_id,
            workspace=tmp_path.resolve(),
            output_dir=Path("runs") / run_id,
            command=CommandSpec(
                argv=["python", "-c", code, "{SESSION_DIR}/simv"],
                tool="python",
            ),
            input_paths=compile_request.input_paths,
            artifact_paths=[Path("simv")],
            metadata=compile_request.metadata,
        )
        result = runner.run(request, profile)
        return json.loads(result.manifest_path.read_text(encoding="utf-8"))

    first = run("compile-one")
    _write(tmp_path / "rtl" / "dut.sv", "module dut; wire changed; endmodule\n")
    second = run("compile-two")
    third = run("compile-three")

    assert set(first["input_hashes"]) >= {"rtl/files.f", "rtl/dut.sv", "rtl/inc"}
    assert first["input_fingerprint"] != second["input_fingerprint"]
    assert second["cache_hit"] is False
    assert third["cache_hit"] is True


def test_runner_rejects_a_closure_shape_changed_while_job_was_queued(tmp_path: Path) -> None:
    """Prevent a queued file-list request from caching newly introduced untracked inputs."""

    _write(tmp_path / "rtl" / "a.svh", "`define VALUE 1\n")
    _write(tmp_path / "rtl" / "b.svh", "`define VALUE 2\n")
    _write(tmp_path / "rtl" / "dut.sv", '`include "a.svh"\nmodule dut; endmodule\n')
    _write(tmp_path / "rtl" / "files.f", "dut.sv\n")
    compile_request = get_adapter("vcs").build_compile_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/unused"),
        top="dut",
        filelists=[Path("rtl/files.f")],
    )
    _write(tmp_path / "rtl" / "dut.sv", '`include "b.svh"\nmodule dut; endmodule\n')
    request = RunRequest(
        run_id="changed-closure",
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/changed-closure"),
        command=CommandSpec(
            argv=["python", "-c", "print('must not execute')"],
            tool="python",
        ),
        input_paths=compile_request.input_paths,
        metadata=compile_request.metadata,
    )

    result = JobRunner(b"changed-closure-key").run(
        request,
        ToolchainProfile(
            id="fake",
            tools={"python": sys.executable},
            minimum_free_bytes=0,
        ),
    )

    assert result.execution_status.value == "error"
    assert result.diagnostics[0]["error_code"] == "input_closure_changed_before_run"
    assert "must not execute" not in result.stdout_log.read_text(encoding="utf-8")


def test_unknown_filelist_option_is_signed_but_explicitly_not_cacheable(tmp_path: Path) -> None:
    """Run known inputs uncached when an option's file dependencies are not provable."""

    _write(tmp_path / "rtl" / "dut.sv", "module dut; endmodule\n")
    _write(tmp_path / "rtl" / "files.f", "-unknown_library_mode\ndut.sv\n")

    request = get_adapter("vcs").build_compile_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/compile"),
        top="dut",
        filelists=[Path("rtl/files.f")],
    )

    closure = request.metadata["input_closure"]
    assert request.metadata["cacheable"] is False
    assert closure["complete"] is False
    assert closure["cacheable"] is False
    assert closure["diagnostics"][0]["error_code"] == "unsupported_filelist_option"
    assert Path("rtl/files.f") in request.input_paths
    assert Path("rtl/dut.sv") in request.input_paths

    events: list[dict[str, object]] = []
    runner_request = RunRequest(
        run_id="uncacheable-closure",
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/uncacheable-closure"),
        command=CommandSpec(
            argv=["python", "-c", "print('compiled')"],
            tool="python",
        ),
        input_paths=request.input_paths,
        metadata=request.metadata,
    )
    JobRunner(b"uncacheable-key").run(
        runner_request,
        ToolchainProfile(
            id="fake",
            tools={"python": sys.executable},
            minimum_free_bytes=0,
        ),
        on_event=events.append,
    )
    cache_event = next(item for item in events if item["type"] == "cache_disabled")
    assert cache_event["payload"]["reason"] == "input_closure_unproven"


@pytest.mark.parametrize(
    ("content", "error_code"),
    [
        ("-F ../../outside.f\n", "input_path_escape"),
        ("$RTL_ROOT/dut.sv\n", "dynamic_input_expression"),
        ("`touch escaped`\n", "dynamic_input_expression"),
        ("[exec touch escaped]\n", "dynamic_input_expression"),
        ("dut*.sv\n", "dynamic_input_expression"),
    ],
)
def test_vcs_filelist_rejects_escape_and_dynamic_constructs(
    tmp_path: Path,
    content: str,
    error_code: str,
) -> None:
    """Reject paths or expressions that would require shell-like evaluation."""

    _write(tmp_path / "rtl" / "files.f", content)

    with pytest.raises(InputClosureSecurityError) as raised:
        resolve_vcs_filelist_closure(
            tmp_path,
            filelists=[Path("rtl/files.f")],
            root_mode="F",
        )

    assert raised.value.error_code == error_code


def test_vcs_filelist_rejects_recursive_inclusion(tmp_path: Path) -> None:
    """Reject direct or indirect response-file recursion before launching VCS."""

    _write(tmp_path / "a.f", "-F b.f\n")
    _write(tmp_path / "b.f", "-F a.f\n")

    with pytest.raises(InputClosureSecurityError) as raised:
        resolve_vcs_filelist_closure(tmp_path, filelists=[Path("a.f")])

    assert raised.value.error_code == "recursive_filelist"


def test_vc_formal_closure_includes_filelists_properties_and_tcl_sources(tmp_path: Path) -> None:
    """Hash all fixed VCF Tcl, SVA, nested RTL, and include dependencies."""

    _write(tmp_path / "rtl" / "dut.sv", "module dut; endmodule\n")
    _write(tmp_path / "rtl" / "include" / "defs.svh", "`define FORMAL 1\n")
    _write(tmp_path / "rtl" / "files.f", "+incdir+include\ndut.sv\n")
    _write(tmp_path / "formal" / "properties.sv", "assert property (1);\n")
    _write(tmp_path / "formal" / "leaf.tcl", "set leaf_loaded 1\n")
    _write(tmp_path / "formal" / "common.tcl", "source {formal/leaf.tcl}\n")
    _write(
        tmp_path / "formal" / "run.tcl",
        "source formal/common.tcl # literal dependency\n",
    )
    _write(
        tmp_path / "formal" / "design.f",
        "-F rtl/files.f\nformal/properties.sv\n",
    )

    request = get_adapter("vc_formal").build_formal_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/fpv"),
        tcl_path=Path("formal/run.tcl"),
        filelist=Path("formal/design.f"),
    )

    assert request.metadata["cacheable"] is True
    assert set(request.input_paths) == {
        Path("formal/run.tcl"),
        Path("formal/common.tcl"),
        Path("formal/leaf.tcl"),
        Path("formal/design.f"),
        Path("formal/properties.sv"),
        Path("rtl/files.f"),
        Path("rtl/dut.sv"),
        Path("rtl/include"),
    }


def test_tcl_source_closure_rejects_dynamic_and_recursive_sources(tmp_path: Path) -> None:
    """Reject VCF Tcl source graphs that cannot be resolved without Tcl execution."""

    _write(tmp_path / "dynamic.tcl", "source $SCRIPT_ROOT/common.tcl\n")
    with pytest.raises(InputClosureSecurityError) as dynamic:
        resolve_tcl_source_closure(tmp_path, [Path("dynamic.tcl")])
    assert dynamic.value.error_code == "dynamic_tcl_source"

    _write(tmp_path / "a.tcl", "source b.tcl\n")
    _write(tmp_path / "b.tcl", "source a.tcl\n")
    with pytest.raises(InputClosureSecurityError) as recursive:
        resolve_tcl_source_closure(tmp_path, [Path("a.tcl")])
    assert recursive.value.error_code == "recursive_tcl_source"
