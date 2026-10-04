"""Python 3.8 native Campaign workbench and explicit candidate review controls."""

import tkinter as tk
from tkinter import simpledialog, ttk

from .client import collection, segment
from .dialogs import InputDialog
from .i18n import tr
from .views import BaseView
from .widgets import Table, TextBox
from .visuals import ActionButton


class Campaigns(BaseView):
    """Present durable engineering tasks with their next gate instead of anonymous jobs."""

    def __init__(self, parent, app, identifier=None):
        """Build a task list with structured creation and inspection actions."""
        super().__init__(parent, app, identifier)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 14))
        ActionButton(toolbar, tr("campaign_create"), self.create, variant="primary", width=150).pack(side="left")
        ActionButton(toolbar, tr("campaign_open"), self.open, width=150).pack(side="left", padx=10)
        self.table = Table(self, [("name", "name", 240), ("state", "check_status", 100),
            ("next_action", "next_action", 330), ("verification_status", "verification_status", 140)], on_open=self.open)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, text=tr("campaign_boundary"), style="Hint.TLabel", wraplength=1000).pack(fill="x", pady=12)

    def refresh(self):
        """Refresh persisted tasks without automatically retrying writes or starting jobs."""
        self.app.io(self, lambda: collection(self.client.call("/campaigns")), self.render, self.failed)

    def render(self, rows):
        """Show authoritative statuses and the exact next completion gate."""
        self.loaded()
        self.table.set_rows(rows)

    def open(self):
        """Navigate to the selected durable task identity."""
        row = self.table.selected()
        if row:
            self.app.show("campaign", row["id"])

    def create(self):
        """Load real project/toolchain choices before offering the input-partition wizard."""
        def load():
            """Read existing projects and administrator-owned toolchain identifiers."""
            return collection(self.client.call("/projects")), collection(self.client.call("/toolchains"))
        self.app.io(self, load, self.creation_dialog, self.failed)

    def creation_dialog(self, data):
        """Collect distinct RTL/TB/harness tops, explicit engines and confirmed budgets."""
        projects, toolchains = data
        if not projects or not toolchains:
            self.app.notify(tr("campaign_import_first"))
            return
        choices = {row["name"] + " · " + row["id"][:8]: row for row in projects}
        fields = [
            {"key": "project", "label": "project", "value": next(iter(choices)), "choices": list(choices)},
            {"key": "name", "label": "name", "value": "ISP Campaign"},
            {"key": "toolchain", "label": "toolchain", "value": toolchains[0]["id"], "choices": [row["id"] for row in toolchains]},
            {"key": "rtl_top", "label": "campaign_rtl_top", "value": ""},
            {"key": "rtl_sources", "label": "campaign_rtl_sources", "value": ""},
            {"key": "tb_top", "label": "campaign_tb_top", "value": ""},
            {"key": "tb_sources", "label": "campaign_tb_sources", "value": ""},
            {"key": "formal_top", "label": "campaign_formal_top", "value": ""},
            {"key": "formal_sources", "label": "campaign_formal_sources", "value": ""},
            {"key": "specs", "label": "campaign_specs", "value": ""},
            {"key": "models", "label": "campaign_models", "value": ""},
            {"key": "formal", "label": "engine", "value": "none", "choices": ["none", "formalmc", "vc_formal", "sby"]},
            {"key": "lint", "label": "campaign_lint", "value": "none", "choices": ["none", "verilator", "spyglass", "yosys"]},
            {"key": "max_jobs", "label": "campaign_max_jobs", "value": "40"},
            {"key": "wall_seconds", "label": "campaign_wall_seconds", "value": "7200"},
        ]

        def submit(values):
            """Construct the bounded current contract without inferring a synthesizable top."""
            inputs = {"rtl": {"top": values["rtl_top"], "sources": values["rtl_sources"].split()},
                      "specifications": values["specs"].split(), "reference_models": values["models"].split()}
            if values["tb_top"]:
                inputs["testbench"] = {"top": values["tb_top"], "sources": values["tb_sources"].split()}
            if values["formal_top"]:
                inputs["formal_harness"] = {"top": values["formal_top"], "sources": values["formal_sources"].split()}
            return self.client.call("/campaigns", "POST", {
                "name": values["name"], "project_id": choices[values["project"]]["id"],
                "inputs": inputs, "toolchain": values["toolchain"], "formal_engine": values["formal"],
                "lint_engine": values["lint"], "synthesis_engine": "none", "equivalence_engine": "none",
                "budget_confirmed": True,
                "budget": {"max_jobs": int(values["max_jobs"]), "wall_seconds": int(values["wall_seconds"])}})

        InputDialog(self.app, "campaign_create", "campaign_create_help", fields, submit,
                    lambda result: self.app.show("campaign", result["id"]))


