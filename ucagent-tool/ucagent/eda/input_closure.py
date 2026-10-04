"""Resolve workspace-contained VCS file-list and Tcl source input closures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
from typing import Iterable, Literal

from .security import PathSecurityError, resolve_within


_MAX_CONTROL_FILES = 4096
_MAX_CONTROL_FILE_BYTES = 8 * 1024 * 1024
_MAX_DIAGNOSTICS = 128
_MAX_NESTING_DEPTH = 64
_UNSAFE_FILELIST_TOKEN = re.compile(r"[\x00\r\n$`;&|<>]|[?*\[\]]|^~(?:[/\\]|$)")
_TCL_SOURCE = re.compile(
    r"^\s*source(?:\s+-encoding\s+[A-Za-z0-9_.-]+)?\s+"
    r"(?:\{(?P<braced>[^{}]*)\}|\"(?P<quoted>[^\"]*)\"|(?P<bare>[^\s;#]+))"
    r"\s*;?\s*(?:#.*)?$"
)
_HDL_INCLUDE = re.compile(
    r"(?m)^\s*`include\s+(?:\"(?P<quoted>[^\"\r\n]+)\"|<(?P<angled>[^>\r\n]+)>|(?P<dynamic>\S+))"
)
_KNOWN_FLAG_OPTIONS = {
    "-full64",
    "-sverilog",
    "-sysv",
    "-quiet",
    "-q",
}
_KNOWN_VALUE_OPTIONS = {
    "-ntb_opts",
    "-override_timescale",
    "-timescale",
    "-top",
}


class InputClosureSecurityError(ValueError):
    """Reject an input-closure construct that cannot be evaluated without executing it."""

    def __init__(self, error_code: str, message: str) -> None:
        """Store a stable error code alongside a bounded user-facing message."""

        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class InputClosure:
    """Describe the deterministic files and directories that influence one EDA command."""

    input_paths: tuple[Path, ...]
    filelists: tuple[Path, ...] = ()
    sources: tuple[Path, ...] = ()
    include_dirs: tuple[Path, ...] = ()
    includes: tuple[Path, ...] = ()
    scripts: tuple[Path, ...] = ()
    diagnostics: tuple[dict[str, object], ...] = ()

    @property
    def complete(self) -> bool:
        """Return whether every supported transitive input was resolved."""

        return not self.diagnostics

    def as_metadata(
        self,
        *,
        resolvers: Iterable[dict[str, object]] = (),
    ) -> dict[str, object]:
        """Return a JSON-safe closure summary and its runner revalidation recipe."""

        return {
            "complete": self.complete,
            "cacheable": self.complete,
            "input_paths": [path.as_posix() for path in self.input_paths],
            "filelists": [path.as_posix() for path in self.filelists],
            "sources": [path.as_posix() for path in self.sources],
            "include_dirs": [path.as_posix() for path in self.include_dirs],
            "includes": [path.as_posix() for path in self.includes],
            "scripts": [path.as_posix() for path in self.scripts],
            "diagnostics": [dict(item) for item in self.diagnostics],
            "resolvers": [dict(item) for item in resolvers],
        }


def merge_input_closures(*closures: InputClosure) -> InputClosure:
    """Merge independently resolved control-file closures without losing diagnostics."""

    return InputClosure(
        input_paths=_stable_paths(path for closure in closures for path in closure.input_paths),
        filelists=_stable_paths(path for closure in closures for path in closure.filelists),
        sources=_stable_paths(path for closure in closures for path in closure.sources),
        include_dirs=_stable_paths(path for closure in closures for path in closure.include_dirs),
        includes=_stable_paths(path for closure in closures for path in closure.includes),
        scripts=_stable_paths(path for closure in closures for path in closure.scripts),
        diagnostics=tuple(
            dict(item) for closure in closures for item in closure.diagnostics
        ),
    )


def resolve_vcs_filelist_closure(
    workspace: Path,
    *,
    filelists: Iterable[Path] = (),
    sources: Iterable[Path] = (),
    include_dirs: Iterable[Path] = (),
    root_mode: Literal["f", "F"] = "F",
) -> InputClosure:
    """Resolve literal VCS ``-f``/``-F`` file lists and their transitive inputs.

    ``-f`` entries use the invocation workspace as their relative base, while
    ``-F`` entries use the containing file-list directory. Constructs that may
    execute code or expand dynamically are rejected. Missing inputs and unknown
    options are retained as signed inputs but disable cache reuse with a bounded
    diagnostic.
    """

    root = workspace.resolve(strict=True)
    found_filelists: set[Path] = set()
    found_sources: set[Path] = set()
    found_include_dirs: set[Path] = set()
    include_search_order: list[Path] = []
    found_includes: set[Path] = set()
    diagnostics: list[dict[str, object]] = []
    active: list[Path] = []
    parsed: set[tuple[Path, str, Path]] = set()
    control_file_count = 0

    def add_diagnostic(
        error_code: str,
        message: str,
        *,
        control_file: Path | None = None,
        line: int | None = None,
        option: str | None = None,
    ) -> None:
        """Append one deterministic cache-disable reason without raw option values."""

        if len(diagnostics) >= _MAX_DIAGNOSTICS:
            return
        if len(diagnostics) == _MAX_DIAGNOSTICS - 1:
            diagnostics.append(
                {
                    "error_code": "input_closure_diagnostics_truncated",
                    "error": f"Input closure has at least {_MAX_DIAGNOSTICS} diagnostics.",
                    "next_action": "Correct the earlier closure diagnostics before retrying.",
                }
            )
            return
        item: dict[str, object] = {
            "error_code": error_code,
            "error": message,
            "next_action": (
                "Replace the unsupported or missing input with literal workspace-contained "
                "paths, then create a new run."
            ),
        }
        if control_file is not None:
            item["control_file"] = control_file.as_posix()
        if line is not None:
            item["line"] = line
        if option is not None:
            item["option"] = option
        diagnostics.append(item)

    def resolve_literal(
        value: Path | str,
        *,
        base: Path,
        kind: str,
        control_file: Path | None = None,
        line: int | None = None,
    ) -> tuple[Path, Path, bool]:
        """Resolve one literal path and classify missing inputs without escaping root."""

        text = str(value)
        if not text or _UNSAFE_FILELIST_TOKEN.search(text):
            location = (
                f" in {control_file.as_posix()}:{line}"
                if control_file is not None and line is not None
                else ""
            )
            raise InputClosureSecurityError(
                "dynamic_input_expression",
                f"{kind} uses a variable, wildcard, command, or metacharacter{location}",
            )
        raw = Path(text)
        lexical = raw if raw.is_absolute() else base / raw
        try:
            resolved = resolve_within(root, lexical, must_exist=False)
        except (OSError, PathSecurityError, ValueError) as exc:
            location = (
                f" in {control_file.as_posix()}:{line}"
                if control_file is not None and line is not None
                else ""
            )
            raise InputClosureSecurityError(
                "input_path_escape",
                f"{kind} escapes the workspace boundary{location}",
            ) from exc
        relative = resolved.relative_to(root)
        exists = resolved.exists()
        if not exists:
            add_diagnostic(
                "input_missing",
                f"{kind} does not exist: {relative.as_posix()}",
                control_file=control_file,
                line=line,
            )
        return relative, resolved, exists

    def add_source(
        value: Path | str,
        *,
        base: Path,
        control_file: Path | None = None,
        line: int | None = None,
    ) -> None:
        """Add one concrete source file to the closure."""

        relative, resolved, exists = resolve_literal(
            value,
            base=base,
            kind="source input",
            control_file=control_file,
            line=line,
        )
        found_sources.add(relative)
        if exists and not resolved.is_file():
            add_diagnostic(
                "source_not_file",
                f"source input is not a regular file: {relative.as_posix()}",
                control_file=control_file,
                line=line,
            )

    def add_include_dir(
        value: Path | str,
        *,
        base: Path,
        control_file: Path | None = None,
        line: int | None = None,
    ) -> None:
        """Add one include or library directory so every reachable header is hashed."""

        relative, resolved, exists = resolve_literal(
            value,
            base=base,
            kind="include directory",
            control_file=control_file,
            line=line,
        )
        found_include_dirs.add(relative)
        if relative not in include_search_order:
            include_search_order.append(relative)
        if exists and not resolved.is_dir():
            add_diagnostic(
                "include_not_directory",
                f"include input is not a directory: {relative.as_posix()}",
                control_file=control_file,
                line=line,
            )

    def parse_filelist(
        value: Path | str,
        *,
        reference_base: Path,
        mode: Literal["f", "F"],
        parent: Path | None = None,
        line: int | None = None,
    ) -> None:
        """Parse one file list while preserving VCS relative-path semantics."""

        nonlocal control_file_count
        relative, resolved, exists = resolve_literal(
            value,
            base=reference_base,
            kind="file list",
            control_file=parent,
            line=line,
        )
        found_filelists.add(relative)
        if not exists:
            return
        if not resolved.is_file():
            add_diagnostic(
                "filelist_not_file",
                f"file list is not a regular file: {relative.as_posix()}",
                control_file=parent,
                line=line,
            )
            return
        if resolved in active:
            chain = " -> ".join(
                item.relative_to(root).as_posix() for item in [*active, resolved]
            )
            raise InputClosureSecurityError(
                "recursive_filelist",
                f"recursive file-list inclusion is forbidden: {chain}",
            )
        contents_base = root if mode == "f" else resolved.parent
        parse_key = (resolved, mode, contents_base)
        if parse_key in parsed:
            return
        if len(active) >= _MAX_NESTING_DEPTH:
            raise InputClosureSecurityError(
                "filelist_nesting_limit",
                f"file-list nesting exceeds {_MAX_NESTING_DEPTH} levels at {relative.as_posix()}",
            )
        control_file_count += 1
        if control_file_count > _MAX_CONTROL_FILES:
            raise InputClosureSecurityError(
                "filelist_count_limit",
                f"file-list closure exceeds {_MAX_CONTROL_FILES} control files",
            )
        if resolved.stat().st_size > _MAX_CONTROL_FILE_BYTES:
            raise InputClosureSecurityError(
                "filelist_size_limit",
                f"file list exceeds {_MAX_CONTROL_FILE_BYTES} bytes: {relative.as_posix()}",
            )
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            add_diagnostic(
                "filelist_unreadable",
                f"file list cannot be read as UTF-8: {relative.as_posix()}",
                control_file=parent,
                line=line,
            )
            return
        lexer = shlex.shlex(
            _strip_hdl_comments(content),
            infile=relative.as_posix(),
            posix=True,
        )
        lexer.commenters = "#"
        lexer.whitespace_split = True
        tokens: list[tuple[str, int]] = []
        try:
            while True:
                token = lexer.get_token()
                if token == lexer.eof:
                    break
                tokens.append((token, lexer.lineno))
        except ValueError as exc:
            raise InputClosureSecurityError(
                "filelist_syntax_error",
                f"file list has unterminated quoting or escaping: {relative.as_posix()}:{lexer.lineno}",
            ) from exc

        active.append(resolved)
        try:
            index = 0
            while index < len(tokens):
                token, token_line = tokens[index]
                if not token:
                    index += 1
                    continue
                if _UNSAFE_FILELIST_TOKEN.search(token):
                    raise InputClosureSecurityError(
                        "dynamic_input_expression",
                        (
                            "file list uses a variable, wildcard, command, or metacharacter: "
                            f"{relative.as_posix()}:{token_line}"
                        ),
                    )
                if token in {"-f", "-F"}:
                    if index + 1 >= len(tokens):
                        add_diagnostic(
                            "filelist_operand_missing",
                            f"{token} has no file-list operand",
                            control_file=relative,
                            line=token_line,
                            option=token,
                        )
                        break
                    operand, _ = tokens[index + 1]
                    parse_filelist(
                        operand,
                        reference_base=contents_base,
                        mode=token[1],
                        parent=relative,
                        line=token_line,
                    )
                    index += 2
                    continue
                if token.startswith("-f=") or token.startswith("-F="):
                    nested_mode: Literal["f", "F"] = "F" if token.startswith("-F=") else "f"
                    parse_filelist(
                        token[3:],
                        reference_base=contents_base,
                        mode=nested_mode,
                        parent=relative,
                        line=token_line,
                    )
                    index += 1
                    continue
                if token.startswith("+incdir+"):
                    directories = token[len("+incdir+") :].split("+")
                    if not directories or any(not item for item in directories):
                        add_diagnostic(
                            "incdir_operand_missing",
                            "+incdir+ contains an empty directory operand",
                            control_file=relative,
                            line=token_line,
                            option="+incdir+",
                        )
                    else:
                        for directory in directories:
                            add_include_dir(
                                directory,
                                base=contents_base,
                                control_file=relative,
                                line=token_line,
                            )
                    index += 1
                    continue
                if token in {"-incdir", "-y"}:
                    if index + 1 >= len(tokens):
                        add_diagnostic(
                            "directory_operand_missing",
                            f"{token} has no directory operand",
                            control_file=relative,
                            line=token_line,
                            option=token,
                        )
                        break
                    add_include_dir(
                        tokens[index + 1][0],
                        base=contents_base,
                        control_file=relative,
                        line=token_line,
                    )
                    index += 2
                    continue
                if token == "-v":
                    if index + 1 >= len(tokens):
                        add_diagnostic(
                            "source_operand_missing",
                            "-v has no source operand",
                            control_file=relative,
                            line=token_line,
                            option="-v",
                        )
                        break
                    add_source(
                        tokens[index + 1][0],
                        base=contents_base,
                        control_file=relative,
                        line=token_line,
                    )
                    index += 2
                    continue
                if token.startswith(("+define+", "+libext+", "-pvalue+", "-timescale=")):
                    index += 1
                    continue
                if token in _KNOWN_FLAG_OPTIONS:
                    index += 1
                    continue
                if token in _KNOWN_VALUE_OPTIONS:
                    if index + 1 >= len(tokens):
                        add_diagnostic(
                            "option_operand_missing",
                            f"{token} has no operand",
                            control_file=relative,
                            line=token_line,
                            option=token,
                        )
                        break
                    index += 2
                    continue
                if token.startswith(("-", "+")):
                    option = re.split(r"[=+]", token, maxsplit=1)[0][:64]
                    add_diagnostic(
                        "unsupported_filelist_option",
                        (
                            "file-list closure cannot prove the inputs introduced by "
                            f"option {option}"
                        ),
                        control_file=relative,
                        line=token_line,
                        option=option,
                    )
                    index += 1
                    continue
                add_source(
                    token,
                    base=contents_base,
                    control_file=relative,
                    line=token_line,
                )
                index += 1
        finally:
            active.pop()
        parsed.add(parse_key)

    for source in sources:
        add_source(source, base=root)
    for include_dir in include_dirs:
        add_include_dir(include_dir, base=root)
    for filelist in filelists:
        parse_filelist(filelist, reference_base=root, mode=root_mode)

    scanned_includes: set[Path] = set()
    active_includes: list[Path] = []

    def scan_hdl_includes(relative: Path) -> None:
        """Find literal transitive HDL includes selected by bounded search paths."""

        resolved = root / relative
        if not resolved.is_file() or relative in scanned_includes:
            return
        if relative in active_includes:
            chain = " -> ".join(path.as_posix() for path in [*active_includes, relative])
            raise InputClosureSecurityError(
                "recursive_hdl_include",
                f"recursive HDL include is forbidden: {chain}",
            )
        if len(active_includes) >= _MAX_NESTING_DEPTH:
            raise InputClosureSecurityError(
                "hdl_include_nesting_limit",
                f"HDL include nesting exceeds {_MAX_NESTING_DEPTH} levels at {relative.as_posix()}",
            )
        if resolved.stat().st_size > _MAX_CONTROL_FILE_BYTES:
            add_diagnostic(
                "hdl_source_size_limit",
                f"HDL source is too large to inspect for includes: {relative.as_posix()}",
                control_file=relative,
            )
            return
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            add_diagnostic(
                "hdl_source_unreadable",
                f"HDL source cannot be inspected as UTF-8: {relative.as_posix()}",
                control_file=relative,
            )
            return
        active_includes.append(relative)
        try:
            searchable = _strip_hdl_comments(content)
            for match in _HDL_INCLUDE.finditer(searchable):
                line_number = searchable.count("\n", 0, match.start()) + 1
                include_name = match.group("quoted") or match.group("angled")
                if include_name is None:
                    add_diagnostic(
                        "dynamic_hdl_include",
                        (
                            "HDL include uses a macro or non-literal operand: "
                            f"{relative.as_posix()}:{line_number}"
                        ),
                        control_file=relative,
                        line=line_number,
                    )
                    continue
                if _UNSAFE_FILELIST_TOKEN.search(include_name):
                    raise InputClosureSecurityError(
                        "dynamic_hdl_include",
                        (
                            "HDL include uses a variable, wildcard, command, or metacharacter: "
                            f"{relative.as_posix()}:{line_number}"
                        ),
                    )
                include_path = Path(include_name)
                search_bases = [relative.parent, *include_search_order, Path(".")]
                if include_path.is_absolute():
                    search_bases = [Path(".")]
                selected: Path | None = None
                seen_candidates: set[Path] = set()
                for search_base in search_bases:
                    lexical = include_path if include_path.is_absolute() else root / search_base / include_path
                    try:
                        candidate = resolve_within(root, lexical, must_exist=False)
                    except (OSError, PathSecurityError, ValueError) as exc:
                        raise InputClosureSecurityError(
                            "hdl_include_path_escape",
                            (
                                "HDL include may escape the workspace boundary: "
                                f"{relative.as_posix()}:{line_number}"
                            ),
                        ) from exc
                    candidate_relative = candidate.relative_to(root)
                    if candidate_relative in seen_candidates:
                        continue
                    seen_candidates.add(candidate_relative)
                    if candidate.is_file():
                        selected = candidate_relative
                        break
                if selected is None:
                    add_diagnostic(
                        "hdl_include_missing",
                        (
                            "literal HDL include cannot be resolved in the declared search paths: "
                            f"{relative.as_posix()}:{line_number}"
                        ),
                        control_file=relative,
                        line=line_number,
                    )
                    continue
                found_includes.add(selected)
                scan_hdl_includes(selected)
        finally:
            active_includes.pop()
        scanned_includes.add(relative)

    for source in sorted(found_sources, key=lambda path: path.as_posix()):
        scan_hdl_includes(source)

    all_inputs = _stable_paths(
        [*found_filelists, *found_sources, *found_include_dirs, *found_includes]
    )
    return InputClosure(
        input_paths=all_inputs,
        filelists=_stable_paths(found_filelists),
        sources=_stable_paths(found_sources),
        include_dirs=_stable_paths(found_include_dirs),
        includes=_stable_paths(found_includes),
        diagnostics=tuple(diagnostics),
    )


def resolve_tcl_source_closure(workspace: Path, scripts: Iterable[Path]) -> InputClosure:
    """Resolve literal transitive Tcl ``source`` commands without evaluating Tcl."""

    root = workspace.resolve(strict=True)
    found_scripts: set[Path] = set()
    diagnostics: list[dict[str, object]] = []
    active: list[Path] = []
    parsed: set[Path] = set()

    def add_diagnostic(item: dict[str, object]) -> None:
        """Append one bounded Tcl closure diagnostic."""

        if len(diagnostics) >= _MAX_DIAGNOSTICS:
            return
        if len(diagnostics) == _MAX_DIAGNOSTICS - 1:
            diagnostics.append(
                {
                    "error_code": "input_closure_diagnostics_truncated",
                    "error": f"Input closure has at least {_MAX_DIAGNOSTICS} diagnostics.",
                    "next_action": "Correct the earlier closure diagnostics before retrying.",
                }
            )
            return
        diagnostics.append(item)

    def parse_script(value: Path | str, parent: Path | None = None, line: int | None = None) -> None:
        """Read one workspace Tcl script and recurse through literal source commands."""

        text = str(value)
        if not text or re.search(r"[\x00\r\n$`;&|<>]|[?*\[\]]|^~(?:[/\\]|$)", text):
            location = f" in {parent.as_posix()}:{line}" if parent is not None and line else ""
            raise InputClosureSecurityError(
                "dynamic_tcl_source",
                f"Tcl source uses a variable, command, wildcard, or metacharacter{location}",
            )
        raw = Path(text)
        lexical = raw if raw.is_absolute() else root / raw
        try:
            resolved = resolve_within(root, lexical, must_exist=False)
        except (OSError, PathSecurityError, ValueError) as exc:
            location = f" in {parent.as_posix()}:{line}" if parent is not None and line else ""
            raise InputClosureSecurityError(
                "tcl_source_path_escape",
                f"Tcl source escapes the workspace boundary{location}",
            ) from exc
        relative = resolved.relative_to(root)
        found_scripts.add(relative)
        if not resolved.exists():
            add_diagnostic(
                {
                    "error_code": "tcl_source_missing",
                    "error": f"Tcl source does not exist: {relative.as_posix()}",
                    "control_file": parent.as_posix() if parent is not None else relative.as_posix(),
                    **({"line": line} if line is not None else {}),
                    "next_action": "Declare a literal workspace-contained Tcl source and create a new run.",
                }
            )
            return
        if not resolved.is_file():
            add_diagnostic(
                {
                    "error_code": "tcl_source_not_file",
                    "error": f"Tcl source is not a regular file: {relative.as_posix()}",
                    "next_action": "Replace the Tcl source with a regular workspace file.",
                }
            )
            return
        if resolved in active:
            chain = " -> ".join(
                item.relative_to(root).as_posix() for item in [*active, resolved]
            )
            raise InputClosureSecurityError(
                "recursive_tcl_source",
                f"recursive Tcl source inclusion is forbidden: {chain}",
            )
        if resolved in parsed:
            return
        if len(active) >= _MAX_NESTING_DEPTH or len(parsed) >= _MAX_CONTROL_FILES:
            raise InputClosureSecurityError(
                "tcl_source_limit",
                "Tcl source closure exceeds the bounded file or nesting limit",
            )
        if resolved.stat().st_size > _MAX_CONTROL_FILE_BYTES:
            raise InputClosureSecurityError(
                "tcl_source_size_limit",
                f"Tcl source exceeds {_MAX_CONTROL_FILE_BYTES} bytes: {relative.as_posix()}",
            )
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            add_diagnostic(
                {
                    "error_code": "tcl_source_unreadable",
                    "error": f"Tcl source cannot be read as UTF-8: {relative.as_posix()}",
                    "next_action": "Store the Tcl source as UTF-8 and create a new run.",
                }
            )
            return
        active.append(resolved)
        try:
            for line_number, source_line in enumerate(content.splitlines(), start=1):
                stripped = source_line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if not re.search(r"(?:^|[;{}\s])source(?:\s|$)", source_line):
                    continue
                match = _TCL_SOURCE.fullmatch(source_line)
                if match is None:
                    if any(character in source_line for character in ("$", "[", "]", "`")):
                        raise InputClosureSecurityError(
                            "dynamic_tcl_source",
                            (
                                "Tcl source uses variable or command substitution: "
                                f"{relative.as_posix()}:{line_number}"
                            ),
                        )
                    add_diagnostic(
                        {
                            "error_code": "unsupported_tcl_source",
                            "error": (
                                "Tcl source closure cannot prove a compound source command: "
                                f"{relative.as_posix()}:{line_number}"
                            ),
                            "control_file": relative.as_posix(),
                            "line": line_number,
                            "next_action": (
                                "Use one standalone literal source command per line or disable cache reuse."
                            ),
                        }
                    )
                    continue
                operand = next(
                    value for value in match.group("braced", "quoted", "bare") if value is not None
                )
                parse_script(operand, parent=relative, line=line_number)
        finally:
            active.pop()
        parsed.add(resolved)

    for script in scripts:
        parse_script(script)
    ordered_scripts = _stable_paths(found_scripts)
    return InputClosure(
        input_paths=ordered_scripts,
        scripts=ordered_scripts,
        diagnostics=tuple(diagnostics),
    )


def _stable_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Deduplicate and sort workspace-relative paths for stable fingerprints."""

    return tuple(sorted(set(paths), key=lambda path: path.as_posix()))


def _strip_hdl_comments(content: str) -> str:
    """Remove HDL comments while preserving line positions and quoted strings."""

    result: list[str] = []
    index = 0
    state = "normal"
    while index < len(content):
        character = content[index]
        following = content[index + 1] if index + 1 < len(content) else ""
        if state == "line_comment":
            if character == "\n":
                result.append(character)
                state = "normal"
            else:
                result.append(" ")
            index += 1
            continue
        if state == "block_comment":
            if character == "*" and following == "/":
                result.extend((" ", " "))
                index += 2
                state = "normal"
            else:
                result.append("\n" if character == "\n" else " ")
                index += 1
            continue
        if state == "string":
            result.append(character)
            if character == "\\" and following:
                result.append(following)
                index += 2
                continue
            if character == '"':
                state = "normal"
            index += 1
            continue
        if character == "/" and following == "/":
            result.extend((" ", " "))
            index += 2
            state = "line_comment"
            continue
        if character == "/" and following == "*":
            result.extend((" ", " "))
            index += 2
            state = "block_comment"
            continue
        result.append(character)
        if character == '"':
            state = "string"
        index += 1
    return "".join(result)
