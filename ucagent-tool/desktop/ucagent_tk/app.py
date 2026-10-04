"""Native desktop shell with bounded background I/O and main-thread-only Tk updates."""

import gc
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .client import ApiClient
from .i18n import tr
from .model import Preferences
from .widgets import Form
from .visuals import ACCENT, ACCENT_SOFT, FONT, INK, LINE, MUTED, NAV, NAV_TEXT, PAGE, SUCCESS, SUCCESS_SOFT, SURFACE, ActionButton, NavItem, icon, rounded


def _io_worker(work_queue, result_queue, stop):
    """Run I/O without retaining application, widget, or completion-callback ownership."""
    while not stop.is_set():
        try:
            identity, work = work_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            value = work()
            succeeded = True
        except Exception as exc:
            value = exc.with_traceback(None)
            succeeded = False
        # The main-thread registry still owns work here. Drop the worker's last
        # closure reference before announcing completion, so Tk variables cannot
        # be finalized by an I/O thread when a page has already been closed.
        work = None
        result_queue.put((identity, succeeded, value))


class Application:
    """Host native views backed by the same local or remote EDA execution service."""

    def __init__(self, root, origin=None, preferences=None, local_service=None):
        """Build the desktop shell, daemon I/O workers, and initial workbench."""
        # CPython's cyclic collector otherwise runs in whichever HTTP thread
        # happens to allocate next, including finalizing retired Tcl interpreters.
        # This standalone Tk process owns GC and collects on the UI thread instead.
        gc.disable()
        self.last_collection = time.monotonic()
        self.root = root
        self.preferences = preferences or Preferences()
        self.local_service = local_service
        self.client = local_service.client if local_service else ApiClient(origin or self.preferences.origin)
        if not local_service:
            if self.client.origin != self.preferences.origin:
                self.preferences.cursors = {}
            self.preferences.origin = self.client.origin
        self.closed = False
        self.closing = False
        self.stop_workers = threading.Event()
        self.work = queue.Queue(maxsize=32)
        self.results = queue.Queue(maxsize=128)
        self.pending = set()
        self.tasks = {}
        self.task_sequence = 0
        self.local_cancellations = set()
        self.view = None
        self.generation = 0
        self.root.title(tr("app_title"))
        self.root.geometry("1440x940")
        self.root.minsize(1120, 760)
        self.root.configure(background=PAGE)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=PAGE, foreground=INK, troughcolor=PAGE, bordercolor=LINE, lightcolor=PAGE, darkcolor=PAGE)
        style.configure("TFrame", background=PAGE)
        style.configure("TLabel", background=PAGE, foreground=INK)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("Card.TLabel", background=SURFACE)
        style.configure("TButton", padding=(16, 9), relief="flat", borderwidth=1, background=SURFACE, bordercolor="#DFE4EF", lightcolor=SURFACE, darkcolor=SURFACE)
        style.map("TButton", background=[("active", "#F7F8FF"), ("disabled", "#ECEFF5")], bordercolor=[("focus", ACCENT)], foreground=[("disabled", "#A2ABBB")])
        style.configure("Primary.TButton", background=ACCENT, foreground=SURFACE, borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Primary.TButton", background=[("active", "#4556D6"), ("disabled", "#C6CDEF")], foreground=[("disabled", "#F3F4FC")])
        style.configure("Title.TLabel", font=(FONT, 22, "bold"), foreground=INK)
        style.configure("Hint.TLabel", foreground=MUTED, font=(FONT, 9))
        style.configure("Error.TLabel", foreground="#B25B58")
        style.configure("TEntry", padding=(10, 8), fieldbackground=SURFACE, bordercolor="#DFE4EF", lightcolor=SURFACE, darkcolor=SURFACE, insertcolor=INK)
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure("TCombobox", padding=(10, 7), fieldbackground=SURFACE, background=SURFACE, bordercolor="#DFE4EF", arrowcolor=MUTED, lightcolor=SURFACE, darkcolor=SURFACE)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", INK)], bordercolor=[("focus", ACCENT)])
        style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, rowheight=43, borderwidth=0, font=(FONT, 9), foreground=INK)
        style.configure("Treeview.Heading", padding=(12, 11), background="#F7F9FC", foreground=MUTED, font=(FONT, 9), relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", "#EDF1FA")])
        style.configure("TLabelframe", relief="solid", borderwidth=1, bordercolor=LINE)
        style.configure("TLabelframe.Label", font=(FONT, 10, "bold"), foreground=INK)
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", "#364ABD")])
        style.configure("TNotebook", background=PAGE, borderwidth=0, tabmargins=(0, 0, 0, 5))
        style.configure("TNotebook.Tab", padding=(14, 11), background=PAGE, borderwidth=0, lightcolor=PAGE, darkcolor=PAGE, bordercolor=PAGE, foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", ACCENT_SOFT)], foreground=[("selected", ACCENT)], lightcolor=[("selected", SURFACE)], darkcolor=[("selected", SURFACE)], bordercolor=[("selected", SURFACE)])
        style.configure("Vertical.TScrollbar", background="#D7DDE8", troughcolor=PAGE, borderwidth=0, arrowsize=10, width=8)
        style.configure("Horizontal.TScrollbar", background="#D7DDE8", troughcolor=PAGE, borderwidth=0, arrowsize=10, width=8)
        style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"})]})])
        style.layout("Horizontal.TScrollbar", [("Horizontal.Scrollbar.trough", {"sticky": "we", "children": [("Horizontal.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"})]})])
        self.app_icon = tk.PhotoImage(master=root, width=32, height=32)
        self.app_icon.put(ACCENT, to=(0, 0, 32, 32))
        self.app_icon.put("#DDE3FF", to=(7, 7, 25, 25))
        self.app_icon.put(ACCENT, to=(10, 10, 22, 22))
        self.app_icon.put(SURFACE, to=(13, 13, 19, 19))
        self.root.iconphoto(True, self.app_icon)
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        sidebar = tk.Frame(root, background=NAV, width=220)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.pack_propagate(False)
        brand = tk.Canvas(sidebar, height=101, background=NAV, highlightthickness=0)
        brand.pack(fill="x")
        rounded(brand, 23, 27, 60, 64, 11, fill=ACCENT, outline="")
        icon(brand, "chip", 30, 34, 23, SURFACE)
        brand.create_text(73, 37, text="UCAgent", font=("Segoe UI", 17, "bold"), fill=SURFACE, anchor="w")
        brand.create_text(74, 59, text="VERIFICATION STUDIO", font=("Segoe UI", 7), fill="#8E9BB4", anchor="w")
        tk.Frame(sidebar, background="#263149", height=1).pack(fill="x", padx=24, pady=(0, 20))
        self.navigation = {}
        for name in ("overview", "projects", "formal_sessions", "campaigns", "runs", "workflows", "toolchains", "mcp", "settings"):
            if name in ("overview", "runs", "toolchains"):
                tk.Label(sidebar, text=tr("nav_group_"+name), font=(FONT, 8), foreground="#8796AE", background=NAV, anchor="w").pack(fill="x", padx=28, pady=(12 if name != "overview" else 0, 9))
            button = NavItem(sidebar, name, lambda selected=name: self.show(selected))
            button.pack(fill="x", padx=12, pady=2)
            self.navigation[name] = button
        rail_footer = tk.Frame(sidebar, background=NAV)
        rail_footer.pack(side="bottom", fill="x", padx=24, pady=24)
        tk.Label(rail_footer, text="DESKTOP  /  PYTHON 3.8+", background=NAV, foreground="#6C7D99", font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(0, 10))
        self.lifecycle_hint = tk.Label(rail_footer, text=tr("local_restart_warning" if local_service else "restart_warning"), background=NAV, foreground=NAV_TEXT, font=(FONT, 8), justify="left", anchor="w")
        self.lifecycle_hint.pack(fill="x")
        main = ttk.Frame(root)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        topbar = tk.Frame(main, background=SURFACE, height=64)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="WORKSPACE", font=("Segoe UI", 8, "bold"), foreground=MUTED, background=SURFACE).pack(side="left", padx=(28, 12))
        self.breadcrumb = tk.Label(topbar, text=tr("overview"), font=(FONT, 9), foreground=INK, background=SURFACE)
        self.breadcrumb.pack(side="left")
        ActionButton(topbar, tr("connect_short"), self.connection_dialog, variant="ghost", icon_name="settings", background=SURFACE, width=92).pack(side="right", padx=(8, 22))
        self.connection = tk.Label(topbar, text=tr("connecting"), background=PAGE, foreground=MUTED, padx=11, pady=6, font=(FONT, 8))
        self.connection.pack(side="right", padx=10)
        ActionButton(topbar, tr("quick_search"), self.search, variant="secondary", icon_name="search", background=SURFACE, width=214, height=34).pack(side="right", padx=12)
        workspace = ttk.Frame(main, padding=(28, 0, 28, 0))
        workspace.grid(row=1, column=0, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(2, weight=1)
        header = ttk.Frame(workspace)
        header.grid(row=0, column=0, sticky="ew", pady=(24, 18))
        heading = ttk.Frame(header)
        heading.pack(side="left", fill="x", expand=True)
        self.title = ttk.Label(heading, text=tr("overview"), style="Title.TLabel")
        self.title.pack(anchor="w")
        self.subtitle = ttk.Label(heading, text=tr("subtitle_overview"), style="Hint.TLabel")
        self.subtitle.pack(anchor="w", pady=(7, 0))
        self.new_run_button = ActionButton(header, tr("new_run"), self.new_run, variant="primary", icon_name="plus", width=132, height=42)
        self.new_run_button.pack(side="right", padx=(10, 0))
        ActionButton(header, tr("refresh"), self.refresh, icon_name="refresh", width=92, height=42).pack(side="right")
        self.message = ttk.Label(workspace, text="", wraplength=1040, style="Error.TLabel")
        self.message.grid(row=1, column=0, sticky="ew")
        self.message.grid_remove()
        self.content = ttk.Frame(workspace)
        self.content.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        footer = ttk.Frame(workspace)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 9))
        self.status = ttk.Label(footer, text=self.client.origin, style="Hint.TLabel")
        self.status.pack(side="left")
        ttk.Label(footer, text=tr("evidence_footer"), style="Hint.TLabel").pack(side="right")
        for index in range(4):
            threading.Thread(target=_io_worker, args=(self.work, self.results, self.stop_workers), name="desktop-http-{}".format(index), daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<F5>", lambda event: self.refresh())
        self.root.bind("<Control-n>", lambda event: self.new_run())
        self.root.bind("<Control-k>", lambda event: self.search())
        self.pump_timer = self.root.after(40, self._pump)
        self.show("overview")

    def _pump(self):
        """Deliver completed work only to still-live widgets on the Tk main thread."""
        if self.closed:
            return
        if time.monotonic() - self.last_collection >= 2:
            gc.collect()
            self.last_collection = time.monotonic()
        for _ in range(48):
            try:
                identity, succeeded, value = self.results.get_nowait()
            except queue.Empty:
                break
            owner, key, generation, work, done, failed = self.tasks.pop(identity)
            self.pending.discard(key)
            callback = done if succeeded else failed or self.notify
            if not self.closing and generation == self.generation and owner.winfo_exists():
                try:
                    callback(value)
                except Exception as exc:
                    self.notify(exc)
        if self.closing and not self.tasks:
            self.stop_workers.set()
            self.closed = True
            self.root.destroy()
            gc.collect()
        else:
            self.pump_timer = self.root.after(40, self._pump)

    def io(self, owner, work, done, failed=None, key="load"):
        """Schedule coalesced work, keeping network operations out of Tk callbacks."""
        identity = (self.generation, str(owner), key)
        if self.closing or self.closed or identity in self.pending:
            return False
        self.pending.add(identity)
        self.task_sequence += 1
        task_id = self.task_sequence
        self.tasks[task_id] = (owner, identity, self.generation, work, done, failed)
        try:
            self.work.put_nowait((task_id, work))
        except queue.Full:
            del self.tasks[task_id]
            self.pending.discard(identity)
            self.notify("Desktop request queue is full; wait for current operations.")
            return False
        return True

    def notify(self, value):
        """Expose a bounded actionable failure without interrupting background polling."""
        self.message.configure(text=str(value)[:2200])
        self.message.grid()

    def copy(self, value):
        """Copy explicitly selected metadata; never start a local shell or EDA tool."""
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.status.configure(text=tr("copied"))

    def show(self, page, identifier=None):
        """Switch native views and invalidate callbacks owned by the previous view."""
        from .views import Dashboard, Projects, ProjectView, RunHistory, RunView, Workflows, Toolchains, McpView, Settings
        from .campaigns import Campaigns, CampaignView
        from .formal import FormalSessionsView, FormalSessionView
        if self.view is not None and hasattr(self.view, "can_leave") and not self.view.can_leave():
            return
        if self.view is not None:
            self.view.destroy()
        classes = {"overview": Dashboard, "projects": Projects, "project": ProjectView, "runs": RunHistory,
                   "run": RunView, "workflows": Workflows, "toolchains": Toolchains, "mcp": McpView, "settings": Settings,
                   "campaigns": Campaigns, "campaign": CampaignView,
                   "formal_sessions": FormalSessionsView, "formal_session": FormalSessionView}
        self.message.configure(text="")
        self.message.grid_remove()
        self.title.configure(text=tr("runs" if page == "run" else page))
        self.subtitle.configure(text=tr("subtitle_"+page))
        self.breadcrumb.configure(text=tr("runs" if page == "run" else page))
        if page in {"formal_sessions", "formal_session"}:
            self.new_run_button.pack_forget()
        else:
            self.new_run_button.pack(side="right", padx=(10, 0))
        selected = {"run": "runs", "project": "projects", "campaign": "campaigns", "formal_session": "formal_sessions"}.get(page, page)
        for name, button in self.navigation.items():
            button.set_active(name == selected)
        self.view = classes[page](self.content, self, identifier)
        self.view.pack(fill="both", expand=True)
        self.view.refresh()

    def refresh(self):
        """Refresh the visible page without replacing its selection or operation state."""
        if self.view is not None:
            self.view.refresh()

    def search(self):
        """Open keyboard-driven navigation to real projects and persisted runs."""
        from .dialogs import CommandPalette
        for child in self.root.winfo_children():
            if isinstance(child, CommandPalette):
                child.lift()
                return
        CommandPalette(self)

    def new_run(self, project=None, source=None):
        """Load current server defaults before opening a native run wizard."""
        from .client import collection
        from .wizard import RunWizard
        client = self.client
        def load():
            """Load the two authoritative wizard option collections in a worker."""
            return collection(client.call("/projects")), collection(client.call("/toolchains"))
        self.io(self.root, load, lambda data: RunWizard(self, data[0], data[1], project, source), key="new-run")

    def connection_dialog(self):
        """Configure only a service origin and leave SSH credentials outside the application."""
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("connection_title"))
        dialog.geometry("700x300")
        dialog.transient(self.root)
        form = Form(dialog)
        form.pack(fill="x", padx=20, pady=16)
        form.add("origin", "server", self.client.origin)
        ttk.Label(dialog, text=tr("connection_help"), wraplength=660).pack(fill="x", padx=20)
        ttk.Button(dialog, text=tr("copy"), command=lambda: self.copy(tr("tunnel"))).pack(anchor="w", padx=20, pady=12)
        def connect():
            """Validate the origin before rebuilding the visible service context."""
            try:
                client = ApiClient(form.values()["origin"])
                if self.local_service and client.origin == self.local_service.client.origin:
                    client = self.local_service.client
                if client.origin != self.client.origin:
                    self.generation += 1
                    for child in self.root.winfo_children():
                        if isinstance(child, tk.Toplevel) and child is not dialog:
                            child.destroy()
                    if self.view is not None:
                        self.view.destroy()
                        self.view = None
                    self.preferences.cursors = {}
                self.client = client
                self.preferences.origin = client.origin
                self.preferences.save()
                self.status.configure(text=client.origin)
                dialog.destroy()
                self.show("overview")
            except Exception as exc:
                messagebox.showerror(tr("error"), str(exc), parent=dialog)
        ttk.Button(dialog, text=tr("connect"), command=connect, style="Primary.TButton").pack(anchor="e", padx=20)

    def close(self):
        """Hide immediately, cancel local readers, and drain bounded I/O before releasing Tk."""
        if self.closing or self.closed:
            return
        if self.view is not None and hasattr(self.view, "can_leave") and not self.view.can_leave():
            return
        if self.local_service and not messagebox.askyesno(tr("local_mode"), tr("local_exit"), parent=self.root):
            return
        self.closing = True
        self.root.withdraw()
        if self.view is not None:
            self.view.destroy()
            self.view = None
        for cancel in self.local_cancellations:
            cancel.set()
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
        try:
            if not self.local_service or self.client is not self.local_service.client:
                self.preferences.origin = self.client.origin
            self.preferences.save()
        except OSError:
            pass
        # Keep the hidden Tk event loop alive until worker closures have been
        # released back on the main thread. No remote run is cancelled here.
