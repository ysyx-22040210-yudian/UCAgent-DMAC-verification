"""Deterministic UVM 1.2 scaffold generation and structural validation."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from .project import (
    DpiCReferenceModel,
    ExternalReferenceModel,
    ProjectPath,
    ReferenceModel,
    SvReferenceModel,
    _validate_identifier,
)


UVM_MANIFEST = ".ucagent_uvm_manifest.json"
_PLACEHOLDER = re.compile(
    r"(?i)(?:\bTODO\b|\bTBD\b|\bFIXME\b|not[ _-]?implemented|\bplaceholder\b|<[^>]*replace[^>]*>)"
)


def _validate_sv_identifier(value: str) -> str:
    """Validate an identifier stored in the UVM scaffold specification."""
    return _validate_identifier(value, "UVM identifier")


SvIdentifier = Annotated[str, AfterValidator(_validate_sv_identifier)]


class UvmModel(BaseModel):
    """Strict immutable base model for UVM scaffold contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class UvmClock(UvmModel):
    """Describe the DUT clock used by generated clocking blocks."""

    name: SvIdentifier = "clk"
    period_ns: float = Field(default=10.0, gt=0)
    edge: Literal["posedge", "negedge"] = "posedge"


class UvmReset(UvmModel):
    """Describe reset polarity and the generated reset duration."""

    name: SvIdentifier = "rst_n"
    active_level: Literal[0, 1] = 0
    cycles: int = Field(default=5, ge=1)


class UvmSignal(UvmModel):
    """Describe one non-clock DUT port carried by a sequence item."""

    name: SvIdentifier
    direction: Literal["input", "output"]
    width: int = Field(default=1, ge=1, le=4096)
    reset_value: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_reset_value(self) -> "UvmSignal":
        """Require the declared reset value to fit within the signal width."""
        if self.reset_value >= 1 << self.width:
            raise ValueError(f"reset_value for {self.name} does not fit width {self.width}")
        return self


class UvmScaffoldSpec(UvmModel):
    """Provide all design facts needed to generate a compile-ready UVM shell."""

    uvm_version: Literal["1.2"] = "1.2"
    name: SvIdentifier
    dut_top: SvIdentifier
    design_sources: tuple[ProjectPath, ...] = Field(min_length=1)
    signals: tuple[UvmSignal, ...] = Field(min_length=2)
    clock: UvmClock = Field(default_factory=UvmClock)
    reset: UvmReset = Field(default_factory=UvmReset)
    reference_model: ReferenceModel | None = None
    timescale: Literal["1ns/1ps", "1ps/1ps", "10ns/1ns"] = "1ns/1ps"

    @model_validator(mode="after")
    def validate_ports(self) -> "UvmScaffoldSpec":
        """Require unique ports with at least one stimulus and one observation."""
        names = [self.clock.name, self.reset.name, *(signal.name for signal in self.signals)]
        if len(set(names)) != len(names):
            raise ValueError("clock, reset, and transaction signal names must be unique")
        if not any(signal.direction == "input" for signal in self.signals):
            raise ValueError("a UVM scaffold requires at least one DUT input signal")
        if not any(signal.direction == "output" for signal in self.signals):
            raise ValueError("a UVM scaffold requires at least one DUT output signal")
        if len(set(self.design_sources)) != len(self.design_sources):
            raise ValueError("design_sources must not contain duplicates")
        return self


class UvmValidationIssue(UvmModel):
    """Identify one deterministic scaffold validation failure or warning."""

    code: str
    path: str
    message: str
    severity: Literal["error", "warning"] = "error"


