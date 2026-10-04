"""Render and attest native-SBY jobs from the original FG/FC/CK formal records."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from uuid import uuid4

import yaml
from pydantic import Field

from .adapters.sby import SbyAdapter
from .manifest import canonical_json, verify_manifest
from .models import StrictModel, ToolchainProfile
from .runner import JobRunner
from .security import resolve_within


class GuidedSbyOptions(StrictModel):
    """Bound generated native-Yosys harnesses; reviews are not execution inputs."""

    sources: list[str] = Field(min_length=1)
    filelists: list[str] = Field(default_factory=list)
    include_dirs: list[str] = Field(default_factory=list)
    defines: list[str] = Field(default_factory=list)
    mode: str = Field(default="prove", pattern="^(prove|bmc)$")
    depth: int = Field(default=40, ge=1, le=100000, strict=True)
    timeout_seconds: int = Field(default=120, ge=1, le=86400, strict=True)
    reset_policy: str = Field(pattern="^(none|initial|unconstrained)$")
    reset_active: int | None = Field(default=None, ge=0, le=1, strict=True)
    reset_cycles: int | None = Field(default=None, ge=1, le=1024, strict=True)


def publish_text(workspace: Path, path: Path, content: str) -> None:
    """Atomically publish a derived workspace artifact without following escaping links."""
    target = resolve_within(workspace, path, must_exist=False, allow_root=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".formal-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def expression(value: str) -> str:
    """Accept an HDL expression, never procedural code or full concurrent-SVA syntax."""
    if not isinstance(value, str) or not value.strip() or len(value) > 16384:
        raise ValueError("Each SBY property, guard and trigger requires a bounded HDL expression")
    value = value.strip()
    if re.search(r';|`|@|"|//|/\*|\*/|##|\|->|\|=>|\b(property|endproperty|begin|end|assert|assume|cover|s_eventually)\b', value):
        raise ValueError("Native SBY requires an expression without semicolons, concurrent SVA, statements or directives; see Guide_Doc/sby_workflow.md")
    if "TODO" in value or "Not implemented" in value:
        raise ValueError("Replace the SBY expression placeholder with a specification-derived check")
    return value


def identifier(value: str) -> str:
    """Validate literal identifiers before embedding them into generated HDL."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) or value.startswith("uc_"):
        raise ValueError("HDL names must be literal identifiers outside the reserved uc_ namespace")
    return value


