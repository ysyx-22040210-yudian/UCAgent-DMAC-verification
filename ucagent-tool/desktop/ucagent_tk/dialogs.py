"""Native structured mutation dialogs and verified cancellable artifact downloads."""

import json
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .client import Cancelled, collection, segment
from .i18n import tr
from .model import lines, seeds
from .widgets import Form, ScrollFrame, Table, TextBox, format_size
from .visuals import ACCENT, FONT, INK, MUTED, PAGE, SURFACE, ActionButton


class CommandPalette(tk.Toplevel):
    """Keyboard-first navigation over actual server projects and persisted runs."""

    def __init__(self, app):
        """Load real destinations asynchronously and filter locally without sending user query text."""
        super().__init__(app.root)
        self.app = app
        self.client = app.client
        self.rows = []
        self.query = tk.StringVar(self)
        self.title(tr("search_title"))
        self.geometry("820x540+{}+{}".format(app.root.winfo_rootx()+max(20, (app.root.winfo_width()-820)//2), app.root.winfo_rooty()+110))
        self.transient(app.root)
        self.configure(background=PAGE)
        self.grab_set()
        header = ttk.Frame(self, padding=(24, 22, 24, 10))
        header.pack(fill="x")
        ttk.Label(header, text=tr("search_title"), font=(FONT, 17, "bold")).pack(anchor="w")
        ttk.Label(header, text=tr("search_help"), style="Hint.TLabel").pack(anchor="w", pady=(8, 14))
        self.entry = ttk.Entry(header, textvariable=self.query, font=(FONT, 12))
        self.entry.pack(fill="x")
        self.table = Table(self, [("kind", "kind", 80), ("name", "name", 350), ("description", "details", 270)], on_open=self.open, height=8)
        self.table.pack(fill="both", expand=True, padx=24, pady=(6, 24))
        self.message = ttk.Label(header, text=tr("loading"), style="Hint.TLabel")
        self.message.pack(anchor="w", pady=(10, 0))
        self.trace = self.query.trace_add("write", lambda *args: self.filter())
        self.entry.bind("<Return>", lambda event: self.open())
        self.entry.bind("<Down>", lambda event: self.table.tree.focus_set())
        self.bind("<Escape>", lambda event: self.destroy())
        self.entry.focus_set()
        def load():
            """Collect canonical identities; raw names remain display-only data."""
            projects = collection(self.client.call("/projects"))
            runs = collection(self.client.call("/runs"))
            return [{"id": "project:"+row["id"], "entity_id": row["id"], "page": "project", "kind": tr("project"), "name": row["name"], "description": row["path"]} for row in projects] + [{"id": "run:"+row["id"], "entity_id": row["id"], "page": "run", "kind": tr("runs"), "name": row.get("project_name") or row["id"], "description": row["id"], "request": row.get("request")} for row in runs]
        app.io(self, load, self.loaded, lambda error: self.message.configure(text=str(error)[:300]), key="search")

    def loaded(self, rows):
        """Cache only observed destinations and apply the current literal query."""
        self.rows = rows
        self.filter()

    def filter(self):
        """Match names, run ids and tests without interpreting a query as code or a path."""
        query = self.query.get().strip().casefold()
        matches = [row for row in self.rows if not query or query in json.dumps(row, ensure_ascii=False).casefold()]
        self.table.set_rows(matches[:40])
        self.message.configure(text=tr("search_count", count=len(matches)))
        if matches:
            self.table.tree.selection_set(matches[0]["id"])

    def open(self):
        """Navigate using the stored opaque identity of the selected server entity."""
        row = self.table.selected()
        if row:
            self.app.show(row["page"], row["entity_id"])
            self.destroy()

    def destroy(self):
        """Remove query traces and Tcl variables on the main thread before retiring the palette."""
        self.query.trace_remove("write", self.trace)
        self.query = None
        super().destroy()


class InputDialog(tk.Toplevel):
    """Submit an explicit structured operation once and leave failures editable."""

    def __init__(self, app, title, help_key, fields, submit, done):
        """Build a labeled native form without accepting shell commands or evaluating input."""
        super().__init__(app.root)
        self.app = app
        self.submit = submit
        self.done = done
        self.title(tr(title))
        self.geometry("890x690+{}+{}".format(app.root.winfo_rootx()+max(16, (app.root.winfo_width()-890)//2), app.root.winfo_rooty()+48))
        self.minsize(760, 580)
        self.transient(app.root)
        self.configure(background=PAGE)
        header = tk.Frame(self, background=SURFACE, padx=24, pady=22)
        header.pack(fill="x")
        tk.Label(header, text=tr(title), font=(FONT, 17, "bold"), foreground=INK, background=SURFACE).pack(anchor="w", pady=(0, 8))
        tk.Label(header, text=tr(help_key), font=(FONT, 9), foreground=MUTED, background=SURFACE, wraplength=820, justify="left", anchor="w").pack(fill="x")
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True, padx=24, pady=8)
        self.form = Form(scroll.content)
        self.form.pack(fill="x", padx=8)
        for field in fields:
            self.form.add(**field)
        self.error = ttk.Label(self, text="", wraplength=820, style="Error.TLabel")
        self.error.pack(side="bottom", before=scroll, fill="x", padx=24, pady=8)
        footer = tk.Frame(self, background=SURFACE, padx=24, pady=14)
        footer.pack(side="bottom", before=self.error, fill="x")
        self.button = ActionButton(footer, tr("submit"), self.send, variant="primary", icon_name="check", background=SURFACE, width=132)
        self.button.pack(side="right")
        ActionButton(footer, tr("cancel"), self.destroy, variant="ghost", background=SURFACE, width=100).pack(side="right", padx=12)

    def send(self):
        """Read Tk values before passing an immutable value dictionary into background I/O."""
        values = self.form.values()
        self.button.configure(state="disabled")
        if not self.app.io(self, lambda: self.submit(values), self.finished, self.failed, key="submit"):
            self.button.configure(state="normal")

    def failed(self, error):
        """Restore editing without automatically retrying an uncertain mutation."""
        self.error.configure(text=str(error)[:2000])
        self.button.configure(state="normal")

    def finished(self, result):
        """Deliver the observed server response and close only this editor."""
        self.done(result)
        self.destroy()


def import_project(app):
    """Import an allowed server directory with optional explicit project configuration."""
    client = app.client
    def submit(values):
        """Validate the optional JSON object and post one declared server project."""
        body = {"name": values["name"].strip(), "path": values["path"].strip()}
        if not all(body.values()):
            raise ValueError(tr("required"))
        if values["config"].strip():
            body["config"] = json.loads(values["config"])
            if not isinstance(body["config"], dict):
                raise ValueError(tr("json_invalid"))
        return client.call("/projects", "POST", body)
    return InputDialog(app, "import_project", "project_path_help", [
        {"key": "name", "label": "project_name"}, {"key": "path", "label": "path"},
        {"key": "config", "label": "structured", "multiline": True},
    ], submit, lambda result: app.show("project", result["id"]))


def scaffold(app, project):
    """Generate a declared UVM environment, never an invented algorithmic golden model."""
    client = app.client
    design = project["design"]
    def submit(values):
        """Parse explicit ports and a user-supplied model into the canonical scaffold schema."""
        spec = {"name": values["name"], "dut_top": values["top"], "uvm_version": "1.2", "timescale": "1ns/1ps",
                "design_sources": lines(values["sources"]), "signals": json.loads(values["signals"]),
                "reference_model": json.loads(values["model"]),
                "clock": {"name": values["clock"], "period_ns": float(values["period"]), "edge": "posedge"},
                "reset": {"name": values["reset"], "active_level": int(values["active"]), "cycles": 5}}
        return client.call("/projects/{}/uvm/scaffold".format(segment(project["id"])), "POST", {"output_dir": values["output"], "spec": spec})
    def done(result):
        """Show structural results without claiming smoke or functional signoff."""
        window = tk.Toplevel(app.root)
        window.title(tr("generated"))
        window.geometry("900x600")
        box = TextBox(window)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.set(result)
    return InputDialog(app, "scaffold", "scaffold_help", [
        {"key": "output", "label": "output_dir", "value": "uvm"},
        {"key": "name", "label": "dut_name", "value": "dut"},
        {"key": "top", "label": "top", "value": design.get("top", "")},
        {"key": "sources", "label": "sources", "value": "\n".join(design.get("sources", [])), "multiline": True},
        {"key": "clock", "label": "clock"}, {"key": "period", "label": "period", "value": "10"},
        {"key": "reset", "label": "reset"}, {"key": "active", "label": "reset_active", "value": "0", "choices": ["0", "1"]},
        {"key": "signals", "label": "signals", "value": "[]", "multiline": True},
        {"key": "model", "label": "model_json", "value": "null", "multiline": True},
    ], submit, done)


def replay(app, run_id, prop):
    """Bind a signed falsified property to an actual user-selected dynamic test."""
    if not prop or prop.get("status") != "falsified" or not prop.get("counterexample_artifact_id"):
        app.notify(tr("cex_missing"))
        return None
    client = app.client
    def submit(values):
        """Require one test and one seed before asking the server to verify replay provenance."""
        selected_seeds = seeds(values["seed"])
        if len(selected_seeds) != 1 or not values["target"].strip():
            raise ValueError("Replay requires one test and one seed.")
        body = {"property_name": prop["name"], "methodology": values["methodology"], "suite": values["suite"],
                "seed": selected_seeds[0], "simulator": values["simulator"], "waveform": values["waveform"],
                "plusargs": lines(values["plusargs"])}
        body["uvm_test" if values["methodology"] == "uvm" else "unitytest_test"] = values["target"].strip()
        return client.call("/runs/{}/counterexample-replays".format(segment(run_id)), "POST", body)
    return InputDialog(app, "cex_replay", "cex_help", [
        {"key": "methodology", "label": "methodology", "value": "uvm", "choices": ["uvm", "unitytest"]},
        {"key": "target", "label": "cex_target"}, {"key": "suite", "label": "suite", "value": "UT", "choices": ["UT", "IT", "ST"]},
        {"key": "seed", "label": "seed", "value": "1"},
        {"key": "simulator", "label": "simulator", "value": "vcs", "choices": ["vcs", "verilator"]},
        {"key": "waveform", "label": "waveform", "value": "none", "choices": ["none", "vcd", "fst", "vpd", "fsdb"]},
        {"key": "plusargs", "label": "plusargs", "multiline": True},
    ], submit, lambda result: app.show("run", result["target_run_id"]))


class DownloadDialog(tk.Toplevel):
    """Show streaming progress and publish only fully hash-verified artifacts."""

    def __init__(self, app, artifact, destination):
        """Start a user-selected download without buffering large waveforms in memory."""
        super().__init__(app.root)
        self.app = app
        self.cancel = threading.Event()
        app.local_cancellations.add(self.cancel)
        self.received = 0
        self.finished = False
        self.result = None
        self.title(tr("download_title"))
        self.geometry("690x240")
        self.transient(app.root)
        ttk.Label(self, text=artifact["name"], padding=16).pack(fill="x")
        self.label = ttk.Label(self, text=tr("loading"), wraplength=650)
        self.label.pack(fill="x", padx=16)
        self.progress = ttk.Progressbar(self, maximum=max(1, artifact.get("size") or 1))
        self.progress.pack(fill="x", padx=16, pady=12)
        self.button = ttk.Button(self, text=tr("cancel"), command=self.close)
        self.button.pack(anchor="e", padx=16)
        self.protocol("WM_DELETE_WINDOW", self.close)
        client = app.client
        if not app.io(self, lambda: client.download(artifact, destination, self.cancel, self.observe), self.complete, self.failed, key="download"):
            self.failed(ValueError("Download queue is full; no transfer was started."))
        self.timer = self.after(100, self.tick)

    def observe(self, size):
        """Store one bounded progress value from the I/O worker without touching Tk."""
        self.received = size

    def tick(self):
        """Render the latest byte count only from the Tk thread."""
        if not self.finished:
            self.label.configure(text=tr("download_progress", size=format_size(self.received)))
            self.progress.configure(value=self.received)
            self.timer = self.after(100, self.tick)

    def complete(self, result):
        """Show the verified path only after atomic publication succeeds."""
        self.finished = True
        self.result = result
        self.progress.configure(value=result["bytes"])
        self.label.configure(text=tr("download_ok", path=result["path"]))
        self.button.configure(text=tr("close"))

    def failed(self, error):
        """Distinguish a local cancellation from a corrupt or unavailable artifact."""
        self.finished = True
        self.label.configure(text=str(error)[:900], style="Hint.TLabel" if isinstance(error, Cancelled) else "Error.TLabel")
        self.button.configure(text=tr("close"))

    def close(self):
        """Cancel local transfer and remove its timer without affecting remote evidence."""
        self.destroy()

    def destroy(self):
        """Cancel transfers even when the application closes the whole dialog tree."""
        self.cancel.set()
        self.app.local_cancellations.discard(self.cancel)
        if hasattr(self, "timer"):
            self.after_cancel(self.timer)
        super().destroy()


def download(app, artifact):
    """Ask for a local destination; a server filename can never choose an output directory."""
    if not artifact:
        app.notify(tr("selection_required"))
        return None
    if artifact.get("is_directory"):
        app.notify(tr("directory_artifact"))
        return None
    filename = Path(str(artifact["name"]).replace("\\", "/")).name
    destination = filedialog.asksaveasfilename(parent=app.root, title=tr("download_title"), initialfile=filename)
    return DownloadDialog(app, artifact, destination) if destination else None


def upload(app, project_id):
    """Upload explicitly selected small RTL/spec inputs to the backend's non-overwriting area."""
    paths = filedialog.askopenfilenames(parent=app.root, title=tr("upload"))
    if not paths or not messagebox.askyesno(tr("upload"), tr("upload_help"), parent=app.root):
        return
    client = app.client
    def done(result):
        """Display exact uploaded project-relative paths for use in the next run's inputs."""
        window = tk.Toplevel(app.root)
        window.title(tr("uploaded"))
        window.geometry("850x450")
        box = TextBox(window)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.set(result)
    app.io(app.root, lambda: client.upload(project_id, paths), done, key="upload")
