"""Validate actual SBY input closure, macro and memory relocation across an conversion."""
import json
from pathlib import Path

import pytest
from test_sby_guided_workflow import counter, real_session
from ucagent.eda.formalmc_conversion import convert_sby_to_formalmc
from ucagent.eda.sby_guided import render_environment
from ucagent.lang.zh.skills.formal.lib.formal_tools import save_records
from ucagent.platform.project import load_project_config


def test_real_nested_files_macros_parameters_and_memory(real_session, tmp_path):
    """Compile real include/memory dependencies, preserve order and detect changed initialization."""
    session, records = real_session
    root = Path(session.workspace)
    inc = root / "Counter/include"
    (inc / "nested").mkdir(parents=True)
    (inc / "nested/step.vh").write_text("`define STEP_DEFAULT 1\n")
    (inc / "top.vh").write_text('`include "nested/step.vh"\n')
    (inc / "lut.hex").write_text("0\n")
    (root / "Counter/inner.f").write_text("+incdir+include\n+define+REQUIRED_DEFINE=1\nCounter.sv\n")
    (root / "Counter/outer.f").write_text("-F inner.f\n")
    (root / "Counter/Counter.sv").write_text(
        '`include "top.vh"\n'
        'module Counter #(parameter STEP=`STEP_DEFAULT)(input wire clk,rst_n,en,output reg [3:0] y);\n'
        f'reg [3:0] rom[0:0]; initial $readmemh("{(inc / "lut.hex").as_posix()}",rom);\n'
        'always @(posedge clk) if(!rst_n) y<=rom[0]; else if(en) y<=y+STEP;\n'
        'endmodule\n')
    records.spec.parameters = {"STEP": 1}
    records.extra_config["sby"]["filelists"] = ["Counter/outer.f"]
    session.collect(render_environment(session.paths, records), execute=True)
    save_records(session.paths.records_yaml, records)
    files, report = convert_sby_to_formalmc(root, "Counter", session.key)
    moved = tmp_path / "relocated project"
    for name, content in files.items():
        path = moved / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    assert (moved / "inputs/Counter/include/lut.hex").read_text() == "0\n"
    assert report["memory_path_rewrites"] == [{"file": "inputs/Counter/Counter.sv",
        "original": str(inc / "lut.hex"), "packaged": "inputs/Counter/include/lut.hex"}]
    assert report["effective_defines"]["FORMAL"] == "1"
    assert report["effective_defines"]["YOSYS"] == "1"
    assert report["effective_defines"]["REQUIRED_DEFINE"] == "1"
    assert load_project_config(moved).formal.engine == "formalmc"
    assert "localparam STEP = 1;" in (moved / "formal/Counter_wrapper.sv").read_text()

    if __import__("os").environ.get("UCAGENT_TEST_VCS"):
        import os
        import subprocess
        # VCS 2018 links incorrectly when its physical cwd contains spaces.
        # The package check/Tcl tests retain the spaced root; replay uses another root.
        moved = tmp_path / "relocated_vcs"
        for name, content in files.items():
            path = moved / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        manifest = json.loads((moved / "conversion_inputs.json").read_text())
        (moved / "tb.sv").write_text("""
module tb;
reg clk=0,rst_n=0,en=0;
Counter_wrapper dut(.clk(clk),.rst_n(rst_n),.en(en));
initial begin
#5 clk=1; #5 clk=0; #1 rst_n=1; en=1;
repeat(24) begin #5 clk=1; #5 clk=0; end
$display("MEMORY_REPLAY_FINISHED"); $finish;
end
endmodule
""")
        cmd = [os.environ["UCAGENT_TEST_VCS"], "-full64", "-sverilog", "-assert", "svaext",
               "-top", "tb", *["+incdir+" + d for d in manifest["include_dirs"]],
               *manifest["compile_sources"], "tb.sv", "-o", "simv", "-LDFLAGS", "-Wl,--no-as-needed"]
        compiled = subprocess.run(cmd, cwd=moved, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        assert compiled.returncode == 0, compiled.stdout[-6000:]
        replayed = subprocess.run([str(moved / "simv")], cwd=moved, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        assert "MEMORY_REPLAY_FINISHED" in replayed.stdout and " failed" not in replayed.stdout, replayed.stdout
        output = os.environ.get("UCAGENT_EXPORT_ACCEPTANCE_DIR")
        if output:
            destination = Path(output) / "relocated-memory"
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "compile.log").write_text(compiled.stdout)
            (destination / "replay.log").write_text(replayed.stdout)

    (inc / "lut.hex").write_text("1\n")
    with pytest.raises(ValueError, match="hash"):
        convert_sby_to_formalmc(root, "Counter", session.key)
