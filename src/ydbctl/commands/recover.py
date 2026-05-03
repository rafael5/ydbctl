"""`ydbctl recover` — replay journal records via `mupip journal -recover`."""

from __future__ import annotations

from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip


def run(
    profile: Profile,
    *,
    region: str = "*",
    journal_file: str | None = None,
    backward: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Run `mupip journal -recover -backward [<jnl-file>]`.

    Defaults to backward recovery on all regions' active journal files.
    """
    args = ["journal", "-recover", "-backward" if backward else "-forward"]
    if journal_file is None:
        # Recover the active journal of every region
        args.extend(["-region", region])
    else:
        args.append(journal_file)

    try:
        out = mupip(profile, args, timeout=timeout)
    except YdbError as e:
        return error_envelope("recover", code=ErrorCode.YDB_ERROR, message=str(e))

    return success_envelope("recover", {
        "region_arg": region,
        "journal_file": journal_file,
        "direction": "backward" if backward else "forward",
        "raw": out,
    })
