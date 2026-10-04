"""Command-construction tests for built-in EDA toolchain adapters."""

from pathlib import Path

import pytest

from ucagent.eda import ToolchainProfile, get_adapter, list_adapters


def test_registry_exposes_all_requested_adapters() -> None:
    """Expose orthogonal simulator, methodology helper, and formal engines."""

    assert set(list_adapters()) == {
        "picker",
        "pytest",
        "vcs",
        "urg",
        "vc_formal",
        "sby",
        "formal_mc",
        "verdi_artifact",
    }


def test_vcs_native_and_uvm_commands_keep_structured_fields_separate(tmp_path: Path) -> None:
    """Construct deterministic compile and test argv without shell fragments."""

    vcs = get_adapter("vcs")
    fsdb_pli = (tmp_path.resolve() / "novas.tab", tmp_path.resolve() / "pli.a")
    compile_request = vcs.build_compile_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/compile"),
        top="tb_top",
        sources=[Path("rtl/dut.sv"), Path("tb/tb_top.sv")],
        filelists=[Path("rtl/files.f")],
        include_dirs=[Path("tb/include")],
        defines=["WIDTH=32"],
        parameters={"DEPTH": 4},
        methodology="uvm",
        timescale="1ns/1ps",
        coverage=["assert", "line", "tgl"],
        waveform="fsdb",
        fsdb_pli=fsdb_pli,
    )
    assert compile_request.command.argv[:3] == ["vcs", "-full64", "-sverilog"]
    assert ["-ntb_opts", "uvm-1.2"] == compile_request.command.argv[3:5]
    assert "-timescale=1ns/1ps" in compile_request.command.argv
    filelist_index = compile_request.command.argv.index("-F")
    assert compile_request.command.argv[filelist_index : filelist_index + 2] == [
        "-F",
        "{WORKSPACE}/rtl/files.f",
    ]
    fsdb_index = compile_request.command.argv.index("-P")
    assert compile_request.command.argv[fsdb_index : fsdb_index + 7] == [
        "-P",
        str(fsdb_pli[0]),
        str(fsdb_pli[1]),
        "+define+UCAGENT_ENABLE_FSDB",
        "-debug_access+all",
        "-kdb",
        "-lca",
    ]
    assert fsdb_index < compile_request.command.argv.index("-F")
    assert compile_request.command.argv[compile_request.command.argv.index("-cm") + 1] == "line+tgl+assert"
    assert compile_request.command.argv[compile_request.command.argv.index("-cm_dir") + 1] == (
        "{SESSION_DIR}/simv.vdb"
    )
    assert Path("simv.vdb") in compile_request.artifact_paths

    run_request = vcs.build_simulation_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/test"),
        executable=Path("runs/compile/simv"),
        coverage_database=Path("runs/compile/simv.vdb"),
        test_name="uart_test",
        suite="IT",
        seed=123,
        coverage=["line"],
        waveform="fsdb",
        fsdb_runtime_library_path="/opt/verdi/lib",
        plusargs=["+UART_BAUD=115200"],
    )
    assert "+UVM_TESTNAME=uart_test" in run_request.command.argv
    assert "+ntb_random_seed=123" in run_request.command.argv
    assert "+UART_BAUD=115200" in run_request.command.argv
    assert "+fsdbfile={SESSION_DIR}/waves.fsdb" in run_request.command.argv
    assert Path("waves.fsdb") not in run_request.artifact_paths
    assert run_request.session_inputs[0].source == Path("runs/compile/simv.vdb")
    assert run_request.session_inputs[0].destination == Path("simv.vdb")
    assert run_request.parser == "uvm"
    with pytest.raises(ValueError, match="compile-time design VDB"):
        vcs.build_simulation_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/missing-design-vdb"),
            executable=Path("runs/compile/simv"),
            coverage=["line"],
        )
    with pytest.raises(ValueError, match="timescale"):
        vcs.build_compile_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/bad-timescale"),
            top="tb_top",
            methodology="uvm",
            timescale="1ns/1ps;touch escaped",
        )
    with pytest.raises(ValueError, match="explicit fsdb_pli"):
        vcs.build_compile_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/missing-fsdb-pli"),
            top="tb_top",
            sources=[Path("tb/tb_top.sv")],
            waveform="fsdb",
        )

    generated_run = vcs.build_simulation_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/generated-test"),
        executable=Path("runs/compile/simv"),
        waveform="fsdb",
        fsdb_runtime_library_path="/opt/verdi/lib",
        expect_waveform_artifact=True,
    )
    assert Path("waves.fsdb") in generated_run.artifact_paths
    with pytest.raises(ValueError, match="reserved"):
        vcs.build_simulation_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/bad"),
            executable=Path("simv"),
            plusargs=["+UVM_TESTNAME=override"],
        )


