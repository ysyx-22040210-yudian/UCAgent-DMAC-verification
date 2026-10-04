"""Native vector components and shared design tokens for the verification studio."""

import tkinter as tk
import sys
from tkinter import font as tkfont

from .i18n import tr

PAGE = "#F4F6FA"
SURFACE = "#FFFFFF"
INK = "#192438"
MUTED = "#68758B"
LINE = "#E8ECF3"
ACCENT = "#5265E8"
ACCENT_SOFT = "#EEF0FF"
NAV = "#151D2E"
NAV_HOVER = "#202B42"
NAV_TEXT = "#9CAAC1"
SUCCESS = "#19755D"
SUCCESS_SOFT = "#EAF6F0"
WARNING = "#91621D"
WARNING_SOFT = "#FFF4DF"
DANGER = "#B84656"
DANGER_SOFT = "#FFF0F1"
FONT = "Microsoft YaHei UI" if sys.platform == "win32" else "Noto Sans CJK SC"


def rounded(canvas, x1, y1, x2, y2, radius=10, **options):
    """Draw a scalable code-native rounded rectangle without a bitmap dependency."""
    r = min(radius, max(0, (x2 - x1) / 2), max(0, (y2 - y1) / 2))
    points = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
              x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **options)


def icon(canvas, name, x, y, size=20, color=MUTED):
    """Draw a consistent 24-unit line icon using native Canvas geometry."""
    scale = size / 24.0
    paths = {
        "overview": [[3, 3, 10, 3, 10, 10, 3, 10, 3, 3], [14, 3, 21, 3, 21, 10, 14, 10, 14, 3], [3, 14, 10, 14, 10, 21, 3, 21, 3, 14], [14, 14, 21, 14, 21, 21, 14, 21, 14, 14]],
        "projects": [[3, 7, 3, 4, 10, 4, 13, 7, 21, 7, 21, 20, 3, 20, 3, 7, 21, 7]],
        "runs": [[8, 4, 20, 12, 8, 20, 8, 4]],
        "workflows": [[5, 5, 5, 17, 18, 17], [5, 8, 18, 8], [17, 4, 21, 4, 21, 12, 17, 12, 17, 4], [17, 15, 21, 15, 21, 21, 17, 21, 17, 15]],
        "toolchains": [[4, 7, 20, 7, 20, 20, 4, 20, 4, 7], [8, 7, 8, 3, 16, 3, 16, 7], [4, 12, 20, 12], [10, 12, 10, 15, 14, 15, 14, 12]],
        "mcp": [[4, 16, 12, 8, 20, 16], [8, 20, 12, 16, 16, 20], [9, 5, 12, 2, 15, 5]],
        "settings": [[4, 4, 4, 20], [12, 4, 12, 20], [20, 4, 20, 20], [1, 8, 7, 8], [9, 16, 15, 16], [17, 10, 23, 10]],
        "chip": [[6, 6, 18, 6, 18, 18, 6, 18, 6, 6], [10, 10, 14, 10, 14, 14, 10, 14, 10, 10], [9, 2, 9, 6], [15, 2, 15, 6], [9, 18, 9, 22], [15, 18, 15, 22], [2, 9, 6, 9], [2, 15, 6, 15], [18, 9, 22, 9], [18, 15, 22, 15]],
        "search": [[16, 16, 22, 22]],
        "refresh": [[19, 8, 19, 3], [19, 8, 14, 8], [5, 16, 5, 21], [5, 16, 10, 16]],
        "plus": [[12, 5, 12, 19], [5, 12, 19, 12]],
        "arrow": [[5, 12, 19, 12], [14, 7, 19, 12, 14, 17]],
        "chevron": [[9, 5, 16, 12, 9, 19]],
        "check": [[5, 12, 10, 17, 20, 6]],
        "warning": [[12, 3, 22, 21, 2, 21, 12, 3], [12, 9, 12, 14]],
        "disk": [[4, 4, 20, 4, 20, 20, 4, 20, 4, 4], [4, 14, 20, 14], [8, 17, 10, 17]],
        "clock": [[12, 6, 12, 12, 16, 14]],
        "close": [[6, 6, 18, 18], [18, 6, 6, 18]],
        "download": [[12, 3, 12, 15], [7, 10, 12, 15, 17, 10], [4, 16, 4, 21, 20, 21, 20, 16]],
    }
    for path in paths.get(name, paths["chip"]):
        coords = [x + value * scale if index % 2 == 0 else y + value * scale for index, value in enumerate(path)]
        canvas.create_line(*coords, fill=color, width=1.65, capstyle="round", joinstyle="round")
    if name in ("search", "clock"):
        end = 18 if name == "search" else 22
        canvas.create_oval(x+2*scale, y+2*scale, x+end*scale, y+end*scale, outline=color, width=1.65)
    if name == "refresh":
        canvas.create_arc(x+3*scale, y+3*scale, x+21*scale, y+21*scale, start=28, extent=120, style="arc", outline=color, width=1.65)
        canvas.create_arc(x+3*scale, y+3*scale, x+21*scale, y+21*scale, start=208, extent=120, style="arc", outline=color, width=1.65)
    if name == "warning":
        canvas.create_oval(x+11.2*scale, y+17*scale, x+12.8*scale, y+18.6*scale, fill=color, outline="")


