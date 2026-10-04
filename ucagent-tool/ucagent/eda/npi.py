"""Read-only bounded NPI query contracts and target-SDK bridge build requests."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import CommandSpec, RunRequest, SessionInput, StrictModel


class NpiQuery(StrictModel):
    """Select signed artifacts and bounded queries, never arbitrary paths or Tcl."""

    artifact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    operation: Literal["hierarchy", "ports", "signals", "drivers", "loads", "waveform", "coverage"]
    selector: str = Field(default="", max_length=1024)
    signals: list[str] = Field(default_factory=list, max_length=64)
    begin: int = Field(default=0, ge=0, le=2**64-1)
    end: int = Field(default=0, ge=0, le=2**64-1)
    max_objects: int = Field(default=1000, ge=1, le=10000)
    max_depth: int = Field(default=4, ge=1, le=16)
    timeout_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("selector", "signals")
    @classmethod
    def validate_names(cls, value):
        """Permit literal HDL names but exclude control characters and oversized selectors."""
        for name in value if isinstance(value, list) else [value]:
            if len(name) > 1024 or any(ord(char) < 32 for char in name):
                raise ValueError("NPI selectors must be bounded single-line literal names")
        return value

    @model_validator(mode="after")
    def validate_window(self):
        """Require explicit signals and an ordered unsigned time window."""
        if self.end < self.begin:
            raise ValueError("NPI time window end must be at least begin")
        if self.operation == "waveform" and (not self.signals or len(set(self.signals)) != len(self.signals)):
            raise ValueError("Waveform queries require unique explicit signals")
        return self


def build_npi_bridge(*, workspace: Path, source: Path, sdk_include: Path, output_dir: Path) -> RunRequest:
    """Compile only our source against host-owned commercial headers, without packaging them."""
    if not sdk_include.is_absolute() or not (sdk_include / "npi.h").is_file():
        raise ValueError("An existing administrator-owned NPI include directory is required")
    return RunRequest(workspace=workspace, output_dir=output_dir, resource_class="analysis",
        command=CommandSpec(tool="cxx", cwd=Path("{SESSION_DIR}"), timeout_seconds=120,
            argv=["cxx", "-std=c++11", "-fPIC", "-shared", "-Wall", "-Wextra", "-O2",
                  "-I", str(sdk_include), "{SESSION_DIR}/bridge.cpp", "-o", "bridge.so"]),
        session_inputs=[SessionInput(source=source, destination=Path("bridge.cpp"))],
        artifact_paths=[Path("bridge.so")], metadata={"adapter": "npi_bridge_build", "cacheable": False})


def build_npi_request(*, workspace: Path, bridge: Path, request_file: Path,
                      database: Path, output_dir: Path, query: NpiQuery, npi_script: Path) -> RunRequest:
    """Launch the vendor's NPI batch utility with only constant Tcl-safe arguments.

    Database paths and selectors stay inside a data file parsed by our C++ app;
    the O-2018 npi Perl wrapper never interpolates them into Shell or Tcl.
    """
    if not npi_script.is_absolute() or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(npi_script)):
        raise ValueError("NPI requires an explicit administrator-owned shell-safe Perl launcher path")
    staged = [SessionInput(source=bridge, destination=Path("bridge.so")),
              SessionInput(source=request_file, destination=Path("request.txt"))]
    # O-2018 ships a Perl script without a kernel shebang. Invoke its explicit
    # interpreter; do not retry an exec-format error through a generic shell.
    argv = ["perl", str(npi_script), "-dlib", "bridge.so", "-dfunc", "ucagent_npi_query", "-darg", "request.txt"]
    if query.operation in {"hierarchy", "ports", "signals", "drivers", "loads"}:
        staged.append(SessionInput(source=database, destination=Path("design.daidir")))
        argv.extend(["-dbdir", "design.daidir"])
    return RunRequest(workspace=workspace, output_dir=output_dir, resource_class="analysis",
        command=CommandSpec(argv=argv, tool="perl", cwd=Path("{SESSION_DIR}"),
                            timeout_seconds=query.timeout_seconds),
        session_inputs=staged,
        input_paths=[database], artifact_paths=[Path("result.json")],
        memory_limit_bytes=2 * 1024**3, output_limit_bytes=16 * 1024**2,
        metadata={"adapter": "npi", "operation": query.operation, "cacheable": False})


def query_wire_data(query: NpiQuery, database: Path) -> str:
    """Serialize fixed, bounded line records consumed as data, never executed as code."""
    if not database.is_absolute() or any(char in str(database) for char in "\x00\r\n"):
        raise ValueError("NPI database must resolve to an absolute single-line artifact path")
    return "\n".join(["UCAGENT_NPI_V1", query.operation, str(database), query.selector,
                      str(query.begin), str(query.end), str(query.max_objects), str(query.max_depth),
                      *query.signals]) + "\n"


def read_npi_result(path: Path, query: NpiQuery) -> dict:
    """Reject malformed/oversized bridge output and retain explicit evidence gaps."""
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError("NPI result exceeds the bounded result contract")
    result = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(result, dict) or result.get("schema_version") != 1
            or result.get("operation") != query.operation
            or not isinstance(result.get("items"), list)
            or not isinstance(result.get("truncated"), bool)
            or result.get("status") not in {"ok", "insufficient_evidence", "unsupported", "error"}):
        raise ValueError("NPI returned an invalid result envelope")
    if len(result["items"]) > query.max_objects or any(not isinstance(row, dict) for row in result["items"]):
        raise ValueError("NPI returned an invalid or excessive object set")
    for row in result["items"]:
        if query.operation == "waveform" and "value" in row:
            if not re.fullmatch(r"[01xXzZ]+", row["value"]) or not re.fullmatch(r"[0-9]+", row.get("time", "")):
                raise ValueError("NPI waveform records require four-state bits and decimal tick strings")
    # Truncation is not proof that an unobserved transition/bin does not exist.
    if result["truncated"] and result["status"] == "ok":
        result["status"] = "insufficient_evidence"
    return result
