# -*- coding: utf-8 -*-
"""
MCP server lifecycle wrapper for VerifyPDB.

Provides :class:`PdbMcpServer` which manages starting and stopping the
FastMCP/uvicorn server that exposes UCAgent tools via the Model Context
Protocol (MCP).  The class follows the same lifecycle pattern as
:class:`PdbCmdApiServer`.
"""

import json
import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from pydantic import BaseModel

from ucagent.eda.security import is_secret_name, redact_text

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


def _collect_mcp_tools(agent: Any, no_file_ops: bool) -> List[Any]:
    """Return MCP-visible tools, optionally excluding generic file operations."""
    tools = (
        agent.tool_list_base
        + agent.tool_list_task
        + agent.tool_list_ext
        + getattr(agent, "tool_list_waveform", [])
    )
    if not no_file_ops:
        tools += agent.tool_list_file
    return tools


def _redact_public_schema(value: Any, *, secret_field: bool = False) -> Any:
    """Redact secret defaults while preserving a valid JSON-Schema structure."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_public_schema(item, secret_field=secret_field) for item in value]
    if not isinstance(value, Mapping):
        return value

    result: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        if secret_field and key in {"const", "default", "enum", "example", "examples"}:
            continue
        if key == "properties" and isinstance(item, Mapping):
            result[key] = {
                str(field_name): _redact_public_schema(
                    field_schema,
                    secret_field=is_secret_name(str(field_name)),
                )
                for field_name, field_schema in item.items()
            }
            continue
        result[key] = _redact_public_schema(item, secret_field=secret_field)
    return result


def project_mcp_tools(agent: Any, no_file_ops: bool = False) -> list[dict[str, Any]]:
    """Project active agent tools into inert, secret-free public MCP metadata.

    This function reads schemas from existing tool instances.  It never creates
    a tool, converts it into a callable wrapper, or invokes tool code.
    """

    projected: list[dict[str, Any]] = []
    for tool in _collect_mcp_tools(agent, no_file_ops):
        name = getattr(tool, "name", None)
        schema_model = getattr(tool, "tool_call_schema", None)
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(schema_model, type) or not issubclass(schema_model, BaseModel):
            continue
        try:
            schema = _redact_public_schema(schema_model.model_json_schema())
            encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            continue
        if len(encoded.encode("utf-8")) > 512 * 1024:
            continue
        description = redact_text(str(getattr(tool, "description", "") or ""))
        projected.append(
            {
                "name": name.strip()[:256],
                "description": description[:16384],
                "input_schema": schema,
            }
        )
    return projected


def project_fastmcp_tools(server: Any) -> list[dict[str, Any]]:
    """Project registered FastMCP tools into bounded, secret-free metadata.

    The platform embeds FastMCP as an ASGI application rather than converting
    LangChain tools.  FastMCP retains the generated JSON schema on each
    registered tool, so the UI can display the exact callable contract without
    invoking a tool or reaching into a verification workspace.
    """

    manager = getattr(server, "_tool_manager", None)
    list_tools = getattr(manager, "list_tools", None)
    if not callable(list_tools):
        return []
    projected: list[dict[str, Any]] = []
    for tool in list_tools():
        name = getattr(tool, "name", None)
        parameters = getattr(tool, "parameters", None)
        if not isinstance(name, str) or not name.strip() or not isinstance(parameters, Mapping):
            continue
        try:
            schema = _redact_public_schema(parameters)
            encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            continue
        if len(encoded.encode("utf-8")) > 512 * 1024:
            continue
        description = redact_text(str(getattr(tool, "description", "") or ""))
        projected.append(
            {
                "name": name.strip()[:256],
                "description": description[:16384],
                "input_schema": schema,
            }
        )
    return projected


class PdbMcpServer:
    """
    Lifecycle wrapper for the FastMCP/uvicorn MCP server.

    Creates and manages a FastMCP server in a background daemon thread,
    exposing the agent's tools via the Model Context Protocol.

    Usage
    -----
    ::

        server = PdbMcpServer(pdb, host="127.0.0.1", port=5000)
        ok, msg = server.start()
        ...
        ok, msg = server.stop()
    """

    def __init__(
        self,
        pdb_instance: "VerifyPDB",
        host: str = "127.0.0.1",
        port: int = 5000,
        no_file_ops: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        pdb_instance : VerifyPDB
            The active VerifyPDB instance (used to access the underlying agent).
        host : str
            TCP address on which the MCP HTTP server will listen.
        port : int
            TCP port for the MCP HTTP server.
        no_file_ops : bool
            When True, file-operation tools are excluded from the MCP server.
        """
        try:
            import uvicorn  # noqa: F401
            from mcp.server.fastmcp import FastMCP  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "FastMCP and uvicorn are required for the MCP server. "
                "Install them with:  pip install mcp uvicorn"
            ) from exc

        self.pdb = pdb_instance
        self.host = host
        self.port = port
        self.no_file_ops = no_file_ops
        self._server = None          # uvicorn.Server instance
        self._glogger = None         # saved logging.getLogger (for restore on stop)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.started_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Tuple[bool, str]:
        """Build the tool list and start the MCP server in a background thread.

        Returns
        -------
        (success, message)
        """
        if self._running:
            return False, f"MCP server is already running at {self.url()}"

        agent = self.pdb.agent

        tools = _collect_mcp_tools(agent, self.no_file_ops)

        agent.cfg.update_template(
            {"TOOLS": ", ".join([t.name for t in tools])}
        )

        from ucagent.util.functions import create_verify_mcps, start_verify_mcps
        from ucagent.util.log import info

        try:
            server, glogger = create_verify_mcps(
                tools,
                host=self.host,
                port=self.port,
                logger=getattr(agent, "_mcps_logger", None),
            )
        except Exception as exc:
            return False, f"Failed to create MCP server: {exc}"

        self._server = server
        self._glogger = glogger

        info("Init Prompt:\n" + agent.cfg.mcp_server.init_prompt)

        def _run():
            start_verify_mcps(self._server, self._glogger)

        self._thread = threading.Thread(target=_run, daemon=True, name="pdb-mcp-server")
        self._thread.start()

        # Keep agent attributes in sync for backward-compat
        # (api_master.py uses agent._mcps and agent._mcp_server_thread to report
        # mcp_running in heartbeats)
        agent._mcps = server
        agent._mcp_server_thread = self._thread

        self._running = True
        self.started_at = __import__('time').time()
        return True, f"MCP server started at {self.url()}"

    def stop(self) -> Tuple[bool, str]:
        """Stop the MCP server.

        Returns
        -------
        (success, message)
        """
        if not self._running:
            return False, "MCP server is not running"

        from ucagent.util.functions import stop_verify_mcps

        stop_verify_mcps(self._server)
        self._server = None
        self._thread = None
        self._running = False
        self.started_at = None

        # Clear agent backward-compat attributes
        agent = self.pdb.agent
        agent._mcps = None
        agent._mcp_server_thread = None

        return True, "MCP server stopped"

    @property
    def is_running(self) -> bool:
        return (
            self._running
            and self._thread is not None
            and self._thread.is_alive()
        )

    def url(self) -> str:
        """Return the MCP server URL."""
        return f"http://{self.host}:{self.port}"
