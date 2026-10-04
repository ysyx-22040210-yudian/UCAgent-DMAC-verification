"""Synopsys VC Formal FPV adapter with a fixed, auditable Tcl lifecycle."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, Mapping

from .base import ToolchainAdapter
from ..input_closure import (
    merge_input_closures,
    resolve_tcl_source_closure,
    resolve_vcs_filelist_closure,
)
from ..models import CommandSpec, RunRequest, ToolchainProfile


class VcFormalAdapter(ToolchainAdapter):
    """Render fixed FPV Tcl and the confirmed VC Formal O-2018 batch argv."""

    name = "vc_formal"
    required_tools = ("vcf",)

    def probe_commands(self, profile: ToolchainProfile) -> list[CommandSpec]:
        """Use the O-2018 wrapper's non-licensing help path for installation probing."""

        profile.require_tool("vcf")
        return [CommandSpec(argv=["vcf", "-help"], tool="vcf", timeout_seconds=30)]

    def render_tcl(
        self,
        *,
        filelist: Path,
        top: str,
        clock: Mapping[str, str | int | float],
        reset: Mapping[str, str | int | float],
    ) -> str:
        """Render the required analyze-to-report FPV lifecycle with Tcl-safe atoms."""

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*", top):
            raise ValueError("top is not a valid hierarchical HDL identifier")
        clock_name = str(clock.get("name") or clock.get("signal") or "")
        reset_name = str(reset.get("name") or reset.get("signal") or "")
        if not clock_name or not reset_name:
            raise ValueError("clock and reset each require a name or signal")
        clock_args = [self._tcl_atom(clock_name)]
        if "period" in clock:
            clock_args.extend(["-period", self._tcl_atom(str(clock["period"]))])
        reset_args = [self._tcl_atom(reset_name)]
        if "sense" in reset:
            sense = str(reset["sense"]).lower()
            if sense not in {"high", "low"}:
                raise ValueError("reset sense must be 'high' or 'low'")
            reset_args.extend(["-sense", sense])
        filelist_value = filelist.as_posix()
        if (
            not re.fullmatch(r"[A-Za-z0-9_./:+-]+", filelist_value)
            or filelist_value.startswith("-")
        ):
            raise ValueError(
                "filelist path must use only Tcl/VCS-safe path characters; "
                "copy it to a workspace-relative path without whitespace or metacharacters"
            )
        lines = [
            f"analyze -format sverilog -vcs {{ -f {filelist_value} }}",
            f"elaborate -sva {self._tcl_atom(top)}",
            f"create_clock {' '.join(clock_args)}",
            f"create_reset {' '.join(reset_args)}",
            "sim_run -stable",
            "sim_save_reset",
            "check_fv -block",
            "report_fv -list",
            "report_fv -verbose",
            "exit",
        ]
        return "\n".join(lines) + "\n"

    def build_formal_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        tcl_path: Path,
        filelist: Path,
        design_inputs: Iterable[Path] = (),
        property_set: str | None = None,
        run_id: str | None = None,
        timeout_seconds: float = 14400,
    ) -> RunRequest:
        """Build the confirmed VC Formal batch command and evidence collection request."""

        argv = [
            "vcf",
            "-batch",
            "-no_ui",
            "-no_restore",
            "-fmode",
            "FPV",
            "-out_dir",
            "{SESSION_DIR}",
            "-output_log_file",
            "console.log",
            "-f",
            f"{{WORKSPACE}}/{tcl_path.as_posix()}",
        ]
        design_input_values = list(design_inputs)
        input_closure = merge_input_closures(
            resolve_tcl_source_closure(workspace, [tcl_path]),
            resolve_vcs_filelist_closure(
                workspace,
                filelists=[filelist],
                root_mode="f",
            ),
        )
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(argv=argv, tool="vcf", timeout_seconds=timeout_seconds),
            "input_paths": list(
                dict.fromkeys(
                    [tcl_path, filelist, *input_closure.input_paths, *design_input_values]
                )
            ),
            "artifact_paths": [Path(".")],
            "result_paths": [Path("console.log")],
            "parser": "formal",
            "property_set": property_set,
            "metadata": {
                "adapter": self.name,
                "engine": "vc_formal",
                "mode": "FPV",
                "cacheable": input_closure.complete,
                "input_closure": input_closure.as_metadata(
                    resolvers=[
                        {
                            "kind": "tcl_source",
                            "scripts": [tcl_path.as_posix()],
                        },
                        {
                            "kind": "vcs_filelist",
                            "root_mode": "f",
                            "filelists": [filelist.as_posix()],
                            "sources": [],
                            "include_dirs": [],
                        },
                    ]
                ),
            },
        }
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)

    @staticmethod
    def _tcl_atom(value: str) -> str:
        """Brace one Tcl atom while escaping characters that could end the command."""

        if not value or any(char in value for char in ("\x00", "\r", "\n")):
            raise ValueError("Tcl values must be non-empty single-line strings")
        escaped = value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        return "{" + escaped + "}"