def test_vcs_imported_recipe_requires_declared_target_and_variables(tmp_path: Path) -> None:
    """Prevent arbitrary Make targets and undeclared assignment parameters."""

    vcs = get_adapter("vcs")
    request = vcs.build_recipe_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/recipe"),
        makefile=Path("flows/vcs.mk"),
        target="smoke",
        declared_targets=["smoke"],
        variables={"MODE": "nightly"},
        allowed_variables=["MODE", "TEST", "SEED", "RUN_DIR", "COVERAGE", "WAVEFORM"],
        test_variable="TEST",
        test_name="uart_test",
        seed_variable="SEED",
        seed=17,
        output_variable="RUN_DIR",
        coverage_variable="COVERAGE",
        coverage=["tgl", "line"],
        waveform_variable="WAVEFORM",
        waveform="fsdb",
        artifact_paths=[Path("coverage/simv.vdb"), Path("waves.fsdb")],
        result_paths=[Path("logs/result.log")],
        success_markers=["UART REGRESSION PASSED"],
        suite="IT",
    )
    assert request.command.argv == [
        "make",
        "-f",
        "{WORKSPACE}/flows/vcs.mk",
        "smoke",
        "COVERAGE=line+tgl",
        "MODE=nightly",
        "RUN_DIR={SESSION_DIR}",
        "SEED=17",
        "TEST=uart_test",
        "WAVEFORM=fsdb",
    ]
    assert request.command.tool == "make"
    assert request.input_paths == [Path("flows/vcs.mk")]
    assert request.artifact_paths == [
        Path("coverage/simv.vdb"),
        Path("waves.fsdb"),
        Path("logs/result.log"),
    ]
    assert request.result_paths == [Path("logs/result.log")]
    assert request.test_name == "uart_test"
    assert request.suite == "IT"
    assert request.seed == 17
    assert request.success_markers == ["UART REGRESSION PASSED"]
    assert request.metadata["coverage"] == ["line", "tgl"]
    assert request.metadata["waveform"] == "fsdb"
    with pytest.raises(ValueError, match="not declared"):
        vcs.build_recipe_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/rejected"),
            target="clean",
            declared_targets=["smoke"],
            variables={},
            allowed_variables=["TEST", "SEED", "RUN_DIR"],
            test_variable="TEST",
            test_name="uart_test",
            seed_variable="SEED",
            seed=17,
            output_variable="RUN_DIR",
        )

    with pytest.raises(ValueError, match="no coverage_variable"):
        vcs.build_recipe_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/missing-coverage-contract"),
            target="smoke",
            declared_targets=["smoke"],
            variables={},
            allowed_variables=["TEST", "SEED", "RUN_DIR"],
            test_variable="TEST",
            test_name="uart_test",
            seed_variable="SEED",
            seed=17,
            output_variable="RUN_DIR",
            coverage=["line"],
        )

    with pytest.raises(ValueError, match="no waveform_variable"):
        vcs.build_recipe_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/missing-waveform-contract"),
            target="smoke",
            declared_targets=["smoke"],
            variables={},
            allowed_variables=["TEST", "SEED", "RUN_DIR"],
            test_variable="TEST",
            test_name="uart_test",
            seed_variable="SEED",
            seed=17,
            output_variable="RUN_DIR",
            waveform="fsdb",
        )
    with pytest.raises(ValueError, match="Make-active"):
        vcs.build_recipe_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/injected"),
            target="smoke",
            declared_targets=["smoke"],
            variables={"MODE": "$(shell touch escaped)"},
            allowed_variables=["MODE", "TEST", "SEED", "RUN_DIR"],
            test_variable="TEST",
            test_name="uart_test",
            seed_variable="SEED",
            seed=17,
            output_variable="RUN_DIR",
        )


