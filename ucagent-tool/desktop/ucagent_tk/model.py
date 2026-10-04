"""Pure Python 3.8-compatible draft validation and non-secret desktop preferences."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile

from .client import ApiError, validate_origin


def lines(value):
    """Split newline-delimited literal fields without corrupting commas inside paths or plusargs."""
    return list(dict.fromkeys(part.strip() for part in value.splitlines() if part.strip()))


def seeds(value):
    """Require every entered seed to be a positive integer without silently dropping tokens."""
    values = [part.strip() for part in re.split(r"[\n,]", value) if part.strip()]
    if not values or any(not re.fullmatch(r"[0-9]+", item) or int(item) < 1 for item in values):
        raise ValueError("Seeds must be positive integers, separated by commas.")
    return list(dict.fromkeys(int(item) for item in values))


def simulation_defaults(methodology):
    """Choose conservative output defaults when switching verification methodology."""
    return {"simulator": "verilator" if methodology == "unitytest" else "vcs", "uvm_version": "1.2", "suites": ["UT"] if methodology == "uvm" else [], "tests": [], "unitytest_tests": [], "seeds": [1], "coverage": [], "waveform": "none", "plusargs": []}


def initial_draft(project, source=None):
    """Copy a saved project or immutable run request without sharing mutable input data."""
    body = source or project.get("run_defaults")
    if not body:
        raise ValueError("This service does not expose project run_defaults. Update the backend before using the desktop client.")
    draft = deepcopy(body)
    draft["project_id"] = project["id"]
    return draft


def formal_toolchains(toolchains, engine):
    """Return configured compatible profiles, keeping license-blocked choices visible."""
    required = {"sby": {"sby", "yosys", "yosys-smtbmc", "z3"}, "vc_formal": {"vcf"}, "formalmc": {"formalmc"}}.get(engine)
    if required is None:
        raise ValueError("Select an explicit supported formal engine.")
    return [item["id"] for item in toolchains if required.issubset({cap.get("name") for cap in item.get("capabilities", [])})]


def validate_draft(draft):
    """Validate desktop-visible scope without weakening the authoritative server preflight."""
    body = deepcopy(draft)
    if not body.get("project_id") or not body.get("toolchain") or not body.get("design", {}).get("top", "").strip():
        raise ValueError("Project, toolchain and design top are required.")
    if body["family"] == "simulation":
        sim = body["simulation"]
        sim["seeds"] = seeds(",".join(str(item) for item in sim["seeds"]))
        if body["methodology"] == "uvm" and not sim["tests"]:
            raise ValueError("Select at least one real UVM test class.")
        if body["methodology"] == "unitytest" and not sim["unitytest_tests"]:
            raise ValueError("Select at least one real pytest file.")
    else:
        if body["formal"]["engine"] == "formalmc":
            scripts = [item for item in body["formal"].get("property_sets", []) if Path(item).suffix.lower() == ".tcl"]
            if len(scripts) != 1:
                raise ValueError("FormalMC requires exactly one entry .tcl in formal.property_sets.")
            if body["formal"].get("clock") or body["formal"].get("reset"):
                raise ValueError("FormalMC clock/reset constraints belong in the Tcl script; leave clock and reset empty.")
        elif body["formal"]["engine"] == "sby":
            options = body["formal"].get("sby") or {}
            if options.get("mode", "prove") not in ("prove", "bmc", "cover"):
                raise ValueError("SBY mode must be prove, bmc, or cover.")
            for key, maximum, default in (("depth", 100000, 40), ("timeout_seconds", 86400, 120)):
                value = options.get(key, default)
                if type(value) is not int or not 1 <= value <= maximum:
                    raise ValueError("SBY {} must be an integer from 1 to {}.".format(key, maximum))
        elif not body["formal"]["clock"].get("signal") or not body["formal"]["reset"].get("signal"):
            raise ValueError("Formal proof requires explicit clock and reset signals.")
    return body


def next_action(run):
    """Map observed results to a next destination without equating failures with tool errors."""
    status = run.get("execution_status")
    result = run.get("verification_status")
    formal = run.get("family") == "formal"
    if status in ("queued", "running"):
        return "action_running", "logs"
    if (run.get("summary") or {}).get("diagnostic_code") == "license_unavailable":
        return "action_license", "jobs"
    if status in ("error", "timeout", "cancelled"):
        return "action_execution", "jobs"
    if result == "failed":
        return ("action_cex", "properties") if formal else ("action_failure", "tests")
    if result == "passed":
        return "action_passed", "coverage" if (run.get("summary") or {}).get("coverage_metrics") else "artifacts"
    return "action_inconclusive", "properties" if formal else "jobs"


class Preferences:
    """Store only a validated origin and bounded event cursors; never credentials."""

    def __init__(self, path=None):
        """Load an optional local preferences file without requiring it for startup."""
        self.path = Path(path) if path else Path.home() / ".ucagent-tk" / "preferences.json"
        self.origin = "http://127.0.0.1:8800"
        self.cursors = {}
        try:
            if self.path.stat().st_size > 128 * 1024:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.origin = validate_origin(data["origin"])
            self.cursors = {key: value for key, value in data.get("cursors", {}).items() if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key) and type(value) is int and value >= 0}
        except (ApiError, OSError, ValueError, KeyError, TypeError, AttributeError):
            self.cursors = {}

    def save(self):
        """Atomically publish the allowlisted non-secret preference fields."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"origin": validate_origin(self.origin), "cursors": dict(list(self.cursors.items())[-500:])}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(self.path.parent), prefix=".preferences-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(self.path))
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink()
