"""`ydbctl sql` — run SQL via Octo (when installed).

The yottadb-base image doesn't ship Octo. Calls return `not_found`
with a clear hint when Octo isn't present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, has_octo, octo_exec


def run(
    profile: Profile,
    *,
    statement: str | None = None,
    file: Path | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    sql = _resolve_sql(statement=statement, file=file)
    if sql is None:
        return error_envelope(
            "sql",
            code=ErrorCode.USAGE,
            message="sql needs a statement: pass it inline or via --file PATH",
            hint="example: ydbctl sql 'SELECT * FROM names LIMIT 10'",
        )

    if not has_octo(profile):
        return error_envelope(
            "sql",
            code=ErrorCode.NOT_FOUND,
            message="Octo CLI not installed in this container",
            hint=("switch to yottadb/yottadb-debian image (Octo bundled), "
                  "or run `ydbinstall --octo` inside the container"),
        )

    try:
        out = octo_exec(profile, sql, timeout=timeout)
    except YdbError as e:
        return error_envelope("sql", code=ErrorCode.YDB_ERROR, message=str(e))

    return success_envelope("sql", {
        "statement": sql.strip()[:200],
        "output": out,
    })


def _resolve_sql(*, statement: str | None, file: Path | None) -> str | None:
    if statement is not None:
        return statement
    if file is not None:
        return Path(file).read_text(encoding="utf-8")
    return None