class UvmValidationResult(UvmModel):
    """Summarize structural validation without invoking a simulator."""

    valid: bool
    issues: tuple[UvmValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[UvmValidationIssue, ...]:
        """Return only issues that prevent scaffold acceptance."""
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[UvmValidationIssue, ...]:
        """Return non-blocking observations such as edited generated files."""
        return tuple(issue for issue in self.issues if issue.severity == "warning")


class UvmScaffoldResult(UvmModel):
    """Report the published scaffold files and their validation result."""

    output_dir: str
    files: tuple[str, ...]
    manifest: str
    validation: UvmValidationResult


def _sv_type(width: int) -> str:
    """Return a four-state SystemVerilog type for one port width."""
    return "logic" if width == 1 else f"logic [{width - 1}:0]"


def _item_type(width: int) -> str:
    """Return a two-state sequence-item type for one port width."""
    return "bit" if width == 1 else f"bit [{width - 1}:0]"


def _sha256(path: Path) -> str:
    """Hash one evidence or generated source file with SHA-256."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_inside(root: Path, relative_path: str, label: str) -> Path:
    """Resolve a declared path and fail when a symbolic link escapes the project."""
    candidate = (root / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes the project root: {relative_path}") from error
    return candidate


def _reference_files(reference_model: Any) -> tuple[tuple[str, Literal["file", "directory"]], ...]:
    """Project the filesystem evidence declared by one reference-model variant."""
    if isinstance(reference_model, SvReferenceModel):
        return tuple((path, "file") for path in reference_model.sources)
    if isinstance(reference_model, DpiCReferenceModel):
        return (
            *((path, "file") for path in reference_model.sources),
            *((path, "directory") for path in reference_model.include_dirs),
            *((path, "file") for path in reference_model.libraries),
        )
    if isinstance(reference_model, ExternalReferenceModel):
        return ((reference_model.executable, "file"),)
    return ()


def _render_scaffold(spec: UvmScaffoldSpec, output_dir: str) -> dict[str, str]:
    """Render all canonical UVM source files from explicit design metadata."""
    name = spec.name
    def from_filelist(path: str) -> str:
        """Express a project-relative input relative to the generated filelist."""

        return posixpath.relpath(path, start=output_dir)

    inputs = tuple(signal for signal in spec.signals if signal.direction == "input")
    edge = spec.clock.edge
    interface_declarations = "\n".join(
        f"  {_sv_type(signal.width)} {signal.name};" for signal in spec.signals
    )
    driver_clocking = "\n".join(f"    output {signal.name};" for signal in inputs)
    monitor_clocking = "\n".join(f"    input {signal.name};" for signal in spec.signals)
    dut_modport = ",\n".join(
        (
            f"    input {spec.clock.name}",
            f"    input {spec.reset.name}",
            *(
                f"    {signal.direction} {signal.name}"
                for signal in spec.signals
            ),
        )
    )
    interface = f"""`timescale {spec.timescale}

interface {name}_if(input logic {spec.clock.name});
  logic {spec.reset.name};
{interface_declarations}

  clocking drv_cb @({edge} {spec.clock.name});
    default input #1step output #0;
{driver_clocking}
  endclocking

  clocking mon_cb @({edge} {spec.clock.name});
    default input #1step output #0;
    input {spec.reset.name};
{monitor_clocking}
  endclocking

  modport DUT (
{dut_modport}
  );
endinterface
"""
    item_fields = "\n".join(
        f"  {'rand ' if signal.direction == 'input' else ''}{_item_type(signal.width)} {signal.name};"
        for signal in spec.signals
    )
    item_macros = "\n".join(
        f"    `uvm_field_int({signal.name}, UVM_ALL_ON)" for signal in spec.signals
    )
    item = f"""class {name}_item extends uvm_sequence_item;
{item_fields}

  `uvm_object_utils_begin({name}_item)
{item_macros}
  `uvm_object_utils_end

  function new(string name = "{name}_item");
    super.new(name);
  endfunction
endclass
"""
    sequence = f"""class {name}_smoke_sequence extends uvm_sequence #({name}_item);
  `uvm_object_utils({name}_smoke_sequence)

  function new(string name = "{name}_smoke_sequence");
    super.new(name);
  endfunction

  task body();
    req = {name}_item::type_id::create("req");
    start_item(req);
    if (!req.randomize())
      `uvm_fatal(get_type_name(), "sequence item randomization failed")
    finish_item(req);
  endtask
endclass
"""
    sequencer = f"""class {name}_sequencer extends uvm_sequencer #({name}_item);
  `uvm_component_utils({name}_sequencer)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
endclass
"""
    driver_assignments = "\n".join(
        f"    vif.drv_cb.{signal.name} <= item.{signal.name};" for signal in inputs
    )
    driver = f"""class {name}_driver extends uvm_driver #({name}_item);
  `uvm_component_utils({name}_driver)
  virtual {name}_if vif;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(virtual {name}_if)::get(this, "", "vif", vif))
      `uvm_fatal(get_type_name(), "virtual interface is not configured")
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      seq_item_port.get_next_item(req);
      drive_item(req);
      seq_item_port.item_done();
    end
  endtask

  task drive_item({name}_item item);
    @(vif.drv_cb);
{driver_assignments}
  endtask
endclass
"""
    monitor_assignments = "\n".join(
        f"      item.{signal.name} = vif.mon_cb.{signal.name};" for signal in spec.signals
    )
    monitor = f"""class {name}_monitor extends uvm_monitor;
  `uvm_component_utils({name}_monitor)
  virtual {name}_if vif;
  uvm_analysis_port #({name}_item) observed_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    observed_ap = new("observed_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(virtual {name}_if)::get(this, "", "vif", vif))
      `uvm_fatal(get_type_name(), "virtual interface is not configured")
  endfunction

  task run_phase(uvm_phase phase);
    {name}_item item;
    forever begin
      @(vif.mon_cb);
      if (vif.mon_cb.{spec.reset.name} == 1'b{spec.reset.active_level})
        continue;
      item = {name}_item::type_id::create("item");
{monitor_assignments}
      observed_ap.write(item);
    end
  endtask
endclass
"""
    agent = f"""class {name}_agent extends uvm_agent;
  `uvm_component_utils({name}_agent)
  {name}_sequencer sequencer;
  {name}_driver driver;
  {name}_monitor monitor;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    sequencer = {name}_sequencer::type_id::create("sequencer", this);
    driver = {name}_driver::type_id::create("driver", this);
    monitor = {name}_monitor::type_id::create("monitor", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    driver.seq_item_port.connect(sequencer.seq_item_export);
  endfunction
endclass
"""
    scoreboard = f"""class {name}_scoreboard extends uvm_subscriber #({name}_item);
  `uvm_component_utils({name}_scoreboard)
  int unsigned observed_count;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void write({name}_item observed);
    observed_count++;
    `uvm_info(get_type_name(), observed.sprint(), UVM_HIGH)
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    if (observed_count == 0)
      `uvm_error(get_type_name(), "no post-reset DUT transaction was observed")
  endfunction
endclass
"""
    coverage_points = "\n".join(
        f"    cp_{signal.name}: coverpoint sample_item.{signal.name};" for signal in spec.signals
    )
    coverage = f"""class {name}_coverage extends uvm_subscriber #({name}_item);
  `uvm_component_utils({name}_coverage)
  {name}_item sample_item;

  covergroup transaction_cg;
    option.per_instance = 1;
{coverage_points}
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    transaction_cg = new();
  endfunction

  function void write({name}_item observed);
    sample_item = observed;
    transaction_cg.sample();
  endfunction
endclass
"""
    environment = f"""class {name}_env extends uvm_env;
  `uvm_component_utils({name}_env)
  {name}_agent agent;
  {name}_scoreboard scoreboard;
  {name}_coverage coverage;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    agent = {name}_agent::type_id::create("agent", this);
    scoreboard = {name}_scoreboard::type_id::create("scoreboard", this);
    coverage = {name}_coverage::type_id::create("coverage", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    agent.monitor.observed_ap.connect(scoreboard.analysis_export);
    agent.monitor.observed_ap.connect(coverage.analysis_export);
  endfunction
endclass
"""
    reset_inactive = 1 - spec.reset.active_level
    test = f"""class {name}_test extends uvm_test;
  `uvm_component_utils({name}_test)
  {name}_env env;
  virtual {name}_if vif;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(virtual {name}_if)::get(this, "", "vif", vif))
      `uvm_fatal(get_type_name(), "virtual interface is not configured")
    env = {name}_env::type_id::create("env", this);
  endfunction

  task run_phase(uvm_phase phase);
    {name}_smoke_sequence smoke;
    phase.raise_objection(this);
    wait (vif.{spec.reset.name} === 1'b{reset_inactive});
    smoke = {name}_smoke_sequence::type_id::create("smoke");
    smoke.start(env.agent.sequencer);
    repeat (2) @({edge} vif.{spec.clock.name});
    phase.drop_objection(this);
  endtask
endclass
"""
    include_order = (
        "item",
        "sequence",
        "sequencer",
        "driver",
        "monitor",
        "agent",
        "scoreboard",
        "coverage",
        "env",
        "test",
    )
    includes = "\n".join(f'  `include "{name}_{part}.sv"' for part in include_order)
    package = f"""package {name}_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
{includes}
endpackage
"""
    signal_initialization = "\n".join(
        f"    vif.{signal.name} = {signal.width}'d{signal.reset_value};" for signal in inputs
    )
    dut_connections = ",\n".join(
        (
            f"    .{spec.clock.name}(vif.{spec.clock.name})",
            f"    .{spec.reset.name}(vif.{spec.reset.name})",
            *(f"    .{signal.name}(vif.{signal.name})" for signal in spec.signals),
        )
    )
    half_period = spec.clock.period_ns / 2
    tb_top = f"""`timescale {spec.timescale}

module tb_top;
  import uvm_pkg::*;
  import {name}_pkg::*;

  logic {spec.clock.name} = 1'b0;
  always #{half_period:g} {spec.clock.name} = ~{spec.clock.name};

  {name}_if vif({spec.clock.name});
  {spec.dut_top} dut (
{dut_connections}
  );

`ifdef UCAGENT_ENABLE_FSDB
  initial begin
    string fsdb_path;
    if ($value$plusargs("fsdbfile=%s", fsdb_path)) begin
      $fsdbDumpfile(fsdb_path);
      $fsdbDumpvars(0, tb_top);
    end
  end
`endif

  initial begin
    vif.{spec.reset.name} = 1'b{spec.reset.active_level};
{signal_initialization}
    repeat ({spec.reset.cycles}) @({edge} {spec.clock.name});
    vif.{spec.reset.name} = 1'b{reset_inactive};
  end

  initial begin
    uvm_config_db #(virtual {name}_if)::set(null, "uvm_test_top", "vif", vif);
    uvm_config_db #(virtual {name}_if)::set(null, "uvm_test_top.env.agent.*", "vif", vif);
    // The adapter supplies +UVM_TESTNAME for every matrix item.  Keeping this
    // argument empty prevents the generated top from silently overriding the
    // test identity recorded in signed run evidence.
    run_test();
  end
endmodule
"""
    compile_reference_sources: list[str] = []
    compile_reference_options: list[str] = []
    if isinstance(spec.reference_model, SvReferenceModel):
        compile_reference_sources.extend(from_filelist(path) for path in spec.reference_model.sources)
    elif isinstance(spec.reference_model, DpiCReferenceModel):
        compile_reference_options.extend(
            f"+incdir+{from_filelist(include_dir)}"
            for include_dir in spec.reference_model.include_dirs
        )
        compile_reference_sources.extend(from_filelist(path) for path in spec.reference_model.sources)
        compile_reference_sources.extend(from_filelist(path) for path in spec.reference_model.libraries)
    filelist_lines = [
        *(from_filelist(path) for path in spec.design_sources),
        *compile_reference_options,
        *compile_reference_sources,
        "+incdir+.",
        f"{name}_if.sv",
        f"{name}_pkg.sv",
        "tb_top.sv",
    ]
    return {
        f"{name}_if.sv": interface,
        f"{name}_item.sv": item,
        f"{name}_sequence.sv": sequence,
        f"{name}_sequencer.sv": sequencer,
        f"{name}_driver.sv": driver,
        f"{name}_monitor.sv": monitor,
        f"{name}_agent.sv": agent,
        f"{name}_scoreboard.sv": scoreboard,
        f"{name}_coverage.sv": coverage,
        f"{name}_env.sv": environment,
        f"{name}_test.sv": test,
        f"{name}_pkg.sv": package,
        "tb_top.sv": tb_top,
        "files.f": "\n".join(filelist_lines) + "\n",
    }


