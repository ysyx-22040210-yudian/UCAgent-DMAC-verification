"""Synopsys VCS adapter for native SystemVerilog and UVM 1.2 regressions."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, Mapping

from .base import ToolchainAdapter
from ..input_closure import resolve_vcs_filelist_closure
from ..models import CommandSpec, RunRequest, SessionInput, ToolchainProfile


_COVERAGE_ORDER = ("line", "cond", "tgl", "fsm", "branch", "assert")


class VcsAdapter(ToolchainAdapter):
    """Construct VCS compile/elaboration and simulation requests from structured fields."""

    name = "vcs"
    required_tools = ("vcs",)

    def probe_commands(self, profile: ToolchainProfile) -> list[CommandSpec]:
        """Use VCS's stable identity flag for a bounded installation probe."""

        profile.require_tool("vcs")
        return [CommandSpec(argv=["vcs", "-ID"], tool="vcs", timeout_seconds=30)]

    def build_compile_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        top: str,
        sources: Iterable[Path] = (),
        filelists: Iterable[Path] = (),
        include_dirs: Iterable[Path] = (),
        defines: Iterable[str] = (),
        parameters: Mapping[str, str | int | float] | None = None,
        methodology: str = "systemverilog",
        uvm_version: str = "1.2",
        timescale: str | None = None,
        configuration_inputs: Iterable[Path] = (),
        coverage: Iterable[str] = (),
        waveform: str = "none",
        fsdb_pli: tuple[Path, Path] | None = None,
        run_id: str | None = None,
        timeout_seconds: float = 7200,
    ) -> RunRequest:
        """Build a native VCS compile request with a session-local ``simv`` output."""

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*", top):
            raise ValueError("top is not a valid hierarchical HDL identifier")
        if methodology not in {"systemverilog", "uvm"}:
            raise ValueError("methodology must be 'systemverilog' or 'uvm'")
        if methodology == "uvm" and uvm_version != "1.2":
            raise ValueError("generated commercial UVM flows require UVM 1.2")
        if timescale is not None and not re.fullmatch(
            r"[1-9][0-9]*(?:s|ms|us|ns|ps|fs)/[1-9][0-9]*(?:s|ms|us|ns|ps|fs)",
            timescale,
        ):
            raise ValueError("timescale must be a safe <unit>/<precision> literal")
        if waveform not in {"none", "fsdb", "vpd"}:
            raise ValueError("waveform must be one of: none, fsdb, vpd")
        coverage_values = self._normalize_coverage(coverage)
        source_values = list(sources)
        filelist_values = list(filelists)
        include_values = list(include_dirs)
        configuration_values = list(configuration_inputs)
        input_closure = resolve_vcs_filelist_closure(
            workspace,
            filelists=filelist_values,
            sources=source_values,
            include_dirs=include_values,
            root_mode="F",
        )
        argv = ["vcs", "-full64", "-sverilog"]
        if methodology == "uvm":
            argv.extend(["-ntb_opts", f"uvm-{uvm_version}"])
        if timescale is not None:
            # A generated environment may be compiled after a user DUT without a
            # directive.  VCS O-2018 otherwise rejects the mixed compilation unit.
            argv.append(f"-timescale={timescale}")
        if waveform == "fsdb":
            if fsdb_pli is None:
                raise ValueError(
                    "native VCS FSDB compilation requires explicit fsdb_pli table and library paths"
                )
            table, library = fsdb_pli
            if not table.is_absolute() or not library.is_absolute():
                raise ValueError("FSDB PLI table and library paths must be absolute")
            # VCS O-2018 applies preprocessing options in argv order, so this
            # macro must precede every source and file-list argument.
            argv.extend(
                [
                    "-P",
                    str(table),
                    str(library),
                    "+define+UCAGENT_ENABLE_FSDB",
                    "-debug_access+all",
                    "-kdb",
                    "-lca",
                ]
            )
        elif waveform == "vpd":
            argv.append("-debug_access+all")
        for filelist in filelist_values:
            # ``-F`` makes nested source/include paths relative to the filelist
            # itself, so an isolated session cwd cannot change their meaning.
            argv.extend(["-F", f"{{WORKSPACE}}/{filelist.as_posix()}"])
        for include_dir in include_values:
            argv.append(f"+incdir+{{WORKSPACE}}/{include_dir.as_posix()}")
        for define in defines:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:=[^\r\n\x00]+)?", define):
                raise ValueError(f"invalid VCS define: {define!r}")
            argv.append(f"+define+{define}")
        for name, value in sorted((parameters or {}).items()):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*", name):
                raise ValueError(f"invalid parameter name: {name!r}")
            argv.append(f"-pvalue+{top}.{name}={value}")
        argv.extend(f"{{WORKSPACE}}/{source.as_posix()}" for source in source_values)
        argv.extend(["-top", top, "-o", "{SESSION_DIR}/simv"])
        artifact_paths = [Path("simv"), Path("simv.daidir")]
        if coverage_values:
            argv.extend(
                ["-cm", "+".join(coverage_values), "-cm_dir", "{SESSION_DIR}/simv.vdb"]
            )
            artifact_paths.append(Path("simv.vdb"))
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(argv=argv, tool="vcs", cwd=Path("{SESSION_DIR}"), timeout_seconds=timeout_seconds),
            "input_paths": [
                *input_closure.input_paths,
                *configuration_values,
            ],
            "artifact_paths": artifact_paths,
            "metadata": {
                "adapter": self.name,
                "phase": "compile",
                "top": top,
                "methodology": methodology,
                "timescale": timescale,
                "coverage": coverage_values,
                "waveform": waveform,
                "cacheable": input_closure.complete,
                "input_closure": input_closure.as_metadata(
                    resolvers=[
                        {
                            "kind": "vcs_filelist",
                            "root_mode": "F",
                            "filelists": [path.as_posix() for path in filelist_values],
                            "sources": [path.as_posix() for path in source_values],
                            "include_dirs": [path.as_posix() for path in include_values],
                        }
                    ]
                ),
            },
        }
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)

    def build_simulation_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        executable: Path,
        runtime_inputs: Iterable[Path] = (),
        coverage_database: Path | None = None,
        test_name: str | None = None,
        suite: str | None = None,
        seed: int | None = None,
        coverage: Iterable[str] = (),
        waveform: str = "none",
        fsdb_runtime_library_path: str | None = None,
        plusargs: Iterable[str] = (),
        success_markers: Iterable[str] = (),
        expect_waveform_artifact: bool = False,
        run_id: str | None = None,
        timeout_seconds: float = 3600,
    ) -> RunRequest:
        """Build one native or UVM simulation while reserving test and seed plusargs."""

        if waveform not in {"none", "fsdb", "vpd"}:
            raise ValueError("waveform must be one of: none, fsdb, vpd")
        coverage_values = self._normalize_coverage(coverage)
        argv = [f"{{WORKSPACE}}/{executable.as_posix()}"]
        if test_name is not None:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$:]*", test_name):
                raise ValueError("test_name is not a valid UVM class identifier")
            argv.append(f"+UVM_TESTNAME={test_name}")
        if seed is not None:
            if seed < 0:
                raise ValueError("seed must not be negative")
            argv.append(f"+ntb_random_seed={seed}")
        for plusarg in plusargs:
            if not plusarg.startswith("+") or any(char in plusarg for char in ("\x00", "\r", "\n")):
                raise ValueError("VCS plusargs must be single-line strings beginning with '+'")
            key = plusarg[1:].split("=", 1)[0].lower()
            if key in {"uvm_testname", "ntb_random_seed", "ntb_random_seed_automatic"}:
                raise ValueError(f"reserved VCS plusarg must use its structured field: {key}")
            argv.append(plusarg)
        artifact_paths: list[Path] = []
        session_inputs: list[SessionInput] = []
        if coverage_values:
            if coverage_database is None:
                raise ValueError(
                    "coverage_database is required so simulation starts from the compile-time design VDB"
                )
            argv.extend(["-cm", "+".join(coverage_values), "-cm_dir", "{SESSION_DIR}/simv.vdb"])
            artifact_paths.append(Path("simv.vdb"))
            session_inputs.append(
                SessionInput(source=coverage_database, destination=Path("simv.vdb"))
            )
        elif coverage_database is not None:
            raise ValueError("coverage_database is valid only when coverage is enabled")
        if waveform == "fsdb":
            if not fsdb_runtime_library_path:
                raise ValueError(
                    "native VCS FSDB simulation requires an explicit runtime library path"
                )
            argv.append("+fsdbfile={SESSION_DIR}/waves.fsdb")
            if expect_waveform_artifact:
                artifact_paths.append(Path("waves.fsdb"))
        elif waveform == "vpd":
            argv.extend(["+vcs+vcdpluson", "+vpdfile+{SESSION_DIR}/waves.vpd"])
            if expect_waveform_artifact:
                artifact_paths.append(Path("waves.vpd"))
        marker_values = list(success_markers)
        runtime_input_values = list(runtime_inputs)
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(
                argv=argv,
                cwd=Path("{SESSION_DIR}"),
                env={"LD_LIBRARY_PATH": fsdb_runtime_library_path}
                if waveform == "fsdb"
                else {},
                timeout_seconds=timeout_seconds,
            ),
            "input_paths": [executable, *runtime_input_values],
            "session_inputs": session_inputs,
            "artifact_paths": artifact_paths,
            "parser": "uvm",
            "test_name": test_name or executable.name,
            "suite": suite,
            "seed": seed,
            "success_markers": marker_values,
            "metadata": {
                "adapter": self.name,
                "phase": "simulate",
                "coverage": coverage_values,
                "waveform": waveform,
                "expect_waveform_artifact": expect_waveform_artifact,
            },
        }
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)

    def build_recipe_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        makefile: Path = Path("Makefile"),
        target: str,
        declared_targets: Iterable[str],
        variables: Mapping[str, str],
        allowed_variables: Iterable[str],
        test_variable: str,
        test_name: str,
        seed_variable: str,
        seed: int,
        output_variable: str,
        coverage_variable: str | None = None,
        coverage: Iterable[str] = (),
        waveform_variable: str | None = None,
        waveform: str = "none",
        artifact_paths: Iterable[Path] = (),
        result_paths: Iterable[Path] = (),
        success_markers: Iterable[str] = (),
        suite: str | None = None,
        run_id: str | None = None,
        timeout_seconds: float = 7200,
    ) -> RunRequest:
        """Build one isolated imported-recipe matrix job from explicit Make mappings."""

        target_set = set(declared_targets)
        allowed_set = set(allowed_variables)
        coverage_values = self._normalize_coverage(coverage)
        if target not in target_set or not re.fullmatch(r"[A-Za-z0-9_.-]+", target):
            raise ValueError("recipe target is not declared")
        if waveform not in {"none", "fsdb", "vpd"}:
            raise ValueError("imported VCS recipe waveform must be none, fsdb, or vpd")
        if coverage_values and coverage_variable is None:
            raise ValueError("coverage was requested but the recipe has no coverage_variable")
        if waveform != "none" and waveform_variable is None:
            raise ValueError("waveform was requested but the recipe has no waveform_variable")
        runner_variables = (
            test_variable,
            seed_variable,
            output_variable,
            coverage_variable,
            waveform_variable,
        )
        dynamic_names = {name for name in runner_variables if name is not None}
        if len(dynamic_names) != len([name for name in runner_variables if name is not None]) or any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in dynamic_names
        ):
            raise ValueError("recipe runner-owned variable names must be distinct identifiers")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", test_name):
            raise ValueError("recipe test_name is not a valid verification test identifier")
        if seed <= 0:
            raise ValueError("recipe seed must be positive")
        if dynamic_names.intersection(variables):
            raise ValueError("recipe matrix variables cannot also be static assignments")
        unknown = sorted((set(variables) | dynamic_names) - allowed_set)
        if unknown:
            raise ValueError(f"recipe variables are not declared: {', '.join(unknown)}")
        artifact_values = list(artifact_paths)
        result_values = list(result_paths)
        argv = ["make", "-f", f"{{WORKSPACE}}/{makefile.as_posix()}", target]
        job_variables = {
            **variables,
            test_variable: test_name,
            seed_variable: str(seed),
            output_variable: "{SESSION_DIR}",
        }
        if coverage_variable is not None:
            job_variables[coverage_variable] = "+".join(coverage_values) or "none"
        if waveform_variable is not None:
            job_variables[waveform_variable] = waveform
        for name, value in sorted(job_variables.items()):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"invalid recipe variable name: {name!r}")
            if value != "{SESSION_DIR}" and not re.fullmatch(r"[A-Za-z0-9_./:+,@%=-]*", value):
                raise ValueError(f"recipe variable {name!r} contains a Make-active or unsupported character")
            argv.append(f"{name}={value}")
        declared_artifacts = list(dict.fromkeys([*artifact_values, *result_values]))
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(argv=argv, tool="make", timeout_seconds=timeout_seconds),
            "input_paths": [makefile],
            "artifact_paths": declared_artifacts,
            "result_paths": result_values,
            "parser": "uvm",
            "test_name": test_name,
            "suite": suite,
            "seed": seed,
            "success_markers": list(success_markers),
            "metadata": {
                "adapter": self.name,
                "phase": "recipe",
                "target": target,
                "matrix_variables": {
                    "test": test_variable,
                    "seed": seed_variable,
                    "output": output_variable,
                    "coverage": coverage_variable,
                    "waveform": waveform_variable,
                },
                "coverage": coverage_values,
                "waveform": waveform,
            },
        }
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)

    @staticmethod
    def _normalize_coverage(values: Iterable[str]) -> list[str]:
        """Validate and deterministically order supported VCS coverage names."""

        supplied = set(values)
        unknown = sorted(supplied - set(_COVERAGE_ORDER))
        if unknown:
            raise ValueError(f"unsupported VCS coverage metrics: {', '.join(unknown)}")
        return [name for name in _COVERAGE_ORDER if name in supplied]
