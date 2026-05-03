"""`ydbctl logs [--tail N]` — recent journal records (read-only)."""

from __future__ import annotations

from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, ydb_run


def run(profile: Profile, *, tail: int = 50) -> dict[str, Any]:
    """Show recent journal records via `mupip journal -show -backward`.

    YottaDB has no IRIS-style messages.log; the closest "what happened
    lately" surface is the journal record stream. We summarize counts
    and return the last N records.
    """
    try:
        res = ydb_run(
            profile,
            ('jnl="$ydb_dir/$ydb_rel/g/yottadb.mjl"; '
             "if [ -f \"$jnl\" ]; then "
             '  mupip journal -show -backward "$jnl" 2>&1 | head -' + str(tail) + '; '
             'else '
             '  echo "no journal file at $jnl"; '
             'fi'),
        )
    except YdbError as e:
        return error_envelope("logs", code=ErrorCode.YDB_ERROR, message=str(e))

    text = res["stdout"]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return success_envelope("logs", {
        "tail": tail,
        "lines": lines,
        "raw": text,
    })
