"""Native project-centred verification views backed exclusively by persisted API evidence."""

import json
import queue
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .client import collection, segment
from .dialogs import download, import_project, replay, scaffold, upload
from .events import EventFeed
from .i18n import tr
from .model import next_action
from .widgets import EvidencePanel, Form, ScrollFrame, StageTree, Table, TextBox, card, display, format_size, pretty, run_rows
from .visuals import ACCENT, FONT, INK, MUTED, PAGE, SUCCESS, SUCCESS_SOFT, SURFACE, WARNING, WARNING_SOFT, ActionButton, AttentionList, MetricCard, ProjectList, RunBanner, RunSummary, Surface, ToolHealth


RUN_COLUMNS = [("project_name", "project_name", 220), ("method_label", "methodology", 105), ("scope_label", "scope", 230),
               ("execution_status", "execution_status", 95), ("verification_status", "verification_status", 100), ("local_time", "time", 140), ("short_id", "ID", 100)]
RESULT_COLUMNS = {
    "jobs": [("name", "name", 150), ("execution_status", "execution_status", 110), ("verification_status", "verification_status", 110), ("exit_code", "Exit", 70), ("diagnostic_code", "reason", 250)],
    "tests": [("name", "test", 290), ("suite", "suite", 65), ("seed", "seed", 70), ("status", "verification_status", 100), ("uvm_errors", "UVM ERROR", 95), ("uvm_fatals", "UVM FATAL", 95)],
    "coverage": [("name", "name", 160), ("percentage", "%", 80), ("covered", "covered", 85), ("total", "count", 80), ("target", "Target %", 90), ("mapping", "FG / FC / CK", 220)],
    "properties": [("name", "name", 320), ("status", "verification_status", 105), ("engine", "engine", 100), ("depth", "depth", 80), ("runtime_seconds", "runtime", 90)],
    "issues": [("title", "name", 300), ("kind", "kind", 100), ("status", "check_status", 100), ("description", "reason", 350)],
    "artifacts": [("name", "name", 330), ("kind", "kind", 120), ("display_size", "size", 95), ("sha256", "SHA-256", 400)],
}


class BaseView(ttk.Frame):
    """Own asynchronous responses and timers so leaving a page cannot update stale widgets."""

    def __init__(self, parent, app, identifier=None):
        """Capture one service context and optional persisted entity identity."""
        super().__init__(parent)
        self.app = app
        self.client = app.client
        self.identifier = identifier
        self.timer = None

    def refresh(self):
        """Refresh this page; concrete views must implement their own read-only query."""
        raise NotImplementedError

    def loaded(self):
        """Report a healthy response without claiming any tool has passed verification."""
        self.app.connection.configure(text=tr("connected"), foreground=SUCCESS, background=SUCCESS_SOFT)
        self.app.message.configure(text="")
        self.app.message.grid_remove()

    def failed(self, error):
        """Expose a request error while preserving the last visible evidence."""
        self.app.connection.configure(text=tr("disconnected"), foreground=WARNING, background=WARNING_SOFT)
        self.app.notify(error)

    def poll(self):
        """Schedule one non-blocking refresh, never accumulate periodic timers."""
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.timer = self.after(5000, self.refresh)

    def destroy(self):
        """Cancel page timers; in-flight responses are discarded by the application owner check."""
        if self.timer is not None:
            self.after_cancel(self.timer)
        super().destroy()


