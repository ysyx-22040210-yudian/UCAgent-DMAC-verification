"""Python 3.8 native formal-stage workbench; all state comes from real server gates."""

import difflib
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlencode
from uuid import uuid4

from .client import collection, segment
from .dialogs import InputDialog, download
from .i18n import tr
from .views import BaseView
from .widgets import StageTree, Table, TextBox


def capability_text(engine):
    """Describe integration limitations in the user's locale, without conflating engines."""
    return tr("formal_caps_" + engine)


class FormalSessionsView(BaseView):
    """List resumable stage sessions separately from EDA-only native runs."""

    def __init__(self, parent, app, identifier=None):
        """Build the stage-session entry point and explicit engine comparison."""
        super().__init__(parent, app, identifier)
        self.projects = []
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Button(toolbar, text=tr("formal_create"), command=self.create, style="Primary.TButton").pack(side="left")
        ttk.Button(toolbar, text=tr("formal_open"), command=self.open).pack(side="left", padx=8)
        ttk.Label(self, text=tr("formal_session_help"), style="Hint.TLabel", wraplength=1030).pack(fill="x", pady=(0, 12))
        self.table = Table(self, [("dut", "dut_name", 170), ("engine", "engine", 110), ("state", "status", 110),
                                 ("current_stage", "stage", 400), ("verification_status", "verification_status", 130)], on_open=self.open)
        self.table.pack(fill="both", expand=True)
        self.capabilities = TextBox(self, height=7)
        self.capabilities.pack(fill="x", pady=(12, 0))
        self.capabilities.set(capability_text("sby") + "\n\n" + capability_text("formalmc"))

    def refresh(self):
        """Read real sessions and projects; an old server's missing endpoint stays an error."""
        def load():
            """Collect session identities without modifying project configuration."""
            return collection(self.client.call("/formal-sessions")), collection(self.client.call("/projects"))
        self.app.io(self, load, self.render, self.failed)

    def render(self, data):
        """Display current engine and stage from the durable lifecycle projection."""
        self.loaded()
        sessions, self.projects = data
        rows = []
        for row in sessions:
            nodes = list(row["view"]["stages"])
            current_stage = tr("completed") if row["view"]["all_completed"] else "--"
            while nodes:
                stage = nodes.pop()
                nodes.extend(stage["children"])
                if stage["current"]:
                    current_stage = tr("formal_stage_" + stage["id"])
            rows.append(dict(row, dut=row["options"]["dut"], engine=row["options"]["engine"], current_stage=current_stage))
        self.table.set_rows(rows)

    def create(self):
        """Choose the engine once, then use the same Agent and original stage operations."""
        if not self.projects:
            self.app.notify(tr("formal_import_first"))
            return
        projects = {row["name"] + " / " + row["id"][:8]: row for row in self.projects}
        first = next(iter(projects))
        def submit(values):
            """Submit only structured choices; imported hooks and old evidence are not inherited."""
            body = {"project_id": projects[values["project"]]["id"], "dut": values["dut"].strip(),
                    "engine": values["engine"], "toolchain": values["toolchain"].strip(),
                    "cex_replay": values["cex"] == "true", "static_review": values["static"] == "true",
                    "human_review": values["review"] == "true"}
            return self.client.call("/formal-sessions", "POST", body, timeout=120)
        dialog = InputDialog(self.app, "formal_create", "formal_create_help", [
            {"key": "project", "label": "project_name", "choices": list(projects), "value": first},
            {"key": "dut", "label": "dut_name", "value": (projects[first].get("design") or {}).get("top", "")},
            {"key": "engine", "label": "engine", "choices": ["formalmc", "sby"], "value": "formalmc"},
            {"key": "toolchain", "label": "toolchain", "value": "sby"},
            {"key": "review", "label": "formal_human_review", "choices": ["true", "false"], "value": "true"},
            {"key": "cex", "label": "cex_replay", "choices": ["true", "false"], "value": "false"},
            {"key": "static", "label": "formal_static", "choices": ["true", "false"], "value": "false"},
        ], submit, lambda row: self.app.show("formal_session", row["id"]))
        return dialog

    def open(self):
        """Open the selected durable session without rerunning a check."""
        row = self.table.selected()
        if row:
            self.app.show("formal_session", row["id"])


