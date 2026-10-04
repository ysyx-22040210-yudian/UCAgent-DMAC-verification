"""Campaign coordination using the existing SQLite, stages, jobs and signed evidence."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4

from ucagent.eda.input_closure import resolve_vcs_filelist_closure
from ucagent.eda.manifest import canonical_json, sha256_file
from ucagent.eda.security import resolve_within
from ucagent.platform.campaign import CampaignCreate, ProposalCreate


class CampaignConflict(ValueError):
    """Report an optimistic-concurrency, baseline or evidence conflict."""


class CampaignService:
    """Coordinate existing Run/Stage entities without creating another execution engine."""

    def __init__(self, runtime):
        """Extend the same WAL database and pause unfinished campaign coordination."""
        self.runtime = runtime
        self.store = runtime.store
        self.root = runtime.state_dir / "campaigns"
        self.root.mkdir(exist_ok=True)
        with self.store._lock, self.store._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY REFERENCES runs(run_id),
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    name TEXT NOT NULL, config_json TEXT NOT NULL,
                    input_hashes_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    jobs_used INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    state TEXT NOT NULL, turns INTEGER NOT NULL DEFAULT 0,
                    last_job_id TEXT REFERENCES jobs(job_id), updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    state TEXT NOT NULL, request_json TEXT NOT NULL,
                    diff TEXT NOT NULL, candidate_hash TEXT NOT NULL,
                    protected INTEGER NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS campaign_run_links (
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    stage_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id),
                    fingerprint TEXT NOT NULL, PRIMARY KEY(campaign_id, stage_id, run_id));
                CREATE TABLE IF NOT EXISTS coverage_bins (
                    id TEXT NOT NULL, design_hash TEXT NOT NULL, model_hash TEXT NOT NULL,
                    data_json TEXT NOT NULL, PRIMARY KEY(id,design_hash,model_hash));
                CREATE TABLE IF NOT EXISTS coverage_observations (
                    bin_id TEXT NOT NULL, design_hash TEXT NOT NULL, model_hash TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(run_id), test TEXT NOT NULL,
                    seed INTEGER NOT NULL, data_json TEXT NOT NULL,
                    PRIMARY KEY(bin_id,design_hash,model_hash,run_id,test,seed));
                CREATE TABLE IF NOT EXISTS finding_groups (
                    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    data_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ppa_results (
                    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    data_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS campaign_knowledge (
                    id TEXT PRIMARY KEY, tool_version TEXT NOT NULL, source TEXT NOT NULL,
                    sha256 TEXT NOT NULL, content TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS campaign_knowledge_fts
                    USING fts5(id UNINDEXED, content, tool_version UNINDEXED);
                UPDATE campaigns SET state='paused', revision=revision+1
                    WHERE state='running';
                UPDATE agent_sessions SET state='interrupted' WHERE state='running';
            """)

    def capabilities(self):
        """Separate configured executables from genuine feature-specific acceptance."""
        features = {
            "claude_code": ("claude",), "vcs_uvm": ("vcs", "urg"),
            "npi_design": ("npi",), "npi_waveform": ("npi",), "npi_coverage": ("npi",),
            "vc_formal": ("vcf",), "sby": ("sby", "yosys"), "formalmc": ("formalmc",),
            "lint_spyglass": ("spyglass",), "lint_verilator": ("verilator",),
            "synthesis_dc": ("dc",), "synthesis_yosys": ("yosys",),
            "equivalence_formality": ("formality",), "equivalence_eqy": ("eqy",),
        }
        rows = []
        for profile in self.runtime._profiles.values():
            for name, aliases in features.items():
                missing = [alias for alias in aliases if alias not in profile.tools]
                rows.append({"id": profile.id + ":" + name, "toolchain": profile.id,
                             "feature": name, "status": "pending_acceptance",
                             "configured": not missing, "missing_tools": missing,
                             "reason": "tool_alias_not_configured" if missing else "real_feature_evidence_required",
                             "evidence": []})
        return {"items": rows, "count": len(rows), "acceptance_complete": False}

    def snapshot_inputs(self, project_root: Path, config: CampaignCreate):
        """Resolve bounded concrete source closure and hash files, never imported hooks."""
        paths = set(config.inputs.specifications + config.inputs.reference_models + config.inputs.constraints)
        for inputs in (config.inputs.rtl, config.inputs.testbench, config.inputs.formal_harness):
            if inputs is None:
                continue
            closure = resolve_vcs_filelist_closure(project_root,
                sources=map(Path, inputs.sources), filelists=map(Path, inputs.filelists),
                include_dirs=map(Path, inputs.include_dirs))
            if not closure.complete:
                raise ValueError("Campaign requires a complete static source closure; resolve dynamic filelist inputs first")
            paths.update(path.as_posix() for path in (*closure.sources, *closure.filelists, *closure.includes))
        if not paths or len(paths) > 10000:
            raise ValueError("Campaign input closure must contain between 1 and 10000 files")
        hashes, size = {}, 0
        for name in sorted(paths):
            if any(part.startswith(".") for part in Path(name).parts):
                raise ValueError("Campaign source closure must not include hidden execution configuration")
            path = resolve_within(project_root, name, must_exist=True, allow_root=False)
            if not path.is_file() or (project_root / name).is_symlink():
                raise ValueError("Campaign inputs must be regular files without symbolic links")
            size += path.stat().st_size
            if size > config.budget.max_candidate_bytes:
                raise ValueError("Campaign input snapshot exceeds the approved candidate byte budget")
            hashes[name] = sha256_file(path)
        fingerprint = hashlib.sha256(canonical_json({"inputs": config.inputs.model_dump(mode="json"),
                                                   "hashes": hashes})).hexdigest()
        return hashes, fingerprint

    def create(self, request: CampaignCreate):
        """Freeze explicit inputs and create the complete gated stage DAG without EDA dispatch."""
        project = self.store.get_project(request.project_id)
        if project is None:
            raise ValueError("Project not found")
        if request.toolchain not in self.runtime._profiles:
            raise ValueError("Administrator toolchain profile not found")
        source_root = Path(project["source_root"])
        hashes, fingerprint = self.snapshot_inputs(source_root, request)
        identifier = uuid4().hex
        destination = self.root / identifier / "baseline"
        destination.mkdir(parents=True)
        for name, digest in hashes.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(resolve_within(source_root, name, must_exist=True), target)
            if sha256_file(target) != digest:
                raise CampaignConflict("Input changed while freezing the baseline; create a fresh campaign")
        snapshot = request.model_dump(mode="json")
        self.store.create_run(project_id=request.project_id, workflow="campaign", adapter="campaign",
                              request=snapshot, run_id=identifier)
        now = time.time()
        with self.store._lock, self.store._connection() as db:
            db.execute("INSERT INTO campaigns(id,project_id,name,config_json,input_hashes_json,fingerprint,state,created_at,updated_at) VALUES(?,?,?,?,?,?,'paused',?,?)",
                       (identifier, request.project_id, request.name, json.dumps(snapshot), json.dumps(hashes), fingerprint, now, now))
        definitions = (
            ("specification", True, "approve_specification_and_inputs", True),
            ("authoring", True, "review_candidate_sources_and_compile_evidence", False),
            ("static", request.lint_engine != "none", "selected_static_tool_report", False),
            ("simulation", request.inputs.testbench is not None, "signed_simulation_results", False),
            ("formal", request.formal_engine != "none", "selected_engine_properties_and_constraint_review", False),
            ("coverage", request.inputs.testbench is not None, "versioned_per_test_coverage_and_frozen_targets", False),
            ("debug", True, "review_failures_and_source_waveform_evidence", False),
            ("synthesis", request.synthesis_engine != "none", "real_library_corner_and_constraint_reports", False),
            ("equivalence", request.equivalence_engine != "none", "semantic_optimization_equivalence_evidence", False),
            ("ppa_targets", request.synthesis_engine != "none", "approve_targets_after_measured_baseline", True),
            ("signoff", True, "all_enabled_gates_and_final_integration_approval", True),
        )
        stages = []
        previous = None
        for name, enabled, gate, approval in definitions:
            stages.append({"id": name, "name": name, "enabled": enabled,
                           "disabled_reason": None if enabled else "not_selected_in_campaign_configuration",
                           "requires_human_approval": approval, "gate": gate,
                           "depends_on": [previous] if previous else [],
                           "next_action": gate, "verification_status": "unknown"})
            if enabled:
                previous = name
        self.store.replace_run_stages(identifier, stages)
        self.store.append_event(identifier, "campaign.created", {"fingerprint": fingerprint})
        return self.get(identifier)

    def get(self, identifier):
        """Return persisted state, explicit blockers and the complete shared stage projection."""
        with self.store._lock, self.store._connection() as db:
            row = db.execute("SELECT * FROM campaigns WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Campaign not found")
        data = dict(row)
        data["config"] = json.loads(data.pop("config_json"))
        data["input_hashes"] = json.loads(data.pop("input_hashes_json"))
        data["stages"] = self.store.list_run_stages(identifier)
        data["proposals"] = self.proposals(identifier)
        pending = [stage for stage in data["stages"] if stage["enabled"] and stage["execution_status"] != "completed"]
        data["next_action"] = pending[0].get("next_action") if pending else "review_final_evidence"
        data["verification_status"] = (self.store.get_run(identifier) or {}).get("verification_status", "unknown")
        data["ppa_status"] = "awaiting_target_approval"
        return data

    def list(self):
        """List bounded persisted campaign summaries including restart-paused tasks."""
        with self.store._lock, self.store._connection() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM campaigns ORDER BY created_at DESC LIMIT 200")]
        return {"items": [self.get(identifier) for identifier in ids], "count": len(ids)}

    def verify_baseline(self, campaign):
        """Fail on any source or snapshot change before approval, resume or dispatch."""
        project = self.store.get_project(campaign["project_id"])
        hashes, fingerprint = self.snapshot_inputs(Path(project["source_root"]), CampaignCreate.model_validate(campaign["config"]))
        if hashes != campaign["input_hashes"] or fingerprint != campaign["fingerprint"]:
            raise CampaignConflict("Project inputs changed; review differences and create a new campaign baseline")
        for name, digest in hashes.items():
            if sha256_file(self.root / campaign["id"] / "baseline" / name) != digest:
                raise CampaignConflict("Frozen baseline was modified; do not reuse its evidence")

    def transition(self, identifier, action, revision):
        """Apply revision-checked pause/resume/cancel and preserve verification conclusions."""
        with self.store._lock:
            campaign = self.get(identifier)
            if campaign["revision"] != revision:
                raise CampaignConflict("Campaign revision changed; refresh before retrying")
            permitted = {"pause": {"running"}, "resume": {"paused", "attention"},
                         "cancel": {"paused", "attention", "running"}}
            if action not in permitted or campaign["state"] not in permitted[action]:
                raise CampaignConflict("Campaign transition is not allowed in the current state")
            if action == "resume":
                self.verify_baseline(campaign)
                if campaign["stages"][0]["approval_status"] != "approved":
                    raise CampaignConflict("Approve the specification stage before resuming")
                if campaign["jobs_used"] >= campaign["config"]["budget"]["max_jobs"]:
                    raise CampaignConflict("Campaign job budget is exhausted")
            state = {"pause": "paused", "resume": "running", "cancel": "cancelled"}[action]
            with self.store._connection() as db:
                changed = db.execute("UPDATE campaigns SET state=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?",
                                     (state, time.time(), identifier, revision)).rowcount
                if not changed:
                    raise CampaignConflict("Concurrent campaign transition; refresh before retrying")
            if action in {"pause", "cancel"}:
                with self.store._connection() as db:
                    linked = [row[0] for row in db.execute("SELECT run_id FROM campaign_run_links WHERE campaign_id=?", (identifier,))]
                for run_id in linked:
                    run = self.store.get_run(run_id)
                    if run and run["execution_status"] in {"running", "queued"}:
                        self.runtime.cancel_run(run_id)
            self.store.append_event(identifier, "campaign." + action, {"revision": revision + 1})
            return self.get(identifier)

    def stage_action(self, identifier, stage_id, action, note):
        """Reuse human approvals while refusing to let approval replace deterministic gates."""
        with self.store._lock:
            campaign = self.get(identifier)
            self.verify_baseline(campaign)
            stage = next((row for row in campaign["stages"] if row["stage_id"] == stage_id), None)
            if stage is None or not stage["enabled"] or not stage.get("requires_human_approval"):
                raise CampaignConflict("The requested stage is not an enabled human gate")
            if action not in {"approve", "reject"} or not note.strip():
                raise ValueError("Human approval requires an explicit decision and review note")
            if stage["approval_status"] != "pending":
                raise CampaignConflict("This stage already has a human decision")
            if stage_id != "specification":
                raise CampaignConflict("This gate requires current signed measurements and all predecessor checks; unavailable evidence cannot be approved")
            self.store.add_stage_action(identifier, stage_id, action, note)
            self.store.update_stage_approval(identifier, stage_id, "approved" if action == "approve" else "rejected")
            if action == "approve":
                self.store.update_stage_execution(identifier, stage_id, "completed")
            return self.get(identifier)

    def propose(self, request: ProposalCreate):
        """Publish an isolated candidate/diff without writing the imported source project."""
        with self.store._lock:
            campaign = self.get(request.campaign_id)
            self.verify_baseline(campaign)
            if request.base_fingerprint != campaign["fingerprint"]:
                raise CampaignConflict("Proposal baseline differs from the frozen campaign input")
            if campaign["state"] == "cancelled":
                raise CampaignConflict("Cancelled campaigns cannot accept proposals")
            with self.store._connection() as db:
                count = db.execute("SELECT count(*) FROM proposals WHERE campaign_id=?", (request.campaign_id,)).fetchone()[0]
            if count >= campaign["config"]["budget"]["iterations_per_stage"]:
                raise CampaignConflict("Automatic proposal budget exhausted; human review is required")
            rtl = set(campaign["config"]["inputs"]["rtl"]["sources"])
            protected = any(item.path not in rtl for item in request.changes)
            identifier = uuid4().hex
            baseline = self.root / request.campaign_id / "baseline"
            candidate = self.root / request.campaign_id / "candidates" / identifier
            edits, diff, total = {}, [], 0
            for change in request.changes:
                if campaign["input_hashes"].get(change.path) != change.before_sha256:
                    raise CampaignConflict("Proposal file is not an exact frozen input: " + change.path)
                original = resolve_within(baseline, change.path, must_exist=True).read_text(encoding="utf-8")
                if original == change.content:
                    raise ValueError("Proposal contains an unchanged file: " + change.path)
                edits[change.path] = change.content
                total += len(change.content.encode("utf-8"))
                diff.extend(difflib.unified_diff(original.splitlines(True), change.content.splitlines(True),
                                               fromfile="a/" + change.path, tofile="b/" + change.path))
            if total > campaign["config"]["budget"]["max_candidate_bytes"]:
                raise ValueError("Candidate exceeds approved byte budget")
            shutil.copytree(baseline, candidate)
            for name, content in edits.items():
                (candidate / name).write_text(content, encoding="utf-8", newline="")
            hashes = {name: sha256_file(candidate / name) for name in campaign["input_hashes"]}
            candidate_hash = hashlib.sha256(canonical_json(hashes)).hexdigest()
            with self.store._connection() as db:
                db.execute("INSERT INTO proposals VALUES(?,?,'pending',?,?,?,?,?)",
                           (identifier, request.campaign_id, request.model_dump_json(), "".join(diff), candidate_hash, int(protected), time.time()))
            self.store.append_event(request.campaign_id, "proposal.created", {"proposal_id": identifier, "protected": protected})
            return self.proposals(request.campaign_id)[-1]

    def proposals(self, campaign_id):
        """Return bounded reviewable patches, never falsely labeled as validated fixes."""
        with self.store._lock, self.store._connection() as db:
            rows = db.execute("SELECT * FROM proposals WHERE campaign_id=? ORDER BY created_at", (campaign_id,)).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            data["request"] = json.loads(data.pop("request_json"))
            data["protected"] = bool(data["protected"])
            data["verification_status"] = "unknown"
            results.append(data)
        return results

    def review_proposal(self, identifier, decision, fingerprint, note):
        """Approve only an unchanged candidate for testing; never silently integrate it."""
        with self.store._lock, self.store._connection() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("Proposal not found")
            campaign = self.get(row["campaign_id"])
            self.verify_baseline(campaign)
            if row["state"] != "pending" or fingerprint != campaign["fingerprint"]:
                raise CampaignConflict("Proposal state or baseline changed; refresh the review")
            if not note.strip() or decision not in {"approve", "reject"}:
                raise ValueError("Proposal review requires an explicit decision and note")
            candidate = self.root / campaign["id"] / "candidates" / identifier
            hashes = {name: sha256_file(resolve_within(candidate, name, must_exist=True)) for name in campaign["input_hashes"]}
            if hashlib.sha256(canonical_json(hashes)).hexdigest() != row["candidate_hash"]:
                raise CampaignConflict("Candidate changed after submission; submit a new proposal")
            db.execute("UPDATE proposals SET state=? WHERE id=?", ("approved_for_testing" if decision == "approve" else "rejected", identifier))
        self.store.add_stage_action(campaign["id"], "proposal-" + identifier, decision, note)
        self.store.append_event(campaign["id"], "proposal.reviewed", {"proposal_id": identifier, "decision": decision})
        return {"id": identifier, "state": "approved_for_testing" if decision == "approve" else "rejected",
                "integrated": False, "verification_status": "unknown"}