class Dashboard(BaseView):
    """Lead with continuing projects, actionable results, and actual resource gates."""

    def __init__(self, parent, app, identifier=None):
        """Build a task-focused native workbench with no fabricated demonstration data."""
        super().__init__(parent, app, identifier)
        viewport = ScrollFrame(self)
        viewport.pack(fill="both", expand=True)
        body = viewport.content
        metrics = ttk.Frame(body)
        metrics.pack(fill="x", pady=(0, 18))
        self.metrics = {}
        for index, (key, picture) in enumerate((("project_count", "projects"), ("active", "runs"), ("attention", "warning"), ("disk", "disk"))):
            metrics.columnconfigure(index, weight=1, uniform="metric")
            metric = MetricCard(metrics, key, picture, WARNING if key == "attention" else ACCENT)
            metric.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 7, 0 if index == 3 else 7))
            self.metrics[key] = metric
        middle = ttk.Frame(body, height=373)
        middle.pack(fill="x", pady=(0, 18))
        middle.grid_propagate(False)
        middle.columnconfigure(0, weight=7, uniform="dashboard")
        middle.columnconfigure(1, weight=3, uniform="dashboard", minsize=296)
        middle.rowconfigure(0, weight=1)
        projects = Surface(middle, height=373, padding=18)
        projects.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        tools = tk.Frame(projects.body, background=SURFACE)
        tools.pack(fill="x", pady=(0, 10))
        tk.Label(tools, text=tr("projects"), font=(FONT, 12, "bold"), foreground=INK, background=SURFACE).pack(side="left")
        self.project_count = tk.Label(tools, text="", font=("Segoe UI", 9), foreground=MUTED, background=SURFACE)
        self.project_count.pack(side="left", padx=10)
        ActionButton(tools, tr("import_project"), lambda: import_project(app), variant="ghost", icon_name="plus", background=SURFACE, height=30).pack(side="right")
        self.projects = ProjectList(projects.body, self.open_project)
        self.projects.pack(fill="both", expand=True)
        tk.Label(projects.body, text=tr("project_list_hint"), font=(FONT, 8), foreground=MUTED, background=SURFACE, anchor="w").pack(side="bottom", before=self.projects, fill="x", pady=(5, 0))
        right = ttk.Frame(middle)
        right.grid(row=0, column=1, sticky="nsew")
        environment = Surface(right, height=212, padding=17)
        environment.pack(fill="x", pady=(0, 14))
        tk.Label(environment.body, text=tr("execution_environment"), font=(FONT, 11, "bold"), foreground=INK, background=SURFACE, anchor="w").pack(fill="x", pady=(0, 8))
        self.tool_health = ToolHealth(environment.body, lambda: app.show("toolchains"))
        self.tool_health.pack(fill="both", expand=True)
        attention = Surface(right, height=147, padding=17)
        attention.pack(fill="both", expand=True)
        tk.Label(attention.body, text=tr("attention"), font=(FONT, 11, "bold"), foreground=INK, background=SURFACE, anchor="w").pack(fill="x", pady=(0, 9))
        self.attention = AttentionList(attention.body, lambda run_id: app.show("run", run_id))
        self.attention.pack(fill="both", expand=True)
        recent = Surface(body, height=224, padding=18)
        recent.pack(fill="x")
        recent_bar = tk.Frame(recent.body, background=SURFACE)
        recent_bar.pack(fill="x", pady=(0, 9))
        tk.Label(recent_bar, text=tr("recent_runs"), font=(FONT, 12, "bold"), foreground=INK, background=SURFACE).pack(side="left")
        ActionButton(recent_bar, tr("view_all"), lambda: app.show("runs"), variant="ghost", icon_name="arrow", background=SURFACE, height=30).pack(side="right")
        self.runs = Table(recent.body, RUN_COLUMNS, on_open=self.open_run, height=3)
        self.runs.pack(fill="both", expand=True)

    def refresh(self):
        """Read the actual activity and latest per-project run results in a background worker."""
        def load():
            """Return three canonical collections without crossing the Tk boundary."""
            return self.client.call("/overview"), collection(self.client.call("/projects")), collection(self.client.call("/runs"))
        self.app.io(self, load, self.render, self.failed)
        self.poll()

    def render(self, data):
        """Project health and next actions from observed states, not names or demo assumptions."""
        overview, projects, runs = data
        self.loaded()
        latest = {}
        for run in runs:
            latest.setdefault(run["project_id"], run)
        attention = [run for run in latest.values() if run.get("verification_status") in ("failed", "inconclusive") or run.get("execution_status") in ("error", "timeout")]
        disk = overview.get("disk", {})
        self.metrics["project_count"].set("{:02d}".format(len(projects)), tr("metric_projects_note"))
        self.metrics["active"].set(display(overview.get("active_jobs")), tr("metric_active_note", count=display(overview.get("queued_jobs"))))
        self.metrics["attention"].set("{:02d}".format(len(attention)), tr("metric_attention_note"))
        self.metrics["disk"].set(format_size(disk.get("free_bytes")), tr("disk_gate_open" if disk.get("gate_open") else "disk_gate_closed"), disk.get("free_bytes", 0)/disk["total_bytes"] if disk.get("total_bytes") else None)
        self.project_count.configure(text="{:02d}".format(len(projects)))
        self.tool_health.set(overview.get("toolchains", []))
        self.attention.set_rows(attention)
        rows = []
        for project in projects:
            run = latest.get(project["id"])
            rows.append({**project, "top": project["design"].get("top"), "method_label": tr("formal" if project.get("workflow_family") == "formal" else project["methodology"]),
                         "latest_result": run.get("verification_status") if run else None, "next": tr(next_action(run)[0]) if run else tr("start_first_run")})
        self.projects.set_rows(rows)
        self.runs.set_rows(run_rows(runs[:12]))

    def open_project(self):
        """Navigate using a selected persisted project identity."""
        item = self.projects.selected()
        if item:
            self.app.show("project", item["id"])

    def start_project(self):
        """Start the run wizard with the selected project's actual saved defaults."""
        item = self.projects.selected()
        self.app.new_run(item["id"] if item else None)

    def open_run(self):
        """Open the selected historical run without creating or retrying work."""
        item = self.runs.selected()
        if item:
            self.app.show("run", item["id"])


