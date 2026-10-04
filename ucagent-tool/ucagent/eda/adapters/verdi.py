"""Verdi artifact helper that never starts a graphical process on the server."""

from __future__ import annotations

from pathlib import Path
import shlex

from .base import ToolchainAdapter


class VerdiArtifactAdapter(ToolchainAdapter):
    """Generate a local FSDB-open command for display or clipboard use only."""

    name = "verdi_artifact"
    required_tools = ()

    def local_open_argv(self, downloaded_fsdb: Path) -> list[str]:
        """Return the local argv a user may run after downloading an FSDB artifact."""

        if downloaded_fsdb.suffix.lower() != ".fsdb":
            raise ValueError("Verdi artifact command requires an .fsdb file")
        return ["verdi", "-ssf", downloaded_fsdb.as_posix()]

    def format_local_command(self, downloaded_fsdb: Path) -> str:
        """Quote the local Verdi argv for safe clipboard display."""

        return shlex.join(self.local_open_argv(downloaded_fsdb))