def ellipsis(text, font, width):
    """Fit literal display text by pixel width while leaving its stored identity unchanged."""
    text = str(text)
    if font.measure(text) <= width:
        return text
    if width < font.measure("…"):
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if font.measure(text[:middle] + "…") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"


def status_colors(status):
    """Map semantic evidence states to a restrained accessible status palette."""
    if status in ("passed", "proven", "available", "connected", "healthy", "completed"):
        return SUCCESS, SUCCESS_SOFT
    if status in ("failed", "falsified", "rejected"):
        return DANGER, DANGER_SOFT
    if status in ("error", "timeout", "unavailable", "inconclusive", "blocked", "degraded"):
        return WARNING, WARNING_SOFT
    if status in ("running", "queued"):
        return ACCENT, ACCENT_SOFT
    return MUTED, PAGE


def badge(canvas, text, status, x, y, font=None):
    """Draw a compact semantic status chip and return its actual pixel width."""
    font = font or tkfont.Font(canvas, family=FONT, size=9)
    foreground, background = status_colors(status)
    width = font.measure(text) + 28
    rounded(canvas, x, y, x+width, y+25, 7, fill=background, outline="")
    canvas.create_oval(x+9, y+10, x+14, y+15, fill=foreground, outline="")
    canvas.create_text(x+19, y+12, text=text, font=font, fill=foreground, anchor="w")
    return width


class ActionButton(tk.Canvas):
    """A keyboard-accessible native rounded button with hover, focus, and disabled states."""

    def __init__(self, parent, text="", command=None, variant="secondary", icon_name=None, background=PAGE, width=None, height=38, state="normal"):
        """Create an actual command control, not a decorative label pretending to be a button."""
        self.label = text
        self.command = command
        self.variant = variant
        self.icon_name = icon_name
        self.button_state = state
        self.hovered = False
        self.focused = False
        self.font = tkfont.Font(parent, family=FONT, size=10, weight="bold" if variant == "primary" else "normal")
        width = width or self.font.measure(text) + (54 if icon_name else 30)
        super().__init__(parent, width=width, height=height, background=background, highlightthickness=0, bd=0, takefocus=1, cursor="hand2")
        self.bind("<Configure>", self.paint)
        self.bind("<Enter>", lambda event: self.interact(hover=True))
        self.bind("<Leave>", lambda event: self.interact(hover=False))
        self.bind("<FocusIn>", lambda event: self.interact(focus=True))
        self.bind("<FocusOut>", lambda event: self.interact(focus=False))
        self.bind("<Button-1>", lambda event: self.invoke())
        self.bind("<Return>", lambda event: self.invoke())
        self.bind("<space>", lambda event: self.invoke())

    def interact(self, hover=None, focus=None):
        """Update visual interaction state without mutating any backend data."""
        if hover is not None:
            self.hovered = hover
        if focus is not None:
            self.focused = focus
        self.paint()

    def invoke(self):
        """Run the declared action once when the control is enabled."""
        if self.button_state != "disabled" and self.command:
            return self.command()

    def configure(self, cnf=None, **options):
        """Support explicit dynamic labels and state changes while retaining native Canvas options."""
        if "text" in options:
            self.label = options.pop("text")
        if "state" in options:
            self.button_state = options.pop("state")
        if "variant" in options:
            self.variant = options.pop("variant")
        if options or cnf:
            super().configure(cnf, **options)
        self.paint()

    def cget(self, key):
        """Expose semantic button state to keyboard logic and native widget tests."""
        if key == "state":
            return self.button_state
        if key == "text":
            return self.label
        return super().cget(key)

    def paint(self, event=None):
        """Render a restrained rounded control from the current real interaction state."""
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if self.variant == "primary":
            background, foreground, border = ("#4355D2" if self.hovered else ACCENT), SURFACE, ""
        elif self.variant == "ghost":
            background, foreground, border = ("#EAEEF5" if self.hovered else self.cget("background")), MUTED, ""
        else:
            background, foreground, border = ("#F8F9FD" if self.hovered else SURFACE), INK, "#DFE4EF"
        if self.button_state == "disabled":
            background, foreground, border = "#E9ECF4", "#A3ABBC", ""
        if self.focused:
            rounded(self, 0, 0, width, height, 11, fill=ACCENT_SOFT, outline=ACCENT)
        rounded(self, 2, 2, width-2, height-2, 8, fill=background, outline=border)
        label_width = self.font.measure(self.label)
        left = (width - label_width - (24 if self.icon_name else 0)) / 2
        if self.icon_name:
            icon(self, self.icon_name, left, (height-18)/2, 18, foreground)
            left += 24
        self.create_text(left, height/2, text=self.label, anchor="w", fill=foreground, font=self.font)