class Projects(BaseView):
    """List imported server projects with their authoritative configuration."""

    def __init__(self, parent, app, identifier=None):
        """Create project navigation and an explicit server-directory import action."""
        super().__init__(parent, app, identifier)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Button(toolbar, text=tr("import_project"), command=lambda: import_project(app), style="Primary.TButton").pack(side="left")
        ttk.Button(toolbar, text=tr("open_project"), command=self.open).pack(side="left", padx=8)
        self.detail = EvidencePanel(self, height=9)
        self.table = Table(self, [("name", "project_name", 260), ("path", "path", 500), ("id", "ID", 260)], on_select=lambda item: self.detail.set(item or {}), on_open=self.open)
        self.table.pack(fill="both", expand=True)
        self.detail.pack(side="bottom", before=self.table, fill="x", pady=(12, 0))

    def refresh(self):
        """Read project records without mutating configuration files."""
        self.app.io(self, lambda: collection(self.client.call("/projects")), self.render, self.failed)

    def render(self, rows):
        """Replace project rows only after a valid server collection is received."""
        self.loaded()
        self.table.set_rows(rows)

    def open(self):
        """Enter one real project workspace."""
        item = self.table.selected()
        if item:
            self.app.show("project", item["id"])


class ProjectView(BaseView):
    """Keep saved inputs, model boundaries, and run history together within one project."""

    def __init__(self, parent, app, identifier=None):
        """Build a native project workspace whose primary action is a scoped run."""
        super().__init__(parent, app, identifier)
        self.project = None
        self.label = ttk.Label(self, text=tr("loading"), wraplength=1050)
        self.label.pack(fill="x", pady=(0, 12))
        self.migration_hint = ttk.Label(self, text="", style="Hint.TLabel", wraplength=1050)
        self.migration_source = ttk.Button(self, text=tr("formal_migration_open_source"),
            command=lambda: app.show("formal_session", self.project["migration"]["source_session_id"]))
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Button(toolbar, text=tr("new_run"), style="Primary.TButton", command=lambda: app.new_run(identifier)).pack(side="left")
        ttk.Button(toolbar, text=tr("scaffold"), command=self.generate).pack(side="left", padx=8)
        ttk.Button(toolbar, text=tr("upload"), command=lambda: upload(app, identifier)).pack(side="left")
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        self.runs = Table(notebook, RUN_COLUMNS[1:], on_open=self.open_run)
        notebook.add(self.runs, text=tr("runs"))
        self.inputs = Table(notebook, [("name", "name", 180), ("value", "details", 750)], height=10)
        notebook.add(self.inputs, text=tr("inputs"))
        self.assets = Table(notebook, [("name", "name", 180), ("value", "details", 750)], height=10)
        notebook.add(self.assets, text=tr("assets"))
        ttk.Label(self, text=tr("scope_warning"), style="Hint.TLabel", wraplength=1050).pack(fill="x", pady=(12, 0))

    def refresh(self):
        """Load this project's inputs and only its own run history."""
        def load():
            """Read a bounded project context from the captured service origin."""
            return self.client.call("/projects/" + segment(self.identifier)), collection(self.client.call("/runs?project_id=" + segment(self.identifier)))
        self.app.io(self, load, self.render, self.failed)
        self.poll()

    def render(self, data):
        """Show actual source/model/coverage declarations without inventing verification assets."""
        self.loaded()
        self.project, runs = data
        self.label.configure(text="{}\n{}".format(self.project["name"], self.project["path"]))
        migration = self.project.get("migration")
        if migration:
            self.migration_hint.configure(text=tr("formal_migration_source", session=migration["source_session_id"], revision=migration["source_revision"]))
            self.migration_hint.pack(fill="x", after=self.label, pady=(0, 6))
            self.migration_source.pack(anchor="w", after=self.migration_hint, pady=(0, 12))
        else:
            self.migration_hint.pack_forget()
            self.migration_source.pack_forget()
        self.runs.set_rows(run_rows(runs))
        self.inputs.set_rows([{"id": key, "name": tr(key), "value": value if not isinstance(value, (list, dict)) else json.dumps(value, ensure_ascii=False)} for key, value in self.project["design"].items()])
        simulation = self.project.get("simulation") or {}
        rows = [{"id": "reference", "name": tr("reference_model"), "value": simulation.get("reference_model") or tr("not_declared")},
                {"id": "coverage", "name": tr("coverage_mapping"), "value": simulation.get("coverage_mapping") or tr("unmapped")}]
        rows.extend({"id": "suite-"+str(index), "name": "{} · {}".format(suite.get("level", ""), suite.get("name", "")), "value": ", ".join(suite.get("tests", [])) + " | seed " + ", ".join(str(seed) for seed in suite.get("seeds", []))} for index, suite in enumerate(simulation.get("suites", [])))
        rows.append({"id": "agent", "name": "Agent", "value": tr("agent_boundary")})
        self.assets.set_rows(rows)

    def generate(self):
        """Open a separate explicit UVM scaffold dialog after project data is available."""
        if self.project:
            scaffold(self.app, self.project)

    def open_run(self):
        """Open a selected project run without changing it."""
        run = self.runs.selected()
        if run:
            self.app.show("run", run["id"])


