"""`ydbctl integ` — `mupip integ` integrity check + result summary."""

from __future__ import annotations

import re
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip

_REGION_RE = re.compile(r"^\s*Integ of region\s+(\S+)\s*$", re.MULTILINE)
_NO_ERRORS_RE = re.compile(r"No errors detected by (?:fast|full) integ\.",
                             re.IGNORECASE)


def run(
    profile: Profile,
    *,
    region: str = "*",
    full: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    args = ["integ"]
    args.append("-full" if full else "-fast")
    args.extend(["-region", region])

    try:
        out = mupip(profile, args, timeout=timeout)
    except YdbError as e:
        return error_envelope("integ", code=ErrorCode.YDB_ERROR, message=str(e))

    regions_found = _REGION_RE.findall(out)
    no_error_count = len(_NO_ERRORS_RE.findall(out))
    has_errors = no_error_count < len(regions_found)

    summary = []
    for r in regions_found:
        summary.append({
            "region": r,
            "ok": _region_passed(out, r),
        })

    return success_envelope("integ", {
        "mode": "full" if full else "fast",
        "region_arg": region,
        "regions_checked": len(regions_found),
        "all_ok": (not has_errors) and len(regions_found) > 0,
        "regions": summary,
        "raw": out,
    })


def _region_passed(text: str, region: str) -> bool:
    """Did `Integ of region <region>` get followed by 'No errors detected'?"""
    parts = re.split(r"^\s*Integ of region\s+", text, flags=re.MULTILINE)
    for part in parts[1:]:
        first_line = part.splitlines()[0].strip() if part.splitlines() else ""
        if first_line.startswith(region):
            return bool(_NO_ERRORS_RE.search(part.split("Integ of region")[0]))
    return False
