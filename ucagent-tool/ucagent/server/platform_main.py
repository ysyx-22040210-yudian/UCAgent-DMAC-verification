"""Standalone entry point for the single-user verification platform."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import secrets
from types import SimpleNamespace
from typing import Any, Callable, Sequence

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ucagent.server.api_platform import PlatformRuntime, register_platform_routes


class PlatformServerConfig:
    """Expose the small resolved-config interface consumed by platform routes."""

    def __init__(self, toolchains_file: Path | None, mcp_enabled: bool = False) -> None:
        """Store explicit non-secret service settings without loading an agent backend."""

        self._values: dict[str, Any] = {
            "platform": {
                "toolchains_file": str(toolchains_file.resolve()) if toolchains_file else "",
            },
            "mcp_server": {"enabled": mcp_enabled},
        }

    def get_value(self, key: str, default: Any = None) -> Any:
        """Resolve a dotted setting name from the standalone service configuration."""

        current: Any = self._values
        for component in key.split("."):
            if not isinstance(current, dict) or component not in current:
                return default
            current = current[component]
        return current


def create_platform_app(
    *,
    workspace: Path,
    host: str = "127.0.0.1",
    port: int = 8800,
    toolchains_file: Path | None = None,
    import_roots: Sequence[Path] = (),
    password: str = "",
    mcp_enabled: bool = False,
    builtin_toolchains: dict[str, dict[str, Any]] | None = None,
) -> FastAPI:
    """Build a platform-only FastAPI application without legacy Master JSON APIs."""

    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    launch_roots = []
    for index, raw_root in enumerate(import_roots, start=1):
        root = raw_root.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"project import root is not a directory: {root}")
        launch_roots.append(
            {"id": f"platform-root-{index}", "name": root.name or f"root-{index}", "path": str(root)}
        )
    runtime_holder: list[PlatformRuntime] = []
    mcp_holder: list[Any] = []

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Run embedded protocol state and stop owned process trees on shutdown."""

        try:
            if mcp_holder:
                mcp_app = mcp_holder[0].app
                async with mcp_app.router.lifespan_context(mcp_app):
                    yield
            else:
                yield
        finally:
            if runtime_holder:
                runtime_holder[0].shutdown()

    app = FastAPI(
        title="UCAgent Verification Platform",
        description="Structured simulation, UVM, coverage, and formal execution API.",
        version="1.0.0",
        lifespan=lifespan,
    )
    security = HTTPBasic(auto_error=False)

    async def check_password(
        credentials: HTTPBasicCredentials | None = Depends(security),
    ) -> None:
        """Apply optional single-user HTTP Basic authentication."""

        if not password:
            return
        if credentials is None or not secrets.compare_digest(
            credentials.password.encode("utf-8"), password.encode("utf-8")
        ):
            raise HTTPException(
                status_code=401,
                detail="Authentication required.",
                headers={"WWW-Authenticate": 'Basic realm="UCAgent Platform"'},
            )

    @app.middleware("http")
    async def protect_mcp(request: Any, call_next: Callable[[Any], Any]):
        """Apply the platform's optional Basic authentication to the mounted MCP app."""

        if password and request.url.path.rstrip("/") == "/mcp":
            credentials = await security(request)
            try:
                await check_password(credentials)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers,
                )
        return await call_next(request)

    context = SimpleNamespace(
        workspace=str(workspace),
        host=host,
        port=port,
        password=password,
        cfg=PlatformServerConfig(toolchains_file, mcp_enabled=mcp_enabled),
        _launch_roots=launch_roots,
        _builtin_toolchains=dict(builtin_toolchains or {}),
    )
    runtime = register_platform_routes(app, context, check_password)
    runtime_holder.append(runtime)
    app.state.platform_runtime = runtime

    @app.get("/", include_in_schema=False, dependencies=[Depends(check_password)])
    def root() -> RedirectResponse:
        """Send browser users directly to the visual platform."""

        return RedirectResponse(url="/platform/", status_code=307)

    if mcp_enabled:
        from ucagent.server.platform_mcp import PlatformMcpService

        mcp_service = PlatformMcpService(runtime, host=host, port=port)
        context.platform_mcp_server = mcp_service
        app.state.platform_mcp_service = mcp_service
        mcp_holder.append(mcp_service)
        app.mount("/", mcp_service.app, name="platform-mcp")

    return app


def _parser() -> argparse.ArgumentParser:
    """Build the standalone service command-line parser."""

    parser = argparse.ArgumentParser(prog="ucagent-platform")
    parser.add_argument("--workspace", type=Path, required=True, help="Persistent platform state directory.")
    parser.add_argument("--import-root", type=Path, action="append", default=[], help="Allowed project root.")
    parser.add_argument("--toolchains", type=Path, help="Administrator-owned toolchains.yaml path.")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8800, help="HTTP bind port.")
    parser.add_argument(
        "--password-env",
        default="UCAGENT_PLATFORM_PASSWORD",
        help="Environment variable holding optional HTTP Basic password.",
    )
    parser.add_argument(
        "--mcp-enabled",
        action="store_true",
        help="Host the platform MCP streamable-HTTP endpoint at /mcp.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Validate deployment boundaries and serve the platform until terminated."""

    args = _parser().parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise SystemExit("ucagent-platform refuses to run as root; use a dedicated service account")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.password_env):
        raise SystemExit("--password-env must be an environment variable name")
    if args.toolchains is not None and not args.toolchains.expanduser().is_file():
        raise SystemExit(f"toolchain file not found: {args.toolchains}")

    import uvicorn

    app = create_platform_app(
        workspace=args.workspace,
        host=args.host,
        port=args.port,
        toolchains_file=args.toolchains,
        import_roots=args.import_root,
        password=os.environ.get(args.password_env, ""),
        mcp_enabled=args.mcp_enabled,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


__all__ = ["PlatformRuntime", "PlatformServerConfig", "create_platform_app", "main"]


if __name__ == "__main__":
    main()