class RunHistory(BaseView):
    """Search actual run history and distinguish execution failure from verification failure."""

    def __init__(self, parent, app, identifier=None):
        """Create status filters, search, and double-click navigation."""
        super().__init__(parent, app, identifier)
        self.rows = []
        self.search = tk.StringVar(self)
        self.filter = tk.StringVar(self, value="all")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 12))
        ttk.Label(bar, text=tr("search")).pack(side="left")
        ttk.Entry(bar, textvariable=self.search, width=35).pack(side="left", padx=8)
        ttk.Combobox(bar, textvariable=self.filter, values=["all", "queued", "running", "completed", "error", "timeout", "cancelled", "passed", "failed", "inconclusive"], state="readonly", width=15).pack(side="left")
        ttk.Button(bar, text=tr("open_run"), command=self.open).pack(side="right")
        self.detail = EvidencePanel(self, height=8)
        self.table = Table(self, RUN_COLUMNS, on_select=lambda item: self.detail.set(item or {}), on_open=self.open)
        self.table.pack(fill="both", expand=True)
        self.detail.pack(side="bottom", before=self.table, fill="x", pady=(12, 0))
        self.search.trace_add("write", lambda *args: self.filter_rows())
        self.filter.trace_add("write", lambda *args: self.filter_rows())

    def refresh(self):
        """Poll the persisted history while keeping search and selection intact."""
        self.app.io(self, lambda: collection(self.client.call("/runs")), self.render, self.failed)
        self.poll()

    def render(self, rows):
        """Cache observed rows for purely local filtering."""
        self.loaded()
        self.rows = rows
        self.filter_rows()

    def filter_rows(self):
        """Filter literal data without evaluating searches or issuing a new server query."""
        query = self.search.get().casefold().strip()
        status = self.filter.get()
        rows = [row for row in self.rows if (not query or query in json.dumps(row, ensure_ascii=False).casefold()) and (status == "all" or status in (row.get("execution_status"), row.get("verification_status")))]
        self.table.set_rows(run_rows(rows))

    def open(self):
        """Open the selected immutable run record."""
        item = self.table.selected()
        if item:
            self.app.show("run", item["id"])

    def destroy(self):
        """Remove variable traces before asynchronous callbacks can release a retired page."""
        for variable in (self.search, self.filter):
            for modes, command in variable.trace_info():
                variable.trace_remove(modes, command)
        self.search = None
        self.filter = None
        super().destroy()


