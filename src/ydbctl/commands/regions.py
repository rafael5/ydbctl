"""`ydbctl regions` — list M regions via `gde show`.

Phase 1 keeps the parser simple: extract the regions section line by
line. Raw GDE output is included for callers that need it.
"""

from __future__ import annotations

import re
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, gde_show

_NAMES_HEADER_RE = re.compile(r"^\s*Global\s+Region\s*$")


def run(profile: Profile) -> dict[str, Any]:
    try:
        text = gde_show(profile)
    except YdbError as e:
        return error_envelope("regions", code=ErrorCode.YDB_ERROR, message=str(e))

    regions = sorted(_extract_region_names(text))
    name_map = _extract_name_map(text)

    return success_envelope("regions", {
        "container": profile.container,
        "regions": regions,
        "count": len(regions),
        "globals": name_map,
        "raw": text,
    })


def _extract_region_names(text: str) -> set[str]:
    """Pull region names out of the NAMES table second column.

    Falls back to scanning every all-uppercase identifier on the right
    side of the NAMES table.
    """
    found: set[str] = set()
    in_names = False
    for raw in text.splitlines():
        if _NAMES_HEADER_RE.match(raw):
            in_names = True
            continue
        if not in_names:
            continue
        if raw.strip().startswith("---"):
            continue
        if raw.strip() == "" or raw.strip().startswith("***"):
            in_names = False
            continue
        # Lines look like `<global-pattern>            REGION-NAME`
        parts = raw.split()
        if len(parts) >= 2:
            found.add(parts[-1])
    return found


def _extract_name_map(text: str) -> list[dict[str, str]]:
    """Extract the global → region rows from the NAMES section."""
    out: list[dict[str, str]] = []
    in_names = False
    for raw in text.splitlines():
        if _NAMES_HEADER_RE.match(raw):
            in_names = True
            continue
        if not in_names:
            continue
        if raw.strip().startswith("---"):
            continue
        if raw.strip() == "" or raw.strip().startswith("***"):
            in_names = False
            continue
        parts = raw.split()
        if len(parts) >= 2:
            out.append({"global": parts[0], "region": parts[-1]})
    return out