class NavItem(ActionButton):
    """A sidebar navigation item with an explicit current-page indicator."""

    def __init__(self, parent, name, command):
        """Bind a labeled icon to one real application destination."""
        self.name = name
        self.active = False
        super().__init__(parent, tr(name), command, icon_name=name, background=NAV, height=45)

    def set_active(self, active):
        """Mark the current destination without relying only on text color."""
        self.active = active
        self.paint()

    def paint(self, event=None):
        """Draw the current page as a quiet indigo surface in the dark rail."""
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        background = "#2B3653" if self.active else NAV_HOVER if self.hovered or self.focused else NAV
        rounded(self, 0, 1, width, height-1, 8, fill=background, outline=ACCENT if self.focused else "")
        if self.active:
            rounded(self, 0, 13, 3, height-13, 1, fill="#91A0FF", outline="")
        foreground = "#F1F4FE" if self.active else "#D8E0EE" if self.hovered else NAV_TEXT
        icon(self, self.name, 16, 12, 20, "#A7B4FF" if self.active else foreground)
        self.create_text(49, height/2, text=self.label, anchor="w", fill=foreground, font=(FONT, 10))


class Surface(tk.Frame):
    """A softly outlined native card that owns a stretching ordinary Tk content frame."""

    def __init__(self, parent, height=200, padding=18, background=PAGE):
        """Keep rounded boundaries independent of child-widget layout and resize behavior."""
        super().__init__(parent, background=background, height=height)
        self.padding = padding
        self.pack_propagate(False)
        self.canvas = tk.Canvas(self, background=background, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, background=SURFACE)
        self.window = self.canvas.create_window(padding, padding, anchor="nw", window=self.body)
        self.canvas.bind("<Configure>", self.resize)

    def resize(self, event):
        """Keep borders crisp and interior widgets inside the rounded content bounds."""
        self.canvas.delete("surface")
        rounded(self.canvas, 1, 2, event.width-1, event.height-1, 12, fill="#E9EDF5", outline="", tags="surface")
        rounded(self.canvas, 1, 1, event.width-1, event.height-3, 12, fill=SURFACE, outline=LINE, tags="surface")
        self.canvas.tag_lower("surface")
        self.canvas.itemconfigure(self.window, width=max(1, event.width-2*self.padding), height=max(1, event.height-2*self.padding-2))