class RunView(BaseView):
    """Expose run scope, full stage tree, normalized results, live evidence, and explicit actions."""

    def __init__(self, parent, app, identifier=None):
        """Build native evidence tabs and an independently cancellable resumable event reader."""
        super().__init__(parent, app, identifier)
        self.run = None
        self.feed = None
        self.stream_timer = None
        self.tables = {}
        self.details = {}
        self.tabs = {}
        self.rows = {}
        self.active_category = "overview"
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 12))
        self.identity = ttk.Label(bar, text="RUN / " + identifier, font=("Consolas", 10), foreground=MUTED)
        self.identity.pack(side="left")
        self.cancel_button = ActionButton(bar, text=tr("cancel_run"), command=self.cancel_run, state="disabled")
        self.cancel_button.pack(side="right")
        self.clone_button = ActionButton(bar, text=tr("clone_run"), command=self.clone, state="disabled", icon_name="refresh")
        self.clone_button.pack(side="right", padx=8)
        self.summary = RunBanner(self)
        self.summary.pack(fill="x", pady=(0, 12))
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        overview_scroll = ScrollFrame(self.notebook)
        self.tabs["overview"] = overview_scroll
        self.notebook.add(overview_scroll, text=tr("run_overview"))
        overview = ttk.Frame(overview_scroll.content, padding=12)
        overview.pack(fill="x")
        self.action = ttk.Label(overview, text="", wraplength=980, font=("Microsoft YaHei UI", 12, "bold"))
        self.action.pack(fill="x", pady=(4, 10))
        ActionButton(overview, text=tr("next_action"), command=self.go_next, variant="primary", icon_name="arrow").pack(anchor="w", pady=(0, 12))
        ttk.Label(overview, text=tr("scope_warning"), wraplength=980, style="Hint.TLabel").pack(fill="x", pady=(0, 12))
        self.overview = RunSummary(overview)
        self.overview.pack(fill="x")
        self.raw_overview = EvidencePanel(overview, height=7)
        self.raw_overview.pack(fill="x", pady=(10, 0))
        stages = ttk.Frame(self.notebook, padding=8)
        self.tabs["stages"] = stages
        self.notebook.add(stages, text=tr("tab_stages"))
        actionbar = ttk.Frame(stages)
        actionbar.pack(fill="x", pady=(0, 8))
        self.stage_buttons = {}
        for action in ("approve", "reject", "retry"):
            button = ttk.Button(actionbar, text=tr(action), command=lambda choice=action: self.stage_action(choice), state="disabled")
            button.pack(side="left", padx=(0, 8))
            self.stage_buttons[action] = button
        self.stage_detail = EvidencePanel(stages, height=7)
        self.stage_tree = StageTree(stages, self.select_stage)
        self.stage_tree.pack(fill="both", expand=True)
        self.stage_detail.pack(side="bottom", before=self.stage_tree, fill="x", pady=(8, 0))
        for category, columns in RESULT_COLUMNS.items():
            page = ttk.Frame(self.notebook, padding=8)
            self.tabs[category] = page
            self.notebook.add(page, text=tr("tab_"+category))
            if category == "properties":
                tools = ttk.Frame(page)
                tools.pack(fill="x", pady=(0, 8))
                ttk.Button(tools, text=tr("cex_replay"), command=self.replay).pack(side="left")
                ttk.Button(tools, text=tr("replay_history"), command=self.replay_history).pack(side="left", padx=8)
            if category == "artifacts":
                tools = ttk.Frame(page)
                tools.pack(fill="x", pady=(0, 8))
                ttk.Button(tools, text=tr("download"), command=self.download, style="Primary.TButton").pack(side="left")
                ttk.Button(tools, text=tr("verdi"), command=lambda: app.copy(tr("verdi_command"))).pack(side="left", padx=8)
                ttk.Label(page, text=tr("wave_help"), style="Hint.TLabel", wraplength=980).pack(fill="x", pady=(0, 8))
            detail = EvidencePanel(page, height=8)
            table = Table(page, columns, on_select=lambda item, box=detail: box.set(item or {}), height=10)
            table.pack(fill="both", expand=True)
            detail.pack(side="bottom", before=table, fill="x", pady=(8, 0))
            self.tables[category] = table
            self.details[category] = detail
        logs = ttk.Frame(self.notebook, padding=8)
        self.tabs["logs"] = logs
        self.notebook.add(logs, text=tr("tab_logs"))
        logbar = ttk.Frame(logs)
        logbar.pack(fill="x", pady=(0, 8))
        self.follow = tk.BooleanVar(self, value=True)
        ttk.Checkbutton(logbar, text=tr("follow"), variable=self.follow).pack(side="left")
        ttk.Button(logbar, text=tr("history_logs"), command=lambda: self.start_stream(0)).pack(side="left", padx=8)
        ttk.Button(logbar, text=tr("clear"), command=lambda: self.log.set("")).pack(side="left")
        self.stream_status = ttk.Label(logbar, text=tr("stream_connecting"), style="Hint.TLabel")
        self.stream_status.pack(side="right")
        self.log = TextBox(logs, terminal=True)
        self.log.pack(fill="both", expand=True)
        audit = ttk.Frame(self.notebook, padding=8)
        self.tabs["audit"] = audit
        self.notebook.add(audit, text=tr("tab_audit"))
        ttk.Label(audit, text=tr("no_agent"), wraplength=980, style="Hint.TLabel").pack(fill="x", pady=(0, 8))
        self.audit = TextBox(audit)
        self.audit.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.start_stream(app.preferences.cursors.get(identifier, 0))

    def refresh(self):
        """Poll run state and only the visible result category, leaving log streaming independent."""
        self.app.io(self, lambda: self.client.call("/runs/" + segment(self.identifier)), self.render, self.failed)
        self.load_category(self.active_category)
        self.poll()

    def render(self, run):
        """Present separate execution/result states and preserve all recorded stage evidence."""
        self.loaded()
        self.run = run
        self.clone_button.configure(state="normal")
        self.cancel_button.configure(state="normal" if run["execution_status"] in ("queued", "running") else "disabled")
        self.summary.set(run)
        self.action.configure(text=tr(next_action(run)[0]))
        self.overview.set({"summary": run.get("summary"), "request": run.get("request"), "manifest_hash": run.get("manifest_hash"), "cex_replay": run.get("cex_replay"), "created_at": run.get("created_at"), "error": run.get("error")})
        self.raw_overview.set(run)
        self.stage_tree.set_rows(run.get("stages", []))
        self.select_stage(self.stage_tree.selected())

    def tab_changed(self, event=None):
        """Lazily load the selected evidence table instead of polling every large collection."""
        tab = self.notebook.select()
        self.active_category = next((key for key, page in self.tabs.items() if str(page) == tab), "overview")
        self.load_category(self.active_category)

    def select_tab(self, category):
        """Navigate to a real evidence destination using a stable category key."""
        self.notebook.select(self.tabs[category])

    def load_category(self, category):
        """Request one normalized result collection without accepting arbitrary paths."""
        if category not in RESULT_COLUMNS:
            return
        path = "/runs/{}/{}".format(segment(self.identifier), category)
        self.app.io(self, lambda: collection(self.client.call(path)), lambda rows: self.render_category(category, rows), self.failed, key=category)

    def render_category(self, category, rows):
        """Preserve null counters and missing coverage mappings instead of inventing completeness."""
        self.rows[category] = rows
        if category == "artifacts":
            rows = [{**row, "display_size": format_size(row.get("size"))} for row in rows]
        elif category == "tests":
            rows = [{**row, "status": row.get("status") or row.get("verification_status")} for row in rows]
        elif category == "coverage":
            rows = [{**row, "target": row.get("target", tr("no_target")), "mapping": row.get("mapping") or tr("unmapped")} for row in rows]
        self.tables[category].set_rows(rows)

    def go_next(self):
        """Navigate based on this run's observed state rather than a synthetic progress percentage."""
        if self.run:
            self.select_tab(next_action(self.run)[1])

    def clone(self):
        """Copy the immutable saved request into a new editable wizard, preserving every input."""
        if self.run:
            self.app.new_run(self.run["project_id"], self.run["request"])

    def cancel_run(self):
        """Require explicit confirmation before requesting remote process-tree cancellation."""
        if self.run and messagebox.askyesno(tr("cancel_run"), tr("cancel_confirm"), parent=self):
            self.app.io(self, lambda: self.client.call("/runs/{}/cancel".format(segment(self.identifier)), "POST"), lambda result: self.refresh(), key="cancel")

    def select_stage(self, stage):
        """Enable only applicable human decisions; approval cannot rewrite verification evidence."""
        self.stage_detail.set(stage or {})
        pending = bool(stage and stage.get("enabled") and stage.get("requires_human_approval") and stage.get("approval_status") == "pending")
        terminal = bool(stage and stage.get("enabled") and self.run and self.run.get("execution_status") not in ("running", "queued"))
        for action, button in self.stage_buttons.items():
            button.configure(state="normal" if (terminal if action == "retry" else pending) else "disabled")

    def stage_action(self, action):
        """Send one explicit approval or create a separate retry run with a review note."""
        stage = self.stage_tree.selected()
        if not stage:
            return
        if action == "retry" and not messagebox.askyesno(tr("retry"), tr("retry_confirm"), parent=self):
            return
        note = simpledialog.askstring(tr(action), tr("approval_note") + "\n" + tr("approval_help"), parent=self)
        if note is None:
            return
        def done(result):
            """Open a new retry identity or refresh the unchanged original evidence."""
            retry_run = result.get("retry_run")
            if retry_run:
                self.app.show("run", retry_run["id"])
            else:
                self.refresh()
        self.app.io(self, lambda: self.client.call("/stages/{}/{}".format(segment(stage["id"]), action), "POST", {"note": note}), done, key="stage-action")

    def replay(self):
        """Open the explicit CEX-to-dynamic-test mapping dialog."""
        return replay(self.app, self.identifier, self.tables["properties"].selected())

    def replay_history(self):
        """Show persisted replay attempts, including failed or still-unreproduced counterexamples."""
        self.app.io(self, lambda: self.client.call("/runs/{}/counterexample-replays".format(segment(self.identifier))), self.details["properties"].set, key="replays")

    def download(self):
        """Download only an explicitly selected signed file artifact."""
        return download(self.app, self.tables["artifacts"].selected())

    def start_stream(self, cursor):
        """Resume or explicitly rewind a local log viewport without altering server event history."""
        if self.feed:
            self.feed.close()
        if self.stream_timer is not None:
            self.after_cancel(self.stream_timer)
        self.feed = EventFeed(self.client, self.identifier, cursor)
        self.log.set(tr("logs_cursor", cursor=cursor) + "\n" if cursor else "")
        self.audit.set("")
        self.app.preferences.cursors[self.identifier] = cursor
        self.stream_timer = self.after(100, self.drain_stream)

    def drain_stream(self):
        """Render bounded event batches and acknowledge only records consumed by the UI."""
        log_lines = []
        audit_lines = []
        for _ in range(200):
            try:
                kind, value = self.feed.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "event":
                if value["sequence"] <= self.app.preferences.cursors.get(self.identifier, 0):
                    continue
                line = "#{sequence} {timestamp} [{type}] {message}\n".format(sequence=value["sequence"], timestamp=value.get("timestamp", ""), type=value["type"], message=value.get("message") or pretty(value.get("data", {})))
                log_lines.append(line)
                if value["type"].startswith(("agent.", "assistant.", "user.", "stage.", "audit.", "approval.")):
                    audit_lines.append(line)
                self.app.preferences.cursors[self.identifier] = value["sequence"]
                self.stream_status.configure(text=tr("stream_live"))
            elif kind == "status":
                self.stream_status.configure(text=tr(value))
            else:
                self.stream_status.configure(text=tr("stream_retry"))
                self.app.status.configure(text=value)
        if log_lines:
            self.log.append("".join(log_lines), self.follow.get())
        if audit_lines:
            self.audit.append("".join(audit_lines), True)
        self.stream_timer = self.after(100, self.drain_stream)

    def destroy(self):
        """Persist the consumed cursor and stop local readers; remote jobs continue."""
        self.follow = None
        if self.feed:
            self.feed.close()
        if self.stream_timer is not None:
            self.after_cancel(self.stream_timer)
        try:
            self.app.preferences.save()
        except OSError as exc:
            self.app.notify(exc)
        super().destroy()


