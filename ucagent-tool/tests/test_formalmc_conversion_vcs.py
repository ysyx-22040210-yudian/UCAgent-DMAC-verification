"""Real VCS elaboration/replay of converted sampling and reset semantics."""
from pathlib import Path
import os
import subprocess

import pytest
from test_sby_guided_workflow import counter
from ucagent.eda.formalmc_conversion import render_target
from ucagent.eda.sby_guided import render_environment


@pytest.mark.parametrize("policy,edge,fault", [
    ("unconstrained", "posedge", None), ("unconstrained", "negedge", None),
    ("initial", "posedge", None), ("none", "posedge", None),
    ("unconstrained", "posedge", "increment"), ("unconstrained", "posedge", "reset"),
    ("unconstrained", "posedge", "property"), ("unconstrained", "posedge", "comb"),
])
def test_real_vcs_converted_properties(counter, tmp_path, policy, edge, fault):
    """Known directed traces must pass; increment/reset defects must trip converted assertions."""
    vcs = os.environ.get("UCAGENT_TEST_VCS")
    if not vcs:
        pytest.skip("Set UCAGENT_TEST_VCS to run real licensed compiler acceptance")
    paths, records = counter
    records.basic_info["clock_reset"]["clock_edge"] = edge
    records.extra_config["sby"]["reset_policy"] = policy
    if policy != "initial":
        records.extra_config["sby"].pop("reset_cycles", None)
    rtl_path = Path(paths.rtl_dir) / "Counter.sv"
    source = rtl_path.read_text().replace("@(posedge clk)", "@(" + edge + " clk)")
    if policy == "none":
        records.basic_info["clock_reset"]["reset_signal"] = ""
        records.basic_info["ports"]["inputs"] = [p for p in records.basic_info["ports"]["inputs"] if p["name"] != "rst_n"]
        records.extra_config["sby"].pop("reset_active", None)
        points = records.spec.function_groups[1].functions[0].check_points
        points.pop()
        points[0].sby_guard = "uc_past_valid && $past(en)"
        records.spec.function_groups[-1].functions[0].check_points[0].sva_body = "y == 3"
        source = source.replace("clk, rst_n, en", "clk, en").replace("if (!rst_n) y <= 0; else ", "")
        source = source.replace("output reg [3:0] y", "output reg [3:0] y = 0")
    if fault == "increment":
        source = source.replace("y + 4'd1", "y + 4'd2")
    if fault == "reset":
        source = source.replace("y <= 0", "y <= 7")
    rtl_path.write_text(source)
    # Exercise signed-vector conversion as a genuine additional invariant.
    from ucagent.lang.zh.skills.formal.lib.models import CheckPoint
    records.spec.function_groups[1].functions[0].check_points.append(CheckPoint(
        id="CK-SIGNED", style="Seq", description="Signed four-bit interpretation",
        sva_body="($signed(y) < 0) == y[3]", sby_guard="uc_past_valid" if policy == "none" else "uc_past_valid && rst_n"))
    if fault == "property":
        records.spec.function_groups[1].functions[0].check_points[0].sva_body = "y == ($past(y) + 4\'d2)"
    if fault == "comb":
        records.spec.function_groups[1].functions[0].check_points.append(CheckPoint(
            id="CK-COMB", style="Comb", description="Four-bit unsigned bound",
            sva_body="y <= 4\'hf", sby_guard="rst_n"))
    checker, wrapper, _ = render_target(records, render_environment(paths, records))
    target = tmp_path / "target"
    target.mkdir()
    (target / "checker.sv").write_text(checker)
    (target / "wrapper.sv").write_text(wrapper)
    ports = ".clk(clk), .en(en)" + (", .rst_n(rst_n)" if policy != "none" else "")
    cycle = "#5 clk=1; #5 clk=0;"
    reset_again = "#1 rst_n=0; repeat(3) begin " + cycle + " end #1 rst_n=1;" if policy == "unconstrained" else ""
    bench = """module tb;
reg clk=0, rst_n=0, en=0;
Counter_wrapper dut(PORTS);
initial begin
repeat(INIT_CYCLES) begin CYCLE end
#1 rst_n=1; en=1;
repeat(20) begin CYCLE end
 #1 en=0; repeat(3) begin CYCLE end
RESET_AGAIN
en=1; repeat(6) begin CYCLE end
$display("REPLAY_FINISHED"); $finish;
end
endmodule
""".replace("INIT_CYCLES", str(records.extra_config["sby"].get("reset_cycles", 2))).replace("PORTS", ports).replace("CYCLE", cycle).replace("RESET_AGAIN", reset_again)
    (target / "tb.sv").write_text(bench)
    command = [vcs, "-full64", "-sverilog", "-assert", "svaext", "-top", "tb",
               str(rtl_path), "checker.sv", "wrapper.sv", "tb.sv", "-o", "simv",
               "-LDFLAGS", "-Wl,--no-as-needed"]
    compile_log = subprocess.run(command, cwd=target, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=120)
    (target / "compile.log").write_text(compile_log.stdout)
    assert compile_log.returncode == 0, compile_log.stdout[-7000:]
    replay = subprocess.run([str(target / "simv"), "+vcs+lic+wait"], cwd=target, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    (target / "replay.log").write_text(replay.stdout)
    acceptance = os.environ.get("UCAGENT_EXPORT_ACCEPTANCE_DIR")
    if acceptance:
        import shutil
        output = Path(acceptance) / (policy + "-" + edge + "-" + str(fault))
        output.mkdir(parents=True, exist_ok=True)
        for name in ("compile.log", "replay.log", "checker.sv", "wrapper.sv", "tb.sv"):
            shutil.copyfile(target / name, output / name)
        shutil.copyfile(rtl_path, output / "Counter.sv")
    assert "REPLAY_FINISHED" in replay.stdout, replay.stdout
    if fault in {"increment", "reset", "property"}:
        expected = "A_CK_RESET" if fault == "reset" else "A_CK_COUNT"
        assert expected in replay.stdout and " failed" in replay.stdout, replay.stdout
    else:
        assert "Error" not in replay.stdout and " failed" not in replay.stdout, replay.stdout
