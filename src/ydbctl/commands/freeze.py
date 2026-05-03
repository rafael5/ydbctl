"""`ydbctl freeze --on/--off` — suspend/resume DB updates via `mupip freeze`."""

from __future__ import annotations

import re
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip

_FROZEN_RE = re.compile(r"Region\s+(\S+)\s+is now (FROZEN|UNFROZEN)",
                          re.IGNORECASE)


def run(
    profile: Profile,
    *,
    on: bool = False,
    off: bool = False,
    region: str = "*",
    timeout: float = 30.0,
) -> dict[str, Any]:
    if on == off:
        return error_envelope(
            "freeze", code=ErrorCode.USAGE,
            message="freeze needs exactly one of --on or --off",
            hint="ydbctl freeze --on   |   ydbctl freeze --off",
        )

    args = ["freeze", "-on" if on else "-off", region]

    try:
        out = mupip(profile, args, timeout=timeout)
    except YdbError as e:
        return error_envelope("freeze", code=ErrorCode.YDB_ERROR, message=str(e))

    transitions = [
        {"region": m.group(1), "state": m.group(2).upper()}
        for m in _FROZEN_RE.finditer(out)
    ]
    return success_envelope("freeze", {
        "action": "on" if on else "off",
        "region_arg": region,
        "regions_affected": len(transitions),
        "regions": transitions,
        "raw": out,
    })
