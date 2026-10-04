"""Trusted commercial-license smoke inputs and deterministic status classification."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .adapters.base import get_adapter
from .models import ExecutionStatus, RunRequest, VerificationStatus
from .security import resolve_within


class LicenseStatus(str, Enum):
    """Describe a real commercial license checkout independently of tool presence."""

    AVAILABLE = "available"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


_BUSY_PATTERNS = (
    re.compile(r"licensed number of users already reached", re.IGNORECASE),
    re.compile(r"all (?:available )?licenses? (?:are )?(?:currently )?in use", re.IGNORECASE),
    re.compile(r"waiting (?:for|to acquire|to checkout).{0,80}license", re.IGNORECASE),
    re.compile(r"license.{0,40}(?:queued|queue position|retrying checkout)", re.IGNORECASE),
    re.compile(r"flex(?:lm|net).{0,80}(?:error[^\n]*-4\b|-4,[^\n]*licensed)", re.IGNORECASE),
)
_UNAVAILABLE_PATTERNS = (
    re.compile(r"license\s+(?:checkout|check[- ]?out).*(?:fail|denied|unable)", re.IGNORECASE),
    re.compile(
        r"(?:\bno\b|cannot find|unable to obtain).{0,40}(?:valid\s+)?license",
        re.IGNORECASE,
    ),
    re.compile(r"cannot connect to (?:the )?license server", re.IGNORECASE),
    re.compile(r"license server.{0,40}(?:down|unreachable|not responding)", re.IGNORECASE),
    re.compile(r"(?:no such feature|license.{0,40}(?:invalid|expired|not supported))", re.IGNORECASE),
    re.compile(
        r"flex(?:lm|net).{0,100}(?:error[^\n]*-(?:1|2|5|9|10|15|18|96|97)\b|"
        r"-(?:1|2|5|9|10|15|18|96|97),[^\n]*)",
        re.IGNORECASE,
    ),
)


def classify_license_probe(
    text: str,
    *,
    execution_status: ExecutionStatus,
    diagnostics: Iterable[Mapping[str, Any]] = (),
) -> LicenseStatus:
    """Classify a completed smoke, recognized seat contention, or license outage."""

    diagnostic_codes = {
        str(item.get("error_code") or "").casefold() for item in diagnostics
    }
    if "license_busy" in diagnostic_codes or any(pattern.search(text) for pattern in _BUSY_PATTERNS):
        return LicenseStatus.BUSY
    if "license_unavailable" in diagnostic_codes or any(
        pattern.search(text) for pattern in _UNAVAILABLE_PATTERNS
    ):
        return LicenseStatus.UNAVAILABLE
    if execution_status == ExecutionStatus.COMPLETED:
        return LicenseStatus.AVAILABLE
    return LicenseStatus.UNKNOWN


def build_license_probe_request(
    adapter_name: str,
    *,
    workspace: Path,
    input_dir: Path,
    output_dir: Path,
    run_id: str,
    timeout_seconds: float = 120,
) -> RunRequest | None:
    """Materialize trusted built-in inputs and return a bounded license-checkout smoke."""

    if timeout_seconds <= 0 or timeout_seconds > 300:
        raise ValueError("license probe timeout must be greater than zero and at most 300 seconds")
    if input_dir.is_absolute() or input_dir.parts[:3] != (
        ".ucagent",
        "platform",
        "toolchain-probes",
    ):
        raise ValueError("license probe inputs must stay below .ucagent/platform/toolchain-probes")
    input_root = resolve_within(workspace, input_dir, must_exist=False, allow_root=False)
    input_root.mkdir(parents=True, exist_ok=False)

    def write_input(relative: Path, content: str) -> Path:
        """Create one immutable built-in probe input below the unique input root."""

        path = resolve_within(input_root, relative, must_exist=False, allow_root=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        return path

    if adapter_name == "vcs":
        source_relative = input_dir / "vcs_license_probe.sv"
        write_input(
            Path("vcs_license_probe.sv"),
            "module ucagent_vcs_license_probe;\n"
            "  initial begin\n"
            '    $display("UCAGENT_VCS_LICENSE_PROBE_OK");\n'
            "    $finish;\n"
            "  end\n"
            "endmodule\n",
        )
        adapter = get_adapter("vcs")
        request = adapter.build_compile_request(
            workspace=workspace,
            output_dir=output_dir,
            top="ucagent_vcs_license_probe",
            sources=[source_relative],
            run_id=run_id,
            timeout_seconds=timeout_seconds,
        )
        return request.model_copy(
            update={
                "verification_hint": VerificationStatus.PASSED,
                "metadata": {
                    **request.metadata,
                    "probe": True,
                    "probe_kind": "license_checkout",
                },
            }
        )

    if adapter_name == "vc_formal":
        source_relative = input_dir / "vcf_license_probe.sv"
        filelist_relative = input_dir / "vcf_license_probe.f"
        tcl_relative = input_dir / "vcf_license_probe.tcl"
        source_path = write_input(
            Path("vcf_license_probe.sv"),
            "module ucagent_vcf_license_probe(input logic clk, input logic rst_n);\n"
            "  logic sample;\n"
            "  always_ff @(posedge clk or negedge rst_n) begin\n"
            "    if (!rst_n) sample <= 1'b0;\n"
            "    else sample <= ~sample;\n"
            "  end\n"
            "  UCAGENT_LICENSE_PROBE: assert property "
            "(@(posedge clk) disable iff (!rst_n) sample == sample);\n"
            "endmodule\n",
        )
        filelist_path = write_input(
            Path("vcf_license_probe.f"), source_path.as_posix() + "\n"
        )
        adapter = get_adapter("vc_formal")
        tcl = adapter.render_tcl(
            filelist=filelist_path,
            top="ucagent_vcf_license_probe",
            clock={"name": "clk", "period": 10},
            reset={"name": "rst_n", "sense": "low"},
        )
        write_input(Path("vcf_license_probe.tcl"), tcl)
        request = adapter.build_formal_request(
            workspace=workspace,
            output_dir=output_dir,
            tcl_path=tcl_relative,
            filelist=filelist_relative,
            design_inputs=[source_relative],
            property_set="ucagent_license_probe",
            run_id=run_id,
            timeout_seconds=timeout_seconds,
        )
        return request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "probe": True,
                    "probe_kind": "license_checkout",
                },
            }
        )

    input_root.rmdir()
    return None


__all__ = ["LicenseStatus", "build_license_probe_request", "classify_license_probe"]