class Workflows(BaseView):
    """Display the complete workflow catalog, including conditional and disabled stages."""

    def __init__(self, parent, app, identifier=None):
        """Build a native workflow selector and expandable branch hierarchy."""
        super().__init__(parent, app, identifier)
        self.workflows = {}
        self.selected = tk.StringVar(self)
        self.formal_engine = tk.StringVar(self, value="formalmc")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 12))
        self.selector = ttk.Combobox(bar, textvariable=self.selected, state="readonly", width=36)
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", lambda event: self.show_workflow())
        ttk.Label(bar, text=tr("formal_workflow_engine")).pack(side="left", padx=(18, 6))
        self.engine_selector = ttk.Combobox(bar, textvariable=self.formal_engine, values=["formalmc", "sby"], state="readonly", width=12)
        self.engine_selector.pack(side="left")
        self.engine_selector.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        ttk.Button(bar, text=tr("formal_open"), command=lambda: self.app.show("formal_sessions")).pack(side="left", padx=12)
        ttk.Label(self, text=tr("workflow_help"), wraplength=1060, style="Hint.TLabel").pack(fill="x", pady=(0, 12))
        self.detail = EvidencePanel(self, height=9)
        self.tree = StageTree(self, lambda item: self.detail.set(item or {}))
        self.tree.pack(fill="both", expand=True)
        self.detail.pack(side="bottom", before=self.tree, fill="x", pady=(12, 0))

    def refresh(self):
        """Read all registered workflow families without filtering hidden branches client-side."""
        engine = self.formal_engine.get()
        endpoint = "/workflows" if engine == "formalmc" else "/workflows?formal_engine=sby"
        self.app.io(self, lambda: collection(self.client.call(endpoint)), self.render, self.failed)

    def render(self, rows):
        """Populate every workflow and preserve an existing selection when possible."""
        self.loaded()
        self.workflows = {row["id"]: row for row in rows}
        self.selector.configure(values=list(self.workflows))
        if self.selected.get() not in self.workflows:
            self.selected.set(next(iter(self.workflows), ""))
        self.show_workflow()

    def show_workflow(self):
        """Render the selected complete DAG as an inspectable parent/child tree."""
        workflow = self.workflows.get(self.selected.get())
        self.tree.set_rows(workflow["stages"] if workflow else [])
        self.detail.set(workflow and {key: value for key, value in workflow.items() if key != "stages"} or {})

    def destroy(self):
        """Release the workflow selector's Tcl variable on its creating thread."""
        self.selected = None
        self.formal_engine = None
        super().destroy()


