"""Persist client connection variables from an already running local license service.

This administrator utility does not modify license files, features or server
identity. It never prints or copies license contents into project evidence.
"""

import argparse
import os
from pathlib import Path
import re

import psutil


def main():
    """Write a root-only systemd environment file after validating the live daemon."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--license-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Administrator identity required")
    source = args.license_file.resolve(strict=True)
    content = source.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"(?mi)^\s*(?:VENDOR|DAEMON)\s+snpslmd\b", content):
        raise SystemExit("Expected an existing Synopsys license service configuration")
    records = re.findall(r"(?mi)^\s*SERVER\s+\S+\s+\S+\s+(\d+)\s*$", content)
    if len(records) != 1:
        raise SystemExit("This utility requires exactly one local server record")
    port = int(records[0])
    confirmed = False
    for process in psutil.process_iter(["name", "cmdline"]):
        command = process.info["cmdline"] or []
        if process.info["name"] != "lmgrd" or "-c" not in command:
            continue
        configured = command[command.index("-c") + 1]
        if Path(configured).resolve() != source:
            continue
        confirmed = any(connection.status == "LISTEN" and connection.laddr.port == port
                        for connection in process.net_connections(kind="inet"))
        if confirmed:
            break
    if not confirmed:
        raise SystemExit("No matching local daemon is listening; repair the existing license service first")
    target = args.output.absolute()
    if target.parent != Path("/etc/ucagent"):
        raise SystemExit("Environment output must be under the root-owned /etc/ucagent directory")
    target.parent.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        for name in ("SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE"):
            stream.write("{}={}@127.0.0.1\n".format(name, port))
        stream.flush()
        os.fsync(stream.fileno())
    print("Existing local license client environment persisted; values withheld.")


if __name__ == "__main__":
    main()
