"""Python 3.8 Tk tests for one shared Agent entry point and honest engine capabilities."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ucagent_tk.formal import FormalSessionView


class SharedFormalGuiTests(unittest.TestCase):
    """Exercise real widgets without a model or EDA; these are GUI contract tests only."""

    def setUp(self):
        """Construct a hidden Tk workspace with a controlled action recorder."""
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.notes = []
        self.app = SimpleNamespace(client=object(), notify=self.notes.append,
            connection=ttk.Label(self.root), message=ttk.Label(self.root))
        self.view = FormalSessionView(self.root, self.app, "fixture")
        self.view.pack(fill="both", expand=True)
        node = {"id": "requirement_analysis_and_planning", "index": 0, "description": "Planning",
                "enabled": True, "disabled_reason": "", "current": True, "status": "running", "journal": "",
                "children": [], "details": {"needs_human_check": True, "task": {}}}
        self.row = {"id": "fixture", "revision": 3, "state": "ready", "execution_status": "completed",
                    "verification_status": "unknown", "options": {"engine": "sby", "dut": "Counter"},
                    "last_result": None, "capabilities": {},
                    "view": {"current_index": 0, "all_completed": False, "stages": [node]}}

    def tearDown(self):
        """Release Tk resources without touching any real task."""
        self.root.destroy()

    def test_both_choices_share_controls_and_agent_action(self):
        """Engine selection changes capability text, not actions, fields or Agent budgets."""
        controls = None
        for engine in ("sby", "formalmc"):
            row = deepcopy(self.row)
            row["options"]["engine"] = engine
            self.view.render(row)
            if controls is None:
                controls = tuple(self.view.buttons)
            self.assertEqual(tuple(self.view.buttons), controls)
            self.assertIn("agent", controls)
            self.assertIn("COI", self.view.capabilities.cget("text"))
            self.assertEqual(str(self.view.buttons["agent"].cget("state")), "normal")
            with patch.object(self.view, "action") as action, patch("ucagent_tk.formal.messagebox.askyesno", return_value=True):
                self.view.buttons["agent"].invoke()
                self.assertEqual(action.call_args[0], ("agent",))
                self.assertEqual(action.call_args[1]["max_turns"], 12)
                self.assertEqual(action.call_args[1]["timeout"], 600)
                self.assertNotIn("engine", action.call_args[1])

    def test_unsaved_drafts_and_invalid_budgets_block_agent(self):
        """AI authoring cannot silently discard user edits or submit unbounded budgets."""
        self.view.render(self.row)
        with patch.object(self.view, "action") as action:
            self.view.journal.set("unsaved")
            self.view.start_agent()
            self.view.journal.set("")
            self.view.agent_turns.set("100")
            self.view.start_agent()
            action.assert_not_called()
            self.assertEqual(len(self.notes), 2)

    def test_running_controls_and_persisted_diff_display(self):
        """An active turn enables cancellation only; saved tool edits remain reviewable."""
        row = deepcopy(self.row)
        row["state"] = "running"
        with patch.object(self.view, "poll"):
            self.view.loaded_session((row, {"items": []}, {"items": [{"sequence": 1,
                "type": "agent.tool.EditTextFile", "result": {"path": "formal_out/plan.md", "diff": "+Bounded plan"}}]}))
        self.assertEqual(str(self.view.buttons["agent"].cget("state")), "disabled")
        self.assertEqual(str(self.view.buttons["approve"].cget("state")), "disabled")
        self.assertEqual(str(self.view.buttons["cancel"].cget("state")), "normal")
        self.assertIn("+Bounded plan", self.view.agent_edits.get())

    def test_migration_visibility_and_unsaved_drafts(self):
        """Only saved, idle SBY sessions can invoke internal migration."""
        row = deepcopy(self.row)
        for engine, state, enabled in (("sby", "completed", True), ("sby", "paused", True),
                                       ("formalmc", "ready", False), ("sby", "running", False)):
            row["options"]["engine"], row["state"] = engine, state
            self.view.render(row)
            self.assertEqual(str(self.view.buttons["migrate_formalmc"].cget("state")),
                             "normal" if enabled else "disabled")
        self.view.render(self.row)
        self.view.journal.set("unsaved")
        self.view.migrate_formalmc()
        self.assertIn("保存", self.notes[-1])

    def test_migration_uses_public_api_and_opens_existing_project_view(self):
        """One click opens the linked project, with no file dialog or target tool dispatch."""
        from unittest.mock import Mock
        response = {"session": self.row, "project": {"id": "target-project"}}
        self.app.client = Mock()
        self.app.client.call.return_value = response
        self.app.show = Mock()
        self.view.client = self.app.client

        def immediate(view, work, done, fail, **kwargs):
            """Exercise the callback without starting EDA or a model."""
            done(work())
            return True
        self.app.io = immediate
        self.view.render(self.row)
        self.view.migrate_formalmc()
        self.app.show.assert_called_once_with("project", "target-project")
        args = self.app.client.call.call_args
        self.assertTrue(args[0][0].endswith("/migrate-formalmc"))
        self.assertEqual(args[0][2]["revision"], self.row["revision"])
        self.assertFalse(self.view.pending_action)


class MigrationProjectGuiTests(unittest.TestCase):
    """Expose the source link in the existing project page without a file dialog."""

    def test_existing_project_view_shows_source_and_empty_target_history(self):
        """The target page uses normal run controls and returns to its source task."""
        from unittest.mock import Mock
        from ucagent_tk.views import ProjectView
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        try:
            app = SimpleNamespace(client=object(), show=Mock(), new_run=Mock(),
                connection=ttk.Label(root), message=ttk.Label(root))
            view = ProjectView(root, app, "target")
            view.pack()
            project = {"id": "target", "name": "Counter FormalMC", "path": "/managed/target", "design": {},
                "simulation": {}, "migration": {"source_session_id": "source", "source_revision": 7}}
            view.render((project, []))
            self.assertIn("source", view.migration_hint.cget("text"))
            self.assertIn("7", view.migration_hint.cget("text"))
            view.migration_source.invoke()
            app.show.assert_called_once_with("formal_session", "source")
            self.assertEqual(view.runs.tree.get_children(), ())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