def render_environment(paths, records) -> dict:
    """Generate a single-clock or combinational harness with explicit reset semantics."""
    workspace = Path(paths.workspace)
    if records is None or records.dut != paths.dut or records.spec is None:
        raise ValueError("Create matching dut and spec in .formal_records.yaml before generating properties")
    basic = records.basic_info or {}
    if not isinstance(basic.get("ports"), dict) or not isinstance(basic.get("clock_reset"), dict):
        raise ValueError("basic_info.ports and basic_info.clock_reset must be mappings")
    raw_options = dict((records.extra_config or {}).get("sby", {}))
    raw_options.pop("review", None)
    options = GuidedSbyOptions.model_validate(raw_options)
    if records.spec.whitebox_signals:
        raise ValueError("Guided native SBY does not support hierarchical whitebox exports; supply a reviewed explicit harness through the native SBY run interface")
    ports = []
    for direction, group in (("input", "inputs"), ("output", "outputs")):
        declared = basic["ports"].get(group, [])
        if not isinstance(declared, list) or any(not isinstance(p, dict) for p in declared):
            raise ValueError("Each basic_info.ports group must be a list of port mappings")
        for port in declared:
            name = identifier(port["name"])
            width = port["width"]
            if type(width) is not int or not 1 <= width <= 1048576:
                raise ValueError(f"{name}: basic_info.ports width must be a resolved positive integer")
            ports.append({"name": name, "width": width, "direction": direction})
    names = [port["name"] for port in ports]
    if not ports or len(set(names)) != len(names):
        raise ValueError("basic_info.ports must contain a nonempty complete interface with unique names")
    clock_reset = basic.get("clock_reset") or {}
    if not {"clock_signal", "reset_signal"} <= clock_reset.keys():
        raise ValueError("Explicitly declare clock_signal and reset_signal; use empty strings for absent ports")
    clock, reset = clock_reset["clock_signal"], clock_reset["reset_signal"]
    inputs = {port["name"] for port in ports if port["direction"] == "input"}
    for name in (clock, reset):
        if name and (name not in inputs or next(port["width"] for port in ports if port["name"] == name) != 1):
            raise ValueError("Clock and reset must name declared scalar input ports")
    edge = clock_reset.get("clock_edge")
    if clock and (edge not in {"posedge", "negedge"} or clock_reset.get("clock_count") not in {1, "1"}):
        raise ValueError("Guided SBY requires one explicitly declared clock and clock_edge; use native harness mode for multiple clocks")
    if options.reset_policy == "none":
        if reset or options.reset_active is not None or options.reset_cycles is not None:
            raise ValueError("reset_policy=none requires no reset port or reset parameters")
    elif not reset or not clock or options.reset_active is None:
        raise ValueError("Reset modeling requires a clock, reset port and explicit reset_active (0 or 1)")
    if options.reset_policy == "initial" and options.reset_cycles is None:
        raise ValueError("Initial reset requires reset_cycles; signal names never determine reset polarity")
    if options.reset_policy != "initial" and options.reset_cycles is not None:
        raise ValueError("reset_cycles is valid only for reset_policy=initial")
    params = records.spec.parameters or {}
    parameter_text = []
    for name, value in params.items():
        identifier(name)
        if not re.fullmatch(r"-?[0-9]+", str(value)):
            raise ValueError("Guided SBY parameters require resolved integer values")
        parameter_text.append(f"parameter {name} = {value}")
    parameter_header = " #( " + ", ".join(parameter_text) + " )" if params else ""
    parameter_bind = " #( " + ", ".join(f".{name}({value})" for name, value in params.items()) + " )" if params else ""
    declarations = {p["name"]: (f"[{p['width'] - 1}:0] " if p["width"] > 1 else "") + p["name"] for p in ports}
    checker = [f"module {paths.dut}_checker{parameter_header} (", ",\n".join("  input wire " + declarations[p["name"]] for p in ports), ");"]
    if clock:
        checker.extend(["reg uc_past_valid = 1'b0;", f"always @({edge} {clock}) uc_past_valid <= 1'b1;"])
    properties = []
    labels = set()
    for fg in records.spec.function_groups:
        for fc in fg.functions:
            for ck in fc.check_points:
                if not re.fullmatch(r"CK-[A-Za-z0-9_-]+", ck.id):
                    raise ValueError("Each checkpoint requires a literal CK- identifier")
                style = ck.style.lower()
                kind = {"comb": "assert", "seq": "assert", "cover": "cover", "assume": "assume"}.get(style)
                if kind is None or (style == "seq" and not clock):
                    raise ValueError(f"{ck.id}: unsupported style or sequential check without a clock")
                label = {"assert": "A_", "cover": "C_", "assume": "M_"}[kind] + ck.id.replace("-", "_")
                if label in labels:
                    raise ValueError(f"Duplicate or colliding checkpoint identifier: {ck.id}")
                labels.add(label)
                body, guard, trigger = expression(ck.sva_body), expression(ck.sby_guard), expression(ck.sby_trigger)
                if kind == "assert" and body.lower() in {"1", "1'b1", "1'h1", "1'd1", "true"}:
                    raise ValueError(f"{ck.id}: replace a constant-true assertion with a real specification check")
                clocked = bool(clock and style != "comb")
                if not clocked and re.search(r"\$(past|stable|rose|fell)|uc_past_valid", body + guard + trigger):
                    raise ValueError(f"{ck.id}: sampled-value functions require a clocked checkpoint")
                event = f"@({edge} {clock})" if clocked else "@*"
                checker.append(f"always {event} begin\n  if ({guard}) {label}: {kind} ({body});\nend")
                properties.append({"fg": fg.id, "fc": fc.id, "ck": ck.id, "label": label, "kind": kind})
                if kind == "assert":
                    witness = "G_" + label
                    checker.append(f"always {event} begin\n  {witness}: cover (({guard}) && ({trigger}));\nend")
                    properties.append({"fg": fg.id, "fc": fc.id, "ck": ck.id, "label": witness, "kind": "guard_witness"})
    if not any(p["kind"] == "assert" for p in properties) or not any(p["kind"] == "cover" for p in properties):
        raise ValueError("Define at least one assertion and one explicit reachability Cover checkpoint")
    checker.append("endmodule\n")
    wrapper = [f"module {paths.dut}_wrapper (", ",\n".join("  input wire " + declarations[p["name"]] for p in ports if p["direction"] == "input"), ");"]
    wrapper.extend("wire " + declarations[p["name"]] + ";" for p in ports if p["direction"] == "output")
    connections = ", ".join(f".{name}({name})" for name in names)
    wrapper.extend([f"{paths.dut}{parameter_bind} u_dut ({connections});", f"{paths.dut}_checker{parameter_bind} u_checker ({connections});"])
    if options.reset_policy == "initial":
        cycles = options.reset_cycles
        wrapper.extend([f"reg [{cycles.bit_length() - 1}:0] uc_reset_count = 0;", f"always @({edge} {clock}) begin", f"  if (uc_reset_count < {cycles}) uc_reset_count <= uc_reset_count + 1'b1;", f"  M_ENV_RESET: assume ({reset} == ((uc_reset_count < {cycles}) ? 1'b{options.reset_active} : 1'b{1 - options.reset_active}));", "end"])
    wrapper.append("endmodule\n")
    checker_text, wrapper_text = "\n".join(checker), "\n".join(wrapper)
    publish_text(workspace, Path(paths.checker), checker_text)
    publish_text(workspace, Path(paths.wrapper), wrapper_text)
    snapshot = {"schema_version": 1, "dut": paths.dut, "basic_info": basic, "spec": records.spec.model_dump(), "sby": options.model_dump(), "properties": properties}
    snapshot_path = Path(paths.tests) / "sby_inputs.json"
    snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    publish_text(workspace, snapshot_path, snapshot_text)
    hashes = {path.relative_to(workspace).as_posix(): hashlib.sha256(content.encode("utf-8")).hexdigest() for path, content in ((Path(paths.checker), checker_text), (Path(paths.wrapper), wrapper_text), (snapshot_path, snapshot_text))}
    return {"options": options, "properties": properties, "ports": ports, "snapshot": snapshot_path, "hashes": hashes}


