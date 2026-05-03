"""`ydbctl reorg` — `mupip reorg` defrag/coalesce."""

from __future__ import annotations

import re
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip

_GLOBAL_RE = re.compile(r"^Global:\s+(\S+)\s+\(region\s+(\S+)\)",
                          re.MULTILINE)
_BLOCKS_PROC_RE = re.compile(r"Blocks processed\s*:\s*(\d+)", re.IGNORECASE)


def run(
    profile: Profile,
    *,
    region: str = "*",
    truncate: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    args = ["reorg", "-region", region]
    if truncate:
        args.append("-truncate")

    try:
        out = mupip(profile, args, timeout=timeout)
    except YdbError as e:
        return error_envelope("reorg", code=ErrorCode.YDB_ERROR, message=str(e))

    globals_processed = []
    for m in _GLOBAL_RE.finditer(out):
        globals_processed.append({"global": m.group(1), "region": m.group(2)})

    total_blocks = sum(int(m.group(1)) for m in _BLOCKS_PROC_RE.finditer(out))

    return success_envelope("reorg", {
        "region_arg": region,
        "truncate": truncate,
        "globals_processed": len(globals_processed),
        "total_blocks_processed": total_blocks,
        "globals": globals_processed,
        "raw": out,
    })
