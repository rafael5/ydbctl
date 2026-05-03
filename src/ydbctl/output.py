"""Output envelope and rendering — mirrors irisctl/output.py.

Distinct error code: `ipc_orphans` (exit 4) replaces IRIS's
`license_exhausted` since YottaDB has no license concept.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    OK = "ok"
    INTERNAL = "internal"
    USAGE = "usage"
    INSTANCE_NOT_RUNNING = "instance_not_running"
    IPC_ORPHANS = "ipc_orphans"
    AUTH_REQUIRED = "auth_required"
    AUTH_FAILED = "auth_failed"
    NOT_FOUND = "not_found"
    YDB_ERROR = "ydb_error"
    DOCKER_ERROR = "docker_error"
    NETWORK_ERROR = "network_error"


_EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.OK: 0,
    ErrorCode.INTERNAL: 1,
    ErrorCode.USAGE: 2,
    ErrorCode.INSTANCE_NOT_RUNNING: 3,
    ErrorCode.IPC_ORPHANS: 4,
    ErrorCode.AUTH_REQUIRED: 5,
    ErrorCode.AUTH_FAILED: 5,
    ErrorCode.NOT_FOUND: 6,
    ErrorCode.YDB_ERROR: 7,
    ErrorCode.DOCKER_ERROR: 8,
    ErrorCode.NETWORK_ERROR: 9,
}


def exit_code_for(code: ErrorCode) -> int:
    return _EXIT_CODES[code]


def success_envelope(
    command: str,
    data: Any,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "v": 1,
        "ok": True,
        "command": command,
        "data": data,
        "warnings": warnings or [],
    }


def error_envelope(
    command: str,
    *,
    code: ErrorCode,
    message: str,
    hint: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    return {
        "v": 1,
        "ok": False,
        "command": command,
        "error": {
            "code": code.value,
            "message": message,
            "hint": hint,
            "ref": ref,
        },
    }


def render_json(envelope: dict[str, Any], *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(envelope, indent=2, sort_keys=False)
    return json.dumps(envelope, separators=(",", ":"))


def render_human(envelope: dict[str, Any]) -> str:
    if not envelope.get("ok", False):
        return _render_human_error(envelope)
    return _render_human_success(envelope)


def _render_human_success(envelope: dict[str, Any]) -> str:
    lines: list[str] = []
    data = envelope["data"]
    if isinstance(data, dict):
        lines.extend(_kv_block(data))
    elif isinstance(data, list):
        lines.extend(_table(data))
    else:
        lines.append(str(data))

    warnings = envelope.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)


def _render_human_error(envelope: dict[str, Any]) -> str:
    err = envelope["error"]
    lines = [f"ERROR ({err['code']}): {err['message']}"]
    if err.get("hint"):
        lines.append(f"hint: {err['hint']}")
    if err.get("ref"):
        lines.append(f"see:  {err['ref']}")
    return "\n".join(lines)


def _kv_block(d: dict[str, Any]) -> list[str]:
    if not d:
        return ["(empty)"]
    width = max(len(str(k)) for k in d) + 1
    return [f"{str(k).ljust(width)} {_fmt_value(v)}" for k, v in d.items()]


def _table(rows: list[Any]) -> list[str]:
    if not rows:
        return ["(no rows)"]
    if not all(isinstance(r, dict) for r in rows):
        return [str(r) for r in rows]
    cols: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    widths = {c: max(len(c), *(len(_fmt_value(r.get(c, ""))) for r in rows))
              for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    body = [
        "  ".join(_fmt_value(r.get(c, "")).ljust(widths[c]) for c in cols)
        for r in rows
    ]
    return [header, sep, *body]


def _fmt_value(v: Any) -> str:
    if v is True:
        return "yes"
    if v is False:
        return "no"
    if v is None:
        return "-"
    return str(v)