class FormalSessionView(BaseView):
    """Operate native stages, authoring files, reviews and evidence from one workbench."""

    def __init__(self, parent, app, identifier=None):
        """Build a readable stage tree and work area with no synthetic progress controls."""
        super().__init__(parent, app, identifier)
        self.endpoint = "/formal-sessions/" + segment(identifier)
        self.row = None
        self.opened_file = None
        self.last_index = None
        self.saved_journal = ""
        self.selected_stage = None
        self.cursor = 0
        self.pending_action = False
        self.path = tk.StringVar(self)
        self.banner = ttk.Label(self, style="Title.TLabel")
        self.banner.pack(anchor="w", pady=(0, 8))
        self.capabilities = ttk.Label(self, wraplength=1050, justify="left", style="Hint.TLabel")
        self.capabilities.pack(fill="x", pady=(0, 12))
        self.capabilities.bind("<Configure>", lambda event: self.capabilities.configure(wraplength=max(200, event.width - 4)))
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 12))
        self.buttons = {}
        for position, action in enumerate(("check", "complete", "approve", "reject", "pause", "resume", "cancel", "reopen")):
            button = ttk.Button(toolbar, text=tr("formal_" + action), command=lambda name=action: self.action(name),
                                style="Primary.TButton" if action == "complete" else "TButton")
            button.grid(row=position // 4, column=position % 4, sticky="ew", padx=(0, 6), pady=(0, 5))
            self.buttons[action] = button
        self.buttons["migrate_formalmc"] = ttk.Button(toolbar, text=tr("formal_migration_formalmc"), command=self.migrate_formalmc)
        self.buttons["migrate_formalmc"].grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 5))
        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane)
        self.tree = StageTree(left, self.select_stage)
        self.tree.tree.configure(displaycolumns=("execution_status",))
        self.tree.tree.column("#0", width=370, stretch=True)
        self.tree.pack(fill="both", expand=True)
        pane.add(left, weight=2)
        self.tabs = ttk.Notebook(pane)
        pane.add(self.tabs, weight=3)
        task = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(task, text=tr("formal_stage_task"))
        task.columnconfigure(0, weight=1)
        task.rowconfigure(0, weight=1)
        self.task_text = TextBox(task, height=6)
        self.task_text.grid(row=0, column=0, sticky="nsew")
        self.references = Table(task, [("path", "path", 420), ("read", "status", 90)], on_open=self.open_reference, height=2)
        self.references.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        editor = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(editor, text=tr("formal_files"))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(1, weight=1)
        filebar = ttk.Frame(editor)
        filebar.grid(row=0, column=0, sticky="ew")
        self.path_selector = ttk.Combobox(filebar, textvariable=self.path, width=35)
        self.path_selector.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        for column in range(3):
            filebar.columnconfigure(column, weight=1)
        ttk.Button(filebar, text=tr("formal_read"), command=self.read_file).grid(row=1, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(filebar, text=tr("formal_new_file"), command=self.new_file).grid(row=1, column=1, sticky="ew", padx=(0, 5))
        self.download_button = ttk.Button(filebar, text=tr("download"), command=self.download_file)
        self.download_button.grid(row=1, column=2, sticky="ew")
        self.editor = TextBox(editor, height=6, readonly=False)
        self.editor.grid(row=1, column=0, sticky="nsew", pady=8)
        self.file_hint = ttk.Label(editor, text=tr("formal_file_help"), style="Hint.TLabel", wraplength=630)
        self.file_hint.grid(row=2, column=0, sticky="ew")
        self.save_button = ttk.Button(editor, text=tr("formal_diff_save"), command=self.review_edit)
        self.save_button.grid(row=3, column=0, sticky="e", pady=(8, 0))
        evidence = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(evidence, text=tr("formal_results"))
        self.result = TextBox(evidence, height=16)
        self.result.pack(fill="both", expand=True)
        self.events = TextBox(evidence, height=6)
        self.events.pack(fill="x", pady=(10, 0))
        self.review_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.review_tab, text=tr("formal_review_tab"))
        self.review_tab.columnconfigure(0, weight=1)
        self.review_tab.rowconfigure(1, weight=1)
        ttk.Label(self.review_tab, text=tr("formal_journal_help"), style="Hint.TLabel", wraplength=570).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.journal = TextBox(self.review_tab, height=5, readonly=False)
        self.journal.grid(row=1, column=0, sticky="nsew")
        self.journal_button = ttk.Button(self.review_tab, text=tr("formal_journal"), command=lambda: self.action("journal"))
        self.journal_button.grid(row=2, column=0, sticky="e", pady=(8, 0))
        self.agent_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.agent_tab, text=tr("formal_agent_tab"))
        ttk.Label(self.agent_tab, text=tr("formal_agent_help"), style="Hint.TLabel", wraplength=540).pack(fill="x", pady=(0, 8))
        self.agent_prompt = TextBox(self.agent_tab, height=4, readonly=False)
        self.agent_prompt.pack(fill="x")
        self.agent_prompt.set(tr("formal_agent_prompt"))
        agent_bar = ttk.Frame(self.agent_tab)
        agent_bar.pack(fill="x", pady=8)
        ttk.Label(agent_bar, text=tr("formal_agent_turns")).grid(row=0, column=0)
        self.agent_turns = tk.StringVar(self, value="12")
        ttk.Entry(agent_bar, textvariable=self.agent_turns, width=4).grid(row=0, column=1, padx=6)
        ttk.Label(agent_bar, text=tr("formal_agent_seconds")).grid(row=0, column=2)
        self.agent_seconds = tk.StringVar(self, value="600")
        ttk.Entry(agent_bar, textvariable=self.agent_seconds, width=5).grid(row=0, column=3, padx=6)
        self.buttons["agent"] = ttk.Button(agent_bar, text=tr("formal_agent"), style="Primary.TButton", command=self.start_agent)
        self.buttons["agent"].grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.agent_result = TextBox(self.agent_tab, height=5)
        self.agent_result.pack(fill="both", expand=True)
        self.agent_edits = TextBox(self.agent_tab, height=5)
        self.agent_edits.pack(fill="both", expand=True, pady=(8, 0))
        self.tabs.select(self.agent_tab)

    def migrate_formalmc(self):
        """Create and open the linked FormalMC project from saved SBY inputs."""
        if not self.row or self.pending_action:
            return
        if ((self.opened_file and self.editor.get() != self.opened_file["content"])
                or self.journal.get() != self.saved_journal):
            self.app.notify(tr("formal_migration_save_drafts"))
            return
        body = {"revision": self.row["revision"], "request_id": uuid4().hex}
        self.pending_action = True
        self.update_buttons()

        def done(result):
            """Refresh the receipt without implying a target-engine verification pass."""
            self.pending_action = False
            self.render(result["session"])
            self.app.notify(tr("formal_migration_ready"))
            self.app.show("project", result["project"]["id"])

        if not self.app.io(self, lambda: self.client.call(self.endpoint + "/migrate-formalmc", "POST", body, timeout=180),
                           done, self.action_failed, key="action"):
            self.pending_action = False
            self.update_buttons()

    def start_agent(self):
        """Confirm common turn budgets and protect unsaved drafts before AI authoring."""
        if ((self.opened_file and self.editor.get() != self.opened_file["content"])
                or self.journal.get() != self.saved_journal):
            self.app.notify(tr("formal_agent_save_drafts"))
            return
        try:
            turns, seconds = int(self.agent_turns.get()), int(self.agent_seconds.get())
            if not 1 <= turns <= 30 or not 30 <= seconds <= 3600:
                raise ValueError()
        except ValueError:
            self.app.notify(tr("formal_agent_budget_error"))
            return
        if messagebox.askyesno(tr("formal_agent"), tr("formal_agent_confirm", turns=turns, seconds=seconds), parent=self):
            self.action("agent", prompt=self.agent_prompt.get(), max_turns=turns, timeout=seconds)

    def refresh(self):
        """Reconnect using a durable cursor without replaying prior mutations."""
        after = self.cursor
        def load():
            """Read only persisted state, file names and events since the last cursor."""
            return (self.client.call(self.endpoint), self.client.call(self.endpoint + "/files"),
                    self.client.call(self.endpoint + "/events?after=" + str(after)))
        self.app.io(self, load, self.loaded_session, self.failed)

    def loaded_session(self, data):
        """Refresh state without replacing unsaved editor or journal content."""
        row, files, events = data
        self.render(row)
        self.path_selector.configure(values=[item["path"] for item in files["items"]])
        for event in events["items"]:
            if event["sequence"] > self.cursor:
                payload = event.get("payload") or {}
                self.events.append("#{}  {}  {}\n".format(event["sequence"], event["type"], payload.get("text") or "revision=" + str(event.get("revision", "--"))))
                if event["type"] == "agent.tool.EditTextFile":
                    changed = event.get("result") or {}
                    self.agent_edits.append("#{}  {}\n{}\n".format(event["sequence"], changed.get("path", ""), changed.get("diff", "")))
                self.cursor = event["sequence"]
        if row["state"] == "running" or len(events["items"]) == 100:
            self.poll()

    def failed(self, error):
        """Keep reconnecting read-only state and logs; never replay an uncertain mutation."""
        super().failed(error)
        if self.row and self.row["state"] == "running":
            self.poll()

    def render(self, row):
        """Display lifecycle and verification conclusions separately."""
        self.loaded()
        self.row = row
        self.pending_action = False
        engine = row["options"]["engine"]
        self.banner.configure(text="{}  /  {}  ·  {}  ·  {}: {}".format(row["options"]["dut"], engine.upper(), tr(row["state"]), tr("verification_status"), tr(row["verification_status"])))
        self.capabilities.configure(text=capability_text(engine))
        def annotate(nodes):
            """Map actual stage status to the shared tree widget without inventing a DUT pass."""
            return [dict(node, description=tr("formal_stage_" + node["id"]), execution_status=node["status"], verification_status="unknown", children=annotate(node["children"])) for node in nodes]
        self.tree.set_rows(annotate(row["view"]["stages"]))
        index = row["view"]["current_index"]
        current = next((node for node in self.tree.records.values() if node["current"]), None)
        clean_journal = self.journal.get() == self.saved_journal
        self.saved_journal = (current.get("journal") or "") if current else ""
        if clean_journal:
            self.journal.set(self.saved_journal)
        if self.last_index != index:
            self.last_index = index
            self.journal.set(self.saved_journal)
            if current:
                self.tree.tree.selection_set(current["id"])
                self.tree.tree.see(current["id"])
                self.journal.set(current.get("journal") or "")
                self.select_stage(current)
        elif self.selected_stage:
            self.select_stage(self.tree.records.get(self.selected_stage["id"]))
        self.result.set({"execution_status": row["execution_status"], "verification_status": row["verification_status"],
                         "stage_result": row["last_result"], "capabilities": row["capabilities"]})
        agent = row.get("agent") or {}
        self.agent_result.set({"model": agent.get("model", "--"), "session_id": agent.get("session_id", "--"),
                               "status": agent.get("status", "--"), "tool_calls": agent.get("tool_calls", 0),
                               "message": agent.get("message") or row.get("last_result") or tr("formal_agent_help")})
        self.update_buttons()

    def update_buttons(self):
        """Disable unavailable operations locally; the server independently enforces every gate."""
        if not self.row:
            return
        state = self.row["state"]
        for action, button in self.buttons.items():
            enabled = not self.pending_action and state == "ready"
            if action == "migrate_formalmc":
                enabled = not self.pending_action and state in {"ready", "completed", "paused"} and self.row["options"]["engine"] == "sby"
            elif action == "cancel":
                enabled = not self.pending_action and state == "running"
            elif action in {"approve", "reject"}:
                current = next((node for node in self.tree.records.values() if node["current"]), None)
                enabled = enabled and bool(current and current["details"].get("needs_human_check"))
            elif action == "resume":
                enabled = not self.pending_action and state == "paused"
            elif action == "reopen":
                enabled = not self.pending_action and state in {"ready", "completed"} and bool(self.selected_stage and self.selected_stage.get("index") is not None and self.selected_stage["index"] <= self.row["view"]["current_index"])
            button.configure(state="normal" if enabled else "disabled")
        self.save_button.configure(state="normal" if state == "ready" and not self.pending_action and self.opened_file and self.opened_file.get("editable") else "disabled")

    def select_stage(self, stage):
        """Inspect any branch; selecting a future node never changes the active stage."""
        self.selected_stage = stage
        if stage:
            task = stage["details"].get("task") or {}
            gate = stage["details"]
            approval = gate.get("last_human_check_result")
            review = tr("disabled") if not gate.get("needs_human_check") else tr("formal_approve") if approval is True else tr("formal_reject") if approval is False else tr("formal_not_reviewed")
            summary = tr("formal_gate_summary", checked=tr("formal_gate_passed") if gate.get("check_pass") else tr("formal_gate_unpassed"), reviewed=review,
                         note=(gate.get("last_human_check_msg") or "--")[:1000])
            self.task_text.set(stage["description"] + "\n\n" + summary + "\n\n" + "\n\n".join(task.get("description") or []) + "\n\n" + stage["disabled_reason"] +
                               "\n\n" + tr("formal_outputs") + "\n" + "\n".join(task.get("output_files") or []))
            self.references.set_rows([{"id": path, "path": path, "read": value} for path, value in (task.get("reference_files") or {}).items()])
        self.update_buttons()

    def action(self, action, **extra):
        """Send one guarded action; failed and uncertain mutations are never silently retried."""
        if not self.row or self.pending_action:
            return
        index = self.row["view"]["current_index"]
        if action == "reopen":
            if not self.selected_stage or self.selected_stage.get("index") is None:
                return
            if not messagebox.askyesno(tr("formal_reopen"), tr("formal_reopen_confirm"), parent=self):
                return
            index = self.selected_stage["index"]
        body = {"action": action, "revision": self.row["revision"], "stage_index": index,
                "request_id": uuid4().hex, "journal": self.journal.get(), **extra}
        self.submitted = body
        self.pending_action = True
        self.update_buttons()
        if not self.app.io(self, lambda: self.client.call(self.endpoint + "/actions", "POST", body), self.action_done, self.action_failed, key="action"):
            self.pending_action = False
            self.update_buttons()

    def action_done(self, row):
        """Refresh from observed server state rather than advancing the selected tree row."""
        submitted = getattr(self, "submitted", {})
        if submitted.get("action") == "save" and isinstance(row.get("last_result"), dict) and row["last_result"].get("path") == submitted["path"]:
            self.opened_file = {"path": submitted["path"], "content": submitted["content"], "sha256": row["last_result"]["sha256"], "editable": True}
        self.render(row)
        self.refresh()

    def action_failed(self, error):
        """Keep edits and journals intact after a conflict or uncertain connection outcome."""
        self.pending_action = False
        self.update_buttons()
        self.failed(error)

    def read_file(self):
        """Open one literal path and mark it read only through the backend's real file tool."""
        path = self.path.get().strip()
        if self.opened_file and self.editor.get() != self.opened_file["content"] and not messagebox.askyesno(tr("formal_read"), tr("formal_discard"), parent=self):
            return
        self.app.io(self, lambda: self.client.call(self.endpoint + "/read?" + urlencode({"path": path}), "POST"), self.file_loaded, self.failed, key="file")

    def open_reference(self):
        """Open the selected required input rather than marking unread files read in bulk."""
        selected = self.references.selected()
        if selected:
            self.path.set(selected["path"].replace("\\", "/"))
            self.tabs.select(1)
            self.read_file()

    def download_file(self):
        """Download only a selected actual artifact, with hash and size verification."""
        path = self.path.get().strip()
        self.app.io(self, lambda: self.client.call(self.endpoint + "/artifact?" + urlencode({"path": path}), timeout=120),
                    lambda artifact: download(self.app, artifact), self.failed, key="artifact")

    def file_loaded(self, result):
        """Retain the exact base content and hash for a later conflict-checked edit."""
        self.opened_file = {key: value for key, value in result.items() if key != "session"}
        self.editor.set(result["content"])
        self.editor.text.configure(state="normal" if result["editable"] else "disabled")
        self.file_hint.configure(text=(tr("formal_editable") if result["editable"] else tr("formal_readonly")) + "  SHA-256: " + result["sha256"])
        self.render(result["session"])

    def new_file(self):
        """Prepare an empty authoring file; the server validates its path and nonexistence."""
        if self.opened_file and self.editor.get() != self.opened_file["content"] and not messagebox.askyesno(tr("formal_new_file"), tr("formal_discard"), parent=self):
            return
        path = self.path.get().strip()
        self.opened_file = {"path": path, "content": "", "sha256": None, "editable": True}
        self.editor.set("")
        self.file_hint.configure(text=tr("formal_new_file_help"))
        self.update_buttons()

    def review_edit(self):
        """Show a literal diff before requesting the server's compare-and-swap save."""
        if not self.opened_file:
            return
        content = self.editor.get()
        source = dict(self.opened_file)
        window = tk.Toplevel(self)
        window.title(tr("formal_diff_save"))
        window.geometry("900x650")
        box = TextBox(window)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        box.set("".join(difflib.unified_diff(source["content"].splitlines(True), content.splitlines(True), fromfile=source["path"], tofile=source["path"])))
        def save():
            """Submit exactly the reviewed content; do not re-read a possibly edited buffer."""
            self.action("save", path=source["path"], content=content, sha256=source["sha256"])
            window.destroy()
        ttk.Label(window, text=tr("formal_save_warning"), wraplength=840).pack(padx=14, pady=8)
        ttk.Button(window, text=tr("formal_confirm_save"), command=save).pack(pady=12)

    def destroy(self):
        """Release editor variables on the Tk thread; backend operations continue independently."""
        self.path = None
        super().destroy()

    def can_leave(self):
        """Warn before discarding unsaved authoring text or an unsaved stage journal."""
        dirty = self.opened_file and self.editor.get() != self.opened_file["content"]
        if dirty or self.journal.get() != self.saved_journal:
            return messagebox.askyesno(tr("formal_files"), tr("formal_discard"), parent=self)
        return True
