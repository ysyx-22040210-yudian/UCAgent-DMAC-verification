"""Python 3.8 supervisor for the bundled local service, not a second EDA runner."""

import json
import os
from pathlib import Path
import platform
import secrets
import signal
import subprocess
import time
import xml.etree.ElementTree as ET

from .client import ApiClient


class LocalService:
    """Own one authenticated child service and leave its durable runs on disk."""

    def __init__(self, bundle, data=None, toolchains=None):
        """Validate a relocatable Linux package without downloading or installing anything."""
        if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
            raise ValueError("The bundled SBY edition currently requires Linux x86_64.")
        if os.geteuid() == 0:
            raise ValueError("Start the portable edition as an ordinary user, not root.")
        self.bundle = Path(bundle).resolve(strict=True)
        host_profiles = Path(toolchains).expanduser().resolve() if toolchains else Path.home() / ".ucagent/toolchains.yaml"
        if toolchains and not host_profiles.is_file():
            raise ValueError("The selected host toolchain file does not exist.")
        self.toolchains = host_profiles if host_profiles.is_file() else None
        manifest = json.loads((self.bundle / "bundle.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1 or manifest.get("platform") != "linux-x86_64":
            raise ValueError("Unsupported or incomplete offline bundle manifest.")
        self.python = self.bundle / "oss-cad-suite" / "bin" / "tabbypy3"
        if not os.access(str(self.python), os.X_OK):
            raise ValueError("Bundled Python is missing or not executable; extract the complete Linux archive.")
        self.data = Path(data).expanduser().resolve() if data else Path.home() / ".local/share/ucagent-studio"
        self.data.mkdir(parents=True, exist_ok=True)
        if self.data.stat().st_uid != os.geteuid():
            raise ValueError("The local data directory must belong to the current user.")
        os.chmod(str(self.data), 0o700)
        # Older enterprise Linux fontconfig does not resolve prefix="relative".
        # Materialize an escaped absolute font directory outside the read-only bundle.
        font_tree = ET.parse(str(self.bundle / "fonts/fonts.conf"))
        font_tree.getroot().find("dir").text = str(self.bundle / "fonts")
        self.fontconfig = self.data / "fonts.conf"
        font_stage = self.data / (".fonts-" + secrets.token_hex(8) + ".tmp")
        font_tree.write(str(font_stage), encoding="utf-8", xml_declaration=True)
        os.replace(str(font_stage), str(self.fontconfig))
        self.ready = self.data / ("ready-" + secrets.token_hex(12) + ".json")
        self.token = secrets.token_urlsafe(36)
        self.process = None
        self.log = None
        self.client = None

    def start(self):
        """Wait for a private authenticated listener; no external server or PATH setup is used."""
        if self.process is not None or not self.token:
            raise RuntimeError("Create a new LocalService instance for each service lifetime.")
        environment = {name: value for name, value in os.environ.items() if not name.startswith(("PYTHON", "LD_")) and "LICENSE" not in name and name != "UCAGENT_PLATFORM_PASSWORD"}
        if self.toolchains:
            # Only Synopsys license variables are admitted by this desktop entry.
            # The backend then exposes them solely to profiles declaring their names.
            for name in ("SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE"):
                if name in os.environ:
                    environment[name] = os.environ[name]
        environment.update({"PYTHONPATH": str(self.bundle / "backend-deps") + os.pathsep + str(self.bundle / "backend"), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "UCAGENT_LOCAL_TOKEN": self.token})
        self.log = (self.data / "service.log").open("ab")
        os.chmod(str(self.data / "service.log"), 0o600)
        command = [str(self.python), "-m", "ucagent.server.portable_main", "--bundle", str(self.bundle), "--data", str(self.data), "--ready-file", str(self.ready)]
        if self.toolchains:
            command.extend(["--toolchains", str(self.toolchains)])
        try:
            self.process = subprocess.Popen(command, cwd=str(self.bundle), env=environment, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, start_new_session=True)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("Local service did not start. Inspect {}".format(self.data / "service.log"))
                if self.ready.is_file():
                    try:
                        info = json.loads(self.ready.read_text(encoding="utf-8"))
                    except ValueError:
                        time.sleep(0.05)
                        continue
                    if info.get("pid") != self.process.pid:
                        raise RuntimeError("Local service readiness identity mismatch.")
                    if not str(info.get("origin", "")).startswith("http://127.0.0.1:"):
                        raise RuntimeError("Local service readiness must identify a loopback listener.")
                    self.client = ApiClient(info["origin"], token=self.token)
                    self.client.call("/overview", timeout=5)
                    self.ready.unlink()
                    return self.client
                time.sleep(0.05)
            raise TimeoutError("Local service startup exceeded 25 seconds; inspect service.log.")
        except Exception:
            self.close()
            raise

    def close(self):
        """Gracefully stop only the owned service, with a bounded process-group fallback."""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()
        if self.ready.exists():
            self.ready.unlink()
        self.token = None
