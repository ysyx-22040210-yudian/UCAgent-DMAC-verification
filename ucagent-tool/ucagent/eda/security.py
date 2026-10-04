"""Security helpers for workspace containment and secret-free EDA evidence."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping, Sequence


class PathSecurityError(ValueError):
    """Report a path that resolves outside its declared trust boundary."""


_SECRET_NAME = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|token|secret|password|passwd|credential|license(?:_file)?|lm_license_file)(?:$|[_-])",
    re.IGNORECASE,
)
_INLINE_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|token|secret|password|passwd|credential|license(?:_file)?|lm_license_file)\b\s*[=:]\s*)([^\s,;]+)"
)
_URL_CREDENTIAL = re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s:]+(?::[^/@\s]*)?)@", re.IGNORECASE)


def resolve_within(root: Path, candidate: Path | str, *, must_exist: bool = False, allow_root: bool = True) -> Path:
    """Resolve ``candidate`` and prove that it remains below ``root``."""

    root_path = Path(root).resolve(strict=True)
    raw = Path(candidate)
    joined = raw if raw.is_absolute() else root_path / raw
    try:
        resolved = joined.resolve(strict=must_exist)
    except FileNotFoundError:
        raise
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise PathSecurityError(f"path escapes workspace boundary: {candidate}") from exc
    if not allow_root and resolved == root_path:
        raise PathSecurityError("the workspace root is not a valid target for this operation")
    return resolved


def is_secret_name(name: str) -> bool:
    """Identify environment or option names whose values must never be exposed."""

    normalized = name.strip().lstrip("-").replace(".", "_")
    return bool(_SECRET_NAME.search(normalized))


def redact_text(text: str, secret_values: Sequence[str] = ()) -> str:
    """Redact inline credentials and exact configured secret values from text."""

    redacted = text
    for secret in sorted({value for value in secret_values if value}, key=len, reverse=True):
        redacted = redacted.replace(secret, "<redacted>")
    redacted = _INLINE_ASSIGNMENT.sub(lambda match: match.group(1) + "<redacted>", redacted)
    redacted = _URL_CREDENTIAL.sub(lambda match: match.group("scheme") + "<redacted>@", redacted)
    return redacted


def redact_argv(argv: Sequence[str], secret_values: Sequence[str] = ()) -> list[str]:
    """Return an argv copy with sensitive option values removed."""

    result: list[str] = []
    redact_next = False
    for value in argv:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        stripped = value.lstrip("-")
        if "=" in stripped:
            name, _ = stripped.split("=", 1)
            if is_secret_name(name):
                prefix = value[: value.index("=") + 1]
                result.append(prefix + "<redacted>")
                continue
        if is_secret_name(stripped):
            result.append(value)
            redact_next = True
            continue
        result.append(redact_text(value, secret_values))
    return result


def redact_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Produce a display-safe environment mapping for events or manifests."""

    return {name: "<redacted>" if is_secret_name(name) else value for name, value in environment.items()}


def redact_data(value: Any, secret_values: Sequence[str] = ()) -> Any:
    """Recursively redact strings and secret-named mapping fields."""

    if isinstance(value, str):
        return redact_text(value, secret_values)
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if is_secret_name(str(key)) else redact_data(item, secret_values)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [redact_data(item, secret_values) for item in value]
    if isinstance(value, list):
        return [redact_data(item, secret_values) for item in value]
    return value
