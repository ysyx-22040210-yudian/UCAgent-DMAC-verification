"""Drive the real shared GUI-to-CLI start/cancel path; do not claim model or proof completion."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from ucagent_tk.app import Application
from ucagent_tk.formal import FormalSessionView
from ucagent_tk.model import Preferences


def main():
    """Create each engine through Tk and cancel its actual shared Agent session safely."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = tk.Tk()
    errors, sessions = [], []
    root.report_callback_exception = lambda kind, value, trace: errors.append(str(value))
    with tempfile.TemporaryDirectory(prefix="formal-agent-gui-") as directory:
        app = Application(root, args.origin, Preferences(Path(directory) / "preferences.json"))

        def spin(predicate, timeout=90):
            """Pump the actual Tk event loop until backend state is observed, not guessed."""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                root.update()
                if predicate():
                    return
                time.sleep(0.02)
            raise AssertionError("GUI timeout: " + app.message.cget("text"))

        try:
            spin(lambda: not app.pending)
            app.client.call("/projects", "POST", {"name": "Public shared Agent GUI fixture", "path": str(args.fixture)})
            for engine in ("sby", "formalmc"):
                app.show("formal_sessions")
                spin(lambda: bool(app.view.projects))
                dialog = app.view.create()
                dialog.form.fields["dut"].set("Counter")
                dialog.form.fields["engine"].set(engine)
                dialog.button.invoke()
                spin(lambda: isinstance(app.view, FormalSessionView) and app.view.row is not None)
                view = app.view
                view.agent_turns.set("2")
                view.agent_seconds.set("90")
                view.agent_prompt.set("Call RoleInfo and CurrentTips only. Do not edit, run Check or claim verification passed. This turn exercises the GUI cancellation boundary.")
                with patch("ucagent_tk.formal.messagebox.askyesno", return_value=True):
                    view.buttons["agent"].invoke()
                spin(lambda: view.row["state"] == "running" and bool(view.row.get("agent")))
                identifier = view.row["agent"]["session_id"]
                spin(lambda: "eda.running" in view.events.get())
                view.buttons["cancel"].invoke()
                spin(lambda: view.row["state"] == "paused" and not app.pending)
                assert view.row["execution_status"] == "cancelled", view.row["last_result"]
                assert view.row["verification_status"] == "unknown" and view.row["view"]["current_index"] == 0
                assert view.row["options"]["engine"] == engine
                sessions.append({"engine": engine, "id": view.row["id"], "agent_session_id": identifier,
                                 "revision": view.row["revision"], "execution_status": view.row["execution_status"],
                                 "verification_status": view.row["verification_status"]})
            assert not errors, errors
            args.output.write_text(json.dumps({"scope": "Real Tk -> shared CLI start/cancel only; model completion and proof acceptance are not claimed",
                "python": sys.version, "sessions": sessions, "callback_errors": errors}, indent=2), encoding="utf-8")
            print("FORMAL_SHARED_AGENT_GUI_START_CANCEL_PASSED")
        finally:
            with patch("ucagent_tk.formal.messagebox.askyesno", return_value=True):
                app.close()
            spin(lambda: app.closed)


if __name__ == "__main__":
    main()