class CampaignView(BaseView):
    """Unify visible gates, exact patch review and recoverable task controls."""

    def __init__(self, parent, app, identifier=None):
        """Build the engineering review workspace using the existing desktop visual system."""
        super().__init__(parent, app, identifier)
        self.data = None
        self.summary = ttk.Label(self, text=tr("loading"), style="Hint.TLabel", wraplength=1050)
        self.summary.pack(fill="x", pady=(0, 14))
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 14))
        for action in ("resume", "pause", "cancel"):
            ActionButton(toolbar, tr("campaign_" + action), lambda name=action: self.transition(name), width=110).pack(side="left", padx=(0, 8))
        ActionButton(toolbar, tr("campaign_approve_stage"), self.approve_stage, variant="primary", width=155).pack(side="right")
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True)
        self.stages = Table(tabs, [("name", "name", 130), ("execution_status", "execution_status", 110),
            ("approval_status", "check_status", 110), ("gate", "campaign_gate", 370),
            ("disabled_reason", "reason", 300)])
        tabs.add(self.stages, text=tr("tab_stages"))
        review = ttk.Frame(tabs)
        tabs.add(review, text=tr("campaign_review"))
        actions = ttk.Frame(review)
        actions.pack(fill="x", pady=8)
        for decision in ("approve", "reject"):
            ActionButton(actions, tr("campaign_" + decision), lambda value=decision: self.review(value), width=160).pack(side="left", padx=6)
        self.proposals = Table(review, [("id", "ID", 210), ("state", "check_status", 170),
            ("protected", "campaign_protected", 150)], height=5,
            on_select=lambda item: self.diff.set(item.get("diff", "") if item else ""))
        self.proposals.pack(fill="x")
        self.diff = TextBox(review, height=15)
        self.diff.pack(fill="both", expand=True, pady=8)
        self.inputs = Table(tabs, [("name", "path", 350), ("sha256", "SHA-256", 650)])
        tabs.add(self.inputs, text=tr("inputs"))
        self.health = Table(tabs, [("feature", "name", 240), ("status", "check_status", 160), ("reason", "reason", 500)])
        tabs.add(self.health, text=tr("toolchains"))

    def refresh(self):
        """Refresh task data and exact per-feature acceptance status asynchronously."""
        def load():
            """Read the current Campaign and configured tool capabilities."""
            return self.client.call("/campaigns/" + segment(self.identifier)), collection(self.client.call("/capabilities"))
        self.app.io(self, load, self.render, self.failed)

    def render(self, data):
        """Keep task progress, verification and PPA labels independent."""
        self.loaded()
        self.data, health = data
        self.summary.configure(text=tr("campaign_summary", name=self.data["name"], state=self.data["state"],
            next_action=self.data["next_action"], jobs=self.data["jobs_used"], limit=self.data["config"]["budget"]["max_jobs"]))
        self.stages.set_rows(self.data["stages"])
        self.proposals.set_rows(self.data["proposals"])
        self.inputs.set_rows([{"name": name, "sha256": digest} for name, digest in self.data["input_hashes"].items()])
        self.health.set_rows([row for row in health if row["toolchain"] == self.data["config"]["toolchain"]])

    def transition(self, action):
        """Send one revision-bound lifecycle action without retrying conflicts."""
        if self.data:
            body = {"revision": self.data["revision"]}
            path = "/campaigns/" + segment(self.identifier) + "/" + action
            self.app.io(self, lambda: self.client.call(path, "POST", body), lambda _: self.refresh(), self.failed)

    def approve_stage(self):
        """Collect a human review note for the selected explicit approval gate."""
        stage = self.stages.selected()
        if not stage or not self.data:
            return
        note = simpledialog.askstring(tr("campaign_approve_stage"), tr("campaign_review_note"), parent=self)
        if note:
            path = "/stages/" + segment(self.identifier + ":" + stage["stage_id"]) + "/approve"
            self.app.io(self, lambda: self.client.call(path, "POST", {"note": note}), lambda _: self.refresh(), self.failed)

    def review(self, decision):
        """Approve for testing or reject; final source integration is never implied."""
        row = self.proposals.selected()
        if not row or not self.data:
            return
        note = simpledialog.askstring(tr("campaign_review"), tr("campaign_review_note"), parent=self)
        if note:
            body = {"fingerprint": self.data["fingerprint"], "note": note}
            path = "/proposals/" + segment(row["id"]) + "/" + decision
            self.app.io(self, lambda: self.client.call(path, "POST", body), lambda _: self.refresh(), self.failed)
