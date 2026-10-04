"""Drive real native widgets against the configured VM; EDA writes require --execute."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

def main():
    """Perform native read-only QA or explicitly launch isolated real acceptance runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8800")
    parser.add_argument("--execute", action="store_true", help="Authorize new Adder pass/fail and UART UVM test runs")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--visual-review", action="store_true", help="Capture all native pages, run evidence, search, forms, and minimum window layouts without creating runs")
    parser.add_argument("--output", required=True)
    parser.add_argument("--package", help="Test this built zipapp or installed package directory instead of the source tree")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(args.package).resolve() if args.package else Path(__file__).resolve().parents[1]))
    from ucagent_tk.app import Application
    from ucagent_tk.dialogs import CommandPalette, import_project, scaffold
    from ucagent_tk.model import Preferences
    from ucagent_tk.views import RunView
    from ucagent_tk.wizard import RunWizard
    from ucagent_tk import __file__ as package_path
    from capture import capture_window
    output = Path(args.output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="ucagent-tk-acceptance-")
    root = tk.Tk()
    root.geometry("1380x860+80+40")
    errors = []
    root.report_callback_exception = lambda kind, value, traceback: errors.append(str(value))
    app = Application(root, args.server, Preferences(Path(temporary.name) / "preferences.json"))
    report = {"python": platform.python_version(), "tk": root.tk.call("info", "patchlevel"), "package_path": package_path, "server": app.client.origin, "started_at": datetime.now(timezone.utc).isoformat(), "pages": [], "runs": [], "errors": errors}

    def wait(predicate, timeout=30):
        """Keep the real Tk loop responsive while waiting for actual service results."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if errors:
                raise AssertionError("Tk callback errors: " + repr(errors))
            if predicate():
                return
            time.sleep(0.015)
        raise TimeoutError("Native operation timed out: " + app.message.cget("text"))

    def snapshot(name, window=None):
        """Record the exact rendered native window for visual QA when running on Windows."""
        root.update()
        if sys.platform == "win32":
            capture_window(window or root, output / (name + ".png"))

    def open_wizard(project_id):
        """Use the application's normal async action to open an actual project run wizard."""
        app.new_run(project_id)
        wait(lambda: any(isinstance(child, RunWizard) for child in root.winfo_children()))
        return next(child for child in root.winfo_children() if isinstance(child, RunWizard))

    try:
        wait(lambda: bool(app.view.projects.records))
        projects = dict(app.view.projects.records)
        recent_runs = list(app.view.runs.records.values())
        snapshot("01-workbench")
        checks = [("projects", lambda view: bool(view.table.records)), ("runs", lambda view: bool(view.rows)),
                  ("workflows", lambda view: bool(view.tree.records)), ("toolchains", lambda view: bool(view.capabilities.records)),
                  ("mcp", lambda view: bool(view.tools.records)), ("settings", lambda view: str(view.button.cget("state")) == "normal")]
        for page, ready in checks:
            app.show(page)
            wait(lambda: ready(app.view))
            assert not app.message.cget("text"), app.message.cget("text")
            report["pages"].append(page)
            if args.visual_review:
                snapshot("studio-" + page)
            if page == "workflows":
                for workflow in app.view.workflows:
                    app.view.selected.set(workflow)
                    app.view.show_workflow()
                    assert app.view.tree.records
                report["workflow_count"] = len(app.view.workflows)
                snapshot("02-workflows")
        if args.visual_review:
            run = next((row for row in recent_runs if row.get("request", {}).get("methodology") == "uvm" and row.get("verification_status") == "passed"), recent_runs[0] if recent_runs else None)
            if run:
                app.show("run", run["id"])
                view = app.view
                wait(lambda: view.run is not None)
                snapshot("studio-run-overview")
                for category in ("stages", "jobs", "tests", "coverage", "properties", "issues", "artifacts", "logs"):
                    view.select_tab(category)
                    if category in view.tables:
                        wait(lambda: category in view.rows)
                    snapshot("studio-run-" + category)
                root.geometry("1120x760")
                view.select_tab("overview")
                snapshot("studio-compact-run")
                report["reviewed_run"] = run["id"]
            app.show("overview")
            wait(lambda: bool(app.view.projects.records))
            root.geometry("1120x760")
            snapshot("studio-compact-workbench")
            root.geometry("1440x940")
            app.search()
            palette = next(child for child in root.winfo_children() if isinstance(child, CommandPalette))
            wait(lambda: bool(palette.rows))
            project = next(iter(projects.values()))
            palette.query.set(project["name"].split()[0])
            snapshot("studio-search", palette)
            palette.destroy()
            app.show("project", project["id"])
            wait(lambda: app.view.project is not None)
            snapshot("studio-project")
            wizard = open_wizard(project["id"])
            snapshot("studio-wizard-project", wizard)
            wizard.geometry("920x710")
            snapshot("studio-compact-wizard", wizard)
            assert wizard.continue_button.winfo_ismapped()
            assert wizard.continue_button.winfo_rooty()+wizard.continue_button.winfo_height() <= wizard.winfo_rooty()+wizard.winfo_height()
            wizard.geometry("1040x860")
            wizard.advance()
            snapshot("studio-wizard-scope", wizard)
            wizard.destroy()
            dialog = import_project(app)
            snapshot("studio-import", dialog)
            dialog.destroy()
            dialog = scaffold(app, project)
            dialog.geometry("760x580")
            snapshot("studio-compact-scaffold", dialog)
            assert dialog.button.winfo_ismapped()
            assert dialog.button.winfo_rooty()+dialog.button.winfo_height() <= dialog.winfo_rooty()+dialog.winfo_height()
            dialog.destroy()
            report["visual_review"] = {"root_sizes": ["1440x940", "1120x760"], "wizard_sizes": ["1040x860", "920x710"], "scaffold_minimum": "760x580", "footer_actions_visible": True}
        if args.execute:
            acceptance = [("Adder acceptance", "adder-pass", None), ("Adder acceptance", "adder-fail", "+INJECT_FAILURE"), ("UART generated UVM acceptance", "uart-uvm", None)]
            for project_name, case, plusarg in acceptance:
                matches = [item for item in projects.values() if item["name"] == project_name]
                if len(matches) != 1:
                    raise AssertionError("Exactly one existing acceptance project required: " + project_name)
                wizard = open_wizard(matches[0]["id"])
                wizard.continue_button.invoke()
                wizard.form.fields["plusargs"].set(plusarg or "")
                wizard.form.fields["seeds"].set("11,29" if case == "uart-uvm" else "17")
                wizard.continue_button.invoke()
                wait(lambda: wizard.step == 2)
                assert wizard.preview["ready"], json.dumps(wizard.preview.get("checks"), ensure_ascii=False)
                snapshot(case + "-preflight", wizard)
                previous_view = app.view
                wizard.continue_button.invoke()
                wait(lambda: app.view is not previous_view and isinstance(app.view, RunView) and app.view.run is not None)
                view = app.view
                print("RUN", case, view.identifier, flush=True)
                wait(lambda: view.run["execution_status"] not in ("running", "queued"), timeout=300)
                expected = "failed" if plusarg else "passed"
                assert (view.run["execution_status"], view.run["verification_status"]) == ("completed", expected), view.run
                for category in view.tables:
                    view.select_tab(category)
                    wait(lambda: category in view.rows)
                view.select_tab("tests")
                snapshot(case + "-tests")
                record = {"case": case, "id": view.identifier, "execution_status": view.run["execution_status"], "verification_status": view.run["verification_status"], "summary": view.run["summary"], "tests": view.rows["tests"]}
                report["runs"].append(record)
                if case == "uart-uvm":
                    assert {test["seed"] for test in view.rows["tests"]} == {11, 29}
                    assert view.rows["coverage"]
                    fsdb = next(item for item in view.rows["artifacts"] if item["name"].endswith(".fsdb"))
                    view.select_tab("artifacts")
                    view.tables["artifacts"].tree.selection_set(fsdb["id"])
                    with patch("ucagent_tk.dialogs.filedialog.asksaveasfilename", return_value=str(output / "uart.fsdb")):
                        dialog = view.download()
                    wait(lambda: dialog.finished, timeout=60)
                    assert dialog.result, dialog.label.cget("text")
                    report["download"] = dialog.result
                    dialog.close()
                    view.select_tab("coverage")
                    snapshot("03-uart-coverage")
                view.select_tab("logs")
                wait(lambda: app.preferences.cursors.get(view.identifier, 0) > 0)
                report["last_event_cursor"] = app.preferences.cursors[view.identifier]
                snapshot(case + "-logs")
        formal = next((item for item in projects.values() if item["name"] == "VC Formal acceptance"), None)
        if formal:
            wizard = open_wizard(formal["id"])
            wizard.continue_button.invoke()
            wizard.continue_button.invoke()
            wait(lambda: wizard.step == 2)
            report["formal_preflight"] = wizard.preview
            snapshot("04-formal-preflight", wizard)
            wizard.destroy()
        app.show("overview")
        wait(lambda: bool(app.view.projects.records))
        snapshot("05-final-workbench")
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        report["failure"] = str(exc)
        raise
    finally:
        (output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("REPORT", output / "acceptance.json", flush=True)
        if not args.keep_open or "failure" in report:
            app.close()
            wait(lambda: app.closed)
            temporary.cleanup()
    if args.keep_open:
        root.mainloop()
        temporary.cleanup()


if __name__ == "__main__":
    main()
