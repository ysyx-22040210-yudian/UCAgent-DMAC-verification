"""Real Tk event-loop tests for native navigation, scoped runs, evidence, and cancellation."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from ucagent_tk.app import Application
from ucagent_tk.dialogs import CommandPalette, DownloadDialog, InputDialog, import_project, replay, scaffold
from ucagent_tk.i18n import tr
from ucagent_tk.model import Preferences
from ucagent_tk.visuals import ActionButton, ProjectList, RunBanner, RunSummary, ToolHealth, ellipsis, status_colors
from ucagent_tk.widgets import AutoScrollbar, EvidencePanel, Table, TextBox
from ucagent_tk.views import Dashboard, ProjectView, RunView
from ucagent_tk.wizard import RunWizard
from fakes import ARTIFACT, PlatformServer, PROJECT, RUN, WAVEFORM


class NativeGuiTests(unittest.TestCase):
    """Exercise native widget callbacks against a real HTTP fixture service."""

    def setUp(self):
        """Start a hidden but real Tk window and isolated HTTP service."""
        self.temp = tempfile.TemporaryDirectory()
        self.server = PlatformServer()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.server.close()
            self.temp.cleanup()
            self.skipTest("Tk display required: {}".format(exc))
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda kind, value, traceback: self.errors.append(str(value))
        self.preferences = Preferences(Path(self.temp.name) / "preferences.json")
        self.app = Application(self.root, self.server.origin, self.preferences)
        self.spin(lambda: bool(self.app.view.projects.records))

    def tearDown(self):
        """Close local widgets/readers and verify no asynchronous Tcl callback failed."""
        if not self.app.closed:
            self.app.close()
            self.spin(lambda: self.app.closed)
        self.server.close()
        self.root.report_callback_exception = None
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def spin(self, predicate, timeout=4):
        """Pump the real event loop until an observable contract is met or times out."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Tk condition timed out. UI diagnostic: {}".format(self.app.message.cget("text")))

    def wizard(self, project=None, source=None):
        """Open the normal native wizard and wait for its asynchronously loaded defaults."""
        self.app.new_run(project or PROJECT["id"], source)
        self.spin(lambda: any(isinstance(child, RunWizard) for child in self.root.winfo_children()))
        return next(child for child in self.root.winfo_children() if isinstance(child, RunWizard))

    def test_navigation_every_page_and_no_hidden_workflow_branches(self):
        """Every navigation destination loads; a disabled child remains visible and inspectable."""
        destinations = [("projects", lambda view: bool(view.table.records)), ("project", lambda view: view.project is not None),
                        ("runs", lambda view: bool(view.table.records)), ("workflows", lambda view: bool(view.tree.records)),
                        ("toolchains", lambda view: bool(view.capabilities.records)), ("mcp", lambda view: bool(view.tools.records)),
                        ("settings", lambda view: str(view.button.cget("state")) == "normal")]
        for page, ready in destinations:
            with self.subTest(page=page):
                self.app.show(page, PROJECT["id"] if page == "project" else None)
                self.spin(lambda: ready(self.app.view))
                self.assertEqual(self.app.message.cget("text"), "")
                if page == "workflows":
                    tree = self.app.view.tree
                    self.assertIn("run-1:wf:optional", tree.records)
                    self.assertEqual(tree.tree.parent("run-1:wf:optional"), "run-1:wf:gate")
                    self.assertEqual(tree.records["run-1:wf:optional"]["disabled_reason"], "Not selected")

    def test_formal_workflow_preview_explicit_engine(self):
        """Selecting SBY refreshes the native catalog without submitting a run or modifying a project."""
        self.app.show("workflows")
        self.spin(lambda: bool(self.app.view.tree.records))
        view = self.app.view
        self.assertEqual(view.formal_engine.get(), "formalmc")
        offset = len(self.server.requests)
        view.formal_engine.set("sby")
        view.engine_selector.event_generate("<<ComboboxSelected>>")
        self.spin(lambda: any("formal_engine=sby" in request[1] for request in self.server.requests[offset:]))
        self.assertTrue(all(request[0] == "GET" for request in self.server.requests[offset:]))

    def test_tool_health_shows_open_tools_unknown_adapters_and_overflow(self):
        """The overview cannot silently hide a configured open-source or future adapter."""
        health = ToolHealth(self.root, lambda: None)
        health.set([{"capabilities": [{"name": name, "available": True} for name in ("sby", "yosys", "yosys-smtbmc", "z3")]}])
        labels = [health.itemcget(item, "text") for item in health.find_all() if health.type(item) == "text"]
        for name in ("SBY", "Yosys", "SMTBMC", "Z3"):
            self.assertIn(name, labels)
        health.set([{"capabilities": [{"name": "future_adapter", "available": False}]}])
        labels = [health.itemcget(item, "text") for item in health.find_all() if health.type(item) == "text"]
        self.assertIn("future_adapter", labels)
        self.assertIn(tr("unavailable"), labels)
        health.set([{"capabilities": [{"name": str(index), "available": True} for index in range(6)]}])
        labels = [health.itemcget(item, "text") for item in health.find_all() if health.type(item) == "text"]
        self.assertIn(tr("more_tool_observations", count=2), labels)
        health.set([])
        labels = [health.itemcget(item, "text") for item in health.find_all() if health.type(item) == "text"]
        self.assertIn(tr("no_tool_observation"), labels)
        self.assertEqual(self.app.lifecycle_hint.cget("text"), tr("restart_warning"))
        health.destroy()

    def test_slow_requests_keep_tk_responsive_and_stale_views_are_discarded(self):
        """Networking never blocks the UI thread or writes into a page that has been closed."""
        self.server.delay = 0.4
        ticks = []
        self.root.after(30, lambda: ticks.append(True))
        self.app.show("projects")
        self.app.show("runs")
        self.spin(lambda: bool(ticks), timeout=0.2)
        self.spin(lambda: bool(self.app.view.rows))
        self.assertEqual(self.errors, [])

    def test_connection_generation_discards_old_root_callbacks(self):
        """A response from a previous service cannot open a wizard on a different service."""
        observed = []
        self.app.io(self.root, lambda: "old", observed.append, key="epoch")
        self.app.generation += 1
        self.spin(lambda: not any(key[-1] == "epoch" for key in self.app.pending))
        self.assertEqual(observed, [])

    def test_wizard_preserves_parameters_and_launches_exactly_once(self):
        """Native controls produce one immutable request only after a ready server preflight."""
        wizard = self.wizard()
        self.assertEqual(wizard.draft["design"]["parameters"], {"WIDTH": 8})
        wizard.continue_button.invoke()
        self.assertEqual(wizard.step, 1)
        wizard.form.fields["seeds"].set("11,29")
        wizard.continue_button.invoke()
        self.spin(lambda: wizard.step == 2)
        self.assertEqual(wizard.preview["test_count"], 2)
        self.assertFalse(any(path == "/runs" for _, path, _ in self.server.mutations))
        wizard.continue_button.invoke()
        wizard.continue_button.invoke()
        self.spin(lambda: isinstance(self.app.view, RunView) and self.app.view.run is not None)
        creates = [body for _, path, body in self.server.mutations if path == "/runs"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["simulation"]["seeds"], [11, 29])
        self.assertEqual(creates[0]["design"]["parameters"], {"WIDTH": 8})

    def test_clone_keeps_multiple_suites_literal_plusargs_and_extended_design(self):
        """Cloning must not reduce a saved scope or split commas inside source inputs."""
        source = deepcopy(PROJECT["run_defaults"])
        source["methodology"] = "uvm"
        source["simulation"].update(suites=["UT", "IT"], tests=["ut_test"], plusargs=["+VALUES=1,2,4"])
        source["design"].update(sources=["rtl,variant.sv"], declared_option="retained")
        wizard = self.wizard(source=source)
        wizard.advance()
        wizard.advance()
        self.spin(lambda: wizard.step == 2)
        self.assertEqual(wizard.draft, source)

    def test_new_run_replaces_previous_result_only_after_real_create_response(self):
        """An existing result is not evidence that a new launch has completed."""
        self.app.show("run", RUN["id"])
        original_view = self.app.view
        self.spin(lambda: original_view.run is not None)
        wizard = self.wizard()
        wizard.advance()
        wizard.advance()
        self.spin(lambda: wizard.step == 2)
        wizard.advance()
        self.assertIs(self.app.view, original_view)
        self.spin(lambda: self.app.view is not original_view and self.app.view.run is not None)
        self.assertNotEqual(self.app.view.identifier, RUN["id"])

    def test_blocked_preflight_cannot_launch_and_back_invalidates_result(self):
        """A blocked preview remains a recheck action and editing invalidates readiness."""
        self.server.preview_ready = False
        wizard = self.wizard()
        wizard.advance()
        wizard.advance()
        self.spin(lambda: wizard.step == 2)
        wizard.advance()
        self.spin(lambda: not wizard.busy)
        self.assertFalse(any(path == "/runs" for _, path, _ in self.server.mutations))
        wizard.back()
        self.assertIsNone(wizard.preview)
        wizard.form.fields["seeds"].set("1,broken")
        wizard.advance()
        self.assertEqual(wizard.step, 1)
        self.assertIn("positive integers", wizard.error.cget("text"))

    def test_uvm_suite_changes_use_real_saved_test_members(self):
        """UT and IT choices change test/seed membership without manufacturing a smoke class."""
        wizard = self.wizard()
        wizard.form.fields["method"].set("uvm")
        wizard.change_method()
        wizard.advance()
        wizard.form.fields["suite"].set("IT")
        wizard.change_suite()
        self.assertEqual(wizard.form.fields["tests"].get(), "it_test")
        self.assertEqual(wizard.form.fields["seeds"].get(), "29")
        wizard.advance()
        self.spin(lambda: wizard.step == 2)
        self.assertEqual(wizard.preview["matrix"], [{"test": "it_test", "suite": "IT", "seed": 29}])

    def test_formal_requires_explicit_inputs(self):
        """The original FormalMC flow requires a real Tcl entry rather than VCF timing fields."""
        profiles = [{"id": "formal-profile", "capabilities": [{"name": "formalmc"}]}]
        wizard = RunWizard(self.app, [PROJECT], profiles, PROJECT)
        wizard.form.fields["method"].set("formal")
        wizard.change_method()
        wizard.advance()
        wizard.advance()
        self.assertEqual(wizard.step, 1)
        self.assertIn("exactly one entry .tcl", wizard.error.cget("text"))
        wizard.form.fields["property_sets"].set("DUT_formal.tcl")
        wizard.advance()
        self.spin(lambda: wizard.step == 2)
        self.assertEqual(wizard.draft["family"], "formal")
        self.assertFalse(wizard.draft["formal"]["cex_replay"]["enabled"])

    def test_run_result_tabs_logs_and_resume(self):
        """Every result category loads, missing coverage stays unknown, and events do not duplicate."""
        self.app.show("run", RUN["id"])
        view = self.app.view
        self.spin(lambda: view.run is not None and self.preferences.cursors.get(RUN["id"]) == 2)
        for category in view.tables:
            view.select_tab(category)
            self.spin(lambda: category in view.rows)
            self.assertTrue(view.tables[category].records)
        metric = next(iter(view.tables["coverage"].records.values()))
        self.assertIsNone(metric["covered"])
        self.assertNotEqual(metric["target"], 100)
        self.assertEqual(view.log.get().count("#1 "), 1)
        self.assertIn("reviewed", view.audit.get())
        self.app.show("overview")
        self.app.show("run", RUN["id"])
        view = self.app.view
        self.spin(lambda: view.run is not None)
        self.assertEqual(view.log.get().count("#1 "), 0)
        view.start_stream(0)
        self.spin(lambda: "#1 " in view.log.get())
        self.assertEqual(view.log.get().count("#1 "), 1)

    def test_import_and_approval_retry_cancel_are_explicit(self):
        """Native dialogs submit declared project and stage actions, never arbitrary commands."""
        dialog = import_project(self.app)
        dialog.form.fields["name"].set("Imported RTL")
        dialog.form.fields["path"].set("/work/imported")
        dialog.button.invoke()
        self.spin(lambda: isinstance(self.app.view, ProjectView) and self.app.view.project is not None)
        self.assertEqual(self.app.view.project["path"], "/work/imported")
        self.app.show("run", RUN["id"])
        view = self.app.view
        self.spin(lambda: view.run is not None)
        view.stage_tree.tree.selection_set("run-1:wf:gate")
        self.root.update()
        with patch("ucagent_tk.views.simpledialog.askstring", return_value="Reviewed actual evidence"), patch("ucagent_tk.views.messagebox.askyesno", return_value=True):
            view.stage_action("approve")
            self.spin(lambda: any(path.endswith("/approve") for _, path, _ in self.server.mutations))
            self.spin(lambda: not any(key[-1] == "stage-action" for key in self.app.pending))
            view.stage_action("retry")
            self.spin(lambda: self.app.view is not view)
            view = self.app.view
            self.spin(lambda: view.run is not None)
            self.spin(lambda: not any(key[-1] == "cancel" for key in self.app.pending))
            view.cancel_run()
            self.spin(lambda: self.server.runs[0]["execution_status"] == "cancelled")

    def test_native_verified_download_and_cex_dialog(self):
        """Save a real byte stream from the native action and retain explicit CEX test mapping."""
        self.app.show("run", RUN["id"])
        view = self.app.view
        view.select_tab("artifacts")
        self.spin(lambda: bool(view.tables["artifacts"].records))
        view.tables["artifacts"].tree.selection_set(ARTIFACT["id"])
        target = Path(self.temp.name) / "download.fsdb"
        with patch("ucagent_tk.dialogs.filedialog.asksaveasfilename", return_value=str(target)):
            dialog = view.download()
        self.spin(lambda: dialog.finished)
        self.assertIsNotNone(dialog.result)
        self.assertEqual(target.read_bytes(), WAVEFORM)
        dialog.close()
        prop = {"name": "p_correct", "status": "falsified", "counterexample_artifact_id": ARTIFACT["id"]}
        dialog = replay(self.app, RUN["id"], prop)
        dialog.form.fields["target"].set("replay_test")
        dialog.button.invoke()
        self.spin(lambda: not dialog.winfo_exists())
        request = next(body for _, path, body in self.server.mutations if path.endswith("counterexample-replays"))
        self.assertEqual(request["uvm_test"], "replay_test")
        self.assertEqual(request["property_name"], "p_correct")

    def test_uvm_scaffold_model_is_user_explicit(self):
        """Scaffold requests contain only declared ports and an explicit optional user model."""
        dialog = scaffold(self.app, PROJECT)
        dialog.form.fields["clock"].set("clk")
        dialog.form.fields["reset"].set("rst_n")
        dialog.form.fields["signals"].set(json.dumps([{"name": "a", "direction": "input", "width": 8}, {"name": "sum", "direction": "output", "width": 9}]))
        dialog.send()
        self.spin(lambda: not dialog.winfo_exists())
        body = next(body for _, path, body in self.server.mutations if path.endswith("/scaffold"))
        self.assertIsNone(body["spec"]["reference_model"])
        self.assertEqual(body["spec"]["uvm_version"], "1.2")

    def test_settings_invalid_bound_does_not_write(self):
        """Resource policy validation rejects zero disk thresholds and non-finite values."""
        self.app.show("settings")
        view = self.app.view
        self.spin(lambda: str(view.button.cget("state")) == "normal")
        for value in ("0", "nan", "inf", "text"):
            view.form.fields["minimum_free_disk_gb"].set(value)
            view.save()
        self.assertFalse(any(path == "/settings" for _, path, _ in self.server.mutations))

    def test_offline_state_and_recovery_do_not_create_data(self):
        """Service errors preserve the visible history and recover through explicit refresh."""
        self.server.error = (503, {"detail": "Execution service is restarting"})
        self.app.refresh()
        self.spin(lambda: "HTTP 503" in self.app.message.cget("text"))
        self.assertTrue(self.app.view.projects.records)
        self.server.error = None
        self.app.refresh()
        self.spin(lambda: not self.app.message.cget("text"))
        self.assertEqual(self.server.mutations, [])

    def test_close_during_io_hides_immediately_then_drains_on_tk_thread(self):
        """Window closure remains responsive while avoiding off-thread Tcl finalization."""
        self.server.delay = 0.4
        self.app.refresh()
        started = time.monotonic()
        self.app.close()
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertTrue(self.app.closing)
        self.spin(lambda: self.app.closed)
        self.assertFalse(self.app.tasks)

    def test_search_palette_uses_real_ids_and_preserves_literal_queries(self):
        """Search routes actual entities, does not submit queries, and survives repeated opening."""
        self.app.search()
        palette = next(child for child in self.root.winfo_children() if isinstance(child, CommandPalette))
        self.spin(lambda: bool(palette.rows))
        self.app.search()
        self.assertEqual(sum(isinstance(child, CommandPalette) for child in self.root.winfo_children()), 1)
        palette.query.set("<script>{unknown}</script>")
        self.assertFalse(palette.table.records)
        palette.query.set(RUN["id"])
        self.assertEqual(palette.table.selected()["entity_id"], RUN["id"])
        palette.open()
        self.spin(lambda: isinstance(self.app.view, RunView) and self.app.view.run is not None)
        self.assertEqual(self.app.view.identifier, RUN["id"])
        self.assertTrue(self.app.navigation["runs"].active)
        self.assertEqual(sum(button.active for button in self.app.navigation.values()), 1)
        self.assertFalse(self.server.mutations)

    def test_advanced_inputs_survive_collapse_and_footer_stays_visible(self):
        """Advanced design values remain canonical inputs and minimum-size editors retain actions."""
        self.root.deiconify()
        self.root.geometry("1120x760")
        wizard = self.wizard()
        wizard.geometry("920x710")
        self.root.update()
        self.assertFalse(wizard.form.controls["parameters"].winfo_ismapped())
        wizard.toggle_advanced()
        self.root.update()
        self.assertTrue(wizard.form.controls["parameters"].winfo_ismapped())
        wizard.form.fields["parameters"].set('{"WIDTH": 32}')
        wizard.form.fields["include_dirs"].set("include/literal,variant")
        wizard.toggle_advanced()
        wizard.collect()
        self.assertEqual(wizard.draft["design"]["parameters"], {"WIDTH": 32})
        self.assertEqual(wizard.draft["design"]["include_dirs"], ["include/literal,variant"])
        for step in range(3):
            self.root.update()
            self.assertTrue(wizard.continue_button.winfo_ismapped())
            self.assertLessEqual(wizard.continue_button.winfo_rooty()+wizard.continue_button.winfo_height(), wizard.winfo_rooty()+wizard.winfo_height())
            if step < 2:
                wizard.advance()
                self.spin(lambda: wizard.step == step+1)
        self.assertFalse(any(path == "/runs" for _, path, _ in self.server.mutations))
        wizard.destroy()
        dialog = scaffold(self.app, PROJECT)
        dialog.geometry("760x580")
        self.root.update()
        self.assertTrue(dialog.button.winfo_ismapped())
        self.assertLessEqual(dialog.button.winfo_rooty()+dialog.button.winfo_height(), dialog.winfo_rooty()+dialog.winfo_height())
        dialog.destroy()

    def test_table_numeric_sort_and_refresh_preserve_identity(self):
        """Sort native evidence numerically with missing values last and stable selected identities."""
        table = Table(self.root, [("seed", "seed", 100)])
        rows = [{"id": "large", "seed": 29}, {"id": "small", "seed": 2}, {"id": "missing", "seed": None}]
        table.set_rows(rows)
        table.tree.selection_set("large")
        table.sort("seed")
        self.assertEqual(table.tree.get_children(), ("small", "large", "missing"))
        table.sort("seed")
        self.assertEqual(table.tree.get_children(), ("large", "small", "missing"))
        table.set_rows(rows + [{"id": "middle", "seed": 11}])
        self.assertEqual(table.tree.get_children(), ("large", "middle", "small", "missing"))
        self.assertEqual(table.selected()["id"], "large")
        self.assertIsNone(table.records["missing"]["seed"])
        table.destroy()

    def test_vector_buttons_keyboard_focus_and_disabled_contract(self):
        """Custom native controls support keyboard activation but never dispatch when disabled."""
        self.root.deiconify()
        window = tk.Toplevel(self.root)
        calls = []
        button = ActionButton(window, text="Launch", command=lambda: calls.append("invoked"))
        button.pack()
        self.root.update()
        button.focus_force()
        self.root.update()
        button.event_generate("<Return>")
        self.root.update()
        self.assertEqual(calls, ["invoked"])
        self.assertTrue(button.focused)
        button.configure(state="disabled", text="Blocked")
        button.event_generate("<space>")
        button.event_generate("<Button-1>")
        button.invoke()
        self.assertEqual(calls, ["invoked"])
        self.assertEqual(button.cget("text"), "Blocked")
        window.destroy()

    def test_project_list_scroll_selection_and_pixel_ellipsis(self):
        """More projects than visible rows remain reachable by keyboard without altering their names."""
        listing = self.app.view.projects
        rows = [{"id": "project-{}".format(index), "name": "Very long actual project name " * 12} for index in range(20)]
        listing.set_rows(rows)
        listing.move(20)
        self.assertEqual(listing.selected()["id"], "project-19")
        self.assertGreater(listing.offset, 0)
        listing.scroll(-100)
        self.assertEqual(listing.offset, 0)
        listing.set_rows(rows)
        self.assertEqual(listing.selected()["name"], rows[-1]["name"])
        font = listing.title_font
        fitted = ellipsis(rows[0]["name"], font, 120)
        self.assertLessEqual(font.measure(fitted), 120)
        self.assertEqual(ellipsis("retained", font, 0), "")
        listing.set_rows(rows[:2])
        self.assertIsNone(listing.selected())

    def test_evidence_disclosure_and_semantic_states_remain_honest(self):
        """Visual summaries preserve missing counters, failed conclusions, and complete literal evidence."""
        self.root.deiconify()
        window = tk.Toplevel(self.root)
        window.geometry("800x600")
        banner = RunBanner(window)
        banner.pack(fill="x")
        summary = RunSummary(window)
        summary.pack(fill="x")
        panel = EvidencePanel(window)
        panel.pack(fill="x")
        record = {**RUN, "verification_status": "failed"}
        banner.set(record)
        summary.set({"summary": {}, "request": RUN["request"]})
        panel.set(record)
        self.root.update()
        labels = [banner.itemcget(item, "text") for item in banner.find_all() if banner.type(item) == "text"]
        self.assertIn(tr("completed"), labels)
        self.assertIn(tr("failed"), labels)
        self.assertNotEqual(status_colors("failed"), status_colors("error"))
        counters = [summary.itemcget(item, "text") for item in summary.find_all() if summary.type(item) == "text"]
        self.assertIn("-- / --", counters)
        self.assertNotIn("0", counters)
        self.assertFalse(panel.box.winfo_ismapped())
        before = panel.get()
        panel.toggle()
        self.root.update()
        self.assertTrue(panel.box.winfo_ismapped())
        panel.toggle()
        self.assertEqual(panel.get(), before)
        self.assertEqual(json.loads(before)["verification_status"], "failed")
        window.destroy()

    def test_empty_text_hides_scrollbar_and_long_text_reveals_it(self):
        """Quiet editor surfaces still expose actual overflowing evidence through native scrolling."""
        self.root.deiconify()
        window = tk.Toplevel(self.root)
        window.geometry("500x200")
        box = TextBox(window, height=3)
        box.pack(fill="both", expand=True)
        bar = next(child for child in box.winfo_children() if isinstance(child, AutoScrollbar))
        self.root.update()
        self.assertFalse(bar.winfo_ismapped())
        box.set("actual evidence\n"*100)
        self.root.update()
        self.assertTrue(bar.winfo_ismapped())
        box.set("")
        self.root.update()
        self.assertFalse(bar.winfo_ismapped())
        window.destroy()

    def test_compact_window_keeps_all_tabs_and_evidence_actions_reachable(self):
        """All evidence destinations and disclosure controls remain visible at the supported minimum."""
        self.root.deiconify()
        self.root.geometry("1120x760")
        self.app.show("run", RUN["id"])
        view = self.app.view
        self.spin(lambda: view.run is not None)
        self.root.update()
        visible = set()
        # The selected native tab has a different vertical inset from inactive
        # tabs; inspect the whole header hit area, not one arbitrary scanline.
        for y in (8, 20, 32):
            for x in range(0, view.notebook.winfo_width(), 3):
                try:
                    visible.add(view.notebook.index("@{},{}".format(x, y)))
                except tk.TclError:
                    pass
        self.assertEqual(visible, set(range(len(view.tabs))))
        for page, ready in (("toolchains", lambda item: bool(item.capabilities.records)),
                            ("workflows", lambda item: bool(item.tree.records)),
                            ("projects", lambda item: bool(item.table.records)),
                            ("mcp", lambda item: bool(item.tools.records))):
            self.app.show(page)
            self.spin(lambda: ready(self.app.view))
            self.root.update()
            button = self.app.view.detail.button
            self.assertTrue(button.winfo_ismapped(), page)
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height(), page)

    def test_new_formal_selects_formalmc_even_with_installed_sby(self):
        """Tool discovery must not redirect a new Formal request to SBY or VCF."""
        for installed in ("sby", "vcf"):
            profiles = [{"id": PROJECT["run_defaults"]["toolchain"], "capabilities": [{"name": installed}]}]
            wizard = RunWizard(self.app, [PROJECT], profiles, PROJECT)
            wizard.form.fields["method"].set("formal")
            wizard.change_method()
            self.assertEqual(wizard.draft["formal"]["engine"], "formalmc")
            self.assertEqual(wizard.draft["formal"]["clock"], {})
            wizard.advance()
            self.assertEqual(wizard.step, 1)
            wizard.advance()
            self.assertEqual(wizard.step, 1)
            self.assertEqual(wizard.error.cget("text"), tr("formal_select_profile"))
            wizard.destroy()

    def test_formalmc_hides_vcf_fields_and_preserves_explicit_script(self):
        """The restored flow collects Tcl-controlled timing without hidden default periods."""
        profiles = [{"id": "formal-profile", "capabilities": [{"name": "formalmc"}]}]
        wizard = RunWizard(self.app, [PROJECT], profiles, PROJECT)
        wizard.form.fields["method"].set("formal")
        wizard.change_method()
        self.assertEqual(wizard.draft["toolchain"], "formal-profile")
        wizard.advance()
        self.root.update()
        self.assertFalse(wizard.form.controls["clock"].winfo_ismapped())
        wizard.form.fields["property_sets"].set("formal_out/tests/DUT_formal.tcl")
        wizard.collect()
        self.assertEqual(wizard.draft["formal"]["clock"], {})
        self.assertEqual(wizard.draft["formal"]["reset"], {})
        self.assertEqual(wizard.draft["formal"]["property_sets"], ["formal_out/tests/DUT_formal.tcl"])
        self.assertEqual(wizard.draft["formal"]["cex_replay"]["methodology"], "unitytest")
        wizard.destroy()

    def test_sby_options_are_native_and_keep_bounded_mode(self):
        """Expose open formal controls and preserve mode/depth without hidden clock defaults."""
        project = deepcopy(PROJECT)
        project["run_defaults"].pop("simulation", None)
        project["run_defaults"].update(family="formal", methodology="systemverilog", formal={"engine": "sby", "clock": {}, "reset": {}, "property_sets": [], "cex_replay": {"enabled": False, "methodology": "uvm"}, "sby": {"mode": "bmc", "depth": 12, "timeout_seconds": 60}})
        wizard = RunWizard(self.app, [project], [{"id": project["run_defaults"]["toolchain"]}], project)
        wizard.step = 1
        wizard.render()
        self.root.update()
        self.assertEqual(wizard.form.fields["sby_mode"].get(), "bmc")
        self.assertFalse(wizard.form.controls["clock"].winfo_ismapped())
        wizard.form.fields["sby_depth"].set("25")
        wizard.collect()
        self.assertEqual(wizard.draft["formal"]["sby"]["depth"], 25)
        self.assertEqual(wizard.draft["formal"]["clock"], {})
        wizard.destroy()

    def test_formal_engine_selection_preserves_separate_parameters(self):
        """VCF and SBY retain their own options and route only to compatible profiles."""
        project = deepcopy(PROJECT)
        project["run_defaults"].pop("simulation", None)
        project["run_defaults"].update(family="formal", methodology="systemverilog", toolchain="open", formal={"engine": "sby", "clock": {}, "reset": {}, "property_sets": [], "cex_replay": {"enabled": False, "methodology": "uvm"}, "sby": {"mode": "bmc", "depth": 17, "timeout_seconds": 60}})
        profiles = [{"id": "open", "capabilities": [{"name": name} for name in ("sby", "yosys", "yosys-smtbmc", "z3")]}, {"id": "commercial", "capabilities": [{"name": "vcf", "available": False, "license_status": "unavailable"}]}]
        wizard = RunWizard(self.app, [project], profiles, project)
        wizard.advance()
        wizard.form.fields["sby_depth"].set("29")
        wizard.form.fields["engine"].set("vc_formal")
        wizard.change_engine()
        self.assertEqual(wizard.draft["toolchain"], "commercial")
        self.assertNotIn("sby", wizard.draft["formal"])
        self.assertEqual(wizard.form.fields["clock"].get(), "")
        wizard.form.fields["clock"].set("pixel_clk")
        wizard.form.fields["reset"].set("reset_n")
        wizard.form.fields["period"].set("8ns")
        wizard.form.fields["engine"].set("sby")
        wizard.change_engine()
        self.assertEqual(wizard.draft["toolchain"], "open")
        self.assertEqual(wizard.form.fields["sby_mode"].get(), "bmc")
        self.assertEqual(wizard.form.fields["sby_depth"].get(), "29")
        wizard.form.fields["engine"].set("vc_formal")
        wizard.change_engine()
        self.assertEqual(wizard.form.fields["clock"].get(), "pixel_clk")
        self.assertEqual(wizard.form.fields["period"].get(), "8ns")
        self.assertEqual(wizard.form.fields["reset"].get(), "reset_n")
        wizard.collect()
        self.assertNotIn("sby", wizard.draft["formal"])
        self.assertIsNone(wizard.preview)
        wizard.destroy()

    def test_missing_formal_engine_stays_selected_and_cannot_launch(self):
        """An absent engine stays visible and blocked instead of falling back to another tool."""
        wizard = self.wizard()
        wizard.form.fields["method"].set("formal")
        wizard.change_method()
        wizard.advance()
        wizard.form.fields["engine"].set("sby")
        wizard.change_engine()
        self.assertEqual(wizard.draft["formal"]["engine"], "sby")
        self.assertEqual(wizard.draft["toolchain"], "")
        wizard.advance()
        self.assertEqual(wizard.step, 1)
        self.assertEqual(wizard.error.cget("text"), tr("formal_select_profile"))
        self.assertFalse(any(path == "/runs" for _, path, _ in self.server.mutations))
        wizard.destroy()


if __name__ == "__main__":
    unittest.main()