def test_vcs_coverage_stages_compile_design_vdb_for_o2018_urg(tmp_path: Path) -> None:
    """Prevent the O-2018 limited-design URG result by seeding each simulation VDB."""

    observed_log = (
        Path(__file__).parent / "fixtures" / "urg" / "o2018_limited_design_loaded.log"
    ).read_text(encoding="utf-8")
    assert "UCAPI-LDAST" in observed_log

    vcs = get_adapter("vcs")
    compile_request = vcs.build_compile_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/compile"),
        top="tb_top",
        sources=[Path("tb/tb_top.sv")],
        coverage=["line", "assert"],
    )
    simulation_request = vcs.build_simulation_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/test-1"),
        executable=Path("runs/compile/simv"),
        coverage_database=Path("runs/compile/simv.vdb"),
        coverage=["line", "assert"],
        test_name="smoke_test",
        seed=1,
    )

    assert compile_request.command.argv[
        compile_request.command.argv.index("-cm_dir") + 1
    ] == "{SESSION_DIR}/simv.vdb"
    assert Path("simv.vdb") in compile_request.artifact_paths
    assert simulation_request.session_inputs[0].source == Path("runs/compile/simv.vdb")
    assert simulation_request.session_inputs[0].destination == Path("simv.vdb")
    assert simulation_request.command.argv[
        simulation_request.command.argv.index("-cm_dir") + 1
    ] == "{SESSION_DIR}/simv.vdb"


def test_vc_formal_argv_and_tcl_lifecycle_are_exact(tmp_path: Path) -> None:
    """Keep the confirmed O-2018 invocation and required FPV lifecycle stable."""

    adapter = get_adapter("vc_formal")
    tcl = adapter.render_tcl(
        filelist=Path("rtl/files.f"),
        top="dut",
        clock={"name": "clk", "period": 10},
        reset={"name": "rst_n", "sense": "low"},
    )
    assert tcl.splitlines() == [
        "analyze -format sverilog -vcs { -f rtl/files.f }",
        "elaborate -sva {dut}",
        "create_clock {clk} -period {10}",
        "create_reset {rst_n} -sense low",
        "sim_run -stable",
        "sim_save_reset",
        "check_fv -block",
        "report_fv -list",
        "report_fv -verbose",
        "exit",
    ]
    request = adapter.build_formal_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/fpv"),
        tcl_path=Path("formal/run.tcl"),
        filelist=Path("rtl/files.f"),
    )
    assert request.command.argv == [
        "vcf",
        "-batch",
        "-no_ui",
        "-no_restore",
        "-fmode",
        "FPV",
        "-out_dir",
        "{SESSION_DIR}",
        "-output_log_file",
        "console.log",
        "-f",
        "{WORKSPACE}/formal/run.tcl",
    ]
    with pytest.raises(ValueError, match="Tcl/VCS-safe"):
        adapter.render_tcl(
            filelist=Path("rtl/files.f;exec bad"),
            top="dut",
            clock={"name": "clk"},
            reset={"name": "rst_n"},
        )


