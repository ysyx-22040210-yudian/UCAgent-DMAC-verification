"""Run bounded enhancement checks as the existing non-root VM execution identity."""

import argparse
import json
import os
from pathlib import Path

from ucagent.eda.models import ToolchainProfile
from ucagent.eda.npi import build_npi_bridge
from ucagent.eda.npi import NpiQuery, build_npi_request, query_wire_data, read_npi_result
from ucagent.eda.adapters.vcs import VcsAdapter
from ucagent.eda.runner import JobRunner
import yaml


def main():
    """Build our bridge against the installed SDK and print only non-secret evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("build", "roundtrip"), default="build")
    arguments = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run this check as the ucagent execution identity, not root")
    root = Path(__file__).resolve().parents[1]
    profile = ToolchainProfile(id="npi-sdk-build", tools={"cxx": "/usr/bin/g++"},
        environment={"TMPDIR": "/home/ucagent-lab/tmp"}, execution_user="ucagent")
    request = build_npi_bridge(workspace=root, source=Path("ucagent/eda/native/npi_bridge.cpp"),
        sdk_include=Path("/home/synopsys/verdi/Verdi_O-2018.09-SP2/share/NPI/inc"),
        output_dir=Path(arguments.output))
    signing_key = Path("/home/ucagent-lab/state/.ucagent/platform/manifest.key").read_bytes()
    runner = JobRunner(signing_key)
    result = runner.run(request, profile)
    print(json.dumps({"step": "build", "execution_status": result.execution_status,
                      "manifest": str(result.manifest_path), "diagnostics": result.diagnostics}), flush=True)
    if result.execution_status != "completed" or arguments.mode == "build":
        return 0 if result.execution_status == "completed" else 1
    config = yaml.safe_load(Path("/home/ucagent-lab/config/toolchains.yaml").read_text())
    payload = config["profiles"]["synopsys_o2018"]
    payload["id"] = "synopsys_o2018"
    profile = ToolchainProfile.model_validate(payload)
    environment = dict(profile.environment)
    for name in profile.license_environment_names:
        if name in os.environ:
            environment[name] = os.environ[name]
    profile = profile.model_copy(update={"environment": environment,
        "tools": {**profile.tools, "npi": "/home/synopsys/verdi/Verdi_O-2018.09-SP2/bin/npi", "perl": "/usr/bin/perl"}})
    vcs = VcsAdapter()
    base = Path(arguments.output)
    compiled = runner.run(vcs.build_compile_request(workspace=root, output_dir=base / "compile",
        top="npi_roundtrip", sources=[Path("acceptance/fixtures/npi_roundtrip.sv")],
        coverage=["line", "branch", "tgl"], waveform="fsdb", fsdb_pli=profile.require_fsdb_pli(),
        timeout_seconds=120), profile)
    print(json.dumps({"step": "vcs_compile", "execution_status": compiled.execution_status,
                      "manifest": str(compiled.manifest_path), "diagnostics": compiled.diagnostics}), flush=True)
    if compiled.execution_status != "completed":
        return 1
    simulated = runner.run(vcs.build_simulation_request(workspace=root, output_dir=base / "simulate",
        executable=base / "compile/simv", coverage_database=base / "compile/simv.vdb",
        test_name="npi_oracle", seed=11, coverage=["line", "branch", "tgl"], waveform="fsdb",
        fsdb_runtime_library_path=profile.fsdb_runtime_library_path(), expect_waveform_artifact=True,
        success_markers=["NPI_ROUNDTRIP_PASSED"], timeout_seconds=60), profile)
    print(json.dumps({"step": "vcs_simulate", "execution_status": simulated.execution_status,
                      "verification_status": simulated.verification_status,
                      "manifest": str(simulated.manifest_path), "diagnostics": simulated.diagnostics}), flush=True)
    if simulated.execution_status != "completed":
        return 1
    checks = (("waveform", base / "simulate/waves.fsdb", ""),
              ("hierarchy", base / "compile/simv.daidir", ""),
              ("coverage", base / "simulate/simv.vdb", "test"))
    passed = True
    for operation, database, selector in checks:
        query = NpiQuery(artifact_id="acceptance", operation=operation, selector=selector,
                         signals=["npi_roundtrip.pixel"] if operation == "waveform" else [],
                         end=20000, max_depth=16, max_objects=1000)
        controls = root / base / (operation + ".request")
        controls.write_text(query_wire_data(query, root / database), encoding="utf-8")
        request = build_npi_request(workspace=root, bridge=base / "bridge.so", request_file=controls.relative_to(root),
            database=database, output_dir=base / ("query-" + operation), query=query,
            npi_script=Path(profile.require_tool("npi")))
        queried = runner.run(request, profile)
        details = read_npi_result(queried.session_dir / "result.json", query) if queried.execution_status == "completed" else None
        print(json.dumps({"step": operation, "execution_status": queried.execution_status,
                          "manifest": str(queried.manifest_path), "details": details, "diagnostics": queried.diagnostics}), flush=True)
        passed = passed and bool(details and details["status"] == "ok")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
