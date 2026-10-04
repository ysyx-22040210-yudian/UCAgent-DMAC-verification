"""Bounded standard-library HTTP, streaming downloads, and resumable SSE transport."""

import hashlib
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from urllib import error, parse, request

MAX_JSON = 8 * 1024 * 1024
MAX_EVENT = 256 * 1024


class ApiError(Exception):
    """Report a bounded transport or server diagnostic without automatic write retries."""


class Cancelled(Exception):
    """Signal cooperative cancellation of a local download or event reader."""


class NoRedirect(request.HTTPRedirectHandler):
    """Prevent configured API calls and downloads from silently changing destinations."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Reject redirects rather than forwarding data to another endpoint."""
        raise ApiError("API redirects are not accepted; configure the final service origin.")


def validate_origin(value):
    """Accept a credential-free HTTPS origin or loopback HTTP used by SSH forwarding."""
    try:
        parts = parse.urlsplit(value.strip())
        port = parts.port
        host = parts.hostname
    except ValueError as exc:
        raise ApiError("Invalid service origin.") from exc
    if (parts.scheme not in ("http", "https") or not host or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or parts.path not in ("", "/") or any(ord(c) < 32 for c in value)):
        raise ApiError("Use a service origin such as http://127.0.0.1:8800 without credentials or paths.")
    if parts.scheme == "http":
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host.casefold() == "localhost"
        if not loopback:
            raise ApiError("Plain HTTP requires a loopback address. Use SSH forwarding or HTTPS.")
    if port is not None and port < 1:
        raise ApiError("Service port must be positive.")
    return parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def collection(payload):
    """Require the canonical collection envelope; malformed data is not an empty result."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ApiError("The service returned an invalid collection envelope.")
    if any(not isinstance(item, dict) for item in payload["items"]):
        raise ApiError("The service returned an invalid collection item.")
    return payload["items"]


def segment(value):
    """Encode an opaque identifier as exactly one API path segment."""
    return parse.quote(str(value), safe="")


class ApiClient:
    """Access one configured platform without importing its Python 3.11 dependencies."""

    def __init__(self, origin="http://127.0.0.1:8800", timeout=25, token=None):
        """Validate the service address and bound all network socket operations."""
        self.origin = validate_origin(origin)
        self.timeout = timeout
        self._authorization = "Basic " + base64.b64encode(("local:" + token).encode("utf-8")).decode("ascii") if token else None

    def open(self, path, method="GET", body=None, headers=None, timeout=None):
        """Open one same-origin versioned API request with concise error handling."""
        if not path.startswith("/") or path.startswith("//") or "#" in path:
            raise ApiError("API paths must be relative to /api/v1.")
        data = body if isinstance(body, bytes) else None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers = {"Accept": "application/json", "Origin": self.origin}
        if self._authorization:
            request_headers["Authorization"] = self._authorization
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        req = request.Request(self.origin + "/api/v1" + path, data=data, method=method, headers=request_headers)
        try:
            # Avoid ambient proxy settings redirecting a local SSH tunnel.
            opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
            return opener.open(req, timeout=timeout or self.timeout)
        except error.HTTPError as exc:
            raw = exc.read(16000).decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw).get("detail", raw)
                if isinstance(detail, list):
                    detail = "\n".join("{}: {}".format(".".join(str(x) for x in item.get("loc", [])), item.get("msg", "Invalid input")) for item in detail if isinstance(item, dict))
            except (ValueError, AttributeError):
                detail = raw
            raise ApiError("HTTP {}: {}".format(exc.code, str(detail)[:2000])) from None
        except (error.URLError, OSError, TimeoutError) as exc:
            suffix = " No mutation was retried; inspect run history before trying again." if method != "GET" else ""
            raise ApiError("Cannot reach {}. Check the execution service and SSH tunnel. {}{}".format(self.origin, type(exc).__name__, suffix)) from None

    def call(self, path, method="GET", body=None, timeout=None):
        """Read a size-bounded JSON response and reject malformed service data."""
        with self.open(path, method, body, timeout=timeout) as response:
            raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ApiError("JSON response exceeds the desktop size limit.")
            if response.status == 204:
                return None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ApiError("The execution service returned malformed JSON.") from None

    def download(self, artifact, destination, cancel, progress=None):
        """Stream to an owned temporary file, verify hash/size, then atomically publish."""
        if artifact.get("is_directory"):
            raise ApiError("Directory artifacts cannot be downloaded as a file.")
        expected = str(artifact.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ApiError("Artifact download requires a recorded SHA-256.")
        endpoint = artifact.get("download_path")
        if endpoint is not None and not re.fullmatch(r"/formal-sessions/[0-9a-f]{32}/download\?path=[A-Za-z0-9%_.~+-]+", endpoint):
            raise ApiError("Invalid formal-session download endpoint.")
        endpoint = endpoint or "/artifacts/{}/download".format(segment(artifact["id"]))
        target = Path(destination).absolute()
        temporary = None
        size = 0
        digest = hashlib.sha256()
        try:
            with tempfile.NamedTemporaryFile(prefix=".ucagent-download-", dir=str(target.parent), delete=False) as output:
                temporary = Path(output.name)
                with self.open(endpoint) as response:
                    while True:
                        if cancel.is_set():
                            raise Cancelled("Download cancelled; the destination was not replaced.")
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        digest.update(block)
                        size += len(block)
                        if progress:
                            progress(size)
                output.flush()
                os.fsync(output.fileno())
            if cancel.is_set():
                raise Cancelled("Download cancelled; the destination was not replaced.")
            if digest.hexdigest() != expected or (artifact.get("size") is not None and size != artifact["size"]):
                raise ApiError("Artifact hash or size mismatch. The destination was not replaced.")
            os.replace(str(temporary), str(target))
            temporary = None
            return {"path": str(target), "bytes": size, "sha256": expected}
        finally:
            if temporary is not None:
                temporary.unlink()

    def upload(self, project_id, paths):
        """Upload at most 16 explicitly selected files and 32 MiB, with literal safe basenames."""
        if not paths or len(paths) > 16:
            raise ApiError("Select between 1 and 16 input files.")
        boundary = "ucagent-" + uuid.uuid4().hex
        blocks = []
        size = 0
        names = set()
        for filename in paths:
            path = Path(filename)
            name = path.name
            if name in names or any(c in name for c in '\r\n"\\'):
                raise ApiError("Upload filenames must be unique plain basenames.")
            names.add(name)
            with path.open("rb") as stream:
                block = stream.read(32 * 1024 * 1024 - size + 1)
            size += len(block)
            if size > 32 * 1024 * 1024:
                raise ApiError("Desktop input upload is limited to 32 MiB. Transfer larger sources through the administrator workflow.")
            blocks.extend([('--{}\r\nContent-Disposition: form-data; name="files"; filename="{}"\r\nContent-Type: application/octet-stream\r\n\r\n'.format(boundary, name)).encode("utf-8"), block, b"\r\n"])
        blocks.append(("--" + boundary + "--\r\n").encode("ascii"))
        with self.open("/projects/{}/files".format(segment(project_id)), "POST", b"".join(blocks), {"Content-Type": "multipart/form-data; boundary=" + boundary}) as response:
            raw = response.read(MAX_JSON + 1)
        try:
            if len(raw) > MAX_JSON:
                raise ValueError("Oversized upload response")
            result = json.loads(raw)
            collection(result)
            return result
        except (ValueError, UnicodeError):
            raise ApiError("Invalid upload response; inspect project inputs before retrying.") from None

    def events(self, run_id, after, cancel):
        """Yield validated monotonic SSE records; callers reconnect from the last yielded id."""
        path = "/runs/{}/events?after={}".format(segment(run_id), max(0, int(after)))
        with self.open(path, headers={"Accept": "text/event-stream"}, timeout=20) as response:
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                raise ApiError("Expected an event stream from the execution service.")
            lines = []
            length = 0
            cursor = after
            while not cancel.is_set():
                raw = response.readline(MAX_EVENT + 1)
                if not raw:
                    return
                length += len(raw)
                if length > MAX_EVENT:
                    raise ApiError("An event exceeds the desktop size limit.")
                text = raw.decode("utf-8").rstrip("\r\n")
                if text.startswith("data:"):
                    lines.append(text[5:].lstrip(" "))
                elif not text:
                    if lines:
                        try:
                            event = json.loads("\n".join(lines))
                            sequence = event["sequence"]
                            if not isinstance(sequence, int) or isinstance(sequence, bool) or not isinstance(event.get("type"), str):
                                raise ValueError("Invalid event identity")
                        except (ValueError, KeyError, TypeError):
                            raise ApiError("Malformed event; the last verified cursor was preserved.") from None
                        if sequence > cursor:
                            cursor = sequence
                            yield event
                    lines = []
                    length = 0
