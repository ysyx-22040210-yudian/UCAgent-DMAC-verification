"""Synopsys URG adapter for coverage database merge and report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .base import ToolchainAdapter
from ..models import CommandSpec, RunRequest, ToolchainProfile


class UrgAdapter(ToolchainAdapter):
    """Construct deterministic URG merge requests from explicit VDB inputs."""

    name = "urg"
    required_tools = ("urg",)

    def probe_commands(self, profile: ToolchainProfile) -> list[CommandSpec]:
        """Use URG's non-interactive version query for installation probing."""

        profile.require_tool("urg")
        return [CommandSpec(argv=["urg", "-version"], tool="urg", timeout_seconds=30)]

    def build_merge_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        databases: Iterable[Path],
        run_id: str | None = None,
        timeout_seconds: float = 3600,
    ) -> RunRequest:
        """Build an URG invocation that writes merged data and reports to its session."""

        database_values = list(databases)
        if not database_values:
            raise ValueError("at least one VDB database is required")
        argv = ["urg", "-dir"]
        argv.extend(f"{{WORKSPACE}}/{database.as_posix()}" for database in database_values)
        # O-2018 creates the merged database only when ``-dbname`` is a basename
        # in its working directory.  An absolute dbname still produces HTML but
        # silently omits the database, so both outputs are session-relative.
        argv.extend(["-dbname", "merged", "-report", "urg_report"])
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(
                argv=argv,
                tool="urg",
                cwd=Path("{SESSION_DIR}"),
                timeout_seconds=timeout_seconds,
            ),
            "input_paths": database_values,
            "artifact_paths": [Path("merged.vdb"), Path("urg_report")],
            "result_paths": [
                Path("urg_report/dashboard.html"),
                Path("urg_report/dashboard.txt"),
                Path("urg_report/summary.txt"),
            ],
            "parser": "urg",
            "metadata": {"adapter": self.name, "database_count": len(database_values)},
        }
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)