def test_picker_urg_formalmc_and_verdi_build_expected_artifacts(tmp_path: Path) -> None:
    """Smoke the remaining adapter-specific paths and local-only FSDB command."""

    picker = get_adapter("picker").build_export_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/picker"),
        dut_name="Adder",
        top="Adder",
        source=Path("Adder.sv"),
        simulator="vcs",
        waveform="fsdb",
    )
    assert picker.command.tool == "picker"
    assert picker.command.argv == [
        "picker",
        "export",
        "{WORKSPACE}/Adder.sv",
        "--rw",
        "0",
        "--sname",
        "Adder",
        "--tname",
        "Adder",
        "--tdir",
        "{SESSION_DIR}/Adder",
        "--lang",
        "python",
        "--sim",
        "vcs",
        "-w",
        "Adder.fsdb",
        "--verdi-mode",
        "legacy",
    ]
    assert picker.artifact_paths == [Path("Adder")]
    urg = get_adapter("urg").build_merge_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/urg"),
        databases=[Path("runs/a/simv.vdb"), Path("runs/b/simv.vdb")],
    )
    assert urg.parser == "urg"
    assert urg.command.argv[-4:] == [
        "-dbname",
        "merged",
        "-report",
        "urg_report",
    ]
    assert urg.artifact_paths == [Path("merged.vdb"), Path("urg_report")]
    assert urg.result_paths[0] == Path("urg_report/dashboard.html")
    (tmp_path / "formal").mkdir()
    (tmp_path / "formal/run.tcl").write_text("prove\n", encoding="utf-8")
    formal = get_adapter("formal_mc").build_formal_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/formal_mc"),
        tcl_path=Path("formal/run.tcl"),
    )
    assert formal.command.argv[0] == "FormalMC"
    assert get_adapter("verdi_artifact").local_open_argv(Path("download/waves.fsdb")) == [
        "verdi",
        "-ssf",
        "download/waves.fsdb",
    ]
    profile = ToolchainProfile(id="vcs", tools={"vcs": "vcs"}, minimum_free_bytes=0)
    assert get_adapter("vcs").validate_profile(profile) == []


def test_picker_verilator_uses_mem_direct_and_relative_waveform(tmp_path: Path) -> None:
    """Keep Verilator on MEM_DIRECT without embedding the temporary session path."""

    request = get_adapter("picker").build_export_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/picker"),
        dut_name="Uart",
        top="uart_tx",
        source=Path("rtl/uart_tx.sv"),
        filelists=[Path("rtl/files.f")],
        simulator="verilator",
        waveform="fst",
        coverage=True,
    )

    assert request.command.argv[request.command.argv.index("--rw") + 1] == "1"
    assert request.command.argv[request.command.argv.index("--tdir") + 1] == "{SESSION_DIR}/Uart"
    assert request.command.argv[request.command.argv.index("-w") + 1] == "Uart.fst"
    assert "{SESSION_DIR}/Uart/Uart.fst" not in request.command.argv
    assert "-c" in request.command.argv
    assert request.command.argv[-2:] == ["--filelist", "{WORKSPACE}/rtl/files.f"]


@pytest.mark.parametrize(
    ("simulator", "waveform", "message"),
    [
        ("verilator", "fsdb", "Picker verilator waveform"),
        ("vcs", "fst", "Picker vcs waveform"),
        ("vcs", "vcd", "Picker vcs waveform"),
    ],
)
def test_picker_rejects_simulator_waveform_mismatches(
    tmp_path: Path,
    simulator: str,
    waveform: str,
    message: str,
) -> None:
    """Reject wave formats that the selected Picker simulator cannot emit."""

    with pytest.raises(ValueError, match=message):
        get_adapter("picker").build_export_request(
            workspace=tmp_path.resolve(),
            output_dir=Path("runs/picker"),
            dut_name="Adder",
            top="Adder",
            source=Path("Adder.sv"),
            simulator=simulator,
            waveform=waveform,
        )


def test_picker_omits_wave_and_coverage_flags_when_disabled(tmp_path: Path) -> None:
    """Match Picker's empty-wave and disabled-coverage defaults explicitly."""

    request = get_adapter("picker").build_export_request(
        workspace=tmp_path.resolve(),
        output_dir=Path("runs/picker"),
        dut_name="Adder",
        top="Adder",
        source=Path("Adder.sv"),
    )

    assert "-w" not in request.command.argv
    assert "-c" not in request.command.argv
    assert request.metadata["waveform"] == "none"
