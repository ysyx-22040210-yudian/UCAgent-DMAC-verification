"""Run the dependency-free Tk application with Python 3.8 or newer."""

import argparse
import json
import os
import platform
import sys

from .client import ApiClient
from .model import Preferences


def main():
    """Launch Tk or diagnose the interpreter/service without starting an EDA run."""
    parser = argparse.ArgumentParser(description="UCAgent native Tk desktop client (Python 3.8+).")
    parser.add_argument("--server", help="HTTPS origin or loopback HTTP SSH-forwarding origin")
    parser.add_argument("--preferences", help="Alternate non-secret desktop preference file")
    parser.add_argument("--diagnostics", action="store_true", help="Check Python/Tk and the backend without opening the desktop")
    parser.add_argument("--local", action="store_true", help="Start the bundled local SBY service")
    parser.add_argument("--bundle", help="Root of the complete offline Linux bundle")
    parser.add_argument("--data", help="Local state/projects directory for the bundled service")
    parser.add_argument("--toolchains", help="Local administrator toolchain YAML, adding installed VCF alongside bundled SBY")
    args = parser.parse_args()
    if args.toolchains and not args.local:
        parser.error("--toolchains requires --local; remote profiles are managed on the execution server")
    preferences = Preferences(args.preferences)
    local_service = None
    if args.local:
        if not args.bundle or args.server:
            parser.error("--local requires --bundle and cannot be combined with --server")
        from .local_service import LocalService
        local_service = LocalService(args.bundle, args.data, toolchains=args.toolchains)
        local_service.start()
        preferences = Preferences(args.preferences or local_service.data / "desktop.json")
        os.environ["FONTCONFIG_FILE"] = str(local_service.fontconfig)
    if args.diagnostics:
        import tkinter
        client = local_service.client if local_service else ApiClient(args.server or preferences.origin)
        result = {"python": platform.python_version(), "tk": tkinter.TkVersion, "server": client.origin, "desktop_supported": sys.version_info >= (3, 8)}
        try:
            result["overview"] = client.call("/overview")
        except Exception as exc:
            result["error"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if local_service:
            local_service.close()
        return 1 if "error" in result else 0
    import tkinter as tk
    from .app import Application
    try:
        root = tk.Tk()
        Application(root, args.server, preferences, local_service=local_service)
        root.mainloop()
    finally:
        if local_service:
            local_service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
