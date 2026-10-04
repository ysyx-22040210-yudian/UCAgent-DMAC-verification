"""Execute the original UCAgent FormalMC Tcl workflow through the shared runner."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .base import ToolchainAdapter
from ..models import CommandSpec, RunRequest, ToolchainProfile
from ..input_closure import resolve_tcl_source_closure


class FormalMcAdapter(ToolchainAdapter):
    """Construct FormalMC requests without engine-specific execution logic in workflows."""

    name = "formal_mc"
    required_tools = ("formalmc",)

    @staticmethod
    def select_script(property_sets: Iterable[str | Path]) -> Path:
        """Require one explicit Tcl entry point instead of silently ignoring other scripts."""
        candidates = [Path(item) for item in property_sets if Path(item).suffix.lower() == ".tcl"]
        if len(candidates) != 1:
            raise ValueError("FormalMC requires exactly one entry .tcl in formal.property_sets; generate it with the original formal.yaml workflow and source helper scripts from that entry")
        return candidates[0]

    def probe_commands(self, profile: ToolchainProfile) -> list[CommandSpec]:
        """Use FormalMC's non-interactive version query for installation probing."""

        profile.require_tool("formalmc")
        return [CommandSpec(argv=["FormalMC", "-version"], tool="formalmc", timeout_seconds=30)]

    def build_formal_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        tcl_path: Path,
        design_inputs: Iterable[Path] = (),
        property_set: str | None = None,
        run_id: str | None = None,
        timeout_seconds: float = 14400,
    ) -> RunRequest:
        """Build a session-isolated FormalMC batch request."""

        argv = [
            "FormalMC",
            "-f",
            f"{{WORKSPACE}}/{tcl_path.as_posix()}",
            "-override",
            "-work_dir",
            "{SESSION_DIR}",
        ]
        design_input_values = list(design_inputs)
        closure = resolve_tcl_source_closure(workspace, [tcl_path])
        if not closure.complete:
            detail = "; ".join(str(item.get("error", "Unresolved Tcl input")) for item in closure.diagnostics[:3])
            raise ValueError("FormalMC Tcl inputs must be readable and explicit: " + detail[:1000])
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(argv=argv, tool="formalmc", timeout_seconds=timeout_seconds),
            "input_paths": list(dict.fromkeys([tcl_path, *closure.input_paths, *design_input_values])),
            "artifact_paths": [Path(".")],
            "result_paths": [Path("avis.log")],
            "parser": "formal",
            "property_set": property_set,
            # Tcl source closure does not prove every read_design dependency;
            # retain fresh proofs until a complete engine-specific closure exists.
            "metadata": {"adapter": self.name, "engine": "formal_mc", "cacheable": False},
        }
        if (workspace / "conversion_inputs.json").exists():
            from ..formalmc_conversion import verify_converted_project
            from ..manifest import sha256_file
            manifest = verify_converted_project(workspace)
            if tcl_path.as_posix() != "formal.tcl":
                raise ValueError("A migrated FormalMC project must use its fixed formal.tcl entry.")
            values["input_paths"] = list(dict.fromkeys([*values["input_paths"], Path("conversion_inputs.json"),
                                                        *(Path(name) for name in manifest["files"])]))
            values["prepared_input_hashes"] = {**manifest["files"], "conversion_inputs.json": sha256_file(workspace / "conversion_inputs.json")}
            values["metadata"]["expected_properties"] = manifest["properties"]
            values["command"] = CommandSpec(argv=argv, tool="formalmc", timeout_seconds=manifest["timeout_seconds"])
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)
