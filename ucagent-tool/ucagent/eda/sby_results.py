"""Normalize fresh SBY status and JUnit evidence without trusting console prose."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from .models import ExecutionStatus, VerificationStatus, FormalProperty, FormalPropertyStatus
from .parsers import ParsedOutput
from .security import resolve_within


def parse_sby_results(session: Path, *, mode: str, depth: int, return_code: int) -> ParsedOutput:
    """Cross-check status, process exit and typed properties in an isolated proof directory.

    BMC PASS is bounded evidence, never an unbounded proof. A cover miss is not
    an assertion defect. Only a trace explicitly linked by SBY belongs to a
    property; the presence of an arbitrary VCD never proves reproduction.
    """
    result = ParsedOutput(execution_status=ExecutionStatus.ERROR, verification_status=VerificationStatus.UNKNOWN)
    try:
        proof = resolve_within(session, "proof", must_exist=True)
        status_path = resolve_within(proof, "status", must_exist=True)
        if status_path.stat().st_size > 1024:
            raise ValueError("SBY status exceeds its size limit")
        fields = status_path.read_text(encoding="utf-8").split()
        if len(fields) != 3 or fields[0] not in {"PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT"}:
            raise ValueError("SBY status must contain outcome, return code and runtime")
        status, status_code, runtime = fields[0], int(fields[1]), float(fields[2])
        if runtime < 0 or runtime != runtime or runtime == float("inf"):
            raise ValueError("SBY runtime is invalid")
        if status_code != return_code or (status == "PASS" and return_code != 0):
            raise ValueError("SBY status and process exit disagree")
        reports = list(proof.glob("*.xml"))
        if len(reports) != 1:
            raise ValueError("SBY must produce exactly one JUnit report")
        report = resolve_within(session, reports[0], must_exist=True)
        if report.stat().st_size > 16 * 1024**2:
            raise ValueError("SBY JUnit report exceeds 16 MiB")
        content = report.read_bytes()
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            raise ValueError("SBY JUnit must not contain DTDs or entities")
        suites = ET.fromstring(content).findall("testsuite")
        if len(suites) != 1:
            raise ValueError("SBY JUnit must contain exactly one task")
        suite = suites[0]
        declared = suite.find("properties/property[@name='status']")
        if declared is None or declared.get("value") != status:
            raise ValueError("SBY JUnit and status file disagree")
        if status in {"ERROR", "TIMEOUT"}:
            result.execution_status = ExecutionStatus.TIMEOUT if status == "TIMEOUT" else ExecutionStatus.ERROR
            result.diagnostics.append({"error_code": "sby_" + status.lower(), "error": "SBY could not finish verification.", "next_action": "Inspect proof/logfile.txt for RTL, solver or resource errors."})
            return result
        checks = [check for check in suite.findall("testcase")
                  if check.get("type", "").lower() in {"assert", "cover"}]
        display_counts = {}
        for check in checks:
            display = check.get("name") or check.get("id")
            display_counts[display] = display_counts.get(display, 0) + 1
        names: set[str] = set()
        for check in checks:
            kind = check.get("type", "").lower()
            if kind not in {"assert", "cover"}:
                continue
            name = check.get("name") or check.get("id")
            # Generate instances may share location-based display names, but
            # their witness IDs identify separate obligations. Keep all of them.
            if name and display_counts[name] > 1 and check.get("id"):
                name += " [" + check.get("id") + "]"
            if not name or name in names:
                raise ValueError("SBY properties must have nonempty unique identities")
            names.add(name)
            failed = check.find("failure") is not None
            unknown = check.find("skipped") is not None or check.find("error") is not None
            if kind == "cover":
                state = FormalPropertyStatus.INCONCLUSIVE if unknown else FormalPropertyStatus.UNCOVERED if failed else FormalPropertyStatus.COVERED
            else:
                state = FormalPropertyStatus.FALSIFIED if failed else FormalPropertyStatus.INCONCLUSIVE if unknown or mode == "bmc" else FormalPropertyStatus.PROVEN
            details = {"kind": kind, "mode": mode, "property_id": check.get("id"), "location": check.get("location"), "bounded_depth": depth if mode == "bmc" else None}
            # UNKNOWN may contain a failed induction step from unreachable state.
            # It is evidence of an incomplete proof, not a reachable DUT failure.
            if status == "UNKNOWN" and failed:
                state = FormalPropertyStatus.INCONCLUSIVE
                details["unproven_failure_trace"] = True
            if kind != ("cover" if mode == "cover" else "assert"):
                state = FormalPropertyStatus.DISABLED
                details["disabled_reason"] = "This property kind is outside the selected SBY mode."
            trace = check.get("tracefile")
            cex = None
            if trace:
                path = resolve_within(proof, trace, must_exist=False)
                if path.suffix != ".vcd":
                    path = path.with_suffix(".vcd")
                path = resolve_within(proof, path, must_exist=True)
                if not path.is_file():
                    raise ValueError("SBY trace is not a regular file")
                details["trace_path"] = path.relative_to(session).as_posix()
                if state == FormalPropertyStatus.FALSIFIED:
                    cex = path.relative_to(session)
            result.properties.append(FormalProperty(name=name, status=state, runtime_seconds=runtime, engine="sby/smtbmc/z3", counterexample_path=cex, evidence_path=report.relative_to(session), details=details))
        relevant = [p for p in result.properties if p.details["kind"] == ("cover" if mode == "cover" else "assert")]
        if not relevant:
            raise ValueError("SBY produced no individually identified properties for the selected mode")
        if status == "PASS" and any(p.status in {FormalPropertyStatus.FALSIFIED, FormalPropertyStatus.UNCOVERED} for p in relevant):
            raise ValueError("SBY PASS contradicts its property results")
        if status == "FAIL" and not any(p.status in {FormalPropertyStatus.FALSIFIED, FormalPropertyStatus.UNCOVERED} for p in relevant):
            raise ValueError("SBY FAIL has no failed assertion or uncovered target")
        result.execution_status = ExecutionStatus.COMPLETED
        if any(p.status == FormalPropertyStatus.FALSIFIED for p in relevant):
            result.verification_status = VerificationStatus.FAILED
        elif status == "PASS" and mode != "bmc" and all(p.status in {FormalPropertyStatus.PROVEN, FormalPropertyStatus.COVERED} for p in relevant):
            result.verification_status = VerificationStatus.PASSED
        else:
            result.verification_status = VerificationStatus.INCONCLUSIVE
        if mode == "bmc" and status == "PASS":
            result.diagnostics.append({"error_code": "bounded_check_passed", "error": f"No counterexample found within depth {depth}; this is not an unbounded proof.", "next_action": "Select prove mode for an unbounded safety proof."})
    except (OSError, ValueError, ET.ParseError) as exc:
        result.properties = []
        result.diagnostics.append({"error_code": "sby_evidence_invalid", "error": str(exc)[:1000], "next_action": "Inspect the fresh SBY status and JUnit report; rerun without reusing old outputs."})
    return result
