"""Deterministic, evidence-bound conversion of guided SBY inputs to managed FormalMC projects."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace

import yaml

from .adapters.sby import SbyAdapter
from .manifest import sha256_file, verify_manifest
from .sby_guided import render_environment
from .security import resolve_within
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records


class FormalConversionError(ValueError):
    """Provide a bounded conversion diagnostic instead of a partial runnable package."""

    def __init__(self, message, *, location=None):
        """Attach the failed input or checkpoint to a stable error code."""
        super().__init__((str(location) + ": " if location else "") + message)
        self.diagnostic = {"error_code": "FORMALMC_MIGRATION_BLOCKED", "error": str(self),
                           "next_action": "Correct the identified source/CK and rerun the SBY Check before converting."}


def _without_comments(text):
    """Blank comments without changing offsets or quoted path literals."""
    return re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"',
                  lambda m: m.group() if m.group().startswith('"') else
                  "".join("\n" if c == "\n" else " " for c in m.group()), text)


def _portable_expression(text, location):
    """Keep expression semantics literal and reject nonportable system functions."""
    supported = {"past", "stable", "changed", "rose", "fell", "signed", "unsigned", "bits", "clog2"}
    unknown = set(re.findall(r"\$([A-Za-z_]\w*)", text)) - supported
    if unknown:
        raise FormalConversionError("Unsupported expression functions: " + ", ".join(sorted(unknown)), location=location)


def render_target(records, generated):
    """Render explicit sampling and guards without inheriting native FormalMC reset defaults."""
    dut = records.dut
    config = records.basic_info["clock_reset"]
    clock, reset = config["clock_signal"], config["reset_signal"]
    edge = config.get("clock_edge", "posedge")
    event = "@(" + edge + " " + clock + ")"
    params = records.spec.parameters or {}
    header = " #( " + ", ".join("parameter %s = %s" % p for p in params.items()) + " )" if params else ""
    bind = " #( " + ", ".join(".%s(%s)" % (p, p) for p in params) + " )" if params else ""
    ports = generated["ports"]
    declarations = {p["name"]: ("[%d:0] " % (p["width"] - 1) if p["width"] > 1 else "") + p["name"] for p in ports}
    checker = ["module " + dut + "_checker" + header + " (",
               ",\n".join("  input wire " + declarations[p["name"]] for p in ports), ");"]
    if clock:
        checker += ["reg uc_past_valid = 1'b0;", "always " + event + " uc_past_valid <= 1'b1;"]
    mapping = []
    for fg in records.spec.function_groups:
        for fc in fg.functions:
            for ck in fc.check_points:
                kind = {"seq": "assert", "comb": "assert", "assume": "assume", "cover": "cover"}[ck.style.lower()]
                label = {"assert": "A_", "assume": "M_", "cover": "C_"}[kind] + ck.id.replace("-", "_")
                body, guard, trigger = ck.sva_body.strip(), ck.sby_guard.strip(), ck.sby_trigger.strip()
                for field, expr in (("sva_body", body), ("sby_guard", guard), ("sby_trigger", trigger)):
                    _portable_expression(expr, ck.id + "." + field)
                clocked = bool(clock and ck.style.lower() != "comb")
                if not clocked and re.search(r"\$(past|stable|changed|rose|fell)|uc_past_valid", body + guard + trigger):
                    raise FormalConversionError("Sampled history is not a combinational expression", location=ck.id)
                formula = "(%s) && (%s)" % (guard, body) if kind == "cover" else "(%s) |-> (%s)" % (guard, body)
                if clocked:
                    checker += ["%s: %s property (%s (%s));" % (label, kind, event, formula)]
                else:
                    checker += ["always @* begin", "  if (%s) %s: %s (%s);" % (guard, label, kind, body), "end"]
                mapping.append({"fg": fg.id, "fc": fc.id, "ck": ck.id, "label": label, "kind": kind,
                                "sampling": edge + " " + clock if clocked else "combinational",
                                "guard": guard, "body": body, "target_expression": formula if clocked else body})
                if kind == "assert":
                    witness = "G_" + label
                    formula = "(%s) && (%s)" % (guard, trigger)
                    if clocked:
                        checker += ["%s: cover property (%s (%s));" % (witness, event, formula)]
                    else:
                        checker += ["always @* begin", "  %s: cover (%s);" % (witness, formula), "end"]
                    mapping.append({"fg": fg.id, "fc": fc.id, "ck": ck.id, "label": witness,
                                    "kind": "guard_witness", "sampling": edge + " " + clock if clocked else "combinational",
                                    "guard": guard, "body": trigger, "target_expression": formula})
    checker.append("endmodule")
    connections = ", ".join(".%s(%s)" % (name, name) for name in declarations)
    wrapper = ["module " + dut + "_wrapper (",
               ",\n".join("  input wire " + declarations[p["name"]] for p in ports if p["direction"] == "input"), ");"]
    # Resolve DUT and checker parameters at this immutable wrapper instance.
    wrapper += ["localparam %s = %s;" % p for p in params.items()]
    wrapper += ["wire " + declarations[p["name"]] + ";" for p in ports if p["direction"] == "output"]
    wrapper += [dut + bind + " u_dut (" + connections + ");",
                dut + "_checker" + bind + " u_checker (" + connections + ");"]
    opts = generated["options"]
    if opts.reset_policy == "initial":
        cycles = opts.reset_cycles
        wrapper += ["reg [%d:0] uc_reset_count = 0;" % (cycles.bit_length() - 1),
                    "always %s if (uc_reset_count < %d) uc_reset_count <= uc_reset_count + 1'b1;" % (event, cycles),
                    "M_ENV_RESET: assume property (%s (%s == ((uc_reset_count < %d) ? 1'b%d : 1'b%d)));" %
                    (event, reset, cycles, opts.reset_active, 1 - opts.reset_active)]
    wrapper.append("endmodule")
    return "\n".join(checker) + "\n", "\n".join(wrapper) + "\n", mapping


def convert_sby_to_formalmc(workspace, dut, signing_key):
    """Build immutable project files in memory after checking current signed SBY proof and cover inputs."""
    root = Path(workspace).resolve(strict=True)
    record_path = resolve_within(root, "formal_out/.formal_records.yaml", must_exist=True)
    record_hash = sha256_file(record_path)
    records = load_records(str(record_path))
    tests = root / "formal_out/tests"
    if records is None or records.dut != dut:
        raise FormalConversionError("Missing or mismatched formal records")
    # Render source semantics in scratch space: converting cannot rewrite source artifacts.
    with tempfile.TemporaryDirectory(prefix="ucagent-formalmc-convert-") as directory:
        scratch = Path(directory)
        paths = SimpleNamespace(workspace=str(scratch), dut=dut, tests=str(scratch / "formal_out/tests"),
                                checker=str(scratch / "formal_out/tests" / (dut + "_checker.sv")),
                                wrapper=str(scratch / "formal_out/tests" / (dut + "_wrapper.sv")))
        generated = render_environment(paths, records)
        expected = dict(generated["hashes"])
    index = json.loads(resolve_within(root, tests / "sby_evidence.json", must_exist=True).read_text(encoding="utf-8"))
    if index.get("engine") != "sby":
        raise FormalConversionError("Only guided SBY evidence can be converted")
    manifests = []
    provenance = []
    proof_design = None
    for mode in (generated["options"].mode, "cover"):
        path = resolve_within(root, index["manifests"][mode], must_exist=True)
        manifest = verify_manifest(path, signing_key, workspace=root)
        if (manifest.get("execution_status") != "completed" or manifest.get("metadata", {}).get("mode") != mode
                or manifest.get("metadata", {}).get("adapter") != "sby"):
            raise FormalConversionError("SBY compilation/execution is incomplete", location=mode)
        for relative, value in expected.items():
            if manifest.get("input_hashes", {}).get(relative) != value:
                raise FormalConversionError("Current records differ from signed SBY inputs; rerun Check", location=relative)
        compiled = json.loads(resolve_within(path.parent, "proof/src/ucagent_design.json", must_exist=True).read_text(encoding="utf-8"))
        if mode != "cover":
            proof_design = compiled
        for module in compiled["modules"].values():
            if str(module.get("attributes", {}).get("blackbox", "0")).strip("0"):
                raise FormalConversionError("Unmodeled blackbox cannot be converted")
        for prop in generated["properties"]:
            if prop["kind"] == "assume" or (mode == "cover") != (prop["kind"] != "assert"):
                continue
            matches = [p for p in manifest["properties"] if p.get("details", {}).get("property_id") == prop["label"]
                       and p.get("details", {}).get("location", "").startswith("inputs/formal_out/tests/" + dut + "_checker.sv:")]
            if len(matches) != 1:
                raise FormalConversionError("Property is missing or ambiguous in compiled SBY evidence", location=prop["label"])
        manifests.append((path, manifest))
        provenance.append({"mode": mode, "manifest_sha256": sha256_file(path),
                           "source_verification_status": manifest.get("verification_status"),
                           "properties": [{"name": p["details"].get("property_id"), "status": p["status"]}
                                          for p in manifest["properties"]]})
    actual_wrapper = proof_design["modules"][dut + "_wrapper"]
    actual = proof_design["modules"][actual_wrapper["cells"]["u_dut"]["type"]]["ports"]
    if {p["name"]: (p["direction"], p["width"]) for p in generated["ports"]} != {
            n: (p["direction"], len(p["bits"])) for n, p in actual.items()}:
        raise FormalConversionError("Declared ports differ from the compiled DUT")
    opts = generated["options"]
    source_plan = SbyAdapter().prepare(workspace=root, top=dut + "_wrapper",
        sources=[Path(p) for p in opts.sources], filelists=[Path(p) for p in opts.filelists],
        include_dirs=[Path(p) for p in opts.include_dirs], defines=opts.defines)
    files = {}
    current_hashes = {}
    for relative in source_plan.inputs:
        path = resolve_within(root, relative, must_exist=True)
        candidates = [] if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            name = candidate.relative_to(root).as_posix()
            resolve_within(root, name, must_exist=True)
            current_hashes[name] = sha256_file(candidate)
            files["inputs/" + name] = candidate.read_bytes()
    # Input manifests must cover every copied design dependency, including memory contents.
    covered = manifests[0][1]["input_hashes"]
    rewrites = []
    for package_name in list(files):
        if Path(package_name).suffix.lower() not in {".sv", ".v", ".svh", ".vh"}:
            continue
        original = files[package_name].decode("utf-8")
        text = _without_comments(original)
        code = re.sub(r'"(?:\\.|[^"\\])*"', lambda match: " " * len(match.group()), text)
        unsupported = re.search(r"\$(?:anyconst|anyseq|allconst|allseq|initstate|global_clock|anyinit)\b|\b(?:anyconst|anyseq|allconst|allseq|gclk)\s*[=*)]", code)
        if unsupported:
            raise FormalConversionError("Yosys-specific formal construct requires an explicit reviewed model",
                                    location=package_name + ":" + str(text[:unsupported.start()].count("\n") + 1))
        custom = re.search(r"\b(?:assert|assume|cover)\s*(?:property\s*)?\(|\bbind\s|\$(?:past|stable|changed|rose|fell|random|urandom)\b", code)
        if custom:
            raise FormalConversionError("Custom verification or sampled/nondeterministic RTL requires an explicit reviewed model",
                                    location=package_name + ":" + str(text[:custom.start()].count("\n") + 1))
        calls = list(re.finditer(r'\$readmem[hb]\s*\(\s*("(?:[^"\\]|\\.)*"|[^,\n]+)', text))
        replacements = []
        for match in calls:
            literal = match.group(1)
            if not re.fullmatch(r'"[^"\\\n]+"', literal):
                raise FormalConversionError("Memory initialization filename must be a literal", location=package_name)
            name = literal[1:-1]
            source_rel = Path(package_name).relative_to("inputs")
            candidates = []
            for candidate in (root / name, root / source_rel.parent / name,
                              root / name.removeprefix("inputs/")):
                try:
                    candidate = resolve_within(root, candidate, must_exist=True)
                except (ValueError, OSError):
                    continue
                if candidate.is_file() and candidate not in candidates:
                    candidates.append(candidate)
            if len(candidates) != 1:
                raise FormalConversionError("Memory initialization file is missing or ambiguous: " + name, location=package_name)
            relative = candidates[0].relative_to(root).as_posix()
            current_hashes[relative] = sha256_file(candidates[0])
            files["inputs/" + relative] = candidates[0].read_bytes()
            replacement = '"inputs/' + relative + '"'
            if replacement != literal:
                replacements.append((match.start(1), match.end(1), replacement))
                rewrites.append({"file": package_name, "original": name, "packaged": "inputs/" + relative})
        for start, end, value in reversed(replacements):
            original = original[:start] + value + original[end:]
        files[package_name] = original.encode("utf-8")
    for name in current_hashes:
        if not any(name == key or (root / key).is_dir() and name.startswith(key + "/") for key in covered):
            raise FormalConversionError("Dependency was not hashed by the source SBY run", location=name)
    checker, wrapper, mapping = render_target(records, generated)
    files["formal/" + dut + "_checker.sv"] = checker.encode("utf-8")
    files["formal/" + dut + "_wrapper.sv"] = wrapper.encode("utf-8")
    macros = {"FORMAL": "1", "YOSYS": "1"}
    for define in source_plan.defines:
        name, _, value = define.partition("=")
        macros[name] = value if _ else "1"
    prelude = ["// Explicit source-SBY preprocessing environment.", "`undef SYNTHESIS"]
    for name, value in macros.items():
        prelude.extend(["`undef " + name, "`define " + name + " " + value])
    files["formal/source_macros.sv"] = ("\n".join(prelude) + "\n").encode("utf-8")
    compile_sources = ["formal/source_macros.sv", *("inputs/" + p.as_posix() for p in source_plan.sources),
                       "formal/" + dut + "_checker.sv", "formal/" + dut + "_wrapper.sv"]
    includes = ["inputs/" + p.as_posix() for p in source_plan.include_dirs]
    tcl = ["# UCAgent deterministic SBY conversion; FormalMC real-tool acceptance pending.",
           "set ROOT [file normalize [file dirname [info script]]]", "cd $ROOT", "set RTL_FILES [list]"]
    tcl += ["lappend RTL_FILES {%s}" % p for p in compile_sources]
    tcl += ["set READ_FLAGS [list]"]
    tcl += ["lappend READ_FLAGS {+incdir+%s}" % p for p in includes]
    tcl += ["read_design -top %s_wrapper -sysv -mfcu {*}$READ_FLAGS $RTL_FILES" % dut]
    if records.basic_info["clock_reset"]["clock_signal"]:
        tcl += ["def_clk " + records.basic_info["clock_reset"]["clock_signal"]]
    tcl += ["# Reset assumptions reside in HDL; do not add def_rst or default disable iff.",
            "set_opt -time %d" % opts.timeout_seconds, "prove", "show_prop -summary", "fanin -cover -list -dump"]
    files["formal.tcl"] = ("\n".join(tcl) + "\n").encode("utf-8")
    target_records = records.model_dump(mode="json", exclude={"run_results", "analysis", "bugs", "summary", "extra_config"})
    files["source_records.json"] = (json.dumps(target_records, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    report = {"schema_version": 1, "conversion_status": "checked", "verification_status": "not_run",
              "formalmc_acceptance": "not_run", "source_engine": "sby", "target_engine": "formalmc",
              "input_sha256": expected["formal_out/tests/sby_inputs.json"],
              "source_records_sha256": record_hash, "source_dependency_sha256": current_hashes, "source_runs": provenance, "properties": mapping,
              "source_options": opts.model_dump(), "effective_defines": macros, "memory_path_rewrites": rewrites,
              "limitations": ["FormalMC compilation/proof has not been accepted on real hardware.",
                             "guard_witness coverage is not COI or complete vacuity analysis.",
                             "Converted records and hashes do not transfer source approvals or proofs."]}
    files["conversion_report.json"] = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    project = {"schema_version": 1,
               "design": {"top": dut + "_wrapper", "sources": compile_sources, "include_dirs": includes},
               "workflow": {"family": "formal", "methodology": "systemverilog", "authoring_mode": "guided"},
               "toolchain": "formalmc_local", "formal": {"engine": "formalmc", "property_sets": ["formal.tcl"]}}
    # Validate the same public schema used by native-project imports.
    from ucagent.platform.project import ProjectConfig
    project = ProjectConfig.model_validate(project).model_dump(mode="json", exclude_none=True)
    files["project.yaml"] = yaml.safe_dump(project, allow_unicode=True, sort_keys=False).encode("utf-8")
    files[".ucagent/project.yaml"] = files["project.yaml"]
    guide = Path(__file__).parents[1] / "lang/zh/doc/Formal_SBY_Doc/formalmc_migration.md"
    files["README.md"] = guide.read_bytes()
    manifest = {"schema_version": 1, "target_engine": "formalmc", "formalmc_acceptance": "not_run",
                "timeout_seconds": opts.timeout_seconds,
                "properties": [{k: p[k] for k in ("fg", "fc", "ck", "label", "kind")} for p in mapping],
                "design": project["design"], "compile_sources": compile_sources, "include_dirs": includes, "effective_defines": macros,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())
                          if name not in {"project.yaml", ".ucagent/project.yaml"}}}
    files["conversion_inputs.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    if len(files) > 10000 or sum(map(len, files.values())) > 128 * 1024**2:
        raise FormalConversionError("Conversion exceeds 10000 files or 128 MiB")
    # Detect concurrent authoring and dependency changes before publishing the immutable project inputs.
    if sha256_file(record_path) != record_hash or any(sha256_file(root / name) != value for name, value in current_hashes.items()):
        raise FormalConversionError("Source changed while converting; retry stable inputs")
    for path, original_manifest in manifests:
        if verify_manifest(path, signing_key, workspace=root) != original_manifest:
            raise FormalConversionError("Source SBY evidence changed during conversion")
    return files, report


def verify_converted_project(root, expected_manifest_sha256=None):
    """Validate immutable converted inputs while allowing target toolchain settings to change."""
    root = Path(root).resolve(strict=True)
    path = resolve_within(root, "conversion_inputs.json", must_exist=True)
    if expected_manifest_sha256 is not None and sha256_file(path) != expected_manifest_sha256:
        raise FormalConversionError("Converted input manifest changed; create a fresh migration")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("target_engine") != "formalmc":
        raise FormalConversionError("Unsupported converted project schema")
    if not manifest.get("files") or not manifest.get("properties"):
        raise FormalConversionError("Converted input/property manifest is incomplete")
    for name, expected in manifest["files"].items():
        file = resolve_within(root, name, must_exist=True)
        if not file.is_file() or sha256_file(file) != expected:
            raise FormalConversionError("Converted project input changed", location=name)
    for name in manifest["include_dirs"]:
        if not resolve_within(root, name, must_exist=True).is_dir():
            raise FormalConversionError("Converted include directory is missing", location=name)
    return manifest
