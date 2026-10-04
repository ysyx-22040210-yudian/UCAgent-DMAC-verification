"""Drive real Tk controls against an independently running backend and installed SBY."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from ucagent_tk.app import Application
from ucagent_tk.formal import FormalSessionView
from ucagent_tk.dialogs import DownloadDialog
from ucagent_tk.i18n import tr
from ucagent_tk.model import Preferences


def main():
    """Verify create, edit, review, native stage advancement, evidence and reconnection."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--screenshot", type=Path, help="Capture the isolated Xvfb test display only.")
    args = parser.parse_args()
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda kind, value, trace: errors.append(str(value))
    with tempfile.TemporaryDirectory(prefix="formal-gui-client-") as directory:
        app = Application(root, args.origin, Preferences(Path(directory) / "preferences.json"))
        def spin(predicate, timeout=60):
            """Pump actual Tk callbacks until the backend result is visible or timeout is reached."""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                root.update()
                if predicate():
                    return
                time.sleep(0.01)
            raise AssertionError("GUI timeout: " + app.message.cget("text"))
        try:
            spin(lambda: not app.pending)
            project = app.client.call("/projects", "POST", {"name": "Formal GUI Counter acceptance", "path": str(args.fixture)})
            app.show("formal_sessions")
            spin(lambda: bool(app.view.projects))
            dialog = app.view.create()
            dialog.form.fields["dut"].set("Counter")
            dialog.form.fields["engine"].set("sby")
            dialog.form.fields["review"].set("true")
            dialog.button.invoke()
            spin(lambda: isinstance(app.view, FormalSessionView) and app.view.row is not None)
            view = app.view
            identifier = view.row["id"]
            assert len(view.tree.records) == 14
            assert not view.tree.records["counterexample_python_testgen"]["enabled"]
            assert "COI" in view.capabilities.cget("text")
            for geometry in ("1120x760", "1440x940"):
                root.geometry(geometry)
                for tab, control in ((view.agent_tab, view.buttons["agent"]), (view.review_tab, view.journal_button), (1, view.save_button)):
                    view.tabs.select(tab)
                    root.update()
                    assert control.winfo_viewable()
                    assert control.winfo_rooty() + control.winfo_height() <= root.winfo_rooty() + root.winfo_height()
                assert view.buttons["reopen"].winfo_rootx() + view.buttons["reopen"].winfo_width() <= root.winfo_rootx() + root.winfo_width()
                assert view.download_button.winfo_viewable()
                assert view.download_button.winfo_rootx() + view.download_button.winfo_width() <= root.winfo_rootx() + root.winfo_width()
            def read(path):
                """Use the editor's real file-read callback and await its content hash."""
                view.opened_file = None
                view.tabs.select(1)
                view.path.set(path)
                view.read_file()
                spin(lambda: view.opened_file and view.opened_file["path"] == path and not app.pending)
            def save(content):
                """Review the native diff window and click its explicit save confirmation."""
                view.editor.set(content)
                view.review_edit()
                window = next(child for child in view.winfo_children() if isinstance(child, tk.Toplevel))
                button = next(child for child in window.winfo_children() if isinstance(child, ttk.Button))
                button.invoke()
                spin(lambda: not app.pending and view.opened_file["content"] == content)
            def click(name):
                """Click the visible action and wait for its actual asynchronous server result."""
                revision = view.row["revision"]
                view.buttons[name].invoke()
                spin(lambda: view.row["revision"] > revision and view.row["state"] != "running" and not app.pending, timeout=90)
            read("formal_out/.formal_records.yaml")
            save((args.fixture / "records.json").read_text(encoding="utf-8"))
            click("pause")
            assert view.row["state"] == "paused"
            click("resume")
            reviewed = False
            for _ in range(20):
                if view.row["view"]["all_completed"]:
                    break
                index = view.row["view"]["current_index"]
                if index == 8 and not reviewed:
                    assert view.row["verification_status"] == "passed"
                    observed = view.row["evidence"]["input_sha256"]
                    read("formal_out/.formal_records.yaml")
                    # JSON is valid YAML. Read the current normalized records through
                    # a backend-provided JSON view, preserving tool-owned results.
                    data = app.client.call(view.endpoint + "/records")
                    data["extra_config"]["sby"]["review"] = {
                        "input_sha256": observed,
                        "assumptions": {"M_CK_API": "Enable remains unrestricted; this assumption adds no behavior constraints.",
                                        "M_ENV_RESET": "The acceptance scenario begins with one active reset cycle."},
                        "limitations": "COI, full vacuity and unbounded liveness are not established in this integration."}
                    save(json.dumps(data, indent=2))
                    reviewed = True
                current = next(node for node in view.tree.records.values() if node["current"])
                for path in current["details"]["task"]["reference_files"]:
                    read(path.replace("\\", "/"))
                view.tabs.select(view.review_tab)
                view.journal.set("Reviewed current requirements, authored inputs and actual evidence scope.")
                click("check")
                assert view.row["last_result"].get("check_pass"), view.row["last_result"]
                click("approve")
                click("complete")
                assert view.row["view"]["current_index"] > index, view.row["last_result"]
            assert view.row["view"]["all_completed"] and view.row["verification_status"] == "passed"
            files = app.client.call(view.endpoint + "/files")["items"]
            trace = next(item["path"] for item in files if item["path"].endswith(".vcd"))
            destination = args.output.parent / ("gui-trace-" + identifier + ".vcd")
            view.path.set(trace)
            with patch("ucagent_tk.dialogs.filedialog.asksaveasfilename", return_value=str(destination)):
                view.download_file()
                spin(lambda: any(isinstance(child, DownloadDialog) for child in root.winfo_children()))
            transfer = next(child for child in root.winfo_children() if isinstance(child, DownloadDialog))
            spin(lambda: transfer.finished)
            assert transfer.result and destination.is_file()
            transferred = transfer.result
            transfer.close()
            revision = view.row["revision"]
            app.show("formal_sessions")
            spin(lambda: bool(app.view.table.records))
            app.show("formal_session", identifier)
            spin(lambda: app.view.row is not None)
            assert app.view.row["revision"] == revision
            assert not errors, errors
            if args.screenshot:
                node = app.view.tree.records["environment_debugging_iteration"]
                app.view.tree.tree.selection_set(node["id"])
                app.view.select_stage(node)
                root.update()
                assert tr("formal_gate_passed") in app.view.task_text.get()
                assert tr("formal_gate_passed") != tr("passed")
                subprocess.run(["gnome-screenshot", "-f", str(args.screenshot)], check=True, timeout=15)
            args.output.write_text(json.dumps({"python": sys.version, "session_id": identifier, "project_id": project["id"],
                                              "native_tk": True, "real_backend": True, "all_enabled_stages_completed": True,
                                              "verification_status": app.view.row["verification_status"],
                                              "capabilities": app.view.row["capabilities"], "download": transferred, "callback_errors": errors}, indent=2), encoding="utf-8")
            print("FORMAL_GUI_LIVE_ACCEPTANCE_PASSED " + identifier)
        finally:
            with patch("ucagent_tk.formal.messagebox.askyesno", return_value=True):
                app.close()
            spin(lambda: app.closed)


if __name__ == "__main__":
    main()