class Toolchains(BaseView):
    """Separate per-tool executable availability from actual commercial license checkout."""

    def __init__(self, parent, app, identifier=None):
        """Build profile and capability tables with an explicit bounded probe action."""
        super().__init__(parent, app, identifier)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 12))
        self.probe_button = ttk.Button(bar, text=tr("probe"), command=self.probe)
        self.probe_button.pack(side="left")
        ttk.Label(bar, text=tr("probe_help"), wraplength=750, style="Hint.TLabel").pack(side="left", padx=12)
        self.profiles = Table(self, [("name", "name", 250), ("status", "check_status", 130), ("license_status", "license_status", 130), ("last_probe_at", "time", 220)], on_select=self.select, height=2)
        self.profiles.pack(fill="x")
        self.detail = EvidencePanel(self, height=7)
        self.capabilities = Table(self, [("name", "name", 140), ("available", "available", 85), ("license_status", "license_status", 90), ("version", "version", 340), ("reason", "reason", 250)], on_select=lambda item: self.detail.set(item or {}))
        self.capabilities.pack(fill="both", expand=True, pady=(12, 0))
        self.detail.pack(side="bottom", before=self.capabilities, fill="x", pady=(12, 0))

    def refresh(self):
        """Read persisted toolchain health without silently consuming licenses."""
        self.app.io(self, lambda: collection(self.client.call("/toolchains")), self.render, self.failed)

    def render(self, rows):
        """Show per-capability results instead of a single misleading platform Pass badge."""
        self.loaded()
        self.profiles.set_rows(rows)
        if rows and not self.profiles.selected():
            self.profiles.tree.selection_set(rows[0]["id"])
        self.select(self.profiles.selected())

    def select(self, item):
        """Show the selected administrator profile's redacted capability metadata."""
        self.capabilities.set_rows(item.get("capabilities", []) if item else [])
        self.detail.set(item or {})

    def probe(self):
        """Run a user-requested backend probe, keeping the Tk event loop responsive."""
        item = self.profiles.selected()
        if not item or not messagebox.askyesno(tr("probe"), tr("probe_help"), parent=self):
            return
        self.probe_button.configure(state="disabled")
        def done(result):
            """Refresh persisted health after an actual probe completes."""
            self.probe_button.configure(state="normal")
            self.detail.set(result)
            self.refresh()
        def failed(error):
            """Expose an uncertain probe outcome without issuing a second license request."""
            self.probe_button.configure(state="normal")
            self.failed(error)
        self.app.io(self, lambda: self.client.call("/toolchains/{}/probe".format(segment(item["id"])), "POST", timeout=180), done, failed, key="probe")


