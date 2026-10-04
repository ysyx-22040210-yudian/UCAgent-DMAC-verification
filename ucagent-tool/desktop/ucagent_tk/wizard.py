"""Project-first native run wizard preserving saved inputs and authoritative preflight."""

from copy import deepcopy
import json
import tkinter as tk
from tkinter import messagebox, ttk

from .client import ApiError
from .i18n import tr
from .model import formal_toolchains, initial_draft, lines, seeds, simulation_defaults, validate_draft
from .widgets import Form, ScrollFrame, Table, TextBox
from .visuals import FONT, INK, MUTED, PAGE, SURFACE, ActionButton, Stepper


class RunWizard(tk.Toplevel):
    """Edit one isolated request, inspect its exact plan, and explicitly dispatch once."""

    def __init__(self, app, projects, toolchains, project=None, source=None):
        """Select a real saved project before presenting any editable run defaults."""
        super().__init__(app.root)
        self.app = app
        self.client = app.client
        self.projects = projects
        self.toolchains = toolchains
        self.source = source
        self.step = 0
        self.preview = None
        self.busy = False
        self.draft = None
        self.project = None
        self.form = None
        self.coverage = {}
        self.advanced_open = False
        self.engine_drafts = {}
        self.title(tr("wizard_title"))
        self.geometry("1040x860+{}+{}".format(app.root.winfo_rootx()+max(10, (app.root.winfo_width()-1040)//2), app.root.winfo_rooty()+24))
        self.minsize(920, 710)
        self.configure(background=PAGE)
        self.transient(app.root)
        self.grab_set()
        header = tk.Frame(self, background=SURFACE)
        header.pack(fill="x")
        tk.Label(header, text=tr("wizard_title"), background=SURFACE, foreground=INK, font=(FONT, 18, "bold")).pack(anchor="w", padx=28, pady=(22, 8))
        self.steps = Stepper(header)
        self.steps.pack(fill="x", padx=24, pady=(2, 12))
        self.body = ttk.Frame(self, padding=(22, 0))
        self.body.pack(fill="both", expand=True)
        self.error = ttk.Label(self, style="Error.TLabel", wraplength=950)
        self.error.pack(side="bottom", before=self.body, fill="x", padx=24, pady=8)
        footer = tk.Frame(self, background=SURFACE, padx=24, pady=14)
        footer.pack(side="bottom", before=self.error, fill="x")
        self.back_button = ActionButton(footer, tr("back"), self.back, background=SURFACE, width=108)
        self.back_button.pack(side="left")
        ActionButton(footer, tr("cancel"), self.destroy, variant="ghost", background=SURFACE, width=90).pack(side="left", padx=8)
        self.continue_button = ActionButton(footer, tr("next"), self.advance, variant="primary", icon_name="arrow", background=SURFACE, width=174, height=40)
        self.continue_button.pack(side="right")
        if not projects:
            self.error.configure(text=tr("no_projects"))
            self.continue_button.configure(state="disabled")
            return
        identifier = project.get("id") if isinstance(project, dict) else project
        self.project = next((item for item in projects if item["id"] == identifier), projects[0])
        try:
            self.draft = initial_draft(self.project, source)
            self.render()
        except Exception as exc:
            self.error.configure(text=str(exc))
            self.continue_button.configure(state="disabled")

    def render(self):
        """Render only the active step while keeping edits in the independent draft."""
        for child in self.body.winfo_children():
            child.destroy()
        self.coverage.clear()
        self.steps.set(self.step)
        self.error.configure(text="")
        self.back_button.configure(state="normal" if self.step and not self.busy else "disabled")
        self.continue_button.configure(text=tr("next" if self.step == 0 else "preflight" if self.step == 1 else "launch" if self.preview and self.preview["ready"] else "recheck"), state="disabled" if self.busy else "normal")
        if self.step == 2:
            self.render_preview()
            return
        scroll = ScrollFrame(self.body)
        scroll.pack(fill="both", expand=True)
        content = scroll.content
        self.form = Form(content)
        self.form.pack(fill="both", expand=True, padx=4, pady=4)
        draft = self.draft
        if self.step == 0:
            choices = ["{} [{}]".format(item["name"], item["id"][:8]) for item in self.projects]
            selected = choices[self.projects.index(self.project)]
            control = self.form.add("project", "project_name", selected, choices=choices)
            control.bind("<<ComboboxSelected>>", self.change_project)
            method = "formal" if draft["family"] == "formal" else draft["methodology"]
            control = self.form.add("method", "methodology", method, choices=["systemverilog", "uvm", "unitytest", "formal"])
            control.bind("<<ComboboxSelected>>", self.change_method)
            self.form.add("toolchain", "toolchain", draft["toolchain"], choices=[item["id"] for item in self.toolchains])
            self.form.add("authoring_mode", "authoring_mode", draft.get("authoring_mode", "guided"), choices=["guided", "incremental", "vibe"])
            if method == "unitytest":
                self.form.add("simulator", "simulator", draft["simulation"]["simulator"], choices=["verilator", "vcs"])
            self.form.add("top", "top", draft["design"].get("top", ""))
            for key in ("filelists", "sources", "include_dirs", "defines"):
                self.form.add(key, key, "\n".join(draft["design"].get(key) or []), multiline=True)
            self.form.add("parameters", "parameters", json.dumps(draft["design"].get("parameters") or {}, indent=2), multiline=True)
            self.form.visible(("include_dirs", "defines", "parameters"), self.advanced_open)
            self.advanced_button = ActionButton(content, tr("advanced_hide" if self.advanced_open else "advanced_show"), self.toggle_advanced, variant="ghost", icon_name="settings", width=350)
            self.advanced_button.pack(anchor="w", pady=(8, 0))
            ttk.Label(content, text=tr("saved_inputs") + "\n" + tr("agent_boundary"), style="Hint.TLabel", wraplength=890).pack(fill="x", pady=12)
        elif draft["family"] == "simulation":
            sim = draft["simulation"]
            if draft["methodology"] == "uvm":
                selected_suites = ", ".join(sim["suites"] or ["UT"])
                choices = list(dict.fromkeys(["UT", "IT", "ST", selected_suites]))
                control = self.form.add("suite", "suite", selected_suites, choices=choices)
                control.bind("<<ComboboxSelected>>", self.change_suite)
                self.form.add("tests", "uvm_tests", "\n".join(sim["tests"]), multiline=True)
                self.form.add("uvm_version", "uvm_version", sim["uvm_version"])
            elif draft["methodology"] == "unitytest":
                self.form.add("unitytest_tests", "pytest_tests", "\n".join(sim["unitytest_tests"]), multiline=True)
            self.form.add("seeds", "seeds", ", ".join(str(seed) for seed in sim["seeds"]))
            choices = ["none", "vcd", "fst"] if sim["simulator"] == "verilator" else ["none", "fsdb"] if draft["methodology"] == "unitytest" else ["none", "fsdb", "vpd"]
            self.form.add("waveform", "waveform", sim["waveform"], choices=choices)
            self.form.add("plusargs", "plusargs", "\n".join(sim["plusargs"]), multiline=True)
            coverage = ttk.LabelFrame(content, text=tr("coverage"), padding=12)
            coverage.pack(fill="x", pady=12)
            self.coverage = {}
            for kind in ("line", "cond", "tgl", "fsm", "branch", "assert"):
                variable = tk.BooleanVar(self, value=kind in sim["coverage"])
                ttk.Checkbutton(coverage, text=kind, variable=variable).pack(side="left", padx=10)
                self.coverage[kind] = variable
            ttk.Label(content, text=tr("native_help") + "\n" + tr("scope_warning"), wraplength=890, style="Hint.TLabel").pack(fill="x", pady=8)
        else:
            formal = draft["formal"]
            control = self.form.add("engine", "engine", formal["engine"], choices=["formalmc", "vc_formal", "sby"])
            control.bind("<<ComboboxSelected>>", self.change_engine)
            compatible = formal_toolchains(self.toolchains, formal["engine"])
            control = self.form.add("toolchain", "toolchain", draft["toolchain"], choices=compatible)
            control.bind("<<ComboboxSelected>>", self.change_toolchain)
            selected = next((item for item in self.toolchains if item["id"] == draft["toolchain"]), {})
            blocked_license = any(item.get("name") == "vcf" and item.get("license_status") == "unavailable" for item in selected.get("capabilities", []))
            hint = "formal_no_profile" if not compatible else "formal_select_profile" if draft["toolchain"] not in compatible else "formal_license_blocked" if formal["engine"] == "vc_formal" and blocked_license else "formal_selection_help"
            ttk.Label(content, text=tr(hint), style="Hint.TLabel", wraplength=880).pack(fill="x", pady=(8, 4))
            self.form.add("clock", "clock", formal["clock"].get("signal"))
            self.form.add("period", "period", formal["clock"].get("period") or "10ns")
            self.form.add("reset", "reset", formal["reset"].get("signal"))
            self.form.add("reset_active", "reset_active", formal["reset"].get("active", "low"), choices=["low", "high"])
            self.form.add("property_sets", "formalmc_script" if formal["engine"] == "formalmc" else "property_sets", "\n".join(formal["property_sets"]), multiline=True)
            self.form.add("cex_enabled", "cex_enabled", formal["cex_replay"]["enabled"], check=True)
            self.form.add("cex_methodology", "cex_methodology", formal["cex_replay"]["methodology"], choices=["uvm", "unitytest"])
            if formal["engine"] == "formalmc":
                self.form.visible(("clock", "period", "reset", "reset_active"), False)
                ttk.Label(content, text=tr("formalmc_help"), wraplength=880, style="Hint.TLabel").pack(fill="x", pady=12)
            if formal["engine"] == "sby":
                options = formal.get("sby") or {}
                self.form.visible(("clock", "period", "reset", "reset_active"), False)
                self.form.add("sby_mode", "sby_mode", options.get("mode", "prove"), choices=["prove", "bmc", "cover"])
                self.form.add("sby_depth", "sby_depth", str(options.get("depth", 40)))
                self.form.add("sby_timeout", "sby_timeout", str(options.get("timeout_seconds", 120)))
                self.form.add("sby_multiclock", "sby_multiclock", options.get("multiclock", False), check=True)
                ttk.Label(content, text=tr("sby_help"), wraplength=880, style="Hint.TLabel").pack(fill="x", pady=12)
            ttk.Label(content, text=tr("cex_help"), wraplength=880, style="Hint.TLabel").pack(fill="x", pady=12)

    def collect(self):
        """Read the visible native controls and preserve every unedited request field."""
        values = self.form.values()
        draft = deepcopy(self.draft)
        if self.step == 0:
            parameters = json.loads(values["parameters"])
            if not isinstance(parameters, dict):
                raise ValueError(tr("json_invalid"))
            draft["design"].update({"top": values["top"].strip(), "parameters": parameters})
            for key in ("filelists", "sources", "include_dirs", "defines"):
                draft["design"][key] = lines(values[key])
            draft["toolchain"] = values["toolchain"]
            draft["authoring_mode"] = values["authoring_mode"]
            if draft["family"] == "simulation" and "simulator" in values:
                if draft["simulation"]["simulator"] != values["simulator"]:
                    draft["simulation"]["waveform"] = "none"
                draft["simulation"]["simulator"] = values["simulator"]
        elif draft["family"] == "simulation":
            sim = draft["simulation"]
            for key in ("tests", "unitytest_tests", "plusargs"):
                if key in values:
                    sim[key] = lines(values[key])
            sim["plusargs"] = [value if value.startswith("+") else "+" + value for value in sim["plusargs"]]
            sim["seeds"] = seeds(values["seeds"])
            sim["waveform"] = values["waveform"]
            sim["coverage"] = [key for key, value in self.coverage.items() if value.get()]
            if "suite" in values:
                sim["suites"] = [part.strip() for part in values["suite"].split(",")]
                sim["uvm_version"] = values["uvm_version"].strip()
        else:
            draft["toolchain"] = values["toolchain"]
            draft["formal"] = {"engine": values["engine"], "clock": {"signal": values["clock"].strip(), "period": values["period"].strip()}, "reset": {"signal": values["reset"].strip(), "active": values["reset_active"]}, "property_sets": lines(values["property_sets"]), "cex_replay": {"enabled": values["cex_enabled"], "methodology": values["cex_methodology"]}}
            if values["engine"] == "formalmc":
                draft["formal"]["clock"] = {}
                draft["formal"]["reset"] = {}
            if values["engine"] == "sby":
                draft["formal"]["clock"] = {}
                draft["formal"]["reset"] = {}
                draft["formal"]["sby"] = {"mode": values.get("sby_mode", "prove"), "depth": int(values.get("sby_depth", 40)), "timeout_seconds": int(values.get("sby_timeout", 120)), "multiclock": values.get("sby_multiclock", False)}
        if not draft["design"]["top"] or (self.step == 0 and not draft["toolchain"]):
            raise ValueError(tr("required"))
        self.draft = draft
        self.preview = None

    def toggle_advanced(self):
        """Reveal optional design fields while keeping their current values in every saved request."""
        self.advanced_open = not self.advanced_open
        self.form.visible(("include_dirs", "defines", "parameters"), self.advanced_open)
        self.advanced_button.configure(text=tr("advanced_hide" if self.advanced_open else "advanced_show"))

    def change_engine(self, event=None):
        """Keep each engine's options separate; never reinterpret or silently fall back."""
        selected = self.form.fields["engine"].get()
        previous = self.draft["formal"]["engine"]
        if selected == previous:
            return
        self.form.fields["engine"].set(previous)
        try:
            self.collect()
            self.engine_drafts[previous] = (deepcopy(self.draft["formal"]), self.draft["toolchain"])
            if selected in self.engine_drafts:
                formal, toolchain = self.engine_drafts[selected]
                self.draft["formal"], self.draft["toolchain"] = deepcopy(formal), toolchain
            else:
                self.draft["formal"] = {"engine": selected, "clock": {}, "reset": {}, "property_sets": list(self.draft["formal"]["property_sets"]), "cex_replay": deepcopy(self.draft["formal"]["cex_replay"])}
            compatible = formal_toolchains(self.toolchains, selected)
            if self.draft["toolchain"] not in compatible:
                self.draft["toolchain"] = compatible[0] if len(compatible) == 1 else ""
            self.preview = None
            self.render()
        except (ValueError, KeyError) as exc:
            self.error.configure(text=str(exc))

    def change_toolchain(self, event=None):
        """Refresh capability guidance without changing the user's selected engine."""
        try:
            self.collect()
            self.render()
        except (ValueError, KeyError) as exc:
            self.error.configure(text=str(exc))

    def change_project(self, event=None):
        """Switch to another project's defaults explicitly, never merge project inputs."""
        index = self.form.controls["project"].current()
        self.project = self.projects[index]
        self.source = None
        self.draft = initial_draft(self.project)
        self.engine_drafts.clear()
        self.preview = None
        self.render()

    def change_method(self, event=None):
        """Preserve design edits and invalidate the old method's execution plan."""
        selected = self.form.values()["method"]
        current = "formal" if self.draft["family"] == "formal" else self.draft["methodology"]
        if selected == current:
            return
        self.engine_drafts.clear()
        try:
            self.collect()
        except Exception as exc:
            self.error.configure(text=str(exc))
            self.form.fields["method"].set(current)
            return
        self.draft.pop("workflow_id", None)
        self.draft["family"] = "formal" if selected == "formal" else "simulation"
        self.draft["methodology"] = "systemverilog" if selected == "formal" else selected
        if selected == "formal":
            self.draft.pop("simulation", None)
            self.draft["formal"] = {"engine": "formalmc", "clock": {}, "reset": {}, "property_sets": [], "cex_replay": {"enabled": False, "methodology": "unitytest"}}
            compatible = formal_toolchains(self.toolchains, "formalmc")
            if self.draft["toolchain"] not in compatible and len(compatible) == 1:
                self.draft["toolchain"] = compatible[0]
        else:
            self.draft.pop("formal", None)
            self.draft["simulation"] = simulation_defaults(selected)
        self.render()

    def change_suite(self, event=None):
        """Select the saved members of one UT/IT/ST suite without cross-product expansion."""
        level = self.form.values()["suite"]
        if "," in level:
            return
        suite = next((item for item in (self.project.get("simulation") or {}).get("suites", []) if item["level"] == level), {})
        self.form.fields["tests"].set("\n".join(suite.get("tests") or []))
        if suite.get("seeds"):
            self.form.fields["seeds"].set(", ".join(str(value) for value in suite["seeds"]))

    def back(self):
        """Return to editing and invalidate any previous preflight result."""
        if self.busy or not self.step:
            return
        try:
            if self.step == 1:
                self.collect()
            self.preview = None
            self.step -= 1
            self.render()
        except Exception as exc:
            self.error.configure(text=str(exc))

    def advance(self):
        """Advance edit steps or explicitly create one immutable backend run."""
        if self.busy or self.draft is None:
            return
        try:
            if self.step < 2:
                self.collect()
            if self.step == 0:
                self.step = 1
                self.render()
                return
            if self.draft["family"] == "formal" and self.draft["toolchain"] not in formal_toolchains(self.toolchains, self.draft["formal"]["engine"]):
                raise ValueError(tr("formal_select_profile"))
            body = validate_draft(self.draft)
            self.busy = True
            self.continue_button.configure(state="disabled")
            self.back_button.configure(state="disabled")
            if self.step == 2 and self.preview and self.preview["ready"]:
                scheduled = self.app.io(self, lambda: self.client.call("/runs", "POST", body), self.launched, self.failed, key="launch")
            else:
                scheduled = self.app.io(self, lambda: self.client.call("/runs/preview", "POST", body), self.checked, self.failed, key="preview")
            if not scheduled:
                self.failed(ApiError("Another operation is pending; wait before retrying."))
        except Exception as exc:
            self.failed(exc)

    def checked(self, result):
        """Accept only a structured readiness response before enabling the launch action."""
        if (not isinstance(result, dict) or type(result.get("ready")) is not bool
                or any(not isinstance(result.get(key), list) for key in ("checks", "jobs", "matrix"))):
            self.failed(ApiError("Invalid preflight response; no run was created."))
            return
        self.preview = result
        self.step = 2
        self.busy = False
        self.render()

    def failed(self, error):
        """Restore editable controls and surface an error without retrying a mutation."""
        self.busy = False
        self.error.configure(text=str(error)[:2000])
        self.continue_button.configure(state="normal")
        self.back_button.configure(state="normal" if self.step else "disabled")

    def launched(self, run):
        """Open the actual persisted run returned by the backend, then close the editor."""
        if not isinstance(run, dict) or not run.get("id"):
            self.failed(ApiError("Run creation returned no identifier; inspect run history before retrying."))
            return
        self.app.show("run", run["id"])
        self.destroy()

    def render_preview(self):
        """Show every check and exact test matrix, keeping command evidence read-only."""
        preview = self.preview
        if preview is None:
            return
        ttk.Label(self.body, text=tr("preflight_ready", jobs=preview["job_count"], tests=preview["test_count"]) if preview["ready"] else tr("preflight_blocked"), style="Hint.TLabel" if preview["ready"] else "Error.TLabel").pack(anchor="w", pady=(2, 8))
        ttk.Label(self.body, text=tr("preflight_help"), wraplength=920).pack(anchor="w", pady=(0, 12))
        notebook = ttk.Notebook(self.body)
        notebook.pack(fill="both", expand=True)
        checks = ttk.Frame(notebook)
        notebook.add(checks, text=tr("preflight"))
        detail = TextBox(checks, height=7)
        table = Table(checks, [("key", "check", 160), ("status_label", "check_status", 85), ("message", "reason", 610)], on_select=lambda item: detail.set(item or {}), height=9)
        table.pack(fill="both", expand=True)
        detail.pack(fill="both", expand=True, pady=(8, 0))
        detail.set(tr("check_details"))
        table.set_rows([{**check, "status_label": tr("check_passed" if check["status"] == "passed" else check["status"])} for check in preview["checks"]])
        matrix = Table(notebook, [("test", "test", 530), ("suite", "suite", 110), ("seed", "seed", 110)])
        matrix.set_rows(preview["matrix"])
        notebook.add(matrix, text=tr("matrix"))
        commands = TextBox(notebook)
        commands.set(preview["jobs"] or {"note": "The formal command and Tcl will be generated when the run is created; preflight does not create proof directories."})
        notebook.add(commands, text=tr("plan"))

    def destroy(self):
        """Release every step-local Tcl variable on the main thread before closing the editor."""
        self.coverage.clear()
        super().destroy()
