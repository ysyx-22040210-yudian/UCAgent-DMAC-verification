"""Start the same execution API against a relocatable, offline Linux SBY bundle."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket

import uvicorn

from .api_platform import ProjectCreateRequest
from .platform_main import create_platform_app


def main() -> None:
    """Resolve bundle-owned tools, protect per-user state and announce a private listener."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--toolchains", type=Path, help="Administrator-owned host profiles, supplementing bundled SBY")
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("The portable platform refuses root; launch as an ordinary desktop user.")
    os.umask(0o077)
    bundle = args.bundle.resolve(strict=True)
    data = args.data.expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    if data.stat().st_uid != os.geteuid():
        raise SystemExit("The local data directory must belong to the current user.")
    os.chmod(data, 0o700)
    # A second server must not mark the first server's live runs as interrupted.
    lock = (data / "service.lock").open("a+")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("This local data directory is already open. Close the other Studio instance.")
    token = os.environ.pop("UCAGENT_LOCAL_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("A private in-memory local authentication token is required.")
    runtime = bundle / "oss-cad-suite"
    tools = {name: str(runtime / "bin" / name) for name in ("sby", "yosys", "yosys-smtbmc", "z3")}
    for path in tools.values():
        if not os.access(path, os.X_OK):
            raise SystemExit(f"Bundled executable missing or not executable: {path}")
    temporary = data / "tmp"
    temporary.mkdir(exist_ok=True)
    os.environ.update({"TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary)})
    config = {
        "profiles": {"bundled_sby": {
            "display_name": "Bundled SBY / Yosys / Z3 (offline)", "tools": tools,
            "environment": {"PATH": str(runtime / "bin") + ":/usr/bin:/bin", "TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary)},
            "execution_user": __import__("pwd").getpwuid(os.geteuid()).pw_name,
            "minimum_free_bytes": 10 * 1024**3, "max_concurrency": 1,
            "versions": json.loads((bundle / "bundle.json").read_text())["tools"],
        }},
    }
    toolchains = args.toolchains.expanduser().resolve() if args.toolchains else Path.home() / ".ucagent/toolchains.yaml"
    if args.toolchains and not toolchains.is_file():
        raise SystemExit("The explicitly selected host toolchain file does not exist.")
    examples = data / "projects"
    examples.mkdir(exist_ok=True)
    for name in ("sby_counter", "sby_counter_bug"):
        destination = examples / name
        if not destination.exists():
            staging = examples / ("." + name + ".tmp")
            if staging.exists():
                raise SystemExit(f"An interrupted example import needs inspection: {staging}")
            shutil.copytree(bundle / "examples" / name, staging)
            os.replace(staging, destination)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    app = create_platform_app(workspace=data / "state", port=port, toolchains_file=toolchains, import_roots=[Path.home(), examples], password=token, builtin_toolchains=config["profiles"])
    platform = app.state.platform_runtime
    existing = {project["source_root"] for project in platform.store.list_projects()}
    for name in ("sby_counter", "sby_counter_bug"):
        path = examples / name
        if str(path) not in existing:
            platform.create_project(ProjectCreateRequest(name=name, path=str(path)))
    ready = args.ready_file.resolve()
    if ready.parent != data or ready.exists():
        raise SystemExit("Readiness file must be a fresh direct child of the private data directory.")

    class LocalServer(uvicorn.Server):
        """Publish readiness only after the authenticated API has finished startup."""

        async def startup(self, sockets=None):
            """Announce the bound origin without serializing the authentication token."""
            await super().startup(sockets=sockets)
            if self.started:
                ready.write_text(json.dumps({"origin": f"http://127.0.0.1:{port}", "pid": os.getpid()}), encoding="utf-8")

    try:
        LocalServer(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False, timeout_graceful_shutdown=10)).run(sockets=[listener])
    finally:
        listener.close()
        ready.unlink(missing_ok=True)
        lock.close()


if __name__ == "__main__":
    main()