class MetricCard(tk.Canvas):
    """A compact observed-value card; it never generates synthetic growth or coverage trends."""

    def __init__(self, parent, title, icon_name, tone=ACCENT):
        """Reserve consistent label, metric, and supporting-evidence hierarchy."""
        super().__init__(parent, height=112, background=PAGE, highlightthickness=0, bd=0)
        self.title = tr(title)
        self.icon_name = icon_name
        self.tone = tone
        self.value = "--"
        self.note = tr("loading")
        self.fraction = None
        self.bind("<Configure>", self.paint)

    def set(self, value, note, fraction=None):
        """Accept only values derived from the server's actual current state."""
        self.value, self.note, self.fraction = str(value), str(note), fraction
        self.paint()

    def paint(self, event=None):
        """Draw a quiet metric with a context icon and optional real-capacity meter."""
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        rounded(self, 1, 1, width-1, height-2, 12, fill=SURFACE, outline=LINE)
        rounded(self, width-52, 15, width-18, 49, 9, fill=ACCENT_SOFT if self.tone == ACCENT else WARNING_SOFT, outline="")
        icon(self, self.icon_name, width-45, 22, 20, self.tone)
        self.create_text(20, 23, text=self.title, fill=MUTED, font=(FONT, 9), anchor="w")
        self.create_text(20, 58, text=self.value, fill=INK, font=("Segoe UI", 25, "bold"), anchor="w")
        self.create_text(20, 91, text=self.note, fill=MUTED, font=(FONT, 9), anchor="w")
        if self.fraction is not None:
            meter_width = min(65, width/4)
            rounded(self, width-meter_width-18, 86, width-18, 90, 2, fill=LINE, outline="")
            filled = max(0, min(1, self.fraction)) * meter_width
            if filled:
                rounded(self, width-meter_width-18, 86, width-meter_width-18+filled, 90, 2, fill=self.tone, outline="")


