"""Generate isolated SBY/SMTBMC jobs from literal RTL inputs, never user scripts."""

from __future__ import annotations

import re
import shlex
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .base import ToolchainAdapter
from ..input_closure import resolve_vcs_filelist_closure
from ..models import CommandSpec, RunRequest, SessionInput, ToolchainProfile
from ..security import resolve_within


@dataclass(frozen=True)
class SbyPlan:
    """Bind generated control text to the exact file lists used while planning."""

    content: str
    inputs: list[Path]
    control_hashes: dict[str, str]
    sources: tuple[Path, ...] = ()
    include_dirs: tuple[Path, ...] = ()
    defines: tuple[str, ...] = ()


class SbyAdapter(ToolchainAdapter):
    """Provide native prove, bounded checking and cover using bundled SMTBMC/Z3."""

    name = "sby"
    required_tools = ("sby", "yosys", "yosys-smtbmc", "z3")

    def probe_commands(self, profile: ToolchainProfile) -> list[CommandSpec]:
        """Probe documented entry points; SMTBMC has help but no version option."""
        commands = []
        for alias, option in (("sby", "--version"), ("yosys", "-V"), ("yosys-smtbmc", "-h"), ("z3", "--version")):
            profile.require_tool(alias)
            commands.append(CommandSpec(argv=[alias, option], tool=alias, timeout_seconds=30))
        return commands

    def prepare(
        self, *, workspace: Path, top: str, sources: Iterable[Path] = (),
        filelists: Iterable[Path] = (), include_dirs: Iterable[Path] = (),
        defines: Iterable[str] = (), parameters: Mapping[str, object] | None = None,
        mode: str = "prove", depth: int = 40, timeout_seconds: int = 120,
        multiclock: bool = False, inspect_design: bool = False,
    ) -> SbyPlan:
        """Validate a literal file-list subset and return safe SBY text and signed inputs.

        Clock/reset assumptions must exist in the HDL harness. No constraints are
        invented from a signal name. File lists accept -f/-F, -I, +incdir+,
        +define+ and -sverilog; simulator-specific switches fail explicitly.
        """
        if mode not in {"prove", "bmc", "cover"}:
            raise ValueError("SBY mode must be prove, bmc, or cover")
        if type(depth) is not int or not 1 <= depth <= 100000:
            raise ValueError("SBY depth must be an integer from 1 to 100000")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 86400:
            raise ValueError("SBY timeout_seconds must be an integer from 1 to 86400")
        if type(multiclock) is not bool or type(inspect_design) is not bool or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", top):
            raise ValueError("SBY requires a boolean multiclock option and a literal HDL top")
        workspace = workspace.resolve(strict=True)
        sources, filelists, include_dirs, defines = list(sources), list(filelists), list(include_dirs), list(defines)
        ordered_sources = list(sources)
        ordered_includes = list(include_dirs)
        active: set[Path] = set()
        control_hashes: dict[str, str] = {}
        visited = 0

        def visit(path: Path, base: Path) -> None:
            """Resolve bounded nested file lists with explicit -f/-F relative semantics."""
            nonlocal visited
            path = resolve_within(workspace, path, must_exist=True)
            visited += 1
            if path in active or len(active) >= 64 or visited > 4096:
                raise ValueError("SBY file lists contain a cycle or exceed the nesting/file limit")
            if path.stat().st_size > 8 * 1024**2:
                raise ValueError("SBY file list exceeds 8 MiB")
            active.add(path)
            raw = path.read_bytes()
            key = path.relative_to(workspace).as_posix()
            digest = hashlib.sha256(raw).hexdigest()
            if len(raw) > 8 * 1024**2 or (key in control_hashes and control_hashes[key] != digest):
                raise ValueError("SBY file list changed during planning or exceeded 8 MiB; retry stable inputs")
            control_hashes[key] = digest
            content = re.sub(r"(?m)^\s*//.*$", "", raw.decode("utf-8"))
            tokens = iter(shlex.split(content, comments=True))
            for token in tokens:
                if token in {"-f", "-F", "-I"}:
                    value = next(tokens, None)
                    if value is None:
                        raise ValueError(f"SBY file-list option {token} requires a path")
                    target = resolve_within(workspace, base / value, must_exist=True)
                    if token == "-I":
                        ordered_includes.append(target.relative_to(workspace))
                    else:
                        visit(target, target.parent if token == "-F" else workspace)
                elif token.startswith("+incdir+"):
                    ordered_includes.extend(resolve_within(workspace, base / item, must_exist=True).relative_to(workspace) for item in token[8:].split("+"))
                elif token.startswith("+define+"):
                    defines.extend(token[8:].split("+"))
                elif token == "-sverilog":
                    continue
                elif token.startswith(("-", "+")):
                    raise ValueError(f"SBY does not support simulator file-list option: {token[:120]}")
                else:
                    ordered_sources.append(resolve_within(workspace, base / token, must_exist=True).relative_to(workspace))
            active.remove(path)

        for path in filelists:
            resolved = resolve_within(workspace, path, must_exist=True)
            visit(resolved, resolved.parent)
        ordered_sources = list(dict.fromkeys(ordered_sources))
        ordered_includes = list(dict.fromkeys(ordered_includes))
        if not ordered_sources:
            raise ValueError("SBY requires explicit RTL/harness sources or literal file lists")
        closure = resolve_vcs_filelist_closure(workspace, sources=ordered_sources, filelists=filelists, include_dirs=ordered_includes)
        if not closure.complete:
            raise ValueError("SBY requires a complete input closure: " + "; ".join(str(item["error"]) for item in closure.diagnostics[:8]))
        inputs = list(closure.input_paths)
        for path in inputs:
            if not path.parts or path.as_posix() == ".":
                raise ValueError("SBY include directories must be explicit subdirectories, not the project root")
            if re.search(r'[\x00\r\n"\\;{}$`]', path.as_posix()):
                raise ValueError("SBY input paths must not contain script metacharacters")
        for value in defines:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_'().+-]+)?", value):
                raise ValueError("SBY defines must be literal NAME or NAME=value tokens")
        if any(re.search(r"\s", path.as_posix()) for path in ordered_includes):
            raise ValueError("SBY/Yosys include directory names must not contain whitespace; rename that relative include directory. Project roots and source filenames may contain spaces.")
        # Yosys retains quotes in option tokens, unlike a shell. Include flags
        # therefore use literal unquoted relative directories validated above.
        read_flags = ["-formal", "-sv", *(f"-Iinputs/{p.as_posix()}" for p in ordered_includes), *(f"-D{v}" for v in defines)]
        script = ["read_verilog " + " ".join([*read_flags, *(f'"inputs/{p.as_posix()}"' for p in ordered_sources)])]
        for name, value in (parameters or {}).items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not re.fullmatch(r"[A-Za-z0-9_'().+-]+", str(value)):
                raise ValueError("SBY parameters require literal HDL identifiers and numeric values")
            script.append(f"chparam -set {name} {value} {top}")
        script.append(f"prep -top {top}")
        if inspect_design:
            script.extend(["check -assert", "write_json ucagent_design.json"])
        text = "\n".join([
            "[options]", f"mode {mode}", f"depth {depth}", f"timeout {timeout_seconds}",
            "multiclock " + ("on" if multiclock else "off"), "", "[engines]", "smtbmc z3", "",
            "[script]", *script, "", "[files]", "inputs", "",
        ])
        return SbyPlan(content=text, inputs=inputs, control_hashes=control_hashes,
                       sources=tuple(resolve_within(workspace, p, must_exist=True).relative_to(workspace) for p in ordered_sources),
                       include_dirs=tuple(ordered_includes), defines=tuple(defines))

    def build_formal_request(
        self, *, workspace: Path, output_dir: Path, config_path: Path,
        plan: SbyPlan, mode: str, depth: int, timeout_seconds: int,
        run_id: str,
    ) -> RunRequest:
        """Stage signed inputs privately and retain real SBY status, XML and VCD evidence."""
        inputs = list(dict.fromkeys(plan.inputs))
        # Collapse children of included directories so staging never overwrites
        # an already copied file; the runner verifies each copy against its hash.
        staged = [path for path in inputs if not any(parent in inputs for parent in path.parents)]
        return RunRequest(
            workspace=workspace, output_dir=output_dir, run_id=run_id,
            command=CommandSpec(tool="sby", argv=["sby", "-d", "proof", "{WORKSPACE}/" + config_path.as_posix()], cwd=Path("{SESSION_DIR}"), timeout_seconds=timeout_seconds + 15),
            input_paths=[config_path, *inputs],
            prepared_input_hashes={**plan.control_hashes, config_path.as_posix(): hashlib.sha256(plan.content.encode("utf-8")).hexdigest()},
            session_inputs=[SessionInput(source=path, destination=Path("inputs") / path) for path in staged],
            artifact_paths=[Path(".")], parser="sby",
            metadata={"adapter": "sby", "engine": "sby/smtbmc/z3", "mode": mode, "depth": depth, "cacheable": False},
        )
