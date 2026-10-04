"""Picker adapter for atomically generated Python/toffee DUT bindings."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from .base import ToolchainAdapter
from ..models import CommandSpec, RunRequest


class PickerAdapter(ToolchainAdapter):
    """Construct Picker exports without deleting or retrying over an existing package."""

    name = "picker"
    required_tools = ("picker",)

    def build_export_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        dut_name: str,
        top: str,
        source: Path,
        filelists: Iterable[Path] = (),
        simulator: str = "verilator",
        waveform: str = "none",
        coverage: bool = False,
        verdi_mode: str = "legacy",
        run_id: str | None = None,
        timeout_seconds: float = 3600,
    ) -> RunRequest:
        """Build an isolated ``picker export`` request using explicit structured options."""

        for label, value in (("dut_name", dut_name), ("top", top)):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value):
                raise ValueError(f"{label} is not a valid HDL identifier")
        if simulator not in {"verilator", "vcs"}:
            raise ValueError("simulator must be 'verilator' or 'vcs'")
        supported_waveforms = {
            "verilator": {"none", "fst", "vcd"},
            "vcs": {"none", "fsdb"},
        }
        if waveform not in supported_waveforms[simulator]:
            choices = ", ".join(sorted(supported_waveforms[simulator]))
            raise ValueError(f"Picker {simulator} waveform must be one of: {choices}")
        if verdi_mode not in {"legacy", "modern"}:
            raise ValueError("verdi_mode must be 'legacy' or 'modern'")
        filelist_values = list(filelists)
        argv = [
            "picker",
            "export",
            f"{{WORKSPACE}}/{source.as_posix()}",
            "--rw",
            "1" if simulator == "verilator" else "0",
            "--sname",
            top,
            "--tname",
            dut_name,
            "--tdir",
            f"{{SESSION_DIR}}/{dut_name}",
            "--lang",
            "python",
            "--sim",
            simulator,
        ]
        if waveform != "none":
            # Picker embeds this string in generated HDL. Keep it relative so
            # atomically moving the generated package cannot stale the path.
            argv.extend(["-w", f"{dut_name}.{waveform}"])
        if coverage:
            argv.append("-c")
        if simulator == "vcs":
            argv.extend(["--verdi-mode", verdi_mode])
        for filelist in filelist_values:
            argv.extend(["--filelist", f"{{WORKSPACE}}/{filelist.as_posix()}"])
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(
                argv=argv,
                tool="picker",
                cwd=Path("{SESSION_DIR}"),
                timeout_seconds=timeout_seconds,
            ),
            "input_paths": [source, *filelist_values],
            "artifact_paths": [Path(dut_name)],
            "metadata": {
                "adapter": self.name,
                "coverage": coverage,
                "dut": dut_name,
                "simulator": simulator,
                "top": top,
                "verdi_mode": verdi_mode if simulator == "vcs" else None,
                "waveform": waveform,
            },
        }
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)
