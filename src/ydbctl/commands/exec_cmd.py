"""`ydbctl exec` — run M code in the container.

Modes:
- positional <code>      — single-shot via `yottadb -run %XCMD '<code>'`
- --stdin                — read M from stdin (flattened to one line for %XCMD)
- --file PATH            — read M from a host file
- --run "ENTRY^ROUTINE"  — invoke a labelled entry via `yottadb -run`
- --direct               — use the multi-line `yottadb -direct` heredoc path

Default mode (no flags) is %XCMD — fastest and cleanest output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import (
    YdbError,
    yottadb_direct,
    yottadb_run_entry,
    yottadb_xcmd,
)


def run(
    profile: Profile,
    *,
    code: str | None = None,
    stdin_text: str | None = None,
    file: Path | None = None,
    run_entry: str | None = None,
    run_args: list[str] | None = None,
    direct: bool = False,
    timeout: float = 60.0,
) -> dict[str, Any]:
    # --run is a separate path
    if run_entry is not None:
        try:
            out = yottadb_run_entry(profile, run_entry,
                                     *(run_args or []), timeout=timeout)
        except YdbError as e:
            return error_envelope("exec", code=ErrorCode.YDB_ERROR, message=str(e))
        return success_envelope("exec", {
            "mode": "run",
            "entry": run_entry,
            "args": run_args or [],
            "output": out,
        })

    # Resolve script payload
    payload = _resolve_payload(code=code, stdin_text=stdin_text, file=file)
    if payload is None:
        return error_envelope(
            "exec",
            code=ErrorCode.USAGE,
            message="exec needs M code: pass it inline, via --stdin, --file PATH, "
                    "or --run ENTRY^ROUTINE",
            hint="examples: ydbctl exec 'W $ZV,!'  |  ydbctl exec --file foo.m",
        )

    try:
        if direct:
            out = yottadb_direct(profile, payload, timeout=timeout)
            mode = "direct"
        else:
            out = yottadb_xcmd(profile, payload, timeout=timeout)
            mode = "xcmd"
    except YdbError as e:
        return error_envelope(
            "exec", code=ErrorCode.YDB_ERROR, message=str(e),
            hint="check the M code; %XCMD requires single-line "
                 "(use --direct for multi-line scripts)",
        )

    return success_envelope("exec", {"mode": mode, "output": out})


def _resolve_payload(
    *,
    code: str | None,
    stdin_text: str | None,
    file: Path | None,
) -> str | None:
    if code is not None:
        return code
    if stdin_text is not None:
        return stdin_text
    if file is not None:
        return Path(file).read_text(encoding="utf-8")
    return None
