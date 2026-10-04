"""Small native ttk widgets with stable table selection and bounded text rendering."""

import json
from datetime import datetime
import tkinter as tk
from tkinter import ttk

from .i18n import tr
from .visuals import ACCENT, FONT, INK, LINE, MUTED, PAGE, SURFACE, ActionButton


def display(value, field=None):
    """Localize typed states only; preserve literal test, tool, and artifact identities."""
    if value is None:
        return "--"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        if field == "available":
            return tr("available" if value else "unavailable")
        return tr("enabled" if value else "disabled")
    if field in ("execution_status", "verification_status", "status", "license_status", "approval_status", "methodology", "family"):
        return tr("error_status" if value == "error" else str(value))
    return str(value)


def pretty(value):
    """Render bounded evidence JSON while making truncation visible."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= 200000 else text[:200000] + "\n... [display truncated; download the artifact for full content]"


def format_size(value):
    """Format observed byte counts without converting missing values to zero."""
    if value is None:
        return "--"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return "{:.1f} {}".format(size, unit)
        size /= 1024


def run_rows(rows):
    """Add compact local-time and scope labels without changing persisted request or identity data."""
    result = []
    for row in rows:
        request = row.get("request") or {}
        simulation = request.get("simulation") or {}
        tests = simulation.get("unitytest_tests") if row.get("methodology") == "unitytest" else simulation.get("tests")
        scope = ", ".join(tests or [])
        if simulation.get("seeds"):
            scope += " | seed " + ",".join(str(seed) for seed in simulation["seeds"])
        if row.get("family") == "formal":
            scope = (request.get("formal") or {}).get("engine", "formal")
        timestamp = row.get("created_at")
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            pass
        result.append({**row, "short_id": row["id"][:8], "local_time": timestamp, "scope_label": scope or "--", "method_label": tr("formal" if row.get("family") == "formal" else row.get("methodology", "unknown"))})
    return result


class TextBox(ttk.Frame):
    """Display evidence or edit explicit input text in a scrollable native control."""

    def __init__(self, parent, height=10, readonly=True, terminal=False):
        """Create a wrapping text control with a vertical scrollbar."""
        super().__init__(parent)
        self.readonly = readonly
        self.text = tk.Text(self, height=height, wrap="word", relief="flat", borderwidth=0,
                            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
                            background=SURFACE, foreground=INK, insertbackground=INK, font=("Consolas", 10), padx=14, pady=12, spacing1=2, spacing3=2)
        if terminal:
            self.text.configure(background="#161F31", foreground="#CCD7EB", insertbackground="#CCD7EB", highlightbackground="#161F31", selectbackground="#344A70", selectforeground="#FFFFFF")
        scrollbar = AutoScrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        if readonly:
            self.text.configure(state="disabled")

    def set(self, value):
        """Replace the visible text while preserving read-only behavior."""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", pretty(value))
        if self.readonly:
            self.text.configure(state="disabled")

    def get(self):
        """Read literal text without parsing, evaluating, or stripping internal whitespace."""
        return self.text.get("1.0", "end-1c")

    def append(self, value, follow=True):
        """Append a batch of log lines and retain at most 3000 visible lines."""
        self.text.configure(state="normal")
        self.text.insert("end", value)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > 3000:
            self.text.delete("1.0", "{}.0".format(lines - 3000))
        if follow:
            self.text.see("end")
        if self.readonly:
            self.text.configure(state="disabled")


class Table(ttk.Frame):
    """Show normalized record fields and preserve selection across background refreshes."""

    def __init__(self, parent, columns, on_select=None, on_open=None, height=12):
        """Build a selectable table from key/title/width column definitions."""
        super().__init__(parent)
        self.columns = columns
        self.records = {}
        self.on_select = on_select
        self.sort_key = None
        self.sort_descending = False
        self.tree = ttk.Treeview(self, columns=[key for key, _, _ in columns], show="headings", height=height, selectmode="browse")
        for key, title, width in columns:
            self.tree.heading(key, text=tr(title), command=lambda selected=key: self.sort(selected))
            self.tree.column(key, width=width, minwidth=60, stretch=True)
        vertical = AutoScrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = AutoScrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._select)
        if on_open:
            self.tree.bind("<Double-1>", lambda event: on_open())
            self.tree.bind("<Return>", lambda event: on_open())
        self.tree.tag_configure("odd", background="#FAFBFD")
        self.tree.tag_configure("failed", background="#FFF7F7")
        self.tree.tag_configure("error", background="#FFFBF3")
        self.tree.tag_configure("disabled", foreground=MUTED)

    def _select(self, event=None):
        """Forward one real selected record to the owning view."""
        if self.on_select:
            self.on_select(self.selected())

    def selected(self):
        """Return the selected record or None, never the display text as an identifier."""
        selected = self.tree.selection()
        return self.records.get(selected[0]) if selected else None

    def sort(self, key):
        """Sort a column while retaining opaque row identities, selection, and refresh behavior."""
        self.sort_descending = not self.sort_descending if self.sort_key == key else False
        self.sort_key = key
        self.set_rows(list(self.records.values()))
        for column, title, _ in self.columns:
            suffix = ("  ↓" if self.sort_descending else "  ↑") if column == key else ""
            self.tree.heading(column, text=tr(title)+suffix)

    def set_rows(self, rows):
        """Replace rows using stable record identity and restore the scroll position."""
        selected = self.tree.selection()
        position = self.tree.yview()
        if self.sort_key:
            known = [row for row in rows if row.get(self.sort_key) is not None]
            missing = [row for row in rows if row.get(self.sort_key) is None]
            rows = sorted(known, key=lambda row: (0 if isinstance(row[self.sort_key], (int, float)) else 1, row[self.sort_key] if isinstance(row[self.sort_key], (int, float)) else str(row[self.sort_key]).casefold()), reverse=self.sort_descending) + missing
        self.tree.delete(*self.tree.get_children())
        self.records = {}
        for index, record in enumerate(rows):
            identity = str(record.get("id") or record.get("key") or record.get("name") or index)
            if identity in self.records:
                identity = "{}:{}".format(identity, index)
            self.records[identity] = record
            status = record.get("verification_status") or record.get("status") or ""
            if record.get("execution_status") in ("error", "timeout"):
                status = "error"
            self.tree.insert("", "end", iid=identity, values=[display(record.get(key), key) for key, _, _ in self.columns], tags=(status, "odd" if index % 2 else "even"))
        if selected and selected[0] in self.records:
            self.tree.selection_set(selected[0])
        if position:
            self.tree.yview_moveto(position[0])


class Form(ttk.Frame):
    """Collect explicit structured values with labels, native entries, and text editors."""

    def __init__(self, parent):
        """Initialize an extensible two-column form with a stretching input column."""
        super().__init__(parent)
        self.fields = {}
        self.controls = {}
        self.labels = {}
        self.columnconfigure(1, weight=1)

    def add(self, key, label, value="", choices=None, multiline=False, check=False):
        """Add one labeled value and retain its literal input source for validation."""
        row = len(self.fields)
        caption = ttk.Label(self, text=tr(label), style="Hint.TLabel")
        caption.grid(row=row, column=0, sticky="nw", padx=(0, 24), pady=(12, 8))
        if multiline:
            field = TextBox(self, height=3, readonly=False)
            field.set(value)
            control = field
        else:
            field = tk.BooleanVar(self, value=bool(value)) if check else tk.StringVar(self, value="" if value is None else str(value))
            if check:
                control = ttk.Checkbutton(self, variable=field)
            elif choices is not None:
                control = ttk.Combobox(self, textvariable=field, values=list(choices), state="readonly")
            else:
                control = ttk.Entry(self, textvariable=field)
        control.grid(row=row, column=1, sticky="nsew", pady=8)
        self.fields[key] = field
        self.controls[key] = control
        self.labels[key] = caption
        return control

    def values(self):
        """Read all controls from the Tk main thread as literal values."""
        return {key: field.get() for key, field in self.fields.items()}

    def visible(self, keys, enabled):
        """Collapse advanced controls without changing their values or excluding them from requests."""
        for key in keys:
            for widget in (self.controls[key], self.labels[key]):
                widget.grid() if enabled else widget.grid_remove()

    def destroy(self):
        """Release Tcl variables on their creating thread before the owning Python view can linger."""
        self.controls.clear()
        self.labels.clear()
        self.fields.clear()
        super().destroy()


class ScrollFrame(ttk.Frame):
    """Keep longer native forms usable on small displays without resizing the window."""

    def __init__(self, parent):
        """Create a vertical canvas viewport containing an ordinary ttk content frame."""
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=PAGE, highlightthickness=0)
        bar = AutoScrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.grid(row=0, column=1, sticky="ns")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self._wheel_binding = self.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        """Scroll only when the pointer is over this form, preserving native text scrolling."""
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None or isinstance(widget, (tk.Text, ttk.Combobox, ttk.Treeview)) or (isinstance(widget, tk.Canvas) and widget is not self.canvas):
            return
        if str(widget).startswith(str(self) + ".") and self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def destroy(self):
        """Remove the scoped wheel callback before destroying the form."""
        self.winfo_toplevel().unbind("<MouseWheel>", self._wheel_binding)
        super().destroy()


class AutoScrollbar(ttk.Scrollbar):
    """A grid-managed scrollbar that leaves no empty track when content fits."""

    def set(self, first, last):
        """Reveal scrolling only when it represents actual offscreen content."""
        if float(first) <= 0 and float(last) >= 1:
            self.grid_remove()
        else:
            self.grid()
        super().set(first, last)


class EvidencePanel(ttk.Frame):
    """Keep complete raw evidence one click away without dominating the primary workflow."""

    def __init__(self, parent, height=8):
        """Create a keyboard-accessible disclosure with the same literal evidence contract as TextBox."""
        super().__init__(parent)
        self.opened = False
        self.button = ActionButton(self, text=tr("show_evidence"), command=self.toggle, variant="ghost")
        self.button.pack(fill="x")
        self.box = TextBox(self, height=height)

    def toggle(self):
        """Expand or collapse evidence without changing or regenerating its contents."""
        self.opened = not self.opened
        self.button.configure(text=tr("hide_evidence" if self.opened else "show_evidence"))
        if self.opened:
            self.box.pack(fill="both", expand=True, pady=(8, 0))
        else:
            self.box.pack_forget()

    def set(self, value):
        """Preserve the exact latest supplied evidence even while its disclosure is collapsed."""
        self.box.set(value)

    def get(self):
        """Read the bounded literal evidence for clipboard and accessibility tests."""
        return self.box.get()


class StageTree(ttk.Frame):
    """Expose every stage, child branch, disabled reason, and human gate in a real tree."""

    def __init__(self, parent, on_select):
        """Create a horizontally scrollable hierarchy with separate result columns."""
        super().__init__(parent)
        self.on_select = on_select
        self.records = {}
        self.tree = ttk.Treeview(self, columns=("enabled", "execution_status", "verification_status", "reason"), height=12)
        self.tree.heading("#0", text=tr("stages"))
        self.tree.column("#0", width=350, minwidth=230)
        for key, width in (("enabled", 85), ("execution_status", 90), ("verification_status", 90), ("reason", 320)):
            self.tree.heading(key, text=tr(key))
            self.tree.column(key, width=width, minwidth=75)
        vertical = ttk.Scrollbar(self, command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        horizontal.pack(side="bottom", fill="x")
        vertical.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("disabled", foreground="#7e8797")
        self.tree.bind("<<TreeviewSelect>>", lambda event: on_select(self.selected()))

    def selected(self):
        """Return the actual stage, keeping compound identifiers opaque."""
        selected = self.tree.selection()
        return self.records.get(selected[0]) if selected else None

    def set_rows(self, rows):
        """Flatten nested or parent-linked canonical nodes without hiding disabled branches."""
        selected = self.tree.selection()
        opened = {key: self.tree.item(key, "open") for key in self.records}
        position = self.tree.yview()
        self.tree.delete(*self.tree.get_children())
        self.records = {}
        flattened = []
        def visit(nodes, parent=""):
            """Retain explicit nested ownership while collecting nodes in source order."""
            for node in nodes:
                identity = str(node["id"])
                flattened.append((identity, parent or node.get("parent_id") or "", node))
                visit(node.get("children", []), identity)
        visit(rows)
        for identity, parent, node in flattened:
            if identity in self.records:
                continue
            self.records[identity] = node
            self.tree.insert("", "end", iid=identity, text=node.get("description") or node.get("name") or identity,
                             values=[display(node.get("enabled")), display(node.get("execution_status"), "execution_status"), display(node.get("verification_status"), "verification_status"), node.get("disabled_reason") or ""],
                             tags=("disabled",) if node.get("enabled") is False else (), open=opened.get(identity, True))
        for identity, parent, _ in flattened:
            if parent in self.records and parent != identity:
                self.tree.move(identity, parent, "end")
        if selected and selected[0] in self.records:
            self.tree.selection_set(selected[0])
        if position:
            self.tree.yview_moveto(position[0])


def card(parent, title):
    """Create a consistently spaced native labeled group for one bounded task."""
    frame = ttk.LabelFrame(parent, text=tr(title), padding=12)
    return frame
