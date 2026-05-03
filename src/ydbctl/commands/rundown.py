"""`ydbctl rundown` — release orphan IPC via `mupip rundown -region '*'`."""

from __future__ import annotations

import re
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip

_OK_RE = re.compile(r"%YDB-I-MUFILRNDWNSUC,\s*File\s+(\S+)\s+successfully rundown")


def run(
    profile: Profile,
    *,
    region: str = "*",
    timeout: float = 60.0,
) -> dict[str, Any]:
    args = ["rundown", "-region", region]
    try:
        out = mupip(profile, args, timeout=timeout)
    except YdbError as e:
        # mupip rundown returns non-zero when files are missing (e.g. no
        # .repl on a non-replicated install). That's not a real failure
        # — we surface as a warning and still report success if the
        # individual region rundowns succeeded.
        msg = str(e)
        if "MUFILRNDWNSUC" not in msg:
            return error_envelope("rundown", code=ErrorCode.YDB_ERROR,
                                   message=msg)
        out = msg

    files = [m.group(1) for m in _OK_RE.finditer(out)]
    warnings = []
    if "FILENOTFND" in out:
        warnings.append("some auxiliary files (e.g. .repl) were not found "
                         "— harmless on non-replicated installs")
    return success_envelope("rundown", {
        "region_arg": region,
        "files_run_down": files,
        "count": len(files),
        "raw": out,
    }, warnings=warnings)