class McpView(BaseView):
    """Expose real service schemas and client configuration without treating MCP as a webpage."""

    def __init__(self, parent, app, identifier=None):
        """Create a native protocol inspector with copyable configuration."""
        super().__init__(parent, app, identifier)
        self.config = {}
        ttk.Label(self, text=tr("mcp_help"), wraplength=1050, style="Hint.TLabel").pack(fill="x", pady=(0, 12))
        ttk.Button(self, text=tr("copy"), command=lambda: app.copy(pretty(self.config))).pack(anchor="w", pady=(0, 12))
        self.status = ttk.Label(self, text=tr("loading"))
        self.status.pack(fill="x", pady=(0, 12))
        self.detail = EvidencePanel(self, height=12)
        self.tools = Table(self, [("name", "name", 250), ("description", "details", 700)], on_select=lambda item: self.detail.set(item or {}), height=8)
        self.tools.pack(fill="both", expand=True)
        self.detail.pack(side="bottom", before=self.tools, fill="x", pady=(12, 0))

    def refresh(self):
        """Read the actual hosted MCP service and its current schemas."""
        self.app.io(self, lambda: self.client.call("/mcp"), self.render, self.failed)

    def render(self, result):
        """Display observed protocol metadata rather than generated placeholder tools."""
        self.loaded()
        self.config = result.get("client_config", {})
        self.status.configure(text="{}   {}   {}".format(display(result.get("status"), "status"), result.get("protocol_url", ""), result.get("transport", "")))
        self.tools.set_rows(result.get("tools", []))
        self.detail.set({key: value for key, value in result.items() if key != "tools"})


class Settings(BaseView):
    """Separate non-secret local connection preferences from typed backend resource limits."""

    def __init__(self, parent, app, identifier=None):
        """Create guarded fields without exposing administrator secrets or shell recipes."""
        super().__init__(parent, app, identifier)
        viewport = ScrollFrame(self)
        viewport.pack(fill="both", expand=True)
        body = viewport.content
        ttk.Label(body, text=tr("connection_help"), wraplength=800, style="Hint.TLabel").pack(fill="x", pady=(0, 12))
        ActionButton(body, text=tr("preferences"), command=app.connection_dialog, icon_name="settings").pack(anchor="w", pady=(0, 16))
        group = card(body, "platform_settings")
        group.pack(fill="x", pady=(0, 12))
        self.form = Form(group)
        self.form.pack(fill="x")
        for key in ("minimum_free_disk_gb", "max_concurrency", "retention_days"):
            self.form.add(key, key)
        self.button = ttk.Button(group, text=tr("save"), command=self.save, state="disabled")
        self.button.pack(anchor="e", pady=(8, 0))
        self.detail = EvidencePanel(body)
        self.detail.pack(fill="x")

    def refresh(self):
        """Load current limits and readonly deployment paths."""
        self.app.io(self, lambda: self.client.call("/settings"), self.render, self.failed)

    def render(self, result):
        """Populate only supported writable settings and keep deployment paths readonly."""
        self.loaded()
        for key, field in self.form.fields.items():
            field.set("" if result.get(key) is None else str(result[key]))
        self.detail.set(result)
        self.button.configure(state="normal")

    def save(self):
        """Validate numeric bounds before explicitly updating backend resource policy."""
        try:
            values = self.form.values()
            body = {"minimum_free_disk_gb": float(values["minimum_free_disk_gb"]), "max_concurrency": int(values["max_concurrency"]), "retention_days": int(values["retention_days"]) if values["retention_days"].strip() else None}
            if not 1 <= body["minimum_free_disk_gb"] < float("inf") or body["max_concurrency"] < 1 or (body["retention_days"] is not None and body["retention_days"] < 1):
                raise ValueError("Disk, concurrency and optional retention must be positive; disk requires at least 1 GiB.")
            self.app.io(self, lambda: self.client.call("/settings", "PUT", body), self.render, key="save")
        except ValueError as exc:
            self.app.notify(exc)
