"""Exercise the shipped desktop/API/SBY package against real isolated RTL jobs."""

import argparse
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import threading
import time
import zlib


def main():
    """Create fresh ordinary-user state and retain the actual acceptance evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--require-offline", action="store_true")
    parser.add_argument("--screenshots", action="store_true", help="Capture only the tested Tk windows using Xvfb/xwd")
    parser.add_argument("--toolchains", type=Path, help="Optional real host profiles for dual-engine acceptance")
    parser.add_argument("--vcf-profile", help="Probe this installed VCF profile and exercise the native engine selector")
    args = parser.parse_args()
    if args.vcf_profile and (not args.toolchains or args.require_offline):
        parser.error("VCF selection acceptance requires --toolchains and the real license network, not --require-offline")
    if args.data.exists():
        raise ValueError("Acceptance requires a fresh data directory, never existing user state")
    bundle = args.bundle.resolve(strict=True)
    sys.path.insert(0, str(bundle / "UCAgent-Desktop.pyz"))
    from ucagent_tk.client import ApiClient, ApiError, collection
    from ucagent_tk.local_service import LocalService
    from ucagent_tk.model import Preferences, initial_draft
    service = LocalService(bundle, args.data, toolchains=args.toolchains)
    report = {"bundle": str(bundle), "python": platform.python_version(), "system": platform.platform(), "runs": [], "checks": []}
    if args.require_offline:
        report["network_devices"] = [line.split(":")[0].strip() for line in Path("/proc/net/dev").read_text().splitlines()[2:]]
        assert report["network_devices"] == ["lo"], report["network_devices"]
    root, app, errors = None, None, []

    def wait(predicate, timeout=45):
        """Wait for bounded asynchronous work while keeping native Tk responsive."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if root:
                root.update()
            if errors:
                raise AssertionError(errors)
            result = predicate()
            if result:
                return result
            time.sleep(0.04)
        raise TimeoutError("Acceptance operation exceeded its deadline")

    def capture(window, name):
        """Capture only a tested native X11 window, not other desktop applications."""
        if not args.screenshots:
            return
        root.update()
        raw = subprocess.check_output(["xwd", "-silent", "-id", str(window.winfo_id())], timeout=10)
        fields = struct.unpack(">25I", raw[:100])
        header_size, version, fmt, depth, width, height = fields[:6]
        if version != 7 or fmt != 2 or depth != 24 or fields[11] != 32 or fields[14:17] != (0xff0000, 0xff00, 0xff):
            raise ValueError("Screenshot requires a 24-bit TrueColor Xvfb display")
        offset, stride = header_size + fields[19] * 12, fields[12]
        pixels = bytearray()
        for row in range(height):
            pixels.append(0)
            for column in range(width):
                position = offset + row * stride + column * 4
                value = int.from_bytes(raw[position:position + 4], "little" if fields[7] == 0 else "big")
                pixels.extend(((value >> 16) & 255, (value >> 8) & 255, value & 255))
        output = bytearray(b"\x89PNG\r\n\x1a\n")
        for kind, payload in ((b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)), (b"IDAT", zlib.compress(pixels)), (b"IEND", b"")):
            output.extend(struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))
        (args.data / (name + ".png")).write_bytes(output)

    try:
        client = service.start()
        try:
            ApiClient(client.origin).call("/overview")
            raise AssertionError("Unauthenticated local API unexpectedly accepted a request")
        except ApiError as exc:
            assert "401" in str(exc), str(exc)
        report["checks"].append("private_authenticated_listener")
        projects = {item["name"]: item for item in collection(client.call("/projects"))}
        assert set(projects) == {"sby_counter", "sby_counter_bug"}, projects
        probe = client.call("/toolchains/bundled_sby/probe", "POST", {}, timeout=60)
        assert all(item["available"] for item in probe["capabilities"]), probe
        report["checks"].append("all_four_real_tool_probes")
        if args.vcf_profile:
            probe = client.call("/toolchains/" + args.vcf_profile + "/probe", "POST", {}, timeout=180)
            vcf = next(item for item in probe["capabilities"] if item["name"] == "vcf")
            report["vcf_probe"] = {key: vcf.get(key) for key in ("name", "binary_available", "available", "license_status", "version_probe_status", "license_probe_status")}
            assert vcf["binary_available"], report["vcf_probe"]
            report["checks"].append("real_vcf_checkout_observed_without_claiming_proof_pass")
        if args.gui:
            os.environ["FONTCONFIG_FILE"] = str(service.fontconfig)
            import tkinter as tk
            from unittest.mock import patch
            from ucagent_tk.app import Application
            from ucagent_tk.wizard import RunWizard
            root = tk.Tk()
            from tkinter import font as tkfont
            assert "Noto Sans CJK SC" in tkfont.families(root), "Bundled CJK font was not discovered"
            report["font"] = "Noto Sans CJK SC"
            root.report_callback_exception = lambda kind, value, traceback: errors.append(str(value))
            app = Application(root, None, Preferences(args.data / "preferences.json"), local_service=service)
            wait(lambda: bool(app.view.projects.records))
            from ucagent_tk.i18n import tr
            assert app.lifecycle_hint.cget("text") == tr("local_restart_warning")
            health = app.view.tool_health
            labels = [health.itemcget(item, "text") for item in health.find_all() if health.type(item) == "text"]
            assert set(("VC Formal", "SBY") if args.vcf_profile else ("SBY", "Yosys", "SMTBMC", "Z3")).issubset(labels), labels
            report["checks"].append("local_lifecycle_and_open_tool_visibility")
            capture(root, "workbench")
            app.new_run(projects["sby_counter"]["id"])
            wizard = wait(lambda: next((item for item in root.winfo_children() if isinstance(item, RunWizard)), None))
            wizard.advance()
            assert wizard.form.fields["engine"].get() == "sby"
            assert "sby_depth" in wizard.form.fields and not wizard.form.controls["clock"].winfo_ismapped()
            capture(wizard, "sby-wizard")
            if args.vcf_profile:
                saved_depth = wizard.form.fields["sby_depth"].get()
                wizard.form.fields["engine"].set("vc_formal")
                wizard.change_engine()
                root.update()
                assert wizard.draft["formal"]["engine"] == "vc_formal"
                assert wizard.draft["toolchain"] == args.vcf_profile
                assert wizard.form.controls["clock"].winfo_ismapped()
                assert not wizard.form.fields["clock"].get(), "Switching cannot invent VCF timing constraints"
                assert "sby" not in wizard.draft["formal"]
                capture(wizard, "vcf-wizard")
                wizard.form.fields["engine"].set("sby")
                wizard.change_engine()
                assert wizard.draft["toolchain"] == "bundled_sby"
                assert wizard.form.fields["sby_depth"].get() == saved_depth
                report["checks"].append("native_vcf_sby_selection_and_separate_parameters")
            wizard.advance()
            wait(lambda: str(wizard.continue_button.cget("state")) == "normal")
            assert wizard.preview and wizard.preview["ready"], wizard.preview
            wizard.advance()
            wait(lambda: bool(collection(client.call("/runs"))))
            native_run = collection(client.call("/runs"))[0]
            wait(lambda: client.call("/runs/" + native_run["id"])["execution_status"] not in {"queued", "running"})
            report["native_run"] = client.call("/runs/" + native_run["id"])
            assert report["native_run"]["verification_status"] == "passed", report["native_run"]
            report["checks"].append("native_tk_wizard_real_proof")
            with patch("ucagent_tk.app.messagebox.askyesno", return_value=True):
                app.close()
            wait(lambda: app.closed)
            root, app = None, None
        for name, project_name, mode, depth, expected in (
            ("prove", "sby_counter", "prove", 20, "passed"),
            ("counterexample", "sby_counter_bug", "prove", 20, "failed"),
            ("bounded", "sby_counter", "bmc", 5, "inconclusive"),
            ("cover", "sby_counter", "cover", 20, "passed"),
            ("cover_miss", "sby_counter", "cover", 2, "inconclusive"),
        ):
            body = initial_draft(projects[project_name])
            body["formal"]["sby"].update(mode=mode, depth=depth)
            preview = client.call("/runs/preview", "POST", body)
            assert preview["ready"], preview
            run = client.call("/runs", "POST", body)
            path = "/runs/" + run["id"]
            wait(lambda: client.call(path)["execution_status"] not in {"queued", "running"})
            finished = client.call(path)
            assert finished["execution_status"] == "completed" and finished["verification_status"] == expected, finished
            properties = collection(client.call(path + "/properties"))
            artifacts = collection(client.call(path + "/artifacts"))
            stages = collection(client.call(path + "/stages"))
            assert not any(stage["enabled"] and stage["execution_status"] in {"queued", "running"} for stage in stages), stages
            item = {"case": name, "id": run["id"], "execution_status": finished["execution_status"], "verification_status": finished["verification_status"], "properties": properties, "stages": stages, "artifacts": artifacts}
            report["runs"].append(item)
            if name == "counterexample":
                waves = [artifact for artifact in artifacts if str(artifact.get("path", "")).endswith(".vcd")]
                assert waves, artifacts
                item["download"] = client.download(waves[0], args.data / "counterexample.vcd", threading.Event())
            stream = client.events(run["id"], 0, threading.Event())
            first = next(stream)
            stream.close()
            stream = client.events(run["id"], first["sequence"], threading.Event())
            assert next(stream)["sequence"] > first["sequence"]
            stream.close()
            print(json.dumps({"case": name, "run": run["id"], "status": expected}), flush=True)
        for name in ("timeout", "cancel", "shutdown_cancel", "syntax_error"):
            body = initial_draft(projects["sby_counter"])
            body["formal"]["sby"].update(mode="bmc", depth=100000, timeout_seconds=1 if name == "timeout" else 120)
            if name == "syntax_error":
                bad_source = Path(projects["sby_counter"]["path"]) / "invalid.sv"
                bad_source.write_text("module counter(; this is not valid HDL", encoding="utf-8")
                body["design"]["sources"] = ["invalid.sv"]
            run = client.call("/runs", "POST", body)
            path = "/runs/" + run["id"]
            if name in {"cancel", "shutdown_cancel"}:
                wait(lambda: any(job["execution_status"] == "running" for job in collection(client.call(path + "/jobs"))))
                if name == "cancel":
                    client.call(path + "/cancel", "POST", {})
                else:
                    service.close()
                    service = LocalService(bundle, args.data, toolchains=args.toolchains)
                    client = service.start()
            wait(lambda: client.call(path)["execution_status"] not in {"queued", "running"})
            finished = client.call(path)
            expected = "error" if name == "syntax_error" else "cancelled" if "cancel" in name else "timeout"
            assert finished["execution_status"] == expected, finished
            assert finished["verification_status"] != "passed", finished
            report["runs"].append({"case": name, "id": run["id"], "execution_status": finished["execution_status"], "verification_status": finished["verification_status"], "properties": collection(client.call(path + "/properties"))})
            print(json.dumps({"case": name, "run": run["id"], "status": expected}), flush=True)
        structured = args.data / "projects" / "literal inputs"
        (structured / "rtl/inc").mkdir(parents=True)
        (structured / "lists/nested").mkdir(parents=True)
        (structured / "rtl/inc/settings.vh").write_text("localparam STEP = `COUNT_STEP;\n")
        (structured / "rtl/structured top.sv").write_text("module counter #(parameter W=4)(input clk);\n`include \"settings.vh\"\nreg [W-1:0] count=0; reg valid=0; always @(posedge clk) begin valid<=1; count<=count+STEP; if(valid) increment_ok: assert(count == $past(count)+W'(STEP)); end endmodule\n")
        (structured / "lists/inputs.f").write_text("-F nested/rtl.f\n")
        (structured / "lists/nested/rtl.f").write_text('+incdir+../../rtl/inc\n+define+COUNT_STEP=1\n"../../rtl/structured top.sv"\n')
        config = {"schema_version": 1, "design": {"top": "counter", "filelists": ["lists/inputs.f"], "parameters": {"W": 6}}, "workflow": {"family": "formal", "methodology": "systemverilog"}, "toolchain": "bundled_sby", "formal": {"engine": "sby", "cex_replay": {"enabled": False}}}
        imported = client.call("/projects", "POST", {"name": "literal inputs", "path": str(structured), "config": config})
        body = initial_draft(imported)
        preview = client.call("/runs/preview", "POST", body)
        assert preview["ready"], preview
        run = client.call("/runs", "POST", body)
        path = "/runs/" + run["id"]
        wait(lambda: client.call(path)["execution_status"] not in {"queued", "running"})
        finished = client.call(path)
        assert finished["execution_status"] == "completed" and finished["verification_status"] == "passed", finished
        report["runs"].append({"case": "literal_filelists_includes_defines_parameters_spaces", "id": run["id"], "execution_status": "completed", "verification_status": "passed", "properties": collection(client.call(path + "/properties"))})
        # A concurrent start must fail before it can recover or mutate live state.
        duplicate = LocalService(bundle, args.data, toolchains=args.toolchains)
        try:
            duplicate.start()
            raise AssertionError("A duplicate local service started with the same data")
        except RuntimeError:
            pass
        finally:
            duplicate.close()
        report["checks"].append("exclusive_data_lock")
        before = {item["id"] for item in collection(client.call("/runs"))}
        service.close()
        service = LocalService(bundle, args.data, toolchains=args.toolchains)
        client = service.start()
        assert {item["id"] for item in collection(client.call("/runs"))} == before
        for run in report["runs"]:
            assert client.call("/runs/" + run["id"])["verification_status"] == run["verification_status"]
            assert collection(client.call("/runs/" + run["id"] + "/properties")) == run["properties"]
        report["checks"].extend(["history_properties_artifacts_restart", "sse_cursor_resume", "sha256_waveform_download"])
        report["status"] = "passed"
    finally:
        if app:
            from unittest.mock import patch
            with patch("ucagent_tk.app.messagebox.askyesno", return_value=True):
                app.close()
            wait(lambda: app.closed)
        service.close()
        report["tk_errors"] = errors
        (args.data / "acceptance.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": report["checks"], "evidence": str(args.data / "acceptance.json")}), flush=True)


if __name__ == "__main__":
    main()
