# -*- coding: utf-8 -*-
"""Resolve formal-workflow artifacts from trusted runtime configuration."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ucagent.util.config import Config, load_runtime_config


_SAFE_DUT_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")


def _resolved_template_values(cfg: Config | dict[str, Any]) -> dict[str, Any]:
    """Return DUT/OUT values from an already-resolved UCAgent configuration."""

    if isinstance(cfg, Config):
        values = cfg.get_value("_temp_cfg", None)
    elif isinstance(cfg, dict):
        values = cfg.get("_temp_cfg")
    else:
        raise TypeError("resolved_cfg must be a Config or mapping.")
    if isinstance(values, Config):
        values = values.as_dict()
    if not isinstance(values, dict):
        raise ValueError("Resolved configuration has no _temp_cfg DUT/OUT mapping.")
    return values


def _validate_relative_output(value: str) -> str:
    """Validate a workspace-relative output directory without option injection."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("Resolved OUT must be a non-empty string.")
    if value != value.strip() or Path(value).is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise ValueError("Resolved OUT must be a normalized workspace-relative path.")
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    for part in parts:
        if (
            part in {"", ".", ".."}
            or part.startswith("-")
            or any(ch in {'\"', "'"} or unicodedata.category(ch).startswith("C") for ch in part)
        ):
            raise ValueError("Resolved OUT contains an unsafe path component.")
    return os.path.join(*parts)


@dataclass(frozen=True)
class FormalPaths:
    """All formal artifact paths for one explicitly identified workspace.

    Callers must construct instances through :meth:`from_runtime_config` or
    :meth:`from_resolved_config`. The class deliberately has no environment,
    current-directory, directory-scan, or legacy-metadata fallback.
    """

    workspace: str
    dut: str
    out: str

    def __post_init__(self) -> None:
        """Validate identity and confine resolved paths to the workspace."""

        workspace = Path(self.workspace)
        if not workspace.is_absolute():
            raise ValueError("Formal workspace must be an absolute path.")
        workspace = workspace.resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Formal workspace must be an existing directory.")
        if not isinstance(self.dut, str) or not _SAFE_DUT_NAME.fullmatch(self.dut):
            raise ValueError("Resolved DUT must be a safe single path component.")
        output = _validate_relative_output(self.out)
        output_path = (workspace / output).resolve(strict=False)
        rtl_path = (workspace / self.dut).resolve(strict=False)
        for candidate in (output_path, rtl_path):
            try:
                candidate.relative_to(workspace)
            except ValueError as error:
                raise ValueError("Formal artifact path escapes the workspace.") from error
        object.__setattr__(self, "workspace", str(workspace))
        object.__setattr__(self, "out", output)

    @classmethod
    def from_runtime_config(cls, workspace: str | os.PathLike[str]) -> "FormalPaths":
        """Load DUT and OUT from ``.ucagent/runtime_config.json``."""

        workspace_path = Path(workspace).resolve(strict=True)
        runtime = load_runtime_config(str(workspace_path))
        return cls(workspace=str(workspace_path), dut=runtime["DUT"], out=runtime["OUT"])

    @classmethod
    def from_resolved_config(
        cls,
        workspace: str | os.PathLike[str],
        resolved_cfg: Config | dict[str, Any] | None,
    ) -> "FormalPaths":
        """Resolve paths from an explicit workspace and resolved configuration.

        ``None`` selects the persisted runtime snapshot. This is useful for
        standalone Skill scripts, while Checkers pass their already-resolved
        configuration so initialization does not depend on process state.
        """

        if resolved_cfg is None:
            return cls.from_runtime_config(workspace)
        values = _resolved_template_values(resolved_cfg)
        return cls(
            workspace=str(Path(workspace).resolve(strict=True)),
            dut=values.get("DUT"),
            out=values.get("OUT"),
        )

    @property
    def base(self) -> str:
        """Return the formal output root."""

        return os.path.join(self.workspace, self.out)

    @property
    def tests(self) -> str:
        """Return the formal executable-artifact directory."""

        return os.path.join(self.base, "tests")

    @property
    def checker(self) -> str:
        """Return the generated SVA checker path."""

        return os.path.join(self.tests, f"{self.dut}_checker.sv")

    @property
    def wrapper(self) -> str:
        """Return the generated DUT wrapper path."""

        return os.path.join(self.tests, f"{self.dut}_wrapper.sv")

    @property
    def tcl(self) -> str:
        """Return the FormalMC Tcl path."""

        return os.path.join(self.tests, f"{self.dut}_formal.tcl")

    @property
    def log(self) -> str:
        """Return the FormalMC result-log path."""

        return os.path.join(self.tests, "avis.log")

    @property
    def fanin(self) -> str:
        """Return the FormalMC fan-in coverage report path."""

        return os.path.join(self.tests, "avis", "fanin.rep")

    @property
    def spec(self) -> str:
        """Return the rendered formal specification path."""

        return os.path.join(self.base, f"03_{self.dut}_functions_and_checks.md")

    @property
    def planning(self) -> str:
        """Return the rendered formal verification plan path."""

        return os.path.join(self.base, f"01_{self.dut}_verification_needs_and_plan.md")

    @property
    def basic_info(self) -> str:
        """Return the rendered DUT information path."""

        return os.path.join(self.base, f"02_{self.dut}_basic_info.md")

    @property
    def summary(self) -> str:
        """Return the rendered formal summary path."""

        return os.path.join(self.base, f"05_{self.dut}_formal_summary.md")

    @property
    def analysis(self) -> str:
        """Return the rendered environment-analysis path."""

        return os.path.join(self.base, f"07_{self.dut}_env_analysis.md")

    @property
    def bug_report(self) -> str:
        """Return the rendered formal bug-report path."""

        return os.path.join(self.base, f"04_{self.dut}_bug_report.md")

    @property
    def static_doc(self) -> str:
        """Return the optional static-analysis document path."""

        return os.path.join(self.base, f"04_{self.dut}_static_bug_analysis.md")

    @property
    def test_file(self) -> str:
        """Return the Python counterexample replay test path."""

        return os.path.join(self.tests, f"test_{self.dut}_counterexample.py")

    @property
    def counterexample_evidence(self) -> str:
        """Return the signed counterexample replay evidence path."""

        return os.path.join(self.tests, "counterexample_replay_evidence.json")

    @property
    def rtl_dir(self) -> str:
        """Return the configured DUT source directory."""

        return os.path.join(self.workspace, self.dut)

    @property
    def rtl_path(self) -> str:
        """Return the conventional single-file Verilog DUT path."""

        return os.path.join(self.rtl_dir, f"{self.dut}.v")

    @property
    def records_yaml(self) -> str:
        """Return the structured record accumulated by formal stages."""

        return os.path.join(self.base, ".formal_records.yaml")