class GuidedSbySession:
    """Reuse JobRunner manifests for resumable proof and cover under one guided session."""

    def __init__(self, paths, profile: ToolchainProfile, key: bytes):
        """Bind a workspace to host-owned execution settings and a private signing key."""
        self.paths, self.profile, self.key = paths, profile, key
        self.workspace = Path(paths.workspace)
        self.runner = JobRunner(key)
        self.index = Path(paths.tests) / "sby_evidence.json"

    @classmethod
    def from_host(cls, paths, profile_id: str):
        """Read only the selected administrator profile; never persist its environment."""
        directory = Path.home() / ".ucagent"
        config_path = directory / "toolchains.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        values = dict(config["profiles"][profile_id])
        values["id"] = profile_id
        profile = ToolchainProfile.model_validate(values)
        for alias in SbyAdapter.required_tools:
            profile.require_tool(alias)
        key_path = directory / "formal-manifest.key"
        if key_path.is_symlink():
            raise ValueError("The host formal signing key must not be a symbolic link")
        try:
            descriptor = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(secrets.token_bytes(32))
        key = key_path.read_bytes()
        if len(key) != 32 or (os.name != "nt" and key_path.stat().st_mode & 0o077):
            raise ValueError("The host formal signing key requires 32 bytes and owner-only permissions")
        return cls(paths, profile, key)

    def collect(self, generated: dict, *, execute: bool, cancel_event=None, on_event=None) -> dict:
        """Verify exact current evidence, or run both proof and cover when explicitly requested."""
        options = generated["options"]
        # Bind reuse to the entire host profile without exposing secret environment values.
        profile_digest = hmac.new(self.key, canonical_json(self.profile.model_dump(mode="json")), hashlib.sha256).hexdigest()
        manifests = {}
        try:
            index_path = resolve_within(self.workspace, self.index, must_exist=True)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for mode in (options.mode, "cover"):
                path = resolve_within(self.workspace, index["manifests"][mode], must_exist=True)
                manifest = verify_manifest(path, self.key, workspace=self.workspace)
                required_inputs = {generated["snapshot"].relative_to(self.workspace).as_posix(), Path(self.paths.checker).relative_to(self.workspace).as_posix(), Path(self.paths.wrapper).relative_to(self.workspace).as_posix()}
                if (manifest["metadata"].get("guided_profile") != profile_digest or manifest["metadata"].get("mode") != mode or manifest["execution_status"] != "completed" or not required_inputs <= manifest["input_hashes"].keys()):
                    raise ValueError("Guided evidence has a different profile/mode or incomplete execution")
                if any(manifest["input_hashes"][name] != digest for name, digest in generated["hashes"].items()):
                    raise ValueError("Guided evidence does not match the generated property contract")
                manifests[mode] = (path, manifest)
        except (OSError, ValueError, KeyError, TypeError):
            if not execute:
                raise ValueError("Current signed SBY evidence is absent, stale or invalid; run Check in script_generation or environment_debugging_iteration")
            manifests = {}
        if not manifests:
            adapter = SbyAdapter()
            for mode in (options.mode, "cover"):
                run_id = "sby-" + uuid4().hex
                plan = adapter.prepare(workspace=self.workspace, top=self.paths.dut + "_wrapper", sources=[Path(item) for item in options.sources] + [Path(self.paths.checker).relative_to(self.workspace), Path(self.paths.wrapper).relative_to(self.workspace)], filelists=[Path(p) for p in options.filelists], include_dirs=[Path(p) for p in options.include_dirs], defines=options.defines, mode=mode, depth=options.depth, timeout_seconds=options.timeout_seconds, inspect_design=True)
                config_path = Path(self.paths.tests).relative_to(self.workspace) / f"{mode}.sby"
                publish_text(self.workspace, config_path, plan.content)
                request = adapter.build_formal_request(workspace=self.workspace, output_dir=Path(self.paths.tests).relative_to(self.workspace) / "sby_runs" / run_id, config_path=config_path, plan=plan, mode=mode, depth=options.depth, timeout_seconds=options.timeout_seconds, run_id=run_id)
                request.input_paths.append(generated["snapshot"].relative_to(self.workspace))
                request.prepared_input_hashes.update(generated["hashes"])
                request.metadata["guided_profile"] = profile_digest
                result = self.runner.run(request, self.profile, cancel_event=cancel_event, on_event=on_event)
                if result.execution_status.value != "completed":
                    raise ValueError(f"SBY {mode} execution {result.execution_status.value}; inspect {request.output_dir}/manifest.json diagnostics (not a DUT failure)")
                path = self.workspace / request.output_dir / "manifest.json"
                manifest = verify_manifest(path, self.key, workspace=self.workspace)
                manifests[mode] = (path, manifest)
            publish_text(self.workspace, self.index, json.dumps({"schema_version": 1, "engine": "sby", "manifests": {mode: str(path.relative_to(self.workspace).as_posix()) for mode, (path, _) in manifests.items()}}, indent=2) + "\n")
        rows = []
        for item in generated["properties"]:
            if item["kind"] == "assume":
                rows.append({**item, "status": "assumption", "mode": None})
                continue
            mode = options.mode if item["kind"] == "assert" else "cover"
            path, manifest = manifests[mode]
            source_location = "inputs/" + Path(self.paths.checker).relative_to(self.workspace).as_posix() + ":"
            matches = [p for p in manifest["properties"] if p["details"].get("property_id") == item["label"] and p["details"].get("location", "").startswith(source_location)]
            if len(matches) != 1:
                raise ValueError(f"{item['label']}: missing or ambiguous compiled property; inspect {path.relative_to(self.workspace)}")
            prop = matches[0]
            rows.append({**item, "status": prop["status"], "mode": mode, "evidence": path.relative_to(self.workspace).as_posix(), "counterexample": prop.get("counterexample_path"), "tool_name": prop["name"]})
        # Compare the declared interface to the elaborated DUT, not to a second regex parser.
        proof_dir = manifests[options.mode][0].parent
        design_path = resolve_within(proof_dir, "proof/src/ucagent_design.json", must_exist=True)
        modules = json.loads(design_path.read_text(encoding="utf-8"))["modules"]
        wrapper = modules[self.paths.dut + "_wrapper"]
        actual = modules[wrapper["cells"]["u_dut"]["type"]]["ports"]
        expected = {p["name"]: (p["direction"], p["width"]) for p in generated["ports"]}
        observed = {name: (p["direction"], len(p["bits"])) for name, p in actual.items()}
        if expected != observed:
            raise ValueError("basic_info.ports does not exactly match the elaborated DUT interface; correct all directions and resolved widths")
        for name, module in modules.items():
            if str(module.get("attributes", {}).get("blackbox", "0")).strip("0"):
                raise ValueError(f"Unmodeled blackbox in guided SBY design: {name}")
        assertions = [p for p in rows if p["kind"] == "assert"]
        covers = [p for p in rows if p["kind"] in {"cover", "guard_witness"}]
        status = "failed" if any(p["status"] == "falsified" for p in assertions) else "passed" if all(p["status"] == "proven" for p in assertions) and all(p["status"] == "covered" for p in covers) else "inconclusive"
        input_digest = hashlib.sha256(generated["snapshot"].read_bytes()).hexdigest()
        report = {"schema_version": 1, "engine": "sby", "input_sha256": input_digest, "verification_status": status, "mode": options.mode, "depth": options.depth, "properties": rows, "coverage": {"covered": sum(p["status"] == "covered" for p in covers), "total": len(covers), "coi": "unsupported", "vacuity": "not_established", "liveness": "not_established"}}
        publish_text(self.workspace, Path(self.paths.tests) / "sby_coverage.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return report