class ProjectList(tk.Canvas):
    """A keyboard-selectable compact project collection with direct context actions."""

    def __init__(self, parent, on_open, height=285):
        """Create a real project list while retaining opaque server ids as selection identity."""
        super().__init__(parent, height=height, background=SURFACE, highlightthickness=0, bd=0, takefocus=1)
        self.records = {}
        self.identity = None
        self.hover = None
        self.on_open = on_open
        self.offset = 0
        self.title_font = tkfont.Font(self, family=FONT, size=10, weight="bold")
        self.small_font = tkfont.Font(self, family=FONT, size=9)
        self.bind("<Configure>", self.paint)
        self.bind("<Motion>", self.motion)
        self.bind("<Leave>", lambda event: self.motion(None))
        self.bind("<Button-1>", self.click)
        self.bind("<Double-1>", lambda event: self.on_open())
        self.bind("<Return>", lambda event: self.on_open())
        self.bind("<Down>", lambda event: self.move(1))
        self.bind("<Up>", lambda event: self.move(-1))
        self.bind("<MouseWheel>", lambda event: self.scroll(-1 if event.delta > 0 else 1))

    def set_rows(self, rows):
        """Replace current project metadata without forgetting a still-valid selection."""
        self.records = {row["id"]: row for row in rows}
        if self.identity not in self.records:
            self.identity = None
        self.offset = min(self.offset, max(0, len(rows)-1))
        self.paint()

    def selected(self):
        """Return only the selected real project, never a display alias."""
        return self.records.get(self.identity)

    def click(self, event):
        """Select a row and invoke its explicit arrow action when clicked."""
        keys = list(self.records)
        index = self.offset + int(event.y // 53)
        visible = max(1, self.winfo_height() // 53)
        if 0 <= event.y < visible * 53 and 0 <= index < len(keys):
            self.identity = keys[index]
            self.focus_set()
            self.paint()
            if event.x > self.winfo_width()-38:
                self.on_open()

    def motion(self, event):
        """Track a row hover without changing the actual project selection."""
        hover = self.offset + int(event.y // 53) if event else None
        if hover != self.hover:
            self.hover = hover
            self.paint()

    def move(self, delta):
        """Support keyboard navigation and ensure the selected row remains in view."""
        keys = list(self.records)
        if not keys:
            return
        index = keys.index(self.identity) if self.identity in keys else -1
        index = max(0, min(len(keys)-1, index+delta))
        self.identity = keys[index]
        visible = max(1, self.winfo_height() // 53)
        self.offset = max(0, min(self.offset, index)) if index < self.offset else max(self.offset, index-visible+1)
        self.paint()
        return "break"

    def scroll(self, delta):
        """Scroll large project collections without hiding rows beyond a fixed dashboard limit."""
        visible = max(1, self.winfo_height() // 53)
        self.offset = max(0, min(max(0, len(self.records)-visible), self.offset+delta))
        self.paint()
        return "break"

    def paint(self, event=None):
        """Render project identity, declared method/top, and separate latest-result chips."""
        self.delete("all")
        width = self.winfo_width()
        if not self.records:
            self.create_text(width/2, 90, text=tr("no_projects"), width=max(120, width-70), fill=MUTED, font=(FONT, 10))
            return
        visible = max(1, self.winfo_height()//53)
        for index, row in enumerate(list(self.records.values())[self.offset:self.offset+visible]):
            y = index * 53
            selected = row["id"] == self.identity
            if selected or index+self.offset == self.hover:
                rounded(self, 0, y+1, width, y+51, 8, fill=ACCENT_SOFT if selected else "#F8FAFD", outline="")
            rounded(self, 9, y+10, 43, y+44, 8, fill=ACCENT_SOFT, outline="")
            icon(self, "chip", 16, y+17, 20, ACCENT)
            self.create_text(56, y+19, text=ellipsis(row["name"], self.title_font, width-205), fill=INK, font=self.title_font, anchor="w")
            subtitle = "{}  ·  {}".format(row.get("method_label", ""), row.get("top") or row.get("design", {}).get("top", "--"))
            self.create_text(56, y+39, text=ellipsis(subtitle, self.small_font, width-205), fill=MUTED, font=self.small_font, anchor="w")
            status = row.get("latest_result") or "unknown"
            badge(self, tr(status), status, width-137, y+15, self.small_font)
            icon(self, "chevron", width-26, y+21, 15, MUTED)
            if index+1 < visible:
                self.create_line(54, y+52, width-8, y+52, fill=LINE)


class ToolHealth(tk.Canvas):
    """Present configured tool capabilities without manufacturing a platform-wide Pass."""

    def __init__(self, parent, on_open):
        """Create an environment summary that links to real toolchain diagnostics."""
        super().__init__(parent, background=SURFACE, height=190, highlightthickness=0, bd=0, cursor="hand2")
        self.profiles = []
        self.small_font = tkfont.Font(self, family=FONT, size=9)
        self.bind("<Configure>", self.paint)
        self.bind("<Button-1>", lambda event: on_open())

    def set(self, profiles):
        """Accept current redacted tool capabilities directly from the service overview."""
        self.profiles = profiles
        self.paint()

    def paint(self, event=None):
        """Show open and commercial tools, with explicit overflow and license uncertainty."""
        self.delete("all")
        width = self.winfo_width()
        names = {"vcs": "VCS", "vcf": "VC Formal", "urg": "URG", "picker": "Picker", "formalmc": "FormalMC", "sby": "SBY", "yosys": "Yosys", "yosys-smtbmc": "SMTBMC", "z3": "Z3"}
        items = [cap for profile in self.profiles for cap in profile.get("capabilities", []) if cap.get("name")]
        items.sort(key=lambda cap: (list(names).index(cap["name"]) if cap["name"] in names else len(names), cap["name"]))
        if not items:
            self.create_text(2, 19, text=tr("no_tool_observation"), anchor="w", width=max(80, width-4), font=self.small_font, fill=MUTED)
        for index, cap in enumerate(items[:4]):
            y = 7 + index*39
            status = cap.get("license_status", "unknown") if cap["name"] in ("vcs", "vcf") else "available" if cap.get("available") else "unavailable"
            self.create_text(2, y+12, text=names.get(cap["name"], cap["name"]), anchor="w", font=("Segoe UI", 10, "bold"), fill=INK)
            text = tr("license_blocked") if status == "unavailable" and cap["name"] in ("vcs", "vcf") else tr(status)
            badge_width = self.small_font.measure(text)+28
            badge(self, text, status, max(115, width-badge_width-2), y, self.small_font)
        if len(items) > 4:
            self.create_text(2, 174, text=tr("more_tool_observations", count=len(items)-4), anchor="w", font=self.small_font, fill=MUTED)


class AttentionList(tk.Canvas):
    """Render a bounded actionable list of the latest project results that need review."""

    def __init__(self, parent, on_open):
        """Keep the issue summary compact and bind each row to its real run."""
        super().__init__(parent, background=SURFACE, height=90, highlightthickness=0, bd=0, cursor="hand2")
        self.rows = []
        self.on_open = on_open
        self.font = tkfont.Font(self, family=FONT, size=9)
        self.bind("<Configure>", self.paint)
        self.bind("<Button-1>", self.open)

    def set_rows(self, rows):
        """Replace only the actual attention queue derived from latest project results."""
        self.rows = rows
        self.paint()

    def open(self, event):
        """Navigate to the clicked run without changing its evidence state."""
        index = event.y // 41
        if 0 <= index < min(2, len(self.rows)):
            self.on_open(self.rows[index]["id"])

    def paint(self, event=None):
        """Show concise identity and cause labels with honest empty-state guidance."""
        self.delete("all")
        width = self.winfo_width()
        if not self.rows:
            icon(self, "check", 2, 17, 20, SUCCESS)
            self.create_text(34, 26, text=tr("no_attention"), width=max(80, width-40), anchor="w", fill=MUTED, font=self.font)
        for index, row in enumerate(self.rows[:2]):
            y = index * 41
            icon(self, "warning", 1, y+9, 17, WARNING)
            self.create_text(28, y+10, text=ellipsis(row.get("project_name", row["id"]), self.font, width-44), anchor="w", fill=INK, font=self.font)
            reason = tr("license_blocked") if (row.get("summary") or {}).get("diagnostic_code") == "license_unavailable" else tr("review_failure")
            self.create_text(28, y+28, text=reason, anchor="w", fill=MUTED, font=self.font)
            icon(self, "chevron", width-15, y+12, 13, MUTED)


class Stepper(tk.Canvas):
    """A real three-step progress control reflecting editor state rather than verification progress."""

    def __init__(self, parent):
        """Reserve the wizard's consistent visual hierarchy for all three editable steps."""
        super().__init__(parent, height=72, background=SURFACE, highlightthickness=0, bd=0)
        self.step = 0
        self.bind("<Configure>", self.paint)

    def set(self, step):
        """Reflect the current editor step without inferring any validation success."""
        self.step = step
        self.paint()

    def paint(self, event=None):
        """Draw numbered stages, connecting rules, and explicit selected/completed states."""
        self.delete("all")
        width = self.winfo_width()
        part = width/3
        for index in range(3):
            x = part*index+14
            if index < 2:
                self.create_line(x+155, 25, x+part-16, 25, fill=LINE, width=2)
            color = ACCENT if index <= self.step else "#A0A9BA"
            self.create_oval(x, 10, x+30, 40, fill=ACCENT if index == self.step else ACCENT_SOFT if index < self.step else PAGE, outline="")
            if index < self.step:
                icon(self, "check", x+6, 17, 17, ACCENT)
            else:
                self.create_text(x+15, 25, text=str(index+1), fill=SURFACE if index == self.step else MUTED, font=("Segoe UI", 10, "bold"))
            self.create_text(x+42, 25, text=tr("step_name_{}".format(index)), fill=color if index == self.step else INK if index < self.step else MUTED, font=(FONT, 10, "bold" if index == self.step else "normal"), anchor="w")
            self.create_text(x+42, 50, text=tr("step_hint_{}".format(index)), fill=MUTED, font=(FONT, 8), anchor="w")


class RunSummary(tk.Canvas):
    """A readable evidence summary that never substitutes presentation for verification proof."""

    def __init__(self, parent):
        """Reserve metric, scope, and input sections for one immutable run payload."""
        super().__init__(parent, height=310, background=PAGE, highlightthickness=0, bd=0)
        self.payload = {}
        self.title_font = tkfont.Font(self, family=FONT, size=10, weight="bold")
        self.small_font = tkfont.Font(self, family=FONT, size=9)
        self.bind("<Configure>", self.paint)

    def set(self, payload):
        """Receive only the actual request, summary counters, and signed-manifest identity."""
        self.payload = payload
        self.paint()

    def paint(self, event=None):
        """Show missing counters as unknown and keep signoff and smoke scope distinct."""
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 120:
            return
        payload = self.payload
        summary = payload.get("summary") or {}
        request = payload.get("request") or {}
        formal = request.get("family") == "formal"
        tiles = [("jobs", "{} / {}".format(summary.get("jobs_finished", "--"), summary.get("jobs_total", "--"))),
                 ("properties" if formal else "tests", summary.get("properties_total" if formal else "tests_total")),
                 ("falsified" if formal else "passed", summary.get("properties_falsified" if formal else "tests_passed")),
                 ("coverage" if formal else "failed", summary.get("coverage_metrics" if formal else "tests_failed"))]
        for index, (label, value) in enumerate(tiles):
            left = index*width/4
            rounded(self, left+1, 1, left+width/4-10, 92, 10, fill=SURFACE, outline=LINE)
            self.create_text(left+18, 23, text=tr(label), fill=MUTED, font=self.small_font, anchor="w")
            self.create_text(left+18, 58, text="--" if value is None else str(value), fill=INK, font=("Segoe UI", 23, "bold"), anchor="w")
        rounded(self, 1, 109, width-10, max(292, height-4), 12, fill=SURFACE, outline=LINE)
        self.create_text(22, 132, text=tr("run_scope_heading"), fill=INK, font=self.title_font, anchor="w")
        design = request.get("design") or {}
        simulation = request.get("simulation") or {}
        proof = request.get("formal") or {}
        tests = simulation.get("unitytest_tests") if request.get("methodology") == "unitytest" else simulation.get("tests")
        values = [("methodology", tr("formal") if formal else tr(request.get("methodology", "unknown"))),
                  ("engine" if formal else "simulator", proof.get("engine", "--") if formal else simulation.get("simulator", "--").upper()),
                  ("top", design.get("top", "--")),
                  ("property_sets" if formal else "test", ", ".join(proof.get("property_sets", []) if formal else tests or []) or "--"),
                  ("clock" if formal else "seed", str((proof.get("clock") or {}).get("signal") or "--") if formal else ", ".join(str(seed) for seed in simulation.get("seeds", [])) or "--"),
                  ("toolchain", request.get("toolchain", "--"))]
        for index, (label, value) in enumerate(values):
            x = 22 + (index%2)*width/2
            y = 168 + (index//2)*34
            self.create_text(x, y, text=ellipsis(tr(label), self.small_font, 120), fill=MUTED, font=self.small_font, anchor="w")
            self.create_text(x+132, y, text=ellipsis(value, self.small_font, width/2-162), fill=INK, font=self.small_font, anchor="w")
        self.create_line(22, 258, width-32, 258, fill=LINE)
        icon(self, "check" if payload.get("manifest_hash") else "clock", 21, 271, 16, SUCCESS if payload.get("manifest_hash") else MUTED)
        text = tr("manifest_recorded") + "  " + str(payload["manifest_hash"])[:16] if payload.get("manifest_hash") else tr("manifest_pending")
        self.create_text(48, 280, text=text, fill=MUTED, font=self.small_font, anchor="w")


class RunBanner(tk.Canvas):
    """Keep execution and verification conclusions visually distinct in a compact run header."""

    def __init__(self, parent):
        """Prepare an observed-state header with no inferred completion or proof claims."""
        super().__init__(parent, height=56, background=PAGE, highlightthickness=0, bd=0)
        self.run = {}
        self.font = tkfont.Font(self, family=FONT, size=9)
        self.bind("<Configure>", self.paint)

    def set(self, run):
        """Accept a persisted run and redraw its independent canonical states."""
        self.run = run
        self.paint()

    def paint(self, event=None):
        """Render independent state chips and actual project identity without pipe-delimited clutter."""
        self.delete("all")
        width = self.winfo_width()
        rounded(self, 1, 1, width-1, 54, 10, fill=SURFACE, outline=LINE)
        x = 18
        for key in ("execution_status", "verification_status"):
            self.create_text(x, 27, text=tr(key), font=self.font, fill=MUTED, anchor="w")
            x += self.font.measure(tr(key))+12
            status = self.run.get(key, "unknown")
            x += badge(self, tr("error_status" if status == "error" else status), status, x, 15, self.font)+25
        self.create_text(x+4, 27, text=ellipsis(self.run.get("project_name", ""), self.font, max(0, width-x-25)), font=self.font, fill=INK, anchor="w")
