"""Deterministic SBY gates for the existing eleven-stage formal authoring workflow."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading

from ucagent.eda.sby_guided import GuidedSbySession, publish_text, render_environment
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records, save_records
from ucagent.lang.zh.skills.formal.lib.models import AnalysisData, AnalysisEntry, RunResults
from ucagent.util.config import load_runtime_config
from .formal import BaseFormalChecker


class SbyGuidedChecker(BaseFormalChecker):
    """Gate generated properties, execution, review, coverage and signoff using signed runs."""

    def __init__(self, dut_name, phase, **kwargs):
        """Store a bounded stage action; defer workspace and toolchain access to Check."""
        super().__init__(dut_name, **kwargs)
        if phase not in {"property", "script", "environment", "coverage", "evidence", "summary"}:
            raise ValueError("Unsupported guided SBY stage action")
        self.phase = phase
        self._cancel = threading.Event()
        self._executing = False
        self._session = None
        self.last_evidence = None
        self.event_callback = None

    def is_processing(self):
        """Expose an active JobRunner invocation to the stage cancellation command."""
        return self._executing

    def kill(self):
        """Request cancellation of the active job including its solver process tree."""
        self._cancel.set()
        return "SBY job cancellation requested."

    def do_check(self, timeout=0, **kwargs):
        """Generate current inputs and validate actual proof/cover evidence for this stage."""
        self._cancel.clear()
        self.last_evidence = None
        try:
            records = load_records(self.paths.records_yaml)
            generated = render_environment(self.paths, records)
            if self.phase == "property":
                return True, {"message": "Properties and explicit harness rendered; compilation remains a separate gate.", "checkpoints": len(generated["properties"]), "next_action": "Review extra_config.sby and run Check in script_generation."}
            if self._session is None:
                runtime = load_runtime_config(self.workspace)
                options = runtime["runtime_options"]
                if options.get("formal_engine") != "sby":
                    raise ValueError("Restart this workspace with runtime_options.formal_engine=sby")
                self._session = GuidedSbySession.from_host(self.paths, options["formal_toolchain"])
            self._executing = True
            report = self._session.collect(generated, execute=self.phase in {"script", "environment", "coverage"}, cancel_event=self._cancel, on_event=self.event_callback)
            self.last_evidence = report
            self._executing = False
            rows = report["properties"]
            assertions = [p for p in rows if p["kind"] == "assert"]
            covers = [p for p in rows if p["kind"] in {"cover", "guard_witness"}]
            failures = [p["label"] for p in assertions if p["status"] == "falsified"]
            undecided = [p["label"] for p in assertions if p["status"] != "proven" and p["status"] != "falsified"]
            missing_covers = [p["label"] for p in covers if p["status"] != "covered"]
            records.run_results = RunResults(timestamp=datetime.now(timezone.utc).isoformat(), log_hash=hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(), stats={"pass_count": sum(p["status"] == "proven" for p in assertions), "fail_count": len(failures), "tt_count": 0, "cover_pass_count": len(covers) - len(missing_covers), "cover_fail_count": len(missing_covers), "undecided_count": len(undecided)}, failing_properties=failures, tt_properties=[], undecided_properties=undecided)
            if records.analysis is None:
                records.analysis = AnalysisData()
            entries = {e.prop_name: e for e in records.analysis.fa_entries}
            if len(entries) != len(records.analysis.fa_entries) or records.analysis.tt_entries:
                raise ValueError("SBY analysis requires unique fa_entries and empty tt_entries; vacuity is not established by this engine path")
            problems = failures + undecided + missing_covers
            for name in problems:
                if name not in entries:
                    entries[name] = AnalysisEntry(id="FA-" + name, prop_name=name)
            # A current report cannot inherit an old RTL_BUG classification from a prior input version.
            stale = [name for name, entry in entries.items() if name not in problems and entry.resolution == "RTL_BUG"]
            if stale:
                raise ValueError("Review stale RTL_BUG classifications after input changes: " + ", ".join(stale[:12]))
            records.analysis.fa_entries = list(entries.values())
            save_records(self.paths.records_yaml, records)
            from jinja2 import Environment, StrictUndefined

            template_dir = Path(__file__).parents[1] / "lang/zh/skills/formal/lib/templates"
            renderer = Environment(undefined=StrictUndefined, autoescape=False)
            analysis_content = renderer.from_string((template_dir / "sby_analysis.md.j2").read_text(encoding="utf-8")).render(dut=self.paths.dut, report=report, entries=records.analysis.fa_entries)
            publish_text(Path(self.workspace), Path(self.paths.analysis), analysis_content + "\n")
            result = {"execution_status": "completed", "verification_status": report["verification_status"], "coverage": report["coverage"], "evidence": str(Path(self.paths.tests) / "sby_evidence.json"), "message": "Stage work completed; verification_status is the DUT conclusion, not the stage completion flag."}
            if self.phase == "script":
                return True, result
            review = (records.extra_config or {}).get("sby", {}).get("review", {})
            if not isinstance(review, dict) or not isinstance(review.get("assumptions", {}), dict):
                raise ValueError("extra_config.sby.review and review.assumptions must be mappings")
            if review.get("input_sha256") != report["input_sha256"]:
                return self._fail("Review is not bound to the current formal inputs.", details=report["input_sha256"], suggestion="Review current assumptions, property outcomes and limitations, then set extra_config.sby.review.input_sha256 to the current tests/sby_coverage.json input_sha256.", error_code="SBY_REVIEW_VERSION_MISMATCH")
            required_assumptions = {p["label"] for p in rows if p["kind"] == "assume"}
            if generated["options"].reset_policy == "initial":
                required_assumptions.add("M_ENV_RESET")
            assumption_reviews = review.get("assumptions", {})
            if set(assumption_reviews) != required_assumptions or any(not isinstance(v, str) or len(v.strip()) < 12 or "TODO" in v for v in assumption_reviews.values()):
                raise ValueError("Review every current assumption, including M_ENV_RESET, in extra_config.sby.review.assumptions; use exact labels and specification-based reasons")
            if not isinstance(review.get("limitations"), str) or len(review["limitations"].strip()) < 12 or "TODO" in review["limitations"]:
                raise ValueError("Record the unsupported COI, vacuity and liveness scope in extra_config.sby.review.limitations")
            unreviewed = []
            for name in problems:
                entry = entries[name]
                allowed = {"RTL_BUG"} if name in failures else {"INCONCLUSIVE"}
                if entry.resolution not in allowed or len(entry.analysis.strip()) < 12 or "TODO" in entry.analysis:
                    unreviewed.append(name)
            if unreviewed:
                return self._fail("Current property results require analysis.", details=", ".join(unreviewed[:20]), suggestion="Fill analysis.fa_entries: a still-falsified assertion requires RTL_BUG or a real environment fix and rerun; a cover miss or unresolved proof requires INCONCLUSIVE. Do not strengthen assumptions to force Pass.", error_code="SBY_REVIEW_REQUIRED")
            if self.phase == "summary":
                summary = records.summary or {}
                if summary.get("overall_result") != report["verification_status"] or not summary.get("acceptance_conclusion") or not summary.get("core_function"):
                    raise ValueError(f"summary requires core_function, acceptance_conclusion and overall_result={report['verification_status']}")
                if "stats_override" in summary:
                    raise ValueError("summary.stats_override is not accepted; signed tool results determine SBY statistics")
                template = template_dir / "sby_summary.md.j2"
                content = renderer.from_string(template.read_text(encoding="utf-8")).render(dut=self.paths.dut, report=report, summary=summary)
                publish_text(Path(self.workspace), Path(self.paths.summary), content + "\n")
            return True, result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return self._fail(str(exc)[:1600], suggestion="Correct the indicated current input or evidence using Guide_Doc/sby_workflow.md, then run Check again.", error_code="SBY_GUIDED_GATE_FAILED")
        finally:
            self._executing = False
