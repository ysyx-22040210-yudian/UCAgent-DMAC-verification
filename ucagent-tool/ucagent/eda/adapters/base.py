"""Base interface and registry for commercial and open EDA tool adapters."""

from __future__ import annotations

from abc import ABC
from pathlib import Path
from threading import RLock

from ..models import CommandSpec, ToolchainProfile


class ToolchainAdapter(ABC):
    """Define the common discovery contract implemented by each EDA adapter."""

    name: str
    required_tools: tuple[str, ...]

    def probe_commands(self, profile: ToolchainProfile) -> list[CommandSpec]:
        """Build bounded version probes for every executable required by this adapter."""

        commands: list[CommandSpec] = []
        for alias in self.required_tools:
            profile.require_tool(alias)
            commands.append(CommandSpec(argv=[alias, "--version"], tool=alias, timeout_seconds=30))
        return commands

    def validate_profile(self, profile: ToolchainProfile) -> list[str]:
        """Return configuration diagnostics without starting a process."""

        diagnostics: list[str] = []
        for alias in self.required_tools:
            try:
                executable = profile.require_tool(alias)
            except ValueError as exc:
                diagnostics.append(str(exc))
                continue
            path = Path(executable)
            if path.is_absolute() and (not path.is_file() or not path.exists()):
                diagnostics.append(f"configured executable does not exist: {alias}={path}")
        if profile.setup_scripts:
            diagnostics.append(
                "setup_scripts require administrator materialization into ToolchainProfile.environment before execution"
            )
        return diagnostics


_REGISTRY: dict[str, ToolchainAdapter] = {}
_REGISTRY_LOCK = RLock()


def register_adapter(adapter: ToolchainAdapter) -> ToolchainAdapter:
    """Register one uniquely named adapter instance and return it."""

    if not adapter.name or not adapter.name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("adapter name must be alphanumeric with optional underscore or dash")
    with _REGISTRY_LOCK:
        if adapter.name in _REGISTRY:
            raise ValueError(f"adapter is already registered: {adapter.name}")
        _REGISTRY[adapter.name] = adapter
    return adapter


def get_adapter(name: str) -> ToolchainAdapter:
    """Return a registered adapter or name all available choices."""

    with _REGISTRY_LOCK:
        try:
            return _REGISTRY[name]
        except KeyError as exc:
            available = ", ".join(sorted(_REGISTRY)) or "none"
            raise KeyError(f"unknown EDA adapter {name!r}; available adapters: {available}") from exc


def list_adapters() -> tuple[str, ...]:
    """List registered adapter names in deterministic order."""

    with _REGISTRY_LOCK:
        return tuple(sorted(_REGISTRY))