def generate_uvm_scaffold(
    workspace: str | Path,
    output_dir: str,
    spec: UvmScaffoldSpec | dict[str, Any],
    *,
    overwrite: bool = False,
) -> UvmScaffoldResult:
    """Generate, validate, and atomically publish a UVM 1.2 scaffold."""
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"workspace does not exist: {root}")
    relative_output = TypeAdapter(ProjectPath).validate_python(output_dir)
    target = _resolve_inside(root, relative_output, "output_dir")
    if target.exists() and target.is_symlink():
        raise ValueError("UVM output directory must not be a symbolic link")
    if target.exists() and not overwrite:
        raise FileExistsError(f"UVM output directory already exists: {target}")
    parsed = spec if isinstance(spec, UvmScaffoldSpec) else UvmScaffoldSpec.model_validate(spec)
    for design_source in parsed.design_sources:
        source_path = _resolve_inside(root, design_source, "design source")
        if not source_path.is_file():
            raise FileNotFoundError(f"design source does not exist: {design_source}")
    reference_hashes: list[dict[str, str]] = []
    for reference_path, expected_kind in _reference_files(parsed.reference_model):
        resolved = _resolve_inside(root, reference_path, "reference model path")
        exists_as_expected = resolved.is_file() if expected_kind == "file" else resolved.is_dir()
        if not exists_as_expected:
            raise FileNotFoundError(
                f"reference model {expected_kind} does not exist: {reference_path}"
            )
        try:
            resolved.relative_to(target)
        except ValueError:
            pass
        else:
            raise ValueError("reference-model evidence must be user-owned outside the generated directory")
        if expected_kind == "file":
            reference_hashes.append({"path": reference_path, "sha256": _sha256(resolved)})
    rendered = _render_scaffold(parsed, relative_output)
    staging_parent = target.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-stage-", dir=staging_parent)).resolve()
    try:
        generated_hashes: dict[str, str] = {}
        for filename, content in rendered.items():
            generated_path = staging / filename
            generated_path.write_text(content, encoding="utf-8", newline="\n")
            generated_hashes[filename] = _sha256(generated_path)
        manifest_payload = {
            "schema_version": 1,
            "generator": "ucagent.platform.uvm",
            "output_dir": relative_output,
            "spec": parsed.model_dump(mode="json"),
            "generated_files": generated_hashes,
            "reference_evidence": reference_hashes,
            "golden_model_generated": False,
            "scoreboard_mode": "observational",
        }
        (staging / UVM_MANIFEST).write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        staged_validation = validate_uvm_scaffold(root, staging.relative_to(root).as_posix())
        if not staged_validation.valid:
            issue_summary = "; ".join(f"{issue.code}: {issue.message}" for issue in staged_validation.errors)
            raise ValueError(f"generated UVM scaffold failed validation: {issue_summary}")
        if target.exists():
            target.mkdir(parents=True, exist_ok=True)
            for staged_file in staging.iterdir():
                os.replace(staged_file, target / staged_file.name)
        else:
            os.replace(staging, target)
        final_validation = validate_uvm_scaffold(root, relative_output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    files = tuple(f"{relative_output}/{filename}" for filename in (*rendered.keys(), UVM_MANIFEST))
    return UvmScaffoldResult(
        output_dir=relative_output,
        files=files,
        manifest=f"{relative_output}/{UVM_MANIFEST}",
        validation=final_validation,
    )


def validate_uvm_scaffold(workspace: str | Path, output_dir: str) -> UvmValidationResult:
    """Validate UVM structure, dependencies, registration, and reference provenance."""
    root = Path(workspace).expanduser().resolve()
    relative_output = TypeAdapter(ProjectPath).validate_python(output_dir)
    target = _resolve_inside(root, relative_output, "output_dir")
    issues: list[UvmValidationIssue] = []

    def report(code: str, path: str, message: str, severity: Literal["error", "warning"] = "error") -> None:
        """Append one bounded validation observation."""
        issues.append(UvmValidationIssue(code=code, path=path, message=message, severity=severity))

    manifest_path = target / UVM_MANIFEST
    if not manifest_path.is_file():
        report("UVM_MANIFEST_MISSING", f"{relative_output}/{UVM_MANIFEST}", "scaffold manifest is missing")
        return UvmValidationResult(valid=False, issues=tuple(issues))
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest_payload, dict):
            raise ValueError("manifest root is not an object")
        if manifest_payload.get("schema_version") != 1:
            raise ValueError("manifest schema_version must be 1")
        if manifest_payload.get("generator") != "ucagent.platform.uvm":
            raise ValueError("manifest generator identity is invalid")
        if manifest_payload.get("golden_model_generated") is not False:
            raise ValueError("manifest must attest that no golden model was generated")
        if manifest_payload.get("scoreboard_mode") != "observational":
            raise ValueError("generated scoreboard mode must be observational")
        manifest_output = TypeAdapter(ProjectPath).validate_python(manifest_payload.get("output_dir"))
        spec = UvmScaffoldSpec.model_validate(manifest_payload.get("spec"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        report("UVM_MANIFEST_INVALID", f"{relative_output}/{UVM_MANIFEST}", str(error))
        return UvmValidationResult(valid=False, issues=tuple(issues))
    rendered_names = tuple(_render_scaffold(spec, manifest_output).keys())
    generated_evidence = manifest_payload.get("generated_files")
    if not isinstance(generated_evidence, dict):
        report(
            "UVM_MANIFEST_INVALID",
            f"{relative_output}/{UVM_MANIFEST}",
            "generated_files must be an object of file hashes",
        )
        generated_evidence = {}
    texts: dict[str, str] = {}
    for filename in rendered_names:
        path = target / filename
        if not path.is_file():
            report("UVM_FILE_MISSING", f"{relative_output}/{filename}", "required scaffold file is missing")
            continue
        try:
            texts[filename] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            report("UVM_FILE_UNREADABLE", f"{relative_output}/{filename}", str(error))
            continue
        match = _PLACEHOLDER.search(texts[filename])
        if match:
            report(
                "UVM_PLACEHOLDER_FOUND",
                f"{relative_output}/{filename}",
                f"unresolved scaffold text: {match.group(0)!r}",
            )
        expected_hash = generated_evidence.get(filename)
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            report(
                "UVM_MANIFEST_INVALID",
                f"{relative_output}/{UVM_MANIFEST}",
                f"generated file hash is missing or invalid: {filename}",
            )
        elif _sha256(path) != expected_hash:
            report(
                "UVM_GENERATED_FILE_EDITED",
                f"{relative_output}/{filename}",
                "generated source differs from its initial scaffold hash",
                "warning",
            )
    name = spec.name
    required_registrations = {
        f"{name}_item.sv": f"`uvm_object_utils_begin({name}_item)",
        f"{name}_sequence.sv": f"`uvm_object_utils({name}_smoke_sequence)",
        f"{name}_sequencer.sv": f"`uvm_component_utils({name}_sequencer)",
        f"{name}_driver.sv": f"`uvm_component_utils({name}_driver)",
        f"{name}_monitor.sv": f"`uvm_component_utils({name}_monitor)",
        f"{name}_agent.sv": f"`uvm_component_utils({name}_agent)",
        f"{name}_scoreboard.sv": f"`uvm_component_utils({name}_scoreboard)",
        f"{name}_coverage.sv": f"`uvm_component_utils({name}_coverage)",
        f"{name}_env.sv": f"`uvm_component_utils({name}_env)",
        f"{name}_test.sv": f"`uvm_component_utils({name}_test)",
    }
    for filename, registration in required_registrations.items():
        if filename in texts and registration not in texts[filename]:
            report(
                "UVM_FACTORY_REGISTRATION_MISSING",
                f"{relative_output}/{filename}",
                f"required registration is absent: {registration}",
            )
    package_name = f"{name}_pkg.sv"
    if package_name in texts:
        package_text = texts[package_name]
        expected_includes = [
            f'{name}_{part}.sv'
            for part in (
                "item",
                "sequence",
                "sequencer",
                "driver",
                "monitor",
                "agent",
                "scoreboard",
                "coverage",
                "env",
                "test",
            )
        ]
        positions = [package_text.find(include) for include in expected_includes]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            report(
                "UVM_PACKAGE_DEPENDENCY_ORDER",
                f"{relative_output}/{package_name}",
                "class includes are missing or not in canonical dependency order",
            )
    scoreboard_name = f"{name}_scoreboard.sv"
    if spec.reference_model is None and scoreboard_name in texts:
        invented_model = re.search(r"(?i)\b(?:predict|golden|expected)\b", texts[scoreboard_name])
        if invented_model:
            report(
                "UVM_UNDECLARED_REFERENCE_MODEL",
                f"{relative_output}/{scoreboard_name}",
                "scoreboard prediction requires a declared user-provided reference model",
            )
    if "files.f" in texts:
        filelist = [line.strip() for line in texts["files.f"].splitlines() if line.strip() and not line.lstrip().startswith("#")]
        required_tail = [
            "+incdir+.",
            f"{name}_if.sv",
            f"{name}_pkg.sv",
            "tb_top.sv",
        ]
        tail_positions = [filelist.index(entry) if entry in filelist else -1 for entry in required_tail]
        if any(position < 0 for position in tail_positions) or tail_positions != sorted(tail_positions):
            report(
                "UVM_FILELIST_DEPENDENCY_ORDER",
                f"{relative_output}/files.f",
                "interface, package, and tb_top entries must follow the include directory in order",
            )
    interface_name = f"{name}_if.sv"
    if interface_name in texts:
        for signal in spec.signals:
            if not re.search(rf"\b{re.escape(signal.name)}\s*;", texts[interface_name]):
                report(
                    "UVM_INTERFACE_SIGNAL_MISSING",
                    f"{relative_output}/{interface_name}",
                    f"interface signal is missing: {signal.name}",
                )
    if "tb_top.sv" in texts:
        for port in (spec.clock.name, spec.reset.name, *(signal.name for signal in spec.signals)):
            if f".{port}(vif.{port})" not in texts["tb_top.sv"]:
                report(
                    "UVM_DUT_PORT_CONNECTION_MISSING",
                    f"{relative_output}/tb_top.sv",
                    f"DUT port connection is missing: {port}",
                )
    for design_source in spec.design_sources:
        try:
            resolved_design = _resolve_inside(root, design_source, "design source")
        except ValueError as error:
            report("UVM_DESIGN_SOURCE_ESCAPE", design_source, str(error))
        else:
            if not resolved_design.is_file():
                report("UVM_DESIGN_SOURCE_MISSING", design_source, "declared DUT source is missing")
    reference_evidence = manifest_payload.get("reference_evidence")
    evidence_by_path = {
        item.get("path"): item.get("sha256")
        for item in reference_evidence
        if isinstance(item, dict)
    } if isinstance(reference_evidence, list) else {}
    for reference_path, expected_kind in _reference_files(spec.reference_model):
        try:
            resolved = _resolve_inside(root, reference_path, "reference model path")
        except ValueError as error:
            report("UVM_REFERENCE_EVIDENCE_ESCAPE", reference_path, str(error))
            continue
        exists_as_expected = resolved.is_file() if expected_kind == "file" else resolved.is_dir()
        if not exists_as_expected:
            report(
                "UVM_REFERENCE_EVIDENCE_MISSING",
                reference_path,
                f"declared user-provided reference-model {expected_kind} is missing",
            )
        elif expected_kind == "file" and evidence_by_path.get(reference_path) != _sha256(resolved):
            report(
                "UVM_REFERENCE_EVIDENCE_CHANGED",
                reference_path,
                "reference-model source hash differs from the generation manifest",
            )
    return UvmValidationResult(
        valid=not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
    )
